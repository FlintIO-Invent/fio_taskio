from __future__ import annotations

from django.core.mail import send_mail
from django.conf import settings

from .models import Lead, Client, ActivityLog


_GENERIC_LEAD_VALUES_BY_FIELD = {
    "country": {"sint maarten"},
    "postal_code": {"n/a"},
}


def _normalized_text(value: str | None) -> str:
    return (value or "").strip()


def _default_client_company_name(lead: Lead) -> str:
    company_name = _normalized_text(lead.company_name)
    if company_name:
        return company_name

    full_name = " ".join(
        part for part in [_normalized_text(lead.first_name), _normalized_text(lead.last_name)] if part
    )
    return full_name or _normalized_text(lead.email)


def _build_client_create_defaults_from_lead(lead: Lead) -> dict[str, str]:
    return {
        "business": lead.business,
        "first_name": _normalized_text(lead.first_name),
        "last_name": _normalized_text(lead.last_name),
        "email": _normalized_text(lead.email).lower(),
        "phone": _normalized_text(lead.phone),
        "company_name": _default_client_company_name(lead),
        "street_address": _normalized_text(lead.street_address),
        "district": _normalized_text(lead.district),
        "country": _normalized_text(lead.country) or "Sint Maarten",
        "postal_code": _normalized_text(lead.postal_code) or "N/A",
        "message": _normalized_text(lead.message),
        "notes": _normalized_text(lead.notes),
    }


def _build_client_update_values_from_lead(lead: Lead) -> dict[str, str]:
    return {
        "first_name": _normalized_text(lead.first_name),
        "last_name": _normalized_text(lead.last_name),
        "email": _normalized_text(lead.email).lower(),
        "phone": _normalized_text(lead.phone),
        "company_name": _normalized_text(lead.company_name),
        "street_address": _normalized_text(lead.street_address),
        "district": _normalized_text(lead.district),
        "country": _normalized_text(lead.country) or "Sint Maarten",
        "postal_code": _normalized_text(lead.postal_code) or "N/A",
        "message": _normalized_text(lead.message),
        "notes": _normalized_text(lead.notes),
    }


def _should_update_client_field(*, field_name: str, current_value, incoming_value: str) -> bool:
    incoming_text = _normalized_text(incoming_value)
    if not incoming_text:
        return False

    current_text = _normalized_text(current_value)
    if not current_text:
        return True

    generic_values = _GENERIC_LEAD_VALUES_BY_FIELD.get(field_name, set())
    if incoming_text.casefold() in generic_values and current_text.casefold() != incoming_text.casefold():
        return False

    return current_text != incoming_text


def sync_client_from_lead(lead: Lead) -> tuple[Client, bool]:
    """
    Create or update a client from a lead using the current business-scoped CRM fields.

    Matching is scoped to ``(business, email)`` so legacy cross-tenant collisions do not
    attach a lead to the wrong workspace. Existing clients keep richer non-empty values
    when a lead only provides blank or generic fallback data.
    """
    normalized_email = _normalized_text(lead.email).lower()
    create_defaults = _build_client_create_defaults_from_lead(lead)
    update_values = _build_client_update_values_from_lead(lead)

    client, created = Client.objects.get_or_create(
        business=lead.business,
        email=normalized_email,
        defaults=create_defaults,
    )
    if created:
        return client, True

    updated_fields: list[str] = []
    for field_name, incoming_value in update_values.items():
        if _should_update_client_field(
            field_name=field_name,
            current_value=getattr(client, field_name),
            incoming_value=incoming_value,
        ):
            setattr(client, field_name, incoming_value)
            updated_fields.append(field_name)

    if client.business_id != lead.business_id:
        client.business = lead.business
        updated_fields.append("business")

    if updated_fields:
        client.save(update_fields=[*updated_fields, "updated_at"])

    return client, False


def lead_to_client(lead: Lead) -> Client:
    """
    Compatibility helper for older TaskIO code paths.

    New Clarivo lead capture flows should prefer ``upsert_client_from_lead`` or
    ``sync_client_from_lead`` so lead-to-client conversion stays business-scoped.
    """
    client, _created = sync_client_from_lead(lead)
    return client


def log_activity(
    *,
    actor,
    lead=None,
    client=None,
    business=None,
    action_type: str,
    summary: str = "",
    payload: dict | None = None,
):
    resolved_business = business
    if resolved_business is None and client is not None:
        resolved_business = client.business
    if resolved_business is None and lead is not None:
        resolved_business = lead.business

    ActivityLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        business=resolved_business,
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
