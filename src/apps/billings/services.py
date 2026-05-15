from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from apps.crm.models import ActivityLog, Client, Lead
from apps.crm.services import log_activity

from .models import Invoice


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


def create_invoice_for_client(*, actor, client: Client, lead: Lead | None = None) -> Invoice:
    business = client.business or (lead.business if lead is not None else None)
    if business is None:
        raise ValueError("Invoices require a business-scoped client or lead.")

    invoice = Invoice.objects.create(
        invoice_number=generate_invoice_number(business=business),
        business=business,
        client=client,
        status=Invoice.Status.DRAFT,
        tax=calculate_tax_amount(subtotal=Decimal("0.00"), tax_rate=business.tax_rate),
    )

    if lead is not None:
        lead.status = Lead.Status.INVOICED
        lead.save(update_fields=["status"])

    log_activity(
        actor=actor,
        lead=lead,
        client=client,
        business=business,
        action_type=ActivityLog.ActionType.INVOICE_CREATED,
        summary=f"Invoice {invoice.invoice_number} created",
        payload={"invoice_number": invoice.invoice_number},
    )
    return invoice


def create_invoice_from_lead(*, actor, lead: Lead) -> Invoice:
    client = _client_from_lead(lead)
    return create_invoice_for_client(actor=actor, client=client, lead=lead)
