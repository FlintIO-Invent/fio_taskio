from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.utils import timezone

from apps.businesses.models import BusinessUser

if TYPE_CHECKING:
    from apps.appointments.models import Appointment
    from apps.businesses.models import Business, BusinessInvitation
    from apps.crm.models import Lead


logger = logging.getLogger(__name__)


def _normalize_recipients(recipient_list: list[str] | tuple[str, ...]) -> list[str]:
    recipients: list[str] = []
    for recipient in recipient_list:
        email = (recipient or "").strip()
        if not email:
            continue
        try:
            validate_email(email)
        except ValidationError:
            logger.info("Skipping email notification with invalid recipient address.")
            continue
        recipients.append(email)
    return recipients


def _render_subject(template_name: str, context: dict) -> str:
    return " ".join(render_to_string(template_name, context).split())


def send_templated_email(
    *,
    subject_template: str,
    body_template: str,
    context: dict,
    recipient_list: list[str] | tuple[str, ...],
    log_label: str,
    html_template: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    fail_safely: bool = True,
) -> bool:
    recipients = _normalize_recipients(recipient_list)
    if not recipients:
        logger.info("Skipping %s email notification because no recipient is configured.", log_label)
        return False

    subject = _render_subject(subject_template, context)
    body = render_to_string(body_template, context).strip()

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        if html_template:
            html_body = render_to_string(html_template, context)
            message.attach_alternative(html_body, "text/html")
        for attachment in attachments or []:
            message.attach(*attachment)
        sent_count = message.send(fail_silently=False)
    except Exception:
        logger.exception("Failed to send %s email notification.", log_label)
        if fail_safely:
            return False
        raise

    return sent_count > 0


def _user_display_name(user) -> str:
    if user is None:
        return "a workspace admin"

    full_name = (getattr(user, "full_name", "") or "").strip()
    if full_name:
        return full_name

    get_full_name = getattr(user, "get_full_name", None)
    if callable(get_full_name):
        full_name = (get_full_name() or "").strip()
        if full_name:
            return full_name

    return getattr(user, "email", "") or "a workspace admin"


def _business_timezone(business: Business):
    timezone_name = getattr(business, "timezone", "") or settings.TIME_ZONE
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        logger.info("Business %s has an invalid timezone: %s", business.pk, timezone_name)
        return timezone.get_current_timezone()


def _clock(value) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _format_time_window(start_time, end_time, business: Business) -> str:
    if start_time is None:
        return "Not provided"

    business_tz = _business_timezone(business)
    local_start = timezone.localtime(start_time, business_tz)
    date_text = f"{local_start:%B} {local_start.day}, {local_start:%Y}"
    timezone_label = getattr(local_start.tzinfo, "key", str(local_start.tzinfo))

    if end_time is None:
        return f"{date_text} at {_clock(local_start)} ({timezone_label})"

    local_end = timezone.localtime(end_time, business_tz)
    if local_end.date() == local_start.date():
        return f"{date_text} at {_clock(local_start)} - {_clock(local_end)} ({timezone_label})"

    end_date_text = f"{local_end:%B} {local_end.day}, {local_end:%Y}"
    return (
        f"{date_text} at {_clock(local_start)} - "
        f"{end_date_text} at {_clock(local_end)} ({timezone_label})"
    )


def _lead_requester_name(lead: Lead) -> str:
    full_name = " ".join(
        part.strip()
        for part in [lead.first_name or "", lead.last_name or ""]
        if part and part.strip()
    )
    return full_name or lead.company_name or lead.email or "Public visitor"


def _lead_service_name(lead: Lead) -> str:
    if getattr(lead, "has_valid_requested_service", False):
        return lead.requested_service.name
    if lead.category_id and lead.category is not None:
        return lead.category.name
    return "Service request"


def _business_contact_text(business: Business) -> str:
    contact_lines: list[str] = []
    if business.email:
        contact_lines.append(f"Email: {business.email}")
    if business.phone:
        contact_lines.append(f"Phone: {business.phone}")
    address_lines = getattr(business, "formatted_address_lines", [])
    if address_lines:
        contact_lines.append("Address: " + ", ".join(address_lines))
    return "\n".join(contact_lines) or "Contact the business directly for details."


def _security_email_context(user, *, email_title: str) -> dict:
    return {
        "user": user,
        "email_title": email_title,
        "support_email": getattr(settings, "MOTIONMATE_SUPPORT_EMAIL", ""),
    }


def send_password_reset_complete_email(user) -> bool:
    return send_templated_email(
        subject_template="emails/password_reset_complete_subject.txt",
        body_template="emails/password_reset_complete_body.txt",
        html_template="emails/password_reset_complete_body.html",
        context=_security_email_context(
            user,
            email_title="Your MotionMate password was reset",
        ),
        recipient_list=[user.email],
        log_label="password reset confirmation",
    )


def send_password_change_confirmation_email(user) -> bool:
    return send_templated_email(
        subject_template="emails/password_change_subject.txt",
        body_template="emails/password_change_body.txt",
        html_template="emails/password_change_body.html",
        context=_security_email_context(
            user,
            email_title="Your MotionMate password was changed",
        ),
        recipient_list=[user.email],
        log_label="password change confirmation",
    )


def send_business_invitation_email(
    invitation: BusinessInvitation,
    *,
    accept_url: str,
) -> bool:
    context = {
        "invitation": invitation,
        "business": invitation.business,
        "inviter_name": _user_display_name(invitation.invited_by),
        "role_label": invitation.get_role_display(),
        "accept_url": accept_url,
    }
    return send_templated_email(
        subject_template="emails/invitation_subject.txt",
        body_template="emails/invitation_body.txt",
        context=context,
        recipient_list=[invitation.email],
        log_label="business invitation",
    )


def send_public_booking_request_received_email(lead: Lead) -> bool:
    context = {
        "lead": lead,
        "business": lead.business,
        "requester_name": _lead_requester_name(lead),
        "service_name": _lead_service_name(lead),
        "preferred_window": _format_time_window(
            lead.preferred_start_time,
            lead.preferred_end_time,
            lead.business,
        ),
        "business_contact": _business_contact_text(lead.business),
    }
    return send_templated_email(
        subject_template="emails/booking_request_received_subject.txt",
        body_template="emails/booking_request_received_body.txt",
        context=context,
        recipient_list=[lead.email],
        log_label="public booking request confirmation",
    )


def get_internal_booking_notification_recipient(business: Business) -> str | None:
    if business.email.strip():
        return business.email.strip()

    owner_email = (
        BusinessUser.objects.filter(
            business=business,
            role=BusinessUser.Role.OWNER,
            is_active=True,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("created_at", "pk")
        .values_list("user__email", flat=True)
        .first()
    )
    return owner_email or None


def send_internal_booking_notification_email(
    lead: Lead,
    *,
    request_url: str = "",
) -> bool:
    recipient = get_internal_booking_notification_recipient(lead.business)
    if not recipient:
        logger.info(
            "Skipping internal booking notification for business %s because no recipient is configured.",
            lead.business_id,
        )
        return False

    context = {
        "lead": lead,
        "business": lead.business,
        "requester_name": _lead_requester_name(lead),
        "service_name": _lead_service_name(lead),
        "preferred_window": _format_time_window(
            lead.preferred_start_time,
            lead.preferred_end_time,
            lead.business,
        ),
        "request_url": request_url,
    }
    return send_templated_email(
        subject_template="emails/internal_booking_notification_subject.txt",
        body_template="emails/internal_booking_notification_body.txt",
        context=context,
        recipient_list=[recipient],
        log_label="internal booking request",
    )


def _appointment_service_name(appointment: Appointment) -> str:
    if appointment.service_name:
        return appointment.service_name
    if appointment.service_id and appointment.service is not None:
        return appointment.service.name
    return appointment.title


def send_appointment_confirmation_email(appointment: Appointment) -> bool:
    context = {
        "appointment": appointment,
        "business": appointment.business,
        "client": appointment.client,
        "service_name": _appointment_service_name(appointment),
        "appointment_window": _format_time_window(
            appointment.start_time,
            appointment.end_time,
            appointment.business,
        ),
        "business_contact": _business_contact_text(appointment.business),
    }
    return send_templated_email(
        subject_template="emails/appointment_confirmation_subject.txt",
        body_template="emails/appointment_confirmation_body.txt",
        context=context,
        recipient_list=[appointment.client.email],
        log_label="appointment confirmation",
    )


def send_invoice_email(
    invoice,
    *,
    pdf_bytes: bytes,
    filename: str,
) -> bool:
    context = {
        "invoice": invoice,
        "business": invoice.business,
        "client": invoice.client,
        "amount_due": f"{invoice.currency_code} {invoice.total:.2f}",
    }
    return send_templated_email(
        subject_template="emails/invoice_subject.txt",
        body_template="emails/invoice_body.txt",
        context=context,
        recipient_list=[invoice.client.email],
        attachments=[(filename, pdf_bytes, "application/pdf")],
        log_label="invoice email",
    )
