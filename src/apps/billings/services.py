from __future__ import annotations

from django.utils import timezone

from apps.crm.models import Lead, ActivityLog
from apps.crm.services import lead_to_client, log_activity

from .models import Invoice


def generate_invoice_number() -> str:
    # Simple deterministic format: INV-YYYYMMDD-HHMMSS
    now = timezone.now()
    return f"INV-{now:%Y%m%d-%H%M%S}"


def create_invoice_from_lead(*, actor, lead: Lead) -> Invoice:
    client = lead_to_client(lead)
    inv = Invoice.objects.create(
        invoice_number=generate_invoice_number(),
        client=client,
        lead=lead,
        status=Invoice.Status.DRAFT,
    )
    lead.status = Lead.Status.INVOICED
    lead.save(update_fields=["status"])

    log_activity(
        actor=actor,
        lead=lead,
        client=client,
        action_type=ActivityLog.ActionType.INVOICE_CREATED,
        summary=f"Invoice {inv.invoice_number} created",
        payload={"invoice_number": inv.invoice_number},
    )
    return inv