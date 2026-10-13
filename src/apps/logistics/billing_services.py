"""Saved charge snapshots integrated with Motionmate's Client-owned invoices."""

from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.billings.models import Invoice, InvoiceLine
from apps.billings.services import create_invoice_for_client, recalculate_invoice_totals
from apps.businesses.models import Business, BusinessSubscription
from apps.crm.models import BusinessService, Client

from .charge_identity import logical_charge_key, purpose_key
from .financial_access import (
    require_financial_access,
    require_financial_target,
    require_invoice_access,
)
from .location_access import lock_actor_membership
from .models import LogisticsCharge, LogisticsChargeParcel, Parcel, Shipment


def require_billing_access(*, business, actor, write=False, target_kind="parcel"):
    current = require_financial_access(business=business, actor=actor, write=write)
    subscription = (
        BusinessSubscription.objects.select_related("business", "plan")
        .filter(business=current)
        .first()
    )
    modules = ("invoicing", "parcels" if target_kind == "parcel" else "shipments")
    if not subscription or not all(
        subscription.can_use_module(module) if write else subscription.can_view_module(module)
        for module in modules
    ):
        raise PermissionDenied("Your workspace subscription does not permit Logistics billing.")
    return current


def shipment_billing_client(shipment):
    members = Parcel.objects.filter(shipment=shipment)
    if (
        members.exclude(business_id=shipment.business_id).exists()
        or members.exclude(client__business_id=shipment.business_id).exists()
    ):
        raise ValidationError("Shipment client relationships require integrity review.")
    client_ids = set(members.values_list("client_id", flat=True))
    # Once charges exist, their saved client establishes the billing relationship,
    # including after the last parcel is explicitly removed from the grouping.
    client_ids.update(shipment.charges.values_list("client_id", flat=True))
    if len(client_ids) != 1:
        raise ValidationError(
            "Shipment billing requires exactly one client. Bill individual parcels for mixed-client shipments."
        )
    return Client.objects.get(pk=client_ids.pop(), business_id=shipment.business_id)


def _target(business, parcel=None, shipment=None, *, lock=False, actor=None):
    if (parcel is None) == (shipment is None):
        raise ValidationError("Select exactly one parcel or shipment.")
    model, value = (Parcel, parcel) if parcel is not None else (Shipment, shipment)
    qs = model.objects.filter(business=business, pk=getattr(value, "pk", value))
    if lock:
        qs = qs.select_for_update()
    target = qs.first()
    if target is None:
        raise ValidationError("Billing target is unavailable in this workspace.")
    from .financial_coverage import validate_location_integrity

    validate_location_integrity(target)
    if actor is not None:
        require_financial_target(business=business, actor=actor, target=target, write=lock)
    client = target.client if model is Parcel else shipment_billing_client(target)
    if client.business_id != business.pk:
        raise ValidationError("Billing client must belong to this workspace.")
    return target, client


@transaction.atomic
def add_charge(
    *,
    business,
    actor,
    parcel=None,
    shipment=None,
    service=None,
    description="",
    quantity=Decimal("1.00"),
    unit_price=None,
    idempotency_key,
    occurrence_reference="",
    _supersedes=None,
    _coverage_parcels=None,
    _currency_snapshot=None,
):
    current = Business.objects.select_for_update().get(pk=business.pk)
    lock_actor_membership(current, actor)
    kind = "parcel" if parcel is not None else "shipment"
    current = require_billing_access(business=current, actor=actor, write=True, target_kind=kind)
    if _supersedes is not None or _coverage_parcels is not None or _currency_snapshot is not None:
        require_financial_access(business=current, actor=actor, write=True, accounting=True)
        if _supersedes is None:
            raise ValidationError(
                "Alternate snapshots require an explicit saved-charge correction."
            )
        _supersedes = LogisticsCharge.objects.get(business=current, pk=_supersedes.pk)
        if not _supersedes.voided_at or _currency_snapshot != _supersedes.currency_snapshot:
            raise ValidationError("Correction must preserve the voided charge's currency.")
        if {item.pk for item in _coverage_parcels or []} != set(
            _supersedes.parcel_coverage.values_list("parcel_id", flat=True)
        ):
            raise ValidationError("Correction must preserve exact billed Parcel membership.")
    target, client = _target(current, parcel, shipment, lock=True, actor=actor)
    try:
        key = UUID(str(idempotency_key))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("A valid charge retry token is required.") from exc
    saved_service = None
    if service is not None:
        saved_service = BusinessService.objects.filter(
            business=current, pk=getattr(service, "pk", service)
        ).first()
        if saved_service is None:
            raise ValidationError("Service is unavailable in this workspace.")
    price = saved_service.unit_price if saved_service and unit_price is None else unit_price
    try:
        quantity, price = Decimal(str(quantity)), Decimal(str(price))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("Enter finite charge quantities and prices.") from exc
    if not quantity.is_finite() or not price.is_finite() or quantity <= 0 or price < 0:
        raise ValidationError(
            "Quantity must be positive and price nonnegative; both must be finite."
        )
    description = description.strip() or (
        (saved_service.description.strip() or saved_service.name)[:160] if saved_service else ""
    )
    fields = dict(
        business=current,
        client=client,
        service=saved_service,
        description=description,
        quantity=quantity,
        unit_price=price,
        parcel=target if kind == "parcel" else None,
        shipment=target if kind == "shipment" else None,
        occurrence_reference=occurrence_reference.strip(),
        supersedes=_supersedes,
    )
    previous = LogisticsCharge.objects.filter(business=current, idempotency_key=key).first()
    if previous:
        if any(getattr(previous, name) != value for name, value in fields.items()):
            raise ValidationError("This retry token has already been used for another charge.")
        return previous
    coverage = (
        list(_coverage_parcels)
        if _coverage_parcels is not None
        else (
            [target]
            if kind == "parcel"
            else list(Parcel.objects.select_for_update().filter(shipment=target).order_by("pk"))
        )
    )
    if not coverage:
        raise ValidationError("Shipment freight requires an explicit nonempty Parcel membership.")
    if any((item.business_id, item.client_id) != (current.pk, client.pk) for item in coverage):
        raise ValidationError("Charge coverage must have one workspace and client.")
    logical = logical_charge_key(
        parcel_id=target.pk if kind == "parcel" else None,
        shipment_id=target.pk if kind == "shipment" else None,
        service_id=getattr(saved_service, "pk", None),
        description=description,
        occurrence_reference=occurrence_reference,
    )
    candidates = (
        LogisticsCharge.objects.filter(business=current, voided_at__isnull=True)
        .filter(
            Q(logical_key=logical)
            | Q(parcel_coverage__parcel_id__in=[item.pk for item in coverage])
            | Q(shipment__isnull=False, coverage_recorded_at__isnull=True, client=client)
        )
        .distinct()
    )
    purpose = purpose_key(getattr(saved_service, "pk", None), description)
    for existing in candidates:
        if existing.logical_key == logical or (
            purpose_key(existing.service_id, existing.description) == purpose
            and existing.occurrence_reference.strip().casefold()
            == occurrence_reference.strip().casefold()
        ):
            raise ValidationError(
                "This logical charge already exists. Reuse it or explicitly correct it; a new retry token is not a new obligation."
            )
    if (
        _supersedes is None
        and LogisticsCharge.objects.filter(
            business=current, logical_key=logical, voided_at__isnull=False
        ).exists()
    ):
        raise ValidationError(
            "This logical obligation has voided history. Use an explicit correction or a distinct occurrence reference."
        )
    if saved_service and not saved_service.is_active and _supersedes is None:
        raise ValidationError("Choose an active service for a new charge.")
    charge = LogisticsCharge(
        **fields,
        idempotency_key=key,
        created_by=actor,
        logical_key=logical,
        currency_snapshot=_currency_snapshot or current.currency,
        currency_is_legacy=bool(_supersedes and _supersedes.currency_is_legacy),
        target_reference=(
            (target.internal_reference or target.tracking_code)
            if kind == "parcel"
            else target.reference
        ),
    )
    charge._domain_save(force_insert=True)
    for item in coverage:
        LogisticsChargeParcel(charge=charge, parcel=item)._domain_save(force_insert=True)
    charge.coverage_recorded_at = timezone.now()
    charge._domain_save(update_fields=["coverage_recorded_at"])
    return charge


@transaction.atomic
def invoice_charges(*, business, actor, charge_ids, invoice=None):
    current = Business.objects.select_for_update().get(pk=business.pk)
    lock_actor_membership(current, actor)
    require_financial_access(business=current, actor=actor, write=True)
    ids = set(charge_ids)
    if not ids:
        raise ValidationError("Select at least one uninvoiced charge.")
    charges = list(
        LogisticsCharge.objects.select_for_update()
        .filter(business=current, pk__in=ids)
        .order_by("pk")
    )
    if len(charges) != len(ids):
        raise ValidationError("Charges are unavailable in this workspace.")
    for charge in charges:
        require_billing_access(
            business=current,
            actor=actor,
            write=True,
            target_kind="parcel" if charge.parcel_id else "shipment",
        )
        _, client = _target(current, charge.parcel, charge.shipment, lock=True, actor=actor)
        if client.pk != charge.client_id:
            raise ValidationError("Charge client no longer matches its billing target.")
        charge.full_clean()
    if len({charge.client_id for charge in charges}) != 1:
        raise ValidationError("All charges must belong to the same client.")
    if any(charge.voided_at for charge in charges):
        raise ValidationError("Voided charges cannot be invoiced or reissued.")
    from .financial_coverage import validate_charge_coverage

    for charge in charges:
        validate_charge_coverage(charge)
    active = {
        charge.pk: list(charge.invoice_lines.exclude(invoice__status=Invoice.Status.CANCELLED))
        for charge in charges
    }
    if any(active.values()):
        if all(len(lines) == 1 for lines in active.values()):
            previous_ids = {lines[0].invoice_id for lines in active.values()}
            if len(previous_ids) == 1:
                previous = next(iter(active.values()))[0].invoice
                if invoice is None or previous.pk == getattr(invoice, "pk", invoice):
                    require_invoice_access(
                        business=current, actor=actor, invoice=previous, write=True
                    )
                    return previous
        raise ValidationError("A selected charge already has an active Invoice binding.")
    if any(charge.currency_is_legacy or charge.logical_key is None for charge in charges):
        raise ValidationError(
            "Confirm legacy currency and reconcile ambiguous logical charges before issuing/reissuing them."
        )
    currencies = {charge.currency_snapshot for charge in charges}
    if len(currencies) != 1 or None in currencies:
        raise ValidationError("Invoice charges must share one known saved currency.")
    rates = set()
    for charge in charges:
        historical = charge.invoice_lines.order_by("-pk").first()
        if historical is None and charge.supersedes_id:
            historical = charge.supersedes.invoice_lines.order_by("-pk").first()
        if historical:
            if historical.invoice.snapshot_is_legacy:
                raise ValidationError("Confirm legacy Invoice monetary snapshots before reissue.")
            rates.add(historical.invoice.tax_rate_percentage)
    if len(rates) > 1:
        raise ValidationError(
            "Reissue charges with different saved tax rates on separate Invoices."
        )
    rate = next(iter(rates)) if rates else current.tax_rate
    currency = currencies.pop()
    if invoice is not None:
        selected = (
            Invoice.objects.select_for_update()
            .filter(
                pk=getattr(invoice, "pk", invoice),
                business=current,
                client_id=charges[0].client_id,
                status=Invoice.Status.DRAFT,
            )
            .first()
        )
        if selected is None:
            raise ValidationError("Choose a draft invoice for this workspace and client.")
        require_invoice_access(business=current, actor=actor, invoice=selected, write=True)
        from .financial_coverage import validate_invoice_charge_bindings

        validate_invoice_charge_bindings(selected)
        if selected.currency_code != currency or (rates and selected.tax_rate_percentage != rate):
            raise ValidationError("Draft currency/tax must match the saved charge obligations.")
    else:
        selected = create_invoice_for_client(
            actor=actor,
            client=charges[0].client,
            logistics_target=charges[0].parcel or charges[0].shipment,
            currency_snapshot=currency,
            tax_rate_snapshot=rate,
        )
    for charge in charges:
        line = InvoiceLine.objects.create(
            invoice=selected,
            charge_source=charge,
            service=charge.service,
            parcel=charge.parcel,
            shipment=charge.shipment,
            description=charge.invoice_description,
            quantity=charge.quantity,
            unit_price=charge.unit_price,
        )
        if charge.invoice_line_id is None:
            charge.invoice_line = line
            charge._domain_save(update_fields=["invoice_line"])
    recalculate_invoice_totals(selected, actor=actor)
    return selected


@transaction.atomic
def void_charge(*, business, actor, charge, reason_reference):
    current = Business.objects.select_for_update().get(pk=business.pk)
    lock_actor_membership(current, actor)
    require_financial_access(business=current, actor=actor, write=True, accounting=True)
    selected = (
        LogisticsCharge.objects.select_for_update()
        .filter(business=current, pk=getattr(charge, "pk", charge))
        .first()
    )
    if selected is None:
        raise ValidationError("Charge is unavailable in this workspace.")
    if not reason_reference.strip():
        raise ValidationError("A correction/cancellation reason reference is required.")
    if (
        selected.invoice_line_id
        and selected.invoice_line.invoice.status != Invoice.Status.CANCELLED
    ) or selected.invoice_lines.exclude(invoice__status=Invoice.Status.CANCELLED).exists():
        raise ValidationError(
            "Cancel every linked Invoice before voiding or correcting its charge. Paid Invoices require a separate settlement process."
        )
    if selected.voided_at:
        if selected.void_reason_reference != reason_reference.strip():
            raise ValidationError("A voided charge retains its original reason.")
        return selected
    selected.voided_at = timezone.now()
    selected.void_reason_reference = reason_reference.strip()
    selected._domain_save(update_fields=["voided_at", "void_reason_reference"])
    from apps.crm.models import ActivityLog
    from apps.crm.services import log_activity

    log_activity(
        business=current,
        actor=actor,
        client=selected.client,
        action_type=ActivityLog.ActionType.STATUS_CHANGED,
        summary="Logistics charge voided",
        payload={"charge_id": selected.pk, "reason_reference": reason_reference.strip()},
    )
    return selected


@transaction.atomic
def correct_charge(
    *,
    business,
    actor,
    charge,
    reason_reference,
    idempotency_key,
    quantity=None,
    unit_price=None,
    description=None,
):
    current = Business.objects.select_for_update().get(pk=business.pk)
    lock_actor_membership(current, actor)
    require_financial_access(business=current, actor=actor, write=True, accounting=True)
    old = LogisticsCharge.objects.select_for_update().get(
        business=current, pk=getattr(charge, "pk", charge)
    )
    from .financial_coverage import validate_charge_coverage

    validate_charge_coverage(old)
    replacement = LogisticsCharge.objects.filter(supersedes=old).first()
    if replacement:
        if (
            str(replacement.idempotency_key) == str(idempotency_key)
            and old.void_reason_reference == reason_reference.strip()
            and (quantity is None or replacement.quantity == quantity)
            and (unit_price is None or replacement.unit_price == unit_price)
            and (description is None or replacement.description == description)
        ):
            return replacement
        raise ValidationError(
            "This charge already has an explicit correction; correct its replacement instead."
        )
    old = void_charge(business=current, actor=actor, charge=old, reason_reference=reason_reference)
    return add_charge(
        business=current,
        actor=actor,
        parcel=old.parcel,
        shipment=old.shipment,
        service=old.service,
        description=old.description if description is None else description,
        quantity=old.quantity if quantity is None else quantity,
        unit_price=old.unit_price if unit_price is None else unit_price,
        idempotency_key=idempotency_key,
        occurrence_reference=old.occurrence_reference,
        _supersedes=old,
        _coverage_parcels=[entry.parcel for entry in old.parcel_coverage.select_related("parcel")],
        _currency_snapshot=old.currency_snapshot,
    )


@transaction.atomic
def confirm_legacy_charge_currency(*, business, actor, charge, currency, reason_reference):
    """Attest the observed historical label with evidence; never rewrite money/currency."""
    current = Business.objects.select_for_update().get(pk=business.pk)
    lock_actor_membership(current, actor)
    require_financial_access(business=current, actor=actor, write=True, accounting=True)
    selected = LogisticsCharge.objects.select_for_update().get(
        business=current, pk=getattr(charge, "pk", charge)
    )
    if not reason_reference.strip() or currency != selected.currency_snapshot:
        raise ValidationError(
            "Confirm the saved currency with documentary evidence; conflicting history requires manual reconciliation."
        )
    from .financial_coverage import validate_charge_coverage

    validate_charge_coverage(selected)
    if selected.currency_is_legacy:
        selected.currency_is_legacy = False
        selected._domain_save(update_fields=["currency_is_legacy"])
        from apps.crm.models import ActivityLog
        from apps.crm.services import log_activity

        log_activity(
            actor=actor,
            business=current,
            client=selected.client,
            action_type=ActivityLog.ActionType.STATUS_CHANGED,
            summary="Historical charge currency confirmed",
            payload={
                "charge_id": selected.pk,
                "reason_reference": reason_reference.strip(),
                "currency": currency,
            },
        )
    return selected


@transaction.atomic
def confirm_legacy_invoice_snapshot(
    *, business, actor, invoice, currency, tax_rate, reason_reference
):
    current = Business.objects.select_for_update().get(pk=business.pk)
    lock_actor_membership(current, actor)
    selected = Invoice.objects.select_for_update().get(
        business=current, pk=getattr(invoice, "pk", invoice)
    )
    require_invoice_access(
        business=current, actor=actor, invoice=selected, write=True, accounting=True
    )
    if (
        not reason_reference.strip()
        or currency != selected.currency_code
        or Decimal(str(tax_rate)) != selected.tax_rate_percentage
    ):
        raise ValidationError(
            "Confirm the saved currency/tax label with documentary evidence; conflicting history requires manual reconciliation."
        )
    from apps.billings.services import calculate_tax_amount

    if (
        calculate_tax_amount(subtotal=selected.subtotal, tax_rate=selected.tax_rate_percentage)
        != selected.tax
        or selected.total != selected.subtotal + selected.tax
    ):
        raise ValidationError(
            "Historical totals do not reconcile with the observed tax label; manual reconciliation is required."
        )
    if selected.snapshot_is_legacy:
        selected.snapshot_is_legacy = False
        selected.save(update_fields=["snapshot_is_legacy"])
        from apps.crm.models import ActivityLog
        from apps.crm.services import log_activity

        log_activity(
            actor=actor,
            business=current,
            client=selected.client,
            action_type=ActivityLog.ActionType.STATUS_CHANGED,
            summary="Historical Invoice financial snapshot confirmed",
            payload={
                "invoice_id": selected.pk,
                "reason_reference": reason_reference.strip(),
                "currency": currency,
                "tax_rate": str(tax_rate),
            },
        )
    return selected
