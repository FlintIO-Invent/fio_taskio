"""Saved charge snapshots integrated with Motionmate's Client-owned invoices."""

from decimal import Decimal
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.billings.models import Invoice, InvoiceLine
from apps.billings.services import create_invoice_for_client, recalculate_invoice_totals
from apps.businesses.models import Business, BusinessSubscription, BusinessUser
from apps.businesses.utils import BILLING_MANAGE_ROLES, BILLING_VIEW_ROLES
from apps.crm.models import BusinessService, Client

from .models import LogisticsCharge, Parcel, Shipment


def require_billing_access(*, business, actor, write=False, target_kind="parcel"):
    current = Business.objects.filter(
        pk=getattr(business, "pk", None), is_active=True, vertical="LOGISTICS"
    ).first()
    if (
        current is None
        or not BusinessUser.objects.filter(
            business=current,
            user_id=getattr(actor, "pk", None),
            is_active=True,
            user__is_active=True,
            role__in=BILLING_MANAGE_ROLES if write else BILLING_VIEW_ROLES,
        ).exists()
    ):
        raise PermissionDenied("Your workspace role does not permit Logistics billing.")
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
    if actor is not None:
        from .location_access import scope_records

        qs = scope_records(qs, business=business, actor=actor)
    if lock:
        qs = qs.select_for_update()
    target = qs.first()
    if target is None:
        raise ValidationError("Billing target is unavailable in this workspace.")
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
):
    current = Business.objects.select_for_update().get(pk=business.pk)
    kind = "parcel" if parcel is not None else "shipment"
    current = require_billing_access(business=current, actor=actor, write=True, target_kind=kind)
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
    )
    previous = LogisticsCharge.objects.filter(business=current, idempotency_key=key).first()
    if previous:
        if any(getattr(previous, name) != value for name, value in fields.items()):
            raise ValidationError("This retry token has already been used for another charge.")
        return previous
    if saved_service and not saved_service.is_active:
        raise ValidationError("Choose an active service for a new charge.")
    charge = LogisticsCharge(
        **fields,
        idempotency_key=key,
        created_by=actor,
        target_reference=(
            (target.internal_reference or target.tracking_code)
            if kind == "parcel"
            else target.reference
        ),
    )
    charge._domain_save(force_insert=True)
    return charge


@transaction.atomic
def invoice_charges(*, business, actor, charge_ids, invoice=None):
    current = Business.objects.select_for_update().get(pk=business.pk)
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
    linked = [charge.invoice_line_id for charge in charges]
    if any(linked):
        if all(linked) and len({charge.invoice_line.invoice_id for charge in charges}) == 1:
            previous = charges[0].invoice_line.invoice
            if invoice is None or previous.pk == getattr(invoice, "pk", invoice):
                return previous  # Exact submission replay cannot create a second invoice.
        raise ValidationError("A selected charge has already been invoiced.")
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
    else:
        selected = create_invoice_for_client(actor=actor, client=charges[0].client)
    for charge in charges:
        line = InvoiceLine.objects.create(
            invoice=selected,
            service=charge.service,
            parcel=charge.parcel,
            shipment=charge.shipment,
            description=charge.invoice_description,
            quantity=charge.quantity,
            unit_price=charge.unit_price,
        )
        charge.invoice_line = line
        charge._domain_save(update_fields=["invoice_line"])
    recalculate_invoice_totals(selected)
    return selected
