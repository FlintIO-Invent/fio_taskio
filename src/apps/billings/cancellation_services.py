"""Cancellation settlement uses original billing rows and completed manual refunds."""

import hashlib
import json
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.businesses.models import Business
from apps.crm.models import ActivityLog
from apps.crm.services import log_activity

from .models import (
    Invoice,
    InvoiceCancellationCredit,
    InvoiceLine,
    InvoiceObligationShare,
    InvoicePayment,
    InvoiceReceiptShare,
    InvoiceRefundAllocation,
    ParcelCancellationSettlement,
)
from .services import calculate_tax_amount

ZERO = Decimal("0.00")


def _amount(value, currency):
    from .payment_services import money

    result = money(value, currency)
    if result < 0:
        raise ValidationError("Amounts cannot be negative.")
    return result


def _sum(values):
    return sum(values, ZERO)


def _access(business, actor, parcel, lock=False):
    from apps.logistics.financial_access import require_financial_access
    from apps.logistics.location_access import lock_actor_membership
    from apps.logistics.models import Parcel

    if lock:
        business = Business.objects.select_for_update().get(pk=business.pk)
        lock_actor_membership(business, actor)
    require_financial_access(business=business, actor=actor, write=True, accounting=True)
    qs = Parcel.objects.select_related("client").filter(
        business=business, client__business=business
    )
    if lock:
        qs = qs.select_for_update()
    selected = qs.filter(pk=getattr(parcel, "pk", parcel)).first()
    if selected is None:
        raise PermissionDenied("Cancelled Parcel is unavailable in this workspace.")
    if selected.current_status != "CANCELLED":
        raise ValidationError(
            "Cancel the Parcel through its operational workflow before settlement."
        )
    return business, selected


def _line_options(invoice):
    from apps.logistics.financial_coverage import (
        validate_charge_coverage,
        validate_invoice_charge_bindings,
        validate_invoice_money,
    )

    validate_invoice_money(invoice)
    validate_invoice_charge_bindings(invoice)
    if invoice.snapshot_is_legacy:
        raise ValidationError("Confirm legacy currency and tax before cancellation settlement.")
    cumulative, previous_tax, rows = ZERO, ZERO, []
    for line in invoice.lines.select_related("charge_source").order_by("pk"):
        if not line.charge_source_id:
            raise ValidationError(
                "Every shared Invoice line needs proven Logistics charge coverage."
            )
        members = validate_charge_coverage(line.charge_source)
        cumulative += line.line_total
        tax = calculate_tax_amount(subtotal=cumulative, tax_rate=invoice.tax_rate_percentage)
        rows.append(
            {
                "line": line,
                "members": sorted(members, key=lambda p: p.pk),
                "tax": tax - previous_tax,
            }
        )
        previous_tax = tax
    return rows


def _allocated(invoice, supplied):
    """Prepare a complete immutable allocation, without writing during preview."""
    currency = invoice.currency_code
    options = _line_options(invoice)
    saved = list(
        InvoiceObligationShare.objects.filter(line__invoice=invoice).select_related(
            "line", "parcel"
        )
    )
    saved_map = {f"{s.line_id}:{s.parcel_id}": s for s in saved}
    amounts = supplied.get("obligations", {})
    rows = []
    for option in options:
        line, members, tax = option["line"], option["members"], option["tax"]
        subtotal_so_far, tax_so_far = ZERO, ZERO
        for parcel in members:
            key = f"{line.pk}:{parcel.pk}"
            if saved:
                if key not in saved_map:
                    raise ValidationError("Saved obligation allocations are incomplete.")
                subtotal = saved_map[key].subtotal
                if key in amounts and _amount(amounts[key], currency) != subtotal:
                    raise ValidationError("Saved obligation allocations cannot be changed.")
            elif len(members) == 1:
                subtotal = line.line_total
            elif key in amounts:
                subtotal = _amount(amounts[key], currency)
            else:
                raise ValidationError(
                    "Explicit allocation of shared freight to every covered Parcel is required."
                )
            subtotal_so_far += subtotal
            from .payment_services import money

            allocated_tax = (
                money(tax * subtotal_so_far / line.line_total, currency)
                if line.line_total
                else ZERO
            )
            row_tax = allocated_tax - tax_so_far
            tax_so_far = allocated_tax
            row = {
                "key": key,
                "line": line,
                "parcel": parcel,
                "subtotal": subtotal,
                "tax": row_tax,
                "total": subtotal + row_tax,
                "saved": saved_map.get(key),
            }
            if saved and (saved_map[key].tax != row_tax or saved_map[key].currency != currency):
                raise ValidationError("Saved allocation monetary basis is inconsistent.")
            rows.append(row)
        if subtotal_so_far != line.line_total or tax_so_far != tax:
            raise ValidationError(
                "Parcel allocations must add up to the full original line amount."
            )
    keys = {row["key"] for row in rows}
    if set(amounts) - keys or set(saved_map) - keys:
        raise ValidationError("Unknown obligation allocation.")
    payments = list(invoice.payments.order_by("pk"))
    credits_exist = InvoiceCancellationCredit.objects.filter(
        obligation__line__invoice=invoice
    ).exists()
    if not credits_exist and any(p.kind != "RECEIPT" or p.original_id for p in payments):
        raise ValidationError(
            "Existing receipt corrections/refunds need accounting reconciliation before allocation."
        )
    receipts = [p for p in payments if p.kind == "RECEIPT"]
    provided = supplied.get("receipts", {})
    if set(provided) - {str(p.pk) for p in receipts}:
        raise ValidationError("Unknown receipt allocation.")
    receipt_rows, totals = [], {key: ZERO for key in keys}
    for receipt in receipts:
        existing = list(receipt.obligation_shares.select_related("obligation"))
        if any(
            s.business_id != invoice.business_id or s.obligation.business_id != invoice.business_id
            for s in existing
        ):
            raise ValidationError("Receipt allocation has inconsistent tenant ownership.")
        amounts_by_key = {
            f"{s.obligation.line_id}:{s.obligation.parcel_id}": s.amount for s in existing
        }
        if not existing:
            amounts_by_key = provided.get(str(receipt.pk), {})
            if not amounts_by_key and len(rows) == 1:
                amounts_by_key = {rows[0]["key"]: receipt.amount}
            if not amounts_by_key:
                raise ValidationError(
                    "Explicit allocation of each receipt across shared obligations is required."
                )
        if set(amounts_by_key) - keys:
            raise ValidationError("Receipt allocation references an unknown obligation.")
        normalized = {key: _amount(value, currency) for key, value in amounts_by_key.items()}
        if _sum(normalized.values()) != receipt.amount:
            raise ValidationError("Each receipt must be allocated in full.")
        if existing and str(receipt.pk) in provided:
            chosen = {
                key: _amount(value, currency)
                for key, value in provided[str(receipt.pk)].items()
                if _amount(value, currency)
            }
            if chosen != {key: value for key, value in normalized.items() if value}:
                raise ValidationError("Saved receipt allocations cannot be changed.")
        for key, amount in normalized.items():
            totals[key] += amount
            if amount:
                receipt_rows.append(
                    {"receipt": receipt, "key": key, "amount": amount, "saved": bool(existing)}
                )
    if not credits_exist and any(totals[row["key"]] > row["total"] for row in rows):
        raise ValidationError("Receipt allocation exceeds an original obligation.")
    return rows, receipt_rows


def settlement_options(*, business, actor, parcel):
    from apps.logistics.models import LogisticsCharge

    business, parcel = _access(business, actor, parcel)
    if (
        InvoiceLine.objects.filter(invoice__business=business, charge_source__isnull=True)
        .exclude(invoice__status="CANCELLED")
        .filter(Q(parcel=parcel) | Q(shipment__isnull=False, invoice__client=parcel.client))
        .exists()
    ):
        raise ValidationError(
            "Unlinked Invoice history requires accounting reconciliation before cancellation settlement."
        )
    charges = list(
        LogisticsCharge.objects.filter(business=business)
        .filter(
            Q(parcel=parcel)
            | Q(parcel_coverage__parcel=parcel)
            | Q(shipment__isnull=False, coverage_recorded_at__isnull=True, client=parcel.client)
        )
        .distinct()
        .order_by("pk")
    )
    invoice_ids = set()
    for charge in charges:
        invoice_ids.update(
            charge.invoice_lines.exclude(invoice__status="CANCELLED").values_list(
                "invoice_id", flat=True
            )
        )
    invoices = list(Invoice.objects.filter(business=business, pk__in=invoice_ids).order_by("pk"))
    return parcel, charges, [(invoice, _line_options(invoice)) for invoice in invoices]


@transaction.atomic
def review_cancellation(*, business, actor, parcel, choices=None):
    from apps.logistics.financial_coverage import validate_charge_coverage

    from .payment_services import _invoice_settlement

    business, parcel = _access(business, actor, parcel, lock=True)
    choices = json.loads(json.dumps(choices or {}, default=str))
    parcel, charges, invoices = settlement_options(business=business, actor=actor, parcel=parcel)
    if set(choices.get("retained", {})) - {str(c.pk) for c in charges}:
        raise ValidationError("Unknown retained fee.")
    if set(choices.get("invoices", {})) - {str(i.pk) for i, _ in invoices}:
        raise ValidationError("Unknown Invoice allocation.")
    voids, credits, invoice_plans, source = [], [], [], []
    for charge in charges:
        validate_charge_coverage(charge)
        source.append(
            [
                "charge",
                charge.pk,
                str(charge.voided_at),
                list(charge.invoice_lines.values_list("pk", "invoice_id", "invoice__status")),
            ]
        )
        if charge.voided_at:
            continue
        active = list(charge.invoice_lines.exclude(invoice__status="CANCELLED"))
        if len(active) > 1:
            raise ValidationError("Resolve ambiguous active Invoice bindings before settlement.")
        if not active:
            if charge.shipment_id:
                raise ValidationError(
                    "Uninvoiced shared freight requires explicit accounting reconciliation before settlement."
                )
            if _amount(
                choices.get("retained", {}).get(str(charge.pk), "0"), charge.currency_snapshot
            ):
                raise ValidationError(
                    "Retained fees require an existing invoiced obligation; uninvoiced charges are voided in full."
                )
            voids.append(charge)
    for invoice, _ in invoices:
        balance = _invoice_settlement(invoice)
        if balance.issues or balance.legacy_paid_unverified:
            raise ValidationError("Invoice receipt history requires accounting reconciliation.")
        allocations, receipt_rows = _allocated(
            invoice, choices.get("invoices", {}).get(str(invoice.pk), {})
        )
        source.append(
            [
                "invoice",
                invoice.pk,
                invoice.status,
                str(invoice.total),
                str(invoice.updated_at),
                list(invoice.payments.values_list("pk", "kind", "amount", "original_id")),
                list(invoice.lines.values_list("pk", "line_total", "charge_source_id")),
                list(
                    InvoiceCancellationCredit.objects.filter(
                        obligation__line__invoice=invoice
                    ).values_list("pk", "subtotal", "tax")
                ),
            ]
        )
        invoice_credits = []
        for row in allocations:
            if row["parcel"].pk != parcel.pk:
                continue
            retained = _amount(
                choices.get("retained", {}).get(str(row["line"].charge_source_id), "0"),
                invoice.currency_code,
            )
            if retained > row["subtotal"]:
                raise ValidationError("Retained fee cannot exceed the cancelled Parcel obligation.")
            retained_tax = (
                row["tax"]
                if retained == row["subtotal"]
                else min(
                    row["tax"],
                    calculate_tax_amount(subtotal=retained, tax_rate=invoice.tax_rate_percentage),
                )
            )
            credit = {
                **row,
                "credit_subtotal": row["subtotal"] - retained,
                "credit_tax": row["tax"] - retained_tax,
                "retained": retained + retained_tax,
            }
            credit["credit_total"] = credit["credit_subtotal"] + credit["credit_tax"]
            invoice_credits.append(credit)
            credits.append(credit)
        # Preview uses complete shares; existing credits and recorded refunds stay intact.
        before = allocation_balances(invoice, allocations, receipt_rows)
        preview = {key: dict(value) for key, value in before.items()}
        for credit in invoice_credits:
            preview[credit["key"]]["obligation"] -= credit["credit_total"]
        debt = _sum(max(v["obligation"] - v["net"], ZERO) for v in preview.values())
        refund = _sum(max(v["net"] - v["obligation"], ZERO) for v in preview.values())
        invoice_plans.append(
            {
                "invoice": invoice,
                "allocations": allocations,
                "receipts": receipt_rows,
                "credits": invoice_credits,
                "debt": debt,
                "refund_due": refund,
            }
        )
    encoded = json.dumps(source, default=str, sort_keys=True)
    return {
        "parcel": parcel,
        "voids": voids,
        "credits": credits,
        "invoices": invoice_plans,
        "fingerprint": hashlib.sha256(encoded.encode()).hexdigest(),
        "choices": choices,
    }


def allocation_balances(invoice, rows, receipts):
    values = {r["key"]: {"obligation": r["total"], "net": ZERO} for r in rows}
    for row in receipts:
        values[row["key"]]["net"] += row["amount"]
    for credit in InvoiceCancellationCredit.objects.filter(
        obligation__line__invoice=invoice
    ).select_related("obligation"):
        key = f"{credit.obligation.line_id}:{credit.obligation.parcel_id}"
        if key not in values:
            raise ValidationError("Credit allocation is inconsistent.")
        values[key]["obligation"] -= credit.total
    for allocation in InvoiceRefundAllocation.objects.filter(
        refund__invoice=invoice
    ).select_related("refund", "credit__obligation"):
        key = f"{allocation.credit.obligation.line_id}:{allocation.credit.obligation.parcel_id}"
        values[key]["net"] -= allocation.refund.amount
    return values


@transaction.atomic
def confirm_cancellation(
    *, business, actor, parcel, choices, fingerprint, idempotency_key, reason_reference
):
    from apps.logistics.billing_services import void_charge

    from .payment_services import _key

    business, parcel = _access(business, actor, parcel, lock=True)
    key = _key(idempotency_key)
    choices = json.loads(json.dumps(choices, default=str))
    request = {"choices": choices, "reason": reason_reference.strip(), "fingerprint": fingerprint}
    previous = ParcelCancellationSettlement.objects.filter(business=business, parcel=parcel).first()
    if previous:
        if previous.idempotency_key != key or previous.request_snapshot != request:
            raise ValidationError("This cancelled Parcel already has a confirmed settlement.")
        return previous
    if not request["reason"]:
        raise ValidationError("A cancellation settlement reason is required.")
    plan = review_cancellation(business=business, actor=actor, parcel=parcel, choices=choices)
    if fingerprint != plan["fingerprint"]:
        raise ValidationError(
            "Financial records changed after preview. Review the settlement again."
        )
    case = ParcelCancellationSettlement(
        business=business,
        parcel=parcel,
        recorded_by=actor,
        idempotency_key=key,
        reason_reference=request["reason"],
        request_snapshot=request,
    )._append()
    for charge in plan["voids"]:
        void_charge(
            business=business, actor=actor, charge=charge, reason_reference=request["reason"][:160]
        )
    for item in plan["invoices"]:
        invoice = item["invoice"]
        if invoice.financial_snapshot_at is None:
            invoice.financial_snapshot_at = timezone.now()
            invoice.save(update_fields=["financial_snapshot_at"])
        by_key = {}
        for row in item["allocations"]:
            share = (
                row["saved"]
                or InvoiceObligationShare(
                    business=business,
                    recorded_by=actor,
                    line=row["line"],
                    parcel=row["parcel"],
                    subtotal=row["subtotal"],
                    tax=row["tax"],
                    currency=invoice.currency_code,
                )._append()
            )
            by_key[row["key"]] = share
        for row in item["receipts"]:
            if not row["saved"]:
                InvoiceReceiptShare(
                    business=business,
                    recorded_by=actor,
                    receipt=row["receipt"],
                    obligation=by_key[row["key"]],
                    amount=row["amount"],
                )._append()
        for row in item["credits"]:
            InvoiceCancellationCredit(
                business=business,
                recorded_by=actor,
                settlement=case,
                obligation=by_key[row["key"]],
                subtotal=row["credit_subtotal"],
                tax=row["credit_tax"],
            )._append()
    log_activity(
        business=business,
        actor=actor,
        client=parcel.client,
        action_type=ActivityLog.ActionType.STATUS_CHANGED,
        summary="Parcel cancellation settlement confirmed",
        payload={
            "parcel_id": parcel.pk,
            "settlement_id": case.pk,
            "reason_reference": request["reason"],
        },
    )
    return case


def projection(invoice, entries):
    """Validate the complete graph; never derive shares from current Shipment membership."""
    credits = list(
        InvoiceCancellationCredit.objects.filter(obligation__line__invoice=invoice).select_related(
            "obligation", "settlement"
        )
    )
    if not credits:
        return None
    rows, receipts = _allocated(invoice, {})
    if any(
        not row["saved"] or row["saved"].business_id != invoice.business_id for row in rows
    ) or any(not r["saved"] for r in receipts):
        raise ValidationError("Cancellation financial allocations are incomplete.")
    for credit in credits:
        credit.clean()
        if credit.business_id != invoice.business_id:
            raise ValidationError("Cross-tenant cancellation credit.")
    allocations = list(
        InvoiceRefundAllocation.objects.filter(refund__invoice=invoice).select_related(
            "refund", "credit__obligation"
        )
    )
    if {a.refund_id for a in allocations} != {p.pk for p in entries if p.kind != "RECEIPT"}:
        raise ValidationError(
            "Every cancellation refund must be allocated; reversals/corrections require reconciliation."
        )
    receipt_map = {(r["receipt"].pk, r["key"]): r["amount"] for r in receipts}
    refunded = {}
    for allocation in allocations:
        allocation.clean()
        if allocation.business_id != invoice.business_id:
            raise ValidationError("Cross-tenant cancellation refund.")
        key = f"{allocation.credit.obligation.line_id}:{allocation.credit.obligation.parcel_id}"
        pair = (allocation.refund.original_id, key)
        refunded[pair] = refunded.get(pair, ZERO) + allocation.refund.amount
        if refunded[pair] > receipt_map.get(pair, ZERO):
            raise ValidationError("Refund exceeds the original allocated receipt.")
    balances = allocation_balances(invoice, rows, receipts)
    for value in balances.values():
        if value["net"] < 0 or value["obligation"] < 0:
            raise ValidationError("Cancellation allocations have an invalid balance.")
    for credit in credits:
        if _sum(a.refund.amount for a in allocations if a.credit_id == credit.pk) > credit.total:
            raise ValidationError("Refunds exceed the cancellation credit.")
    return {
        "rows": rows,
        "receipts": receipts,
        "balances": balances,
        "credit_total": _sum(c.total for c in credits),
        "adjusted_total": _sum(v["obligation"] for v in balances.values()),
        "outstanding": _sum(max(v["obligation"] - v["net"], ZERO) for v in balances.values()),
        "refund_due": _sum(max(v["net"] - v["obligation"], ZERO) for v in balances.values()),
    }


def parcel_invoice_settled(invoice, parcel_id):
    state = getattr(invoice, "_cancellation_projection", None)
    if state is None:
        return None
    own = [v for key, v in state["balances"].items() if key.endswith(f":{parcel_id}")]
    return bool(own) and all(v["net"] == v["obligation"] for v in own)


def refund_choices(invoice, original=None):
    from .payment_services import _invoice_settlement

    balance = _invoice_settlement(invoice)
    state = getattr(invoice, "_cancellation_projection", None)
    if balance.issues or not state:
        return []
    result = []
    for credit in InvoiceCancellationCredit.objects.filter(
        obligation__line__invoice=invoice
    ).select_related("obligation__parcel", "obligation__line"):
        key = f"{credit.obligation.line_id}:{credit.obligation.parcel_id}"
        value = state["balances"][key]
        due = max(value["net"] - value["obligation"], ZERO)
        if original:
            available = _sum(
                r["amount"]
                for r in state["receipts"]
                if r["key"] == key and r["receipt"].pk == original.pk
            )
            available -= _sum(
                a.refund.amount
                for a in credit.refund_allocations.filter(refund__original=original).select_related(
                    "refund"
                )
            )
            due = min(due, available)
        if due > 0:
            result.append((credit, due))
    return result


def check_refund(*, invoice, original, credit, amount, key):
    selected = InvoiceCancellationCredit.objects.filter(
        pk=getattr(credit, "pk", credit),
        business=invoice.business,
        obligation__line__invoice=invoice,
    ).first()
    if selected is None:
        raise ValidationError("Choose the credited Parcel obligation for this refund.")
    previous = InvoicePayment.objects.filter(business=invoice.business, idempotency_key=key).first()
    if previous:
        allocation = InvoiceRefundAllocation.objects.filter(
            refund=previous, credit=selected
        ).first()
        if allocation is None:
            raise ValidationError("Retry token belongs to a different refund allocation.")
        return selected
    choices = {c.pk: due for c, due in refund_choices(invoice, original)}
    if amount <= 0 or amount > choices.get(selected.pk, ZERO):
        raise ValidationError(
            "Refund exceeds the amount due on this credited obligation and original receipt."
        )
    return selected


def receipt_allocation_fields(invoice):
    from .payment_services import _invoice_settlement

    balance = _invoice_settlement(invoice)
    state = getattr(invoice, "_cancellation_projection", None)
    if balance.issues or not state:
        return []
    return [
        (
            row["saved"],
            max(
                state["balances"][row["key"]]["obligation"] - state["balances"][row["key"]]["net"],
                ZERO,
            ),
        )
        for row in state["rows"]
        if state["balances"][row["key"]]["obligation"] > state["balances"][row["key"]]["net"]
    ]


def allocate_new_receipt(*, invoice, receipt, actor, supplied=None):
    # Called after inserting the receipt, so use the preceding validated graph.
    state = getattr(invoice, "_cancellation_projection", None)
    if state is None:
        if supplied:
            raise ValidationError("Unexpected receipt allocation on an unallocated Invoice.")
        return
    if receipt.obligation_shares.exists():
        if supplied:
            actual = {str(s.obligation_id): s.amount for s in receipt.obligation_shares.all()}
            requested = {
                str(k): _amount(v, receipt.currency)
                for k, v in supplied.items()
                if _amount(v, receipt.currency)
            }
            if actual != requested:
                raise ValidationError("Receipt retry changed its saved allocations.")
        return
    available = {
        str(r["saved"].pk): (
            r["saved"],
            max(
                state["balances"][r["key"]]["obligation"] - state["balances"][r["key"]]["net"], ZERO
            ),
        )
        for r in state["rows"]
    }
    positive = {key: value for key, value in available.items() if value[1] > 0}
    if supplied is None and len(positive) == 1:
        supplied = {next(iter(positive)): receipt.amount}
    if supplied is None:
        raise ValidationError("Explicit receipt allocation is required for this shared Invoice.")
    amounts = {str(k): _amount(v, receipt.currency) for k, v in supplied.items()}
    if set(amounts) - set(available) or _sum(amounts.values()) != receipt.amount:
        raise ValidationError("Allocate the receipt exactly across valid outstanding obligations.")
    for key, amount in amounts.items():
        share, debt = available[key]
        if amount > debt:
            raise ValidationError("Receipt allocation exceeds the obligation outstanding.")
        if amount:
            InvoiceReceiptShare(
                business=invoice.business,
                recorded_by=actor,
                receipt=receipt,
                obligation=share,
                amount=amount,
            )._append()
