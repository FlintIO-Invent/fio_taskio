from __future__ import annotations

from django.utils import timezone

from apps.crm.models import ActivityLog, Client, Lead
from apps.crm.services import log_activity

from .models import Invoice


def generate_invoice_number() -> str:
    # Simple deterministic format: INV-YYYYMMDD-HHMMSS
    now = timezone.now()
    return f"INV-{now:%Y%m%d-%H%M%S}"


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
    client, _created = Client.objects.get_or_create(email=lead.email, defaults=defaults)

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
    invoice = Invoice.objects.create(
        invoice_number=generate_invoice_number(),
        client=client,
        status=Invoice.Status.DRAFT,
    )

    if lead is not None:
        lead.status = Lead.Status.INVOICED
        lead.save(update_fields=["status"])

    log_activity(
        actor=actor,
        lead=lead,
        client=client,
        action_type=ActivityLog.ActionType.INVOICE_CREATED,
        summary=f"Invoice {invoice.invoice_number} created",
        payload={"invoice_number": invoice.invoice_number},
    )
    return invoice


def create_invoice_from_lead(*, actor, lead: Lead) -> Invoice:
    client = _client_from_lead(lead)
    return create_invoice_for_client(actor=actor, client=client, lead=lead)
