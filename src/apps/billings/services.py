from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.businesses.models import Business
from apps.crm.models import ActivityLog, Client, Lead
from apps.crm.services import log_activity

from .models import Invoice, InvoiceLine

if TYPE_CHECKING:
    from apps.appointments.models import Appointment


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_tax_amount(*, subtotal: Decimal, tax_rate: Decimal) -> Decimal:
    return _quantize_money(subtotal * (tax_rate / Decimal("100")))


def generate_invoice_number(*, business) -> str:
    prefix = (business.invoice_prefix or "INV").strip().upper()
    start_number = max(int(business.invoice_start_number or 1), 1)
    width = max(4, len(str(start_number)))
    next_number = start_number

    while True:
        candidate = f"{prefix}-{next_number:0{width}d}"
        if not Invoice.objects.filter(business=business, invoice_number=candidate).exists():
            return candidate
        next_number += 1


def _client_defaults_for_lead(lead: Lead) -> dict[str, str]:
    fallback_name = f"{lead.first_name} {lead.last_name}".strip() or "Unknown Client"
    return {
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "phone": lead.phone,
        "company_name": lead.company_name or fallback_name,
        "street_address": lead.street_address or "N/A",
        "district": lead.district,
        "country": lead.country or "Sint Maarten",
        "postal_code": lead.postal_code or "N/A",
        "message": lead.message,
        "notes": lead.notes,
    }


def _client_from_lead(lead: Lead) -> Client:
    defaults = _client_defaults_for_lead(lead)
    defaults["business"] = lead.business
    client, _created = Client.objects.get_or_create(
        email=lead.email,
        business=lead.business,
        defaults=defaults,
    )

    updated_fields: list[str] = []
    for field_name, new_value in defaults.items():
        if not new_value:
            continue
        if getattr(client, field_name) != new_value:
            setattr(client, field_name, new_value)
            updated_fields.append(field_name)

    if updated_fields:
        client.save(update_fields=updated_fields)

    return client


@transaction.atomic
def create_invoice_for_client(
    *,
    actor,
    client: Client,
    lead: Lead | None = None,
    appointment: Appointment | None = None,
    notes: str = "",
    logistics_target=None,
    currency_snapshot=None,
    tax_rate_snapshot=None,
) -> Invoice:
    business = client.business or (lead.business if lead is not None else None)
    if business is None:
        raise ValueError("Invoices require a business-scoped client or lead.")

    business = Business.objects.select_for_update().get(pk=business.pk)
    if business.vertical == Business.Vertical.LOGISTICS:
        from apps.logistics.financial_access import (
            require_financial_access,
            require_financial_target,
        )
        from apps.logistics.location_access import lock_actor_membership

        lock_actor_membership(business, actor)
        require_financial_access(
            business=business, actor=actor, write=True, accounting=logistics_target is None
        )
        if logistics_target is not None:
            logistics_target = (
                type(logistics_target)
                .objects.select_for_update()
                .get(pk=logistics_target.pk, business=business)
            )
            require_financial_target(
                business=business, actor=actor, target=logistics_target, write=True
            )
            from apps.logistics.billing_services import shipment_billing_client
            from apps.logistics.models import Parcel

            target_client = (
                logistics_target.client
                if isinstance(logistics_target, Parcel)
                else shipment_billing_client(logistics_target)
            )
            if target_client.pk != client.pk:
                raise ValueError("Invoice client must match its Logistics target.")

    if appointment is not None:
        if appointment.business_id != business.id:
            raise ValueError("Appointment must belong to the same workspace as the invoice client.")
        if appointment.client_id != client.id:
            raise ValueError("Appointment must belong to the same client as the invoice.")

    linked_lead = lead if lead is not None else getattr(appointment, "source_lead", None)
    invoice = Invoice.objects.create(
        invoice_number=generate_invoice_number(business=business),
        business=business,
        client=client,
        appointment=appointment,
        status=Invoice.Status.DRAFT,
        notes=notes.strip(),
        **(
            {
                "currency_snapshot": currency_snapshot or business.currency,
                "tax_rate_snapshot": (
                    business.tax_rate if tax_rate_snapshot is None else tax_rate_snapshot
                ),
            }
            if business.vertical == Business.Vertical.LOGISTICS
            else {}
        ),
        tax=calculate_tax_amount(subtotal=Decimal("0.00"), tax_rate=business.tax_rate),
    )

    if lead is not None:
        lead.status = Lead.Status.INVOICED
        lead.save(update_fields=["status"])

    log_activity(
        actor=actor,
        lead=linked_lead,
        client=client,
        business=business,
        action_type=ActivityLog.ActionType.INVOICE_CREATED,
        summary=f"Invoice {invoice.invoice_number} created",
        payload={
            "invoice_number": invoice.invoice_number,
            "appointment_id": appointment.id if appointment is not None else None,
        },
    )
    return invoice


def create_invoice_from_lead(*, actor, lead: Lead) -> Invoice:
    if lead.business and lead.business.vertical == Business.Vertical.LOGISTICS:
        from apps.logistics.financial_access import require_financial_access
        from apps.logistics.location_access import lock_actor_membership

        with transaction.atomic():
            business = Business.objects.select_for_update().get(pk=lead.business_id)
            lock_actor_membership(business, actor)
            require_financial_access(business=business, actor=actor, write=True, accounting=True)
            client = _client_from_lead(lead)
            return create_invoice_for_client(actor=actor, client=client, lead=lead)
    client = _client_from_lead(lead)
    return create_invoice_for_client(actor=actor, client=client, lead=lead)


@transaction.atomic
def recalculate_invoice_totals(invoice: Invoice, *, actor=None) -> None:
    business = Business.objects.select_for_update().get(pk=invoice.business_id)
    if invoice.business.vertical == Business.Vertical.LOGISTICS:
        from apps.logistics.financial_access import require_invoice_access
        from apps.logistics.location_access import lock_actor_membership

        lock_actor_membership(business, actor)
    persisted = Invoice.objects.select_for_update().get(pk=invoice.pk, business=business)
    if persisted.payments.exists():
        raise ValidationError("Invoices with payment history retain their monetary basis.")
    if invoice.business.vertical == Business.Vertical.LOGISTICS:
        require_invoice_access(business=business, actor=actor, invoice=invoice, write=True)
        from apps.logistics.financial_coverage import validate_invoice_charge_bindings

        validate_invoice_charge_bindings(invoice)
        if persisted.financial_snapshot_at or persisted.status != Invoice.Status.DRAFT:
            raise ValidationError("Issued Logistics Invoice totals cannot be recalculated.")
    subtotal = sum(
        (line.line_total for line in InvoiceLine.objects.filter(invoice=invoice)),
        start=Decimal("0.00"),
    )
    invoice.subtotal = subtotal
    invoice.tax = calculate_tax_amount(subtotal=subtotal, tax_rate=invoice.tax_rate_percentage)
    invoice.total = subtotal + invoice.tax
    invoice.save(update_fields=["subtotal", "tax", "total"])


STATUS_TRANSITIONS = {
    Invoice.Status.DRAFT: {Invoice.Status.SENT, Invoice.Status.CANCELLED},
    Invoice.Status.SENT: {Invoice.Status.PAID, Invoice.Status.CANCELLED},
    Invoice.Status.PAID: set(),
    Invoice.Status.CANCELLED: set(),
}


@transaction.atomic
def change_invoice_status(*, business, actor, invoice, status):
    """Serialize issuance against draft append and recheck persisted authorization."""
    current = Business.objects.select_for_update().get(pk=business.pk)
    selected = Invoice.objects.select_for_update().get(pk=invoice.pk, business=current)
    if current.vertical == Business.Vertical.LOGISTICS:
        from apps.logistics.financial_access import require_invoice_access
        from apps.logistics.location_access import lock_actor_membership

        lock_actor_membership(current, actor)
        require_invoice_access(
            business=current,
            actor=actor,
            invoice=selected,
            write=True,
            accounting=status == Invoice.Status.CANCELLED,
        )
    if status not in STATUS_TRANSITIONS.get(selected.status, set()):
        return selected
    if status == Invoice.Status.CANCELLED and selected.payments.exists():
        from .payment_services import _invoice_settlement

        balance = _invoice_settlement(selected)
        if balance.issues or balance.net_paid:
            raise ValidationError(
                "Reverse/refund active customer receipts before cancelling an Invoice."
            )
    if current.vertical == Business.Vertical.LOGISTICS and status in (
        Invoice.Status.SENT,
        Invoice.Status.PAID,
    ):
        from apps.logistics.financial_coverage import validate_invoice_charge_bindings

        validate_invoice_charge_bindings(selected)
    previous_status = selected.status
    selected.status = status
    selected.save()
    log_activity(
        actor=actor,
        action_type=ActivityLog.ActionType.STATUS_CHANGED,
        business=current,
        client=selected.client,
        summary=(
            f"Invoice {selected.invoice_number} status changed from "
            f"{Invoice.Status(previous_status).label} to {Invoice.Status(status).label}"
        ),
        payload={
            "invoice_id": selected.id,
            "invoice_number": selected.invoice_number,
            "from_status": previous_status,
            "to_status": status,
        },
    )
    return selected
