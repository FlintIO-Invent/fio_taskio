from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import ActivityLog, Client, Lead

CLIENT_REQUIRED_FIELDS_FOR_REQUEST_CONVERSION = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "company_name",
    "street_address",
)
CLIENT_REQUIRED_FIELD_LABELS = {
    "first_name": "First name",
    "last_name": "Last name",
    "email": "Email",
    "phone": "Phone",
    "company_name": "Company name",
    "street_address": "Street address",
}


def _normalized_text(value: str | None) -> str:
    return (value or "").strip()


def _normalized_email(value: str | None) -> str:
    return _normalized_text(value).lower()


def _normalized_phone(value: str | None) -> str:
    raw_value = _normalized_text(value)
    if not raw_value:
        return ""
    return "".join(character for character in raw_value if character.isdigit())


def _default_client_company_name(lead: Lead) -> str:
    company_name = _normalized_text(lead.company_name)
    if company_name:
        return company_name

    full_name = " ".join(
        part for part in [_normalized_text(lead.first_name), _normalized_text(lead.last_name)] if part
    )
    return full_name or _normalized_text(lead.email)


def _default_client_type(lead: Lead) -> str:
    return (
        Client.ClientType.BUSINESS
        if _normalized_text(lead.company_name)
        else Client.ClientType.INDIVIDUAL
    )


def _default_client_status(_lead: Lead) -> str:
    return Client.ClientStatus.LEAD


def _request_context_marker(lead: Lead) -> str:
    if lead.request_source == Lead.RequestSource.PUBLIC_BOOKING:
        return f"Public booking #{lead.pk}"
    return f"Public request #{lead.pk}"


def _request_context_block(lead: Lead) -> str:
    received_at = lead.created_at or timezone.now()
    received_at = timezone.localtime(received_at)

    lines = [f"{_request_context_marker(lead)} received on {received_at:%Y-%m-%d %H:%M}"]

    if lead.has_valid_requested_service:
        lines.append(f"Requested service: {lead.requested_service.name}")
    elif lead.category_id and lead.category is not None:
        lines.append(f"Category: {lead.category.name}")
    if lead.preferred_start_time:
        preferred_start_time = timezone.localtime(lead.preferred_start_time)
        preferred_time_label = f"Preferred start: {preferred_start_time:%Y-%m-%d %H:%M}"
        if lead.preferred_end_time:
            preferred_end_time = timezone.localtime(lead.preferred_end_time)
            preferred_time_label = (
                f"{preferred_time_label}-{preferred_end_time:%H:%M}"
            )
        lines.append(preferred_time_label)
    if _normalized_text(lead.message):
        lines.append(f"Message: {lead.message.strip()}")

    if lead.formatted_address:
        lines.append(f"Request location: {lead.formatted_address}")

    return "\n".join(lines)


def _append_request_context(existing_value: str, lead: Lead) -> str:
    request_context = _request_context_block(lead)
    marker = _request_context_marker(lead)
    normalized_existing_value = _normalized_text(existing_value)

    if marker in normalized_existing_value:
        return normalized_existing_value
    if not normalized_existing_value:
        return request_context
    return f"{normalized_existing_value}\n\n{request_context}"


def find_matching_client_for_lead(lead: Lead) -> Client | None:
    same_business_clients = Client.objects.filter(business=lead.business).order_by("pk")
    normalized_email = _normalized_email(lead.email)

    if normalized_email:
        return same_business_clients.filter(email__iexact=normalized_email).first()

    normalized_phone = _normalized_phone(lead.phone)
    if not normalized_phone:
        return None

    phone_matches = [
        candidate
        for candidate in same_business_clients
        if _normalized_phone(candidate.phone) == normalized_phone
    ]
    if len(phone_matches) == 1:
        return phone_matches[0]
    return None


def get_missing_client_required_field_labels_for_lead(lead: Lead) -> list[str]:
    missing_labels: list[str] = []

    for field_name in CLIENT_REQUIRED_FIELDS_FOR_REQUEST_CONVERSION:
        if _normalized_text(getattr(lead, field_name, "")):
            continue
        missing_labels.append(CLIENT_REQUIRED_FIELD_LABELS[field_name])

    return missing_labels


def _build_client_create_defaults_from_lead(lead: Lead) -> dict[str, str]:
    return {
        "business": lead.business,
        "first_name": _normalized_text(lead.first_name),
        "last_name": _normalized_text(lead.last_name),
        "email": _normalized_email(lead.email),
        "phone": _normalized_text(lead.phone),
        "client_type": _default_client_type(lead),
        "company_name": _default_client_company_name(lead),
        "client_status": _default_client_status(lead),
        "lead_source": Client.LeadSource.WEBSITE,
        "priority": Client.Priority.MEDIUM,
        "street_address": _normalized_text(lead.street_address),
        "district": _normalized_text(lead.district),
        "country": _normalized_text(lead.country) or "Sint Maarten",
        "postal_code": _normalized_text(lead.postal_code) or "N/A",
        "message": _normalized_text(lead.message),
        "notes": _normalized_text(lead.notes),
        "communication_notes": _append_request_context("", lead),
        "consent_to_contact": bool(lead.consent_to_contact),
        "is_active": True,
    }


def _build_client_update_values_from_lead(lead: Lead) -> dict[str, str]:
    return {
        "first_name": _normalized_text(lead.first_name),
        "last_name": _normalized_text(lead.last_name),
        "email": _normalized_email(lead.email),
        "phone": _normalized_text(lead.phone),
        "company_name": _default_client_company_name(lead),
        "street_address": _normalized_text(lead.street_address),
        "district": _normalized_text(lead.district),
        "country": _normalized_text(lead.country) or "Sint Maarten",
        "postal_code": _normalized_text(lead.postal_code) or "N/A",
        "message": _normalized_text(lead.message),
    }


def _should_backfill_client_field(*, current_value, incoming_value: str) -> bool:
    incoming_text = _normalized_text(incoming_value)
    if not incoming_text:
        return False

    current_text = _normalized_text(current_value)
    return not current_text


def sync_client_from_lead(lead: Lead) -> tuple[Client, bool]:
    """
    Create or update a client from a lead using the current business-scoped CRM fields.

    Matching is scoped to the current ``lead.business`` so legacy cross-tenant collisions
    do not attach a lead to the wrong workspace. Existing clients are only backfilled
    from public-request data; richer CRM fields and active lifecycle state stay intact.
    """
    if lead.business_id is None:
        raise ValueError("Lead must belong to a business before syncing a client.")

    create_defaults = _build_client_create_defaults_from_lead(lead)
    update_values = _build_client_update_values_from_lead(lead)
    client = find_matching_client_for_lead(lead)

    if client is None:
        client = Client.objects.create(**create_defaults)
        return client, True

    updated_fields: list[str] = []
    for field_name, incoming_value in update_values.items():
        if _should_backfill_client_field(
            current_value=getattr(client, field_name),
            incoming_value=incoming_value,
        ):
            setattr(client, field_name, incoming_value)
            updated_fields.append(field_name)

    if not _normalized_text(client.lead_source):
        client.lead_source = Client.LeadSource.WEBSITE
        updated_fields.append("lead_source")

    if not _normalized_text(client.client_status):
        client.client_status = _default_client_status(lead)
        updated_fields.append("client_status")

    updated_communication_notes = _append_request_context(client.communication_notes, lead)
    if updated_communication_notes != _normalized_text(client.communication_notes):
        client.communication_notes = updated_communication_notes
        updated_fields.append("communication_notes")

    if lead.consent_to_contact and not client.consent_to_contact:
        client.consent_to_contact = True
        updated_fields.append("consent_to_contact")

    if updated_fields:
        client.save(update_fields=[*updated_fields, "updated_at"])

    return client, False


def lead_to_client(lead: Lead) -> Client:
    """
    Compatibility helper for older Motionmate code paths.

    New Motionmate lead capture flows should prefer ``upsert_client_from_lead`` or
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
