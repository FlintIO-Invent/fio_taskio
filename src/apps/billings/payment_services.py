"""Customer Invoice receipts. No SaaS subscription or payment-provider side effects."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID, uuid5

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.businesses.models import Business, BusinessSubscription, BusinessUser
from apps.businesses.utils import BILLING_MANAGE_ROLES, BILLING_VIEW_ROLES, OWNER_ADMIN_ROLES
from apps.crm.models import ActivityLog
from apps.crm.services import log_activity

from .models import Invoice, InvoicePayment

ACCOUNTING_ROLES = (*OWNER_ADMIN_ROLES, BusinessUser.Role.ACCOUNTANT)
# Every currently supported workspace currency has two minor-unit decimals.
# Unsupported currencies fail closed instead of inheriting an arbitrary precision.
CURRENCY_QUANTA = {code: Decimal("0.01") for code in ("USD", "XCD", "EUR", "ANG")}


def money(value, currency):
    try:
        quantum = CURRENCY_QUANTA[currency]
        if isinstance(value, (float, bool)):
            raise ValueError("Use Decimal or an exact decimal string.")
        result = Decimal(value)
        if not result.is_finite():
            raise ValueError("Amounts must be finite.")
        return result.quantize(quantum, rounding=ROUND_HALF_UP)
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(
            "Enter a finite Decimal amount in a supported Invoice currency."
        ) from exc


def _reference(value):
    return " ".join(str(value or "").split()).upper()


def _key(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("A valid payment retry token is required.") from exc


def require_payment_access(*, business, actor, invoice, write=False, accounting=False):
    if invoice.business_id != business.pk or invoice.client.business_id != business.pk:
        raise PermissionDenied("Payment Invoice is unavailable in this workspace.")
    if business.vertical == Business.Vertical.LOGISTICS:
        from apps.logistics.financial_access import require_invoice_access

        require_invoice_access(
            business=business, actor=actor, invoice=invoice, write=write, accounting=accounting
        )
        return
    member = BusinessUser.objects.filter(
        business=business,
        user_id=getattr(actor, "pk", None),
        is_active=True,
        user__is_active=True,
    ).first()
    roles = (
        ACCOUNTING_ROLES if accounting else BILLING_MANAGE_ROLES if write else BILLING_VIEW_ROLES
    )
    subscription = (
        BusinessSubscription.objects.select_related("plan", "business")
        .filter(business=business)
        .first()
    )
    if (
        not business.is_active
        or not member
        or member.role not in roles
        or not subscription
        or not (
            subscription.can_use_module("invoicing")
            if write
            else subscription.can_view_module("invoicing")
        )
    ):
        raise PermissionDenied(
            "Your workspace role/subscription does not permit customer payments."
        )


@dataclass(frozen=True)
class InvoiceSettlement:
    invoice_id: int
    currency: str
    total: Decimal
    received: Decimal
    reductions: Decimal
    net_paid: Decimal
    outstanding: Decimal
    state: str
    settled: bool
    legacy_paid_unverified: bool
    issues: tuple[str, ...]
    credits: Decimal = Decimal("0.00")
    adjusted_total: Decimal = Decimal("0.00")
    refund_due: Decimal = Decimal("0.00")

    @property
    def state_label(self):
        return {
            "UNPAID": "Unpaid",
            "PARTIAL": "Partially paid",
            "SETTLED": "Settled",
            "LEGACY_PAID_UNVERIFIED": "Legacy PAID — unverified",
            "REVIEW_REQUIRED": "Needs accounting review",
            "CANCELLED": "Cancelled",
            "REFUND_DUE": "Refund due — money not yet recorded as returned",
        }[self.state]


def _invoice_settlement(invoice):
    """Trusted projection for already-authorized billing/Parcel coverage callers."""
    entries = sorted(invoice.payments.all(), key=lambda item: item.pk)
    foreign_entries = any(item.business_id != invoice.business_id for item in entries)
    entries = [item for item in entries if item.business_id == invoice.business_id]
    currency = entries[0].currency if entries else invoice.currency_code
    basis = entries[0].invoice_total_snapshot if entries else invoice.total
    issues = []
    if foreign_entries:
        issues.append("Payment history has inconsistent workspace ownership.")
    if (
        entries
        and invoice.business.vertical == Business.Vertical.LOGISTICS
        and invoice.currency_code != currency
    ):
        issues.append("Invoice and receipt currencies require accounting review.")
    try:
        total = money(basis, currency)
        if basis != total or total < 0 or invoice.total != total:
            issues.append("Invoice payment basis requires accounting review.")
    except ValidationError:
        total = Decimal("0.00")
        issues.append("Invoice payment currency/amount requires accounting review.")
    receipts, reductions, reduced = {}, Decimal("0.00"), {}
    for entry in entries:
        if (
            entry.business_id != invoice.business_id
            or entry.currency != currency
            or entry.invoice_total_snapshot != basis
            or not entry.amount.is_finite()
            or entry.amount <= 0
        ):
            issues.append("Payment history has inconsistent ownership or monetary snapshots.")
            continue
        if entry.kind == InvoicePayment.Kind.RECEIPT:
            receipts[entry.pk] = entry
        elif entry.kind in (InvoicePayment.Kind.REFUND, InvoicePayment.Kind.REVERSAL):
            reductions += entry.amount
            reduced[entry.original_id] = (
                reduced.get(entry.original_id, Decimal("0.00")) + entry.amount
            )
        else:
            issues.append("Payment history contains an unknown entry kind.")
    for original_id, amount in reduced.items():
        if original_id not in receipts or amount > receipts[original_id].amount:
            issues.append("Payment reductions exceed or lack their original receipt.")
    for receipt in receipts.values():
        if receipt.original_id and (
            receipt.original_id not in receipts
            or reduced.get(receipt.original_id, Decimal("0.00"))
            != receipts[receipt.original_id].amount
        ):
            issues.append("Payment correction lineage requires accounting review.")
    received = sum((item.amount for item in receipts.values()), Decimal("0.00"))
    net = received - reductions
    if net < 0 or net > total:
        issues.append("Payment history has an invalid Invoice balance.")
    if entries and invoice.status not in (Invoice.Status.SENT, Invoice.Status.PAID) and net:
        issues.append("Invoice status conflicts with its active receipts.")
    legacy = invoice.status == Invoice.Status.PAID and not entries and not foreign_entries
    outstanding = max(total - net, Decimal("0.00"))
    credits, adjusted_total, refund_due = Decimal("0.00"), total, Decimal("0.00")
    invoice._cancellation_projection = None
    if invoice.business.vertical == Business.Vertical.LOGISTICS:
        from .cancellation_services import projection

        try:
            allocated = projection(invoice, entries)
            if allocated:
                invoice._cancellation_projection = allocated
                credits = allocated["credit_total"]
                adjusted_total = allocated["adjusted_total"]
                outstanding = allocated["outstanding"]
                refund_due = allocated["refund_due"]
                if allocated["adjusted_total"] != total - credits:
                    raise ValidationError("Cancellation credit totals require review.")
        except ValidationError as exc:
            issues.extend(exc.messages)
    if invoice.status == Invoice.Status.CANCELLED:
        outstanding = Decimal("0.00")
    settled = (
        not issues
        and not legacy
        and outstanding == 0
        and refund_due == 0
        and (
            invoice.status in (Invoice.Status.SENT, Invoice.Status.PAID)
            or (credits and adjusted_total == 0)
        )
    )
    state = (
        "REVIEW_REQUIRED"
        if issues
        else (
            "LEGACY_PAID_UNVERIFIED"
            if legacy
            else "SETTLED" if settled else "PARTIAL" if net > 0 else "UNPAID"
        )
    )
    if invoice.status == Invoice.Status.CANCELLED and not issues:
        state = "CANCELLED"
    elif refund_due and not issues:
        state = "REFUND_DUE"
    return InvoiceSettlement(
        invoice.pk,
        currency,
        total,
        received,
        reductions,
        net,
        outstanding,
        state,
        settled,
        legacy,
        tuple(dict.fromkeys(issues)),
        credits,
        adjusted_total,
        refund_due,
    )


def invoice_settlement(*, business, actor, invoice):
    selected = (
        Invoice.objects.select_related("business", "client")
        .filter(business=business, pk=getattr(invoice, "pk", invoice))
        .first()
    )
    if selected is None:
        raise PermissionDenied("Payment Invoice is unavailable in this workspace.")
    require_payment_access(business=selected.business, actor=actor, invoice=selected)
    return _invoice_settlement(selected)


def _locked_invoice(*, business, actor, invoice, accounting=False):
    current = Business.objects.select_for_update().get(pk=business.pk)
    BusinessUser.objects.select_for_update().filter(
        business=current, user_id=getattr(actor, "pk", None)
    ).first()
    selected = (
        Invoice.objects.select_for_update()
        .filter(business=current, pk=getattr(invoice, "pk", invoice))
        .first()
    )
    if selected is None:
        raise PermissionDenied("Payment Invoice is unavailable in this workspace.")
    require_payment_access(
        business=current, actor=actor, invoice=selected, write=True, accounting=accounting
    )
    return current, selected


def _replay(business, key, fields):
    previous = InvoicePayment.objects.filter(business=business, idempotency_key=key).first()
    if previous:
        if any(getattr(previous, name) != value for name, value in fields.items()):
            raise ValidationError("This retry token already belongs to another payment operation.")
        return previous
    return None


def _append(*, business, actor, key, fields):
    entry = InvoicePayment(
        business=business, recorded_by=actor, idempotency_key=key, **fields
    )._append()
    log_activity(
        business=business,
        actor=actor,
        client=entry.invoice.client,
        action_type=ActivityLog.ActionType.STATUS_CHANGED,
        summary=f"Customer payment {entry.get_kind_display().lower()} recorded",
        payload={
            "payment_id": entry.pk,
            "invoice_id": entry.invoice_id,
            "kind": entry.kind,
            "amount": str(entry.amount),
            "currency": entry.currency,
            "original_id": entry.original_id,
            "reason_reference": entry.reason_reference,
        },
    )
    return entry


def _record_receipt(
    *,
    current,
    selected,
    actor,
    amount,
    currency,
    method,
    reference,
    verification_reference,
    key,
    original=None,
    reason_reference="",
    receipt_allocations=None,
):
    if method not in InvoicePayment.Method.values:
        raise ValidationError("Choose a supported customer payment method.")
    if method == InvoicePayment.Method.ONLINE and current.vertical != Business.Vertical.LOGISTICS:
        raise ValidationError("Online payment entry is available only for Logistics receipts.")
    if current.vertical == Business.Vertical.LOGISTICS and not _reference(reference):
        reference = f"RECEIPT-{key}"
    if method == InvoicePayment.Method.VERIFIED_ONLINE:
        require_payment_access(
            business=current, actor=actor, invoice=selected, write=True, accounting=True
        )
        if not verification_reference.strip():
            raise ValidationError("Record external verification evidence before an online receipt.")
    amount = money(amount, currency)
    if amount <= 0:
        raise ValidationError("Payment amount must round to a positive currency amount.")
    fields = dict(
        invoice_id=selected.pk,
        kind=InvoicePayment.Kind.RECEIPT,
        amount=amount,
        currency=currency,
        method=method,
        reference=_reference(reference),
        verification_reference=verification_reference.strip(),
        original_id=getattr(original, "pk", None),
        reason_reference=reason_reference.strip(),
    )
    previous = _replay(current, key, fields)
    if previous:
        from .cancellation_services import allocate_new_receipt

        # Recheck supplied allocations on exact retries without creating new shares.
        if receipt_allocations is not None:
            _invoice_settlement(selected)
            allocate_new_receipt(
                invoice=selected, receipt=previous, actor=actor, supplied=receipt_allocations
            )
        return previous
    balance = _invoice_settlement(selected)
    if balance.issues:
        raise ValidationError(balance.issues)
    if selected.status not in (Invoice.Status.SENT, Invoice.Status.PAID):
        raise ValidationError("Record payments only against an issued, active Invoice.")
    if currency != balance.currency:
        raise ValidationError("Payment currency must match the Invoice's saved payment basis.")
    if selected.business.vertical == Business.Vertical.LOGISTICS:
        from apps.logistics.financial_coverage import validate_invoice_charge_bindings

        if selected.snapshot_is_legacy:
            raise ValidationError("Confirm legacy Invoice currency/tax before recording a receipt.")
        validate_invoice_charge_bindings(selected)
    if amount > balance.outstanding:
        raise ValidationError("Payment would exceed the Invoice's outstanding balance.")
    duplicates = InvoicePayment.objects.filter(
        business=current,
        kind=InvoicePayment.Kind.RECEIPT,
        reference=fields["reference"],
    )
    if original:
        # Only this existing correction lineage may reuse its transaction reference.
        ancestor_ids = []
        ancestor = original
        while ancestor:
            ancestor_ids.append(ancestor.pk)
            ancestor = ancestor.original if ancestor.original_id else None
        duplicates = duplicates.exclude(pk__in=ancestor_ids)
    if duplicates.exists():
        raise ValidationError("This receipt/transaction reference is already recorded.")
    fields["invoice_total_snapshot"] = balance.total
    entry = _append(business=current, actor=actor, key=key, fields=fields)
    from .cancellation_services import allocate_new_receipt

    allocate_new_receipt(invoice=selected, receipt=entry, actor=actor, supplied=receipt_allocations)
    return entry


@transaction.atomic
def record_invoice_payment(
    *,
    business,
    actor,
    invoice,
    amount,
    currency,
    method,
    idempotency_key,
    reference="",
    verification_reference="",
    receipt_allocations=None,
):
    current, selected = _locked_invoice(business=business, actor=actor, invoice=invoice)
    return _record_receipt(
        current=current,
        selected=selected,
        actor=actor,
        amount=amount,
        currency=currency,
        method=method,
        reference=reference,
        verification_reference=verification_reference,
        key=_key(idempotency_key),
        receipt_allocations=receipt_allocations,
    )


def _receipt(*, business, invoice, payment):
    original = (
        InvoicePayment.objects.select_for_update()
        .filter(
            business=business, invoice=invoice, pk=getattr(payment, "pk", payment), kind="RECEIPT"
        )
        .first()
    )
    if original is None:
        raise ValidationError("Original receipt is unavailable on this Invoice.")
    return original


def _remaining(original):
    reduced = sum(
        (item.amount for item in original.adjustments.exclude(kind=InvoicePayment.Kind.RECEIPT)),
        Decimal("0.00"),
    )
    return original.amount - reduced


def _reduce(*, current, selected, actor, original, kind, amount, reference, reason_reference, key):
    fields = dict(
        invoice_id=selected.pk,
        original_id=original.pk,
        kind=kind,
        amount=money(amount, original.currency),
        currency=original.currency,
        method=original.method,
        reference=_reference(reference),
        verification_reference=original.verification_reference,
        reason_reference=reason_reference.strip(),
    )
    previous = _replay(current, key, fields)
    if previous:
        return previous
    balance = _invoice_settlement(selected)
    if balance.issues:
        raise ValidationError(balance.issues)
    if not fields["reason_reference"] or not fields["reference"]:
        raise ValidationError("Payment adjustments require transaction and reason references.")
    if fields["amount"] <= 0 or fields["amount"] > _remaining(original):
        raise ValidationError("Reduction exceeds the original receipt's remaining amount.")
    if InvoicePayment.objects.filter(
        business=current, kind__in=["REVERSAL", "REFUND"], reference=fields["reference"]
    ).exists():
        raise ValidationError("This refund/reversal reference is already recorded.")
    fields["invoice_total_snapshot"] = original.invoice_total_snapshot
    return _append(business=current, actor=actor, key=key, fields=fields)


@transaction.atomic
def adjust_invoice_payment(
    *,
    business,
    actor,
    invoice,
    payment,
    kind,
    amount,
    reference,
    reason_reference,
    idempotency_key,
    cancellation_credit=None,
):
    if kind not in (InvoicePayment.Kind.REVERSAL, InvoicePayment.Kind.REFUND):
        raise ValidationError("Choose a reversal or refund adjustment.")
    current, selected = _locked_invoice(
        business=business, actor=actor, invoice=invoice, accounting=True
    )
    original = _receipt(business=current, invoice=selected, payment=payment)
    from .cancellation_services import check_refund
    from .models import InvoiceCancellationCredit, InvoiceRefundAllocation

    key = _key(idempotency_key)
    credit = None
    if InvoiceCancellationCredit.objects.filter(obligation__line__invoice=selected).exists():
        if kind != InvoicePayment.Kind.REFUND:
            raise ValidationError(
                "Cancellation settlement permits allocated completed refunds; receipt reversals require reconciliation."
            )
        credit = check_refund(
            invoice=selected,
            original=original,
            credit=cancellation_credit,
            amount=money(amount, original.currency),
            key=key,
        )
    elif cancellation_credit is not None:
        raise ValidationError("This Invoice has no matching cancellation credit.")
    entry = _reduce(
        current=current,
        selected=selected,
        actor=actor,
        original=original,
        kind=kind,
        amount=amount,
        reference=reference,
        reason_reference=reason_reference,
        key=key,
    )
    if credit and not InvoiceRefundAllocation.objects.filter(refund=entry).exists():
        InvoiceRefundAllocation(
            business=current, recorded_by=actor, refund=entry, credit=credit
        )._append()
    return entry


@transaction.atomic
def correct_invoice_payment(
    *,
    business,
    actor,
    invoice,
    payment,
    amount,
    method,
    reference,
    reason_reference,
    idempotency_key,
    verification_reference="",
):
    current, selected = _locked_invoice(
        business=business, actor=actor, invoice=invoice, accounting=True
    )
    if selected.lines.filter(obligation_shares__cancellation_credit__isnull=False).exists():
        raise ValidationError(
            "Receipts with cancellation allocations require reconciliation before correction."
        )
    original = _receipt(business=current, invoice=selected, payment=payment)
    key = _key(idempotency_key)
    existing = InvoicePayment.objects.filter(original=original, kind="RECEIPT").first()
    if existing:
        fields = dict(
            invoice_id=selected.pk,
            original_id=original.pk,
            kind="RECEIPT",
            amount=money(amount, original.currency),
            currency=original.currency,
            method=method,
            reference=_reference(reference),
            verification_reference=verification_reference.strip(),
            reason_reference=reason_reference.strip(),
        )
        replay = _replay(current, key, fields)
        if replay and replay.pk == existing.pk:
            return replay
        raise ValidationError(
            "This receipt already has a correction; correct its successor instead."
        )
    remaining = _remaining(original)
    if remaining <= 0:
        raise ValidationError("A fully reduced receipt cannot be corrected or reactivated.")
    if remaining != original.amount:
        raise ValidationError(
            "A refunded or partially reversed receipt requires reconciliation before correction."
        )
    _reduce(
        current=current,
        selected=selected,
        actor=actor,
        original=original,
        kind="REVERSAL",
        amount=remaining,
        reference=f"CORRECTION-{key}",
        reason_reference=reason_reference,
        key=uuid5(key, "correction-reversal"),
    )
    return _record_receipt(
        current=current,
        selected=selected,
        actor=actor,
        amount=amount,
        currency=original.currency,
        method=method,
        reference=reference,
        verification_reference=verification_reference,
        key=key,
        original=original,
        reason_reference=reason_reference,
    )
