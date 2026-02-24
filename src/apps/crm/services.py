from __future__ import annotations

from django.core.mail import send_mail
from django.conf import settings

from .models import Lead, Client, ActivityLog


def lead_to_client(lead: Lead) -> Client:
    """Create or get a Client from a Lead (simple matching by email)."""
    name = f"{lead.first_name} {lead.last_name}".strip() or lead.email
    client, _created = Client.objects.get_or_create(
        email=lead.email,
        defaults={
            "name": name,
            "phone": lead.phone,
        },
    )
    # Keep it updated
    if client.name != name and name:
        client.name = name
    if lead.phone and client.phone != lead.phone:
        client.phone = lead.phone
    client.save()
    return client


def log_activity(*, actor, lead=None, client=None, action_type: str, summary: str = "", payload: dict | None = None):
    ActivityLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        lead=lead,
        client=client,
        action_type=action_type,
        summary=summary,
        payload=payload or {},
    )


def send_lead_email(*, actor, lead: Lead, subject: str, body: str) -> None:
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[lead.email],
        fail_silently=False,
    )
    lead.status = Lead.Status.CONTACTED
    lead.save(update_fields=["status"])
    log_activity(
        actor=actor,
        lead=lead,
        action_type=ActivityLog.ActionType.EMAIL_SENT,
        summary=f"Email sent to {lead.email}",
        payload={"subject": subject},
    )