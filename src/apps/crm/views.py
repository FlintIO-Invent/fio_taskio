from __future__ import annotations

import csv
import io
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Q, QuerySet, Sum, Value, When
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods
from loguru import logger

from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.businesses.localization import (
    localized_price_input_example,
    parse_localized_decimal,
    uses_sint_maarten_districts,
)
from apps.businesses.models import Business, BusinessBookingSettings, WeeklyAvailability
from apps.businesses.utils import (
    ALL_WORKSPACE_ROLES,
    APPOINTMENT_VIEW_ROLES,
    BILLING_MANAGE_ROLES,
    BILLING_VIEW_ROLES,
    CLIENT_MANAGE_ROLES,
    LEAD_MANAGE_ROLES,
    SERVICE_MANAGEMENT_ROLES,
    business_module_required,
    business_required,
    business_role_required,
    can_use_module,
    get_business_module_unavailable_message,
    get_current_business,
    get_current_business_membership,
    membership_has_any_role,
    redirect_for_unavailable_business_module,
)
from apps.notifications.emails import (
    send_appointment_confirmation_email,
    send_internal_booking_notification_email,
    send_public_booking_request_received_email,
)
from helpers import upsert_client_from_lead

from .forms import (
    BusinessServiceCSVImportForm,
    BusinessServiceForm,
    LeadClientConversionForm,
    PrivateClientForm,
    PrivateLeadForm,
    PublicBookingForm,
    PublicLeadForm,
    ServiceCategoryForm,
)
from .models import BusinessService, Client, Lead, ServiceCategory
from .services import (
    find_matching_client_for_lead,
    get_missing_client_required_field_labels_for_lead,
    sync_client_from_lead,
)

SERVICE_REQUEST_ACTIVE_STATUSES = (Lead.Status.NEW, Lead.Status.CONTACTED)
SERVICE_REQUEST_COMPLETED_STATUSES = (Lead.Status.INVOICED, Lead.Status.CLOSED)


def _order_service_requests_for_followup(qs: QuerySet[Lead]) -> QuerySet[Lead]:
    return qs.annotate(
        _request_status_priority=Case(
            When(status=Lead.Status.NEW, then=Value(0)),
            When(status=Lead.Status.CONTACTED, then=Value(1)),
            When(status=Lead.Status.INVOICED, then=Value(2)),
            When(status=Lead.Status.CLOSED, then=Value(3)),
            default=Value(9),
            output_field=IntegerField(),
        ),
        _request_time_priority=Case(
            When(preferred_start_time__isnull=False, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    ).order_by(
        "_request_status_priority",
        "_request_time_priority",
        "preferred_start_time",
        "created_at",
        "pk",
    )


def _client_queryset_for_business(business: Business) -> QuerySet[Client]:
    return Client.objects.filter(business=business).select_related("assigned_to")


def _lead_queryset_for_business(business: Business) -> QuerySet[Lead]:
    return Lead.objects.filter(business=business).select_related("category", "requested_service")


def _query_string_with(request: HttpRequest, **updates: str | None) -> str:
    params = request.GET.copy()
    for key, value in updates.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else ""


def _service_category_queryset_for_business(business: Business) -> QuerySet[ServiceCategory]:
    return ServiceCategory.for_business(
        business,
        include_inactive=True,
    ).select_related("business")


def _business_service_queryset_for_business(business: Business) -> QuerySet[BusinessService]:
    return BusinessService.for_business(
        business,
        include_inactive=True,
    ).select_related("business", "category")


def _appointment_queryset_for_business(business: Business) -> QuerySet[Appointment]:
    return Appointment.objects.filter(business=business).select_related(
        "business",
        "client",
        "service",
        "source_lead",
        "staff_member",
    )


def _display_name_for_public_booking_client(lead: Lead, client: Client) -> str:
    if client.company_name:
        return client.company_name

    full_name = " ".join(part for part in [client.first_name, client.last_name] if part).strip()
    return full_name or lead.company_name or lead.email


def _display_name_for_public_staff(user) -> str:
    if user is None:
        return ""
    get_full_name = getattr(user, "get_full_name", None)
    full_name = (get_full_name() if callable(get_full_name) else "") or getattr(
        user,
        "full_name",
        "",
    )
    full_name = full_name.strip()
    return full_name or user.email


def _build_public_booking_location(lead: Lead, client: Client) -> str:
    if lead.formatted_address:
        return lead.formatted_address[:255]

    return client.formatted_address[:255]


def _build_public_booking_title(
    *,
    lead: Lead,
    client: Client,
    service: BusinessService,
) -> str:
    client_label = _display_name_for_public_booking_client(lead, client)
    return f"{service.name} - {client_label}"[:160]


def _build_public_booking_lead_notes(*, booking_intent: str, staff_member) -> str:
    notes = [
        (
            "Booking intent: book an appointment now."
            if booking_intent == PublicBookingForm.BOOK_NOW
            else "Booking intent: contact before booking."
        )
    ]
    staff_label = _display_name_for_public_staff(staff_member)
    if staff_label:
        notes.append(f"Preferred staff: {staff_label}.")
    return "\n".join(notes)


def _build_public_booking_appointment_notes(lead: Lead) -> str:
    notes = [f"Scheduled from public booking request #{lead.pk}."]
    if lead.message.strip():
        notes.append(f"Customer message: {lead.message.strip()}")
    if lead.notes.strip():
        notes.append(lead.notes.strip())
    return "\n\n".join(notes)


def _public_booking_unavailable_response(
    request: HttpRequest,
    *,
    business: Business,
    status: int = 403,
) -> HttpResponse:
    return render(
        request,
        "crm/success_fail/public_booking_unavailable.html",
        {
            "public_business": business,
            "availability_message": (
                "Online booking requests are not available for this business right now."
            ),
        },
        status=status,
    )


def _public_booking_settings_for_business(
    business: Business,
) -> BusinessBookingSettings | None:
    try:
        return business.booking_settings
    except BusinessBookingSettings.DoesNotExist:
        return None


def _public_booking_is_available(
    business: Business,
    booking_settings: BusinessBookingSettings | None,
) -> bool:
    if not can_use_module(business, "public_booking"):
        return False
    if booking_settings is None or not booking_settings.booking_enabled:
        return False
    if not BusinessService.objects.filter(
        business=business,
        is_active=True,
        is_bookable_online=True,
    ).exists():
        return False
    return WeeklyAvailability.objects.filter(
        business=business,
        is_active=True,
    ).exists()


def _time_to_minutes(value: time) -> int:
    return (value.hour * 60) + value.minute


def _business_timezone(business: Business):
    try:
        return ZoneInfo(business.timezone)
    except ZoneInfoNotFoundError:
        return timezone.get_current_timezone()


def _public_booking_slot_picker_data(
    *,
    business: Business,
    booking_settings: BusinessBookingSettings | None,
    form: PublicBookingForm,
) -> dict[str, Any]:
    if booking_settings is None:
        return {}

    business_timezone = _business_timezone(business)
    local_now = timezone.now().astimezone(business_timezone)
    earliest_start = local_now + timedelta(hours=booking_settings.minimum_notice_hours)
    latest_date = local_now.date() + timedelta(days=booking_settings.maximum_days_ahead)
    range_start = datetime.combine(
        earliest_start.date(),
        time.min,
        tzinfo=business_timezone,
    )
    range_end = datetime.combine(
        latest_date + timedelta(days=1),
        time.min,
        tzinfo=business_timezone,
    )

    services = {
        str(service.pk): {
            "durationMinutes": service.default_duration_minutes
            or booking_settings.default_duration_minutes,
        }
        for service in form.fields["service"].queryset
    }

    staff_members = list(form.fields["staff_member"].queryset)
    staff_ids = [staff.pk for staff in staff_members]
    staff = {
        str(staff_member.pk): {
            "name": _display_name_for_public_staff(staff_member),
        }
        for staff_member in staff_members
    }

    availability: dict[str, Any] = {
        "business": [],
        "staff": {},
    }
    availability_blocks = WeeklyAvailability.objects.filter(
        business=business,
        is_active=True,
    ).select_related("staff_member")
    for block in availability_blocks:
        block_data = {
            "day": block.day_of_week,
            "startMinutes": _time_to_minutes(block.start_time),
            "endMinutes": _time_to_minutes(block.end_time),
        }
        if block.staff_member_id:
            availability["staff"].setdefault(str(block.staff_member_id), []).append(block_data)
        else:
            availability["business"].append(block_data)

    appointments: dict[str, list[dict[str, Any]]] = {}
    if staff_ids:
        scheduled_appointments = (
            Appointment.objects.filter(
                business=business,
                staff_member_id__in=staff_ids,
                status=Appointment.Status.SCHEDULED,
                start_time__lt=range_end,
                end_time__gt=range_start,
            )
            .exclude(staff_member__isnull=True)
            .select_related("staff_member")
        )
        for appointment in scheduled_appointments:
            local_start = appointment.start_time.astimezone(business_timezone)
            local_end = appointment.end_time.astimezone(business_timezone)
            current_date = local_start.date()
            while current_date <= local_end.date():
                start_minutes = (
                    _time_to_minutes(local_start.time())
                    if current_date == local_start.date()
                    else 0
                )
                end_minutes = (
                    _time_to_minutes(local_end.time())
                    if current_date == local_end.date()
                    else 24 * 60
                )
                if end_minutes > start_minutes:
                    appointments.setdefault(str(appointment.staff_member_id), []).append(
                        {
                            "date": current_date.isoformat(),
                            "startMinutes": start_minutes,
                            "endMinutes": end_minutes,
                        }
                    )
                current_date += timedelta(days=1)

    return {
        "dateRange": {
            "start": earliest_start.date().isoformat(),
            "end": latest_date.isoformat(),
        },
        "earliestStart": {
            "date": earliest_start.date().isoformat(),
            "minutes": _time_to_minutes(earliest_start.time()),
        },
        "slotStepMinutes": 15,
        "defaultDurationMinutes": booking_settings.default_duration_minutes,
        "services": services,
        "staff": staff,
        "availability": availability,
        "appointments": appointments,
    }


def _business_local_periods(
    business: Business,
    instant,
):
    try:
        local_timezone = ZoneInfo(business.timezone)
    except ZoneInfoNotFoundError:
        local_timezone = timezone.get_current_timezone()

    local_now = timezone.localtime(instant, local_timezone)
    start_of_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_tomorrow = start_of_today + timedelta(days=1)
    start_of_month = start_of_today.replace(day=1)
    return start_of_today, start_of_tomorrow, start_of_month


def _normalize_csv_fieldname(value: str | None) -> str:
    return (value or "").strip().lower()


def _parse_csv_decimal(
    value: str,
    *,
    row_number: int,
    field_name: str,
    business: Business,
) -> Decimal:
    normalized_value = value.strip()
    if not normalized_value:
        raise ValidationError(f"Row {row_number}: {field_name} is required.")

    try:
        return parse_localized_decimal(normalized_value, business)
    except InvalidOperation as exc:
        raise ValidationError(
            f"Row {row_number}: {field_name} must be a valid decimal number."
        ) from exc


def _service_import_example_rows(business: Business) -> list[dict[str, str]]:
    return [
        {
            "name": "Emergency Callout",
            "unit_price": "125.00",
            "description": "After-hours emergency service call",
            "tax_rate": f"{business.tax_rate:.2f}",
            "category": "Urgent Response",
            "is_active": "true",
            "external_code": "EMERGENCY-001",
            "is_bookable_online": "true",
            "default_duration_minutes": "60",
            "booking_buffer_minutes": "15",
            "public_description": "Request an after-hours emergency service call.",
            "requires_manual_confirmation": "true",
        },
        {
            "name": "Standard Consultation",
            "unit_price": "75.00",
            "description": "Initial consultation visit",
            "tax_rate": "",
            "category": "",
            "is_active": "true",
            "external_code": "",
            "is_bookable_online": "false",
            "default_duration_minutes": "",
            "booking_buffer_minutes": "",
            "public_description": "",
            "requires_manual_confirmation": "true",
        },
    ]


def _service_import_columns() -> list[dict[str, str]]:
    return [
        {"name": "name", "required": "Required", "description": "Service name."},
        {"name": "unit_price", "required": "Required", "description": "Decimal service price."},
        {
            "name": "description",
            "required": "Optional",
            "description": "Internal service description.",
        },
        {
            "name": "tax_rate",
            "required": "Optional",
            "description": "Service tax percentage. Blank uses the workspace default.",
        },
        {
            "name": "category",
            "required": "Optional",
            "description": "Existing or new category name for this workspace.",
        },
        {
            "name": "is_active",
            "required": "Optional",
            "description": "true/false, yes/no, or 1/0. Blank defaults to true.",
        },
        {
            "name": "external_code",
            "required": "Optional",
            "description": "Stable code used to update matching services later.",
        },
        {
            "name": "is_bookable_online",
            "required": "Optional",
            "description": "true only when the service should appear on public booking.",
        },
        {
            "name": "default_duration_minutes",
            "required": "Optional",
            "description": "Whole-number booking duration in minutes.",
        },
        {
            "name": "booking_buffer_minutes",
            "required": "Optional",
            "description": "Whole-number buffer in minutes.",
        },
        {
            "name": "public_description",
            "required": "Optional",
            "description": "Public booking description.",
        },
        {
            "name": "requires_manual_confirmation",
            "required": "Optional",
            "description": "true/false. Current Motionmate booking flow is manual confirmation.",
        },
    ]


def _service_import_example_csv_text(business: Business) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[column["name"] for column in _service_import_columns()],
    )
    writer.writeheader()
    writer.writerows(_service_import_example_rows(business))
    return output.getvalue().strip()


def _parse_csv_boolean(
    value: str,
    *,
    default: bool,
    row_number: int,
    field_name: str = "is_active",
) -> bool:
    normalized_value = value.strip().lower()
    if not normalized_value:
        return default

    if normalized_value in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "n", "off"}:
        return False

    raise ValidationError(
        f"Row {row_number}: {field_name} must be one of true/false, yes/no, or 1/0."
    )


def _parse_optional_csv_integer(
    value: str,
    *,
    row_number: int,
    field_name: str,
    minimum: int,
) -> int | None:
    normalized_value = value.strip()
    if not normalized_value:
        return None

    try:
        parsed_value = int(normalized_value)
    except ValueError as exc:
        raise ValidationError(f"Row {row_number}: {field_name} must be a whole number.") from exc

    if parsed_value < minimum:
        if minimum == 1:
            raise ValidationError(f"Row {row_number}: {field_name} must be greater than zero.")
        raise ValidationError(f"Row {row_number}: {field_name} cannot be negative.")

    return parsed_value


def _get_or_create_service_category_for_import(
    *,
    business: Business,
    category_value: str,
) -> tuple[ServiceCategory | None, bool]:
    label = category_value.strip()
    if not label:
        return None, False

    normalized_code = slugify(label).replace("-", "_")
    category = (
        ServiceCategory.objects.filter(business=business)
        .filter(Q(name__iexact=label) | Q(code=normalized_code))
        .order_by("name", "pk")
        .first()
    )
    if category is not None:
        return category, False

    category = ServiceCategory.objects.create(
        business=business,
        name=label,
        is_active=True,
    )
    return category, True


def _import_business_services_from_csv(
    *,
    business: Business,
    uploaded_file,
) -> dict[str, int]:
    try:
        decoded_content = uploaded_file.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("CSV files must be UTF-8 encoded.") from exc

    reader = csv.DictReader(io.StringIO(decoded_content))
    if not reader.fieldnames:
        raise ValidationError("The CSV file must include a header row.")

    normalized_headers = {_normalize_csv_fieldname(fieldname) for fieldname in reader.fieldnames}
    missing_headers = {"name", "unit_price"} - normalized_headers
    if missing_headers:
        missing_label = ", ".join(sorted(missing_headers))
        raise ValidationError(f"Missing required CSV columns: {missing_label}.")

    created_count = 0
    updated_count = 0
    created_category_count = 0

    with transaction.atomic():
        for row_number, raw_row in enumerate(reader, start=2):
            row = {
                _normalize_csv_fieldname(key): (value or "").strip()
                for key, value in raw_row.items()
                if key is not None
            }

            if not any(row.values()):
                continue

            name = row.get("name", "")
            if not name:
                raise ValidationError(f"Row {row_number}: name is required.")

            unit_price = _parse_csv_decimal(
                row.get("unit_price", ""),
                row_number=row_number,
                field_name="unit_price",
                business=business,
            )
            tax_rate_value = row.get("tax_rate", "")
            tax_rate = (
                _parse_csv_decimal(
                    tax_rate_value,
                    row_number=row_number,
                    field_name="tax_rate",
                    business=business,
                )
                if tax_rate_value
                else business.tax_rate
            )
            is_active = _parse_csv_boolean(
                row.get("is_active", ""),
                default=True,
                row_number=row_number,
            )
            is_bookable_online = None
            if "is_bookable_online" in row:
                is_bookable_online = _parse_csv_boolean(
                    row.get("is_bookable_online", ""),
                    default=False,
                    row_number=row_number,
                    field_name="is_bookable_online",
                )
            requires_manual_confirmation = None
            if "requires_manual_confirmation" in row:
                requires_manual_confirmation = _parse_csv_boolean(
                    row.get("requires_manual_confirmation", ""),
                    default=True,
                    row_number=row_number,
                    field_name="requires_manual_confirmation",
                )
            default_duration_minutes = None
            if "default_duration_minutes" in row:
                default_duration_minutes = _parse_optional_csv_integer(
                    row.get("default_duration_minutes", ""),
                    row_number=row_number,
                    field_name="default_duration_minutes",
                    minimum=1,
                )
            booking_buffer_minutes = None
            if "booking_buffer_minutes" in row:
                booking_buffer_minutes = _parse_optional_csv_integer(
                    row.get("booking_buffer_minutes", ""),
                    row_number=row_number,
                    field_name="booking_buffer_minutes",
                    minimum=0,
                )
            category, category_created = _get_or_create_service_category_for_import(
                business=business,
                category_value=row.get("category", ""),
            )
            if category_created:
                created_category_count += 1

            external_code = row.get("external_code", "") or None
            service = None
            if external_code:
                service = (
                    BusinessService.objects.filter(
                        business=business,
                        external_code__iexact=external_code,
                    )
                    .order_by("pk")
                    .first()
                )

            if service is None:
                service = BusinessService(business=business)
                created_count += 1
            else:
                updated_count += 1

            service.category = category
            service.name = name
            service.description = row.get("description", "")
            service.unit_price = unit_price
            service.tax_rate = tax_rate
            service.is_active = is_active
            service.external_code = external_code
            if is_bookable_online is not None:
                service.is_bookable_online = is_bookable_online
            if "default_duration_minutes" in row:
                service.default_duration_minutes = default_duration_minutes
            if "booking_buffer_minutes" in row:
                service.booking_buffer_minutes = booking_buffer_minutes
            if "public_description" in row:
                service.public_description = row.get("public_description", "")
            if requires_manual_confirmation is not None:
                service.requires_manual_confirmation = requires_manual_confirmation
            service.save()

    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "created_category_count": created_category_count,
    }


# Fucntions below relate to public-facing lead capture and agent dashboard
@business_required()
@require_http_methods(["GET"])
def agent_dashboard(request: HttpRequest) -> HttpResponse:
    """Render the agent dashboard."""
    current_business = request.current_business
    current_membership = get_current_business_membership(request)
    now = timezone.now()
    start_of_today, start_of_tomorrow, start_of_month = _business_local_periods(
        current_business,
        now,
    )

    appointments_enabled = can_use_module(current_business, "appointments")
    invoices_enabled = can_use_module(current_business, "invoicing")
    public_booking_enabled = can_use_module(current_business, "public_booking")
    can_view_appointment_activity = appointments_enabled and membership_has_any_role(
        current_membership,
        APPOINTMENT_VIEW_ROLES,
    )
    can_view_invoice_activity = invoices_enabled and membership_has_any_role(
        current_membership,
        BILLING_VIEW_ROLES,
    )

    clients = _client_queryset_for_business(current_business)
    service_requests = _lead_queryset_for_business(current_business).filter(
        lead_type=Lead.LeadType.REQUEST
    )
    open_service_requests = service_requests.filter(status__in=SERVICE_REQUEST_ACTIVE_STATUSES)
    booking_requests_needing_review = service_requests.filter(
        request_source=Lead.RequestSource.PUBLIC_BOOKING,
        status=Lead.Status.NEW,
    )
    service_request_followups = _order_service_requests_for_followup(
        open_service_requests.select_related(
            "category",
            "requested_service",
        )
    )[:5]
    booking_request_followups = booking_requests_needing_review.select_related(
        "category",
        "requested_service",
    ).order_by("preferred_start_time", "created_at", "pk")[:5]

    upcoming_appointments = Appointment.objects.none()
    upcoming_appointment_count = 0
    today_appointment_count = 0

    if can_view_appointment_activity:
        upcoming_appointment_queryset = (
            _appointment_queryset_for_business(current_business)
            .filter(
                status=Appointment.Status.SCHEDULED,
                start_time__gte=now,
            )
            .order_by("start_time", "pk")
        )
        upcoming_appointments = upcoming_appointment_queryset[:5]
        upcoming_appointment_count = upcoming_appointment_queryset.count()
        today_appointment_count = (
            _appointment_queryset_for_business(current_business)
            .filter(
                status=Appointment.Status.SCHEDULED,
                start_time__gte=start_of_today,
                start_time__lt=start_of_tomorrow,
            )
            .count()
        )

    invoices = Invoice.objects.none()
    recent_invoices = Invoice.objects.none()
    unpaid_statuses = [Invoice.Status.DRAFT, Invoice.Status.SENT]
    invoice_count = 0
    draft_invoice_count = 0
    open_invoice_count = 0
    sent_invoice_count = 0
    paid_invoice_count = 0
    invoice_value_this_month = Decimal("0.00")
    unpaid_invoice_total = Decimal("0.00")
    paid_invoice_total = Decimal("0.00")

    if can_view_invoice_activity:
        invoices = Invoice.objects.filter(business=current_business).select_related(
            "client",
            "business",
        )
        paid_invoices = invoices.filter(status=Invoice.Status.PAID)
        recent_invoices = invoices.filter(status__in=unpaid_statuses).order_by(
            "-created_at",
            "-pk",
        )[:5]
        invoice_count = invoices.count()
        draft_invoice_count = invoices.filter(status=Invoice.Status.DRAFT).count()
        sent_invoice_count = invoices.filter(status=Invoice.Status.SENT).count()
        open_invoice_count = invoices.filter(status__in=unpaid_statuses).count()
        paid_invoice_count = paid_invoices.count()
        paid_invoice_total = paid_invoices.aggregate(total=Sum("total"))["total"] or Decimal("0.00")
        invoice_value_this_month = invoices.filter(created_at__gte=start_of_month).exclude(
            status=Invoice.Status.CANCELLED
        ).aggregate(total=Sum("total"))["total"] or Decimal("0.00")
        unpaid_invoice_total = invoices.filter(status__in=unpaid_statuses).aggregate(
            total=Sum("total")
        )["total"] or Decimal("0.00")

    context: dict[str, Any] = {
        "current_business": current_business,
        "dashboard_appointments_enabled": can_view_appointment_activity,
        "dashboard_invoices_enabled": can_view_invoice_activity,
        "appointments_module_enabled": appointments_enabled,
        "invoices_module_enabled": invoices_enabled,
        "public_booking_module_enabled": public_booking_enabled,
        "appointment_unavailable_message": (
            ""
            if appointments_enabled
            else get_business_module_unavailable_message(current_business, "appointments")
        ),
        "invoice_unavailable_message": (
            ""
            if invoices_enabled
            else get_business_module_unavailable_message(current_business, "invoicing")
        ),
        "public_booking_unavailable_message": (
            ""
            if public_booking_enabled
            else get_business_module_unavailable_message(current_business, "public_booking")
        ),
        "client_count": clients.count(),
        "new_client_count_this_month": clients.filter(created_at__gte=start_of_month).count(),
        "service_request_count": service_requests.count(),
        "open_service_request_count": open_service_requests.count(),
        "new_service_request_count": service_requests.filter(status=Lead.Status.NEW).count(),
        "service_request_count_this_month": service_requests.filter(
            created_at__gte=start_of_month,
        ).count(),
        "public_booking_pending_review_count": booking_requests_needing_review.count(),
        "service_request_followups": service_request_followups,
        "booking_request_followups": booking_request_followups,
        "recent_service_requests": service_request_followups,
        "invoice_count": invoice_count,
        "draft_invoice_count": draft_invoice_count,
        "open_invoice_count": open_invoice_count,
        "sent_invoice_count": sent_invoice_count,
        "unpaid_invoice_count": open_invoice_count,
        "paid_invoice_count": paid_invoice_count,
        "paid_invoice_total": paid_invoice_total,
        "invoice_value_this_month": invoice_value_this_month,
        "unpaid_invoice_total": unpaid_invoice_total,
        "recent_invoices": recent_invoices,
        "upcoming_appointments": upcoming_appointments,
        "today_appointment_count": today_appointment_count,
        "today_upcoming_appointment_count": today_appointment_count,
        "upcoming_appointment_count": upcoming_appointment_count,
    }
    return render(request, "crm/agent_dashboard/agent_dashboard.html", context)


@require_http_methods(["GET"])
def public_request_entry(request: HttpRequest) -> HttpResponse:
    current_business = get_current_business(request)
    if current_business is None:
        raise Http404("A business-specific request link is required.")
    if not (
        can_use_module(current_business, "public_booking")
        or can_use_module(current_business, "public_request_form")
    ):
        return redirect_for_unavailable_business_module(request, "public_request_form")
    return redirect("public_booking", business_slug=current_business.slug)


@require_http_methods(["GET", "POST"])
def public_request(request: HttpRequest, business_slug: str) -> HttpResponse:
    """
    Compatibility endpoint for old public request links.

    Public visitors now use the single public booking form. Existing POST
    submissions are still accepted so old embedded forms do not drop requests.
    """
    if request.method == "GET":
        business = get_object_or_404(Business, slug=business_slug, is_active=True)
        return redirect("public_booking", business_slug=business.slug)

    business = get_object_or_404(Business, slug=business_slug, is_active=True)
    if not can_use_module(business, "public_request_form"):
        return render(
            request,
            "crm/success_fail/public_request_unavailable.html",
            {
                "public_business": business,
                "availability_message": get_business_module_unavailable_message(
                    business,
                    "public_request_form",
                ),
            },
            status=403,
        )

    if request.method == "POST":
        form = PublicLeadForm(request.POST, business=business)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.business = business
            lead.request_source = Lead.RequestSource.PUBLIC_REQUEST
            lead.save()

            if lead.lead_type == Lead.LeadType.REQUEST:
                logger.info("Lead is of type REQUEST; creating/updating client")
                upsert_client_from_lead(lead)
            elif lead.lead_type == Lead.LeadType.INTEREST:
                logger.debug("Lead is of type INTEREST; creating lead without client")
            return redirect("public_thank_you")
    else:
        form = PublicLeadForm(business=business)

    return render(
        request,
        "crm/forms/public_request.html",
        {"form": form, "public_business": business},
    )


@require_http_methods(["GET", "POST"])
def public_booking(request: HttpRequest, business_slug: str) -> HttpResponse:
    business = get_object_or_404(Business, slug=business_slug, is_active=True)
    booking_settings = _public_booking_settings_for_business(business)
    appointments_enabled = can_use_module(business, "appointments")

    if not _public_booking_is_available(business, booking_settings):
        return _public_booking_unavailable_response(
            request,
            business=business,
        )

    selected_service_id = request.GET.get("service")
    if request.method == "POST":
        form = PublicBookingForm(
            request.POST,
            business=business,
            booking_settings=booking_settings,
            appointments_enabled=appointments_enabled,
        )
        if form.is_valid():
            service = form.cleaned_data["service"]
            staff_member = form.cleaned_data.get("staff_member")
            booking_intent = form.cleaned_data["booking_intent"]
            wants_appointment = booking_intent == PublicBookingForm.BOOK_NOW
            appointment = None
            with transaction.atomic():
                lead = Lead.objects.create(
                    business=business,
                    lead_type=Lead.LeadType.REQUEST,
                    status=Lead.Status.NEW,
                    category=service.category,
                    requested_service=service,
                    preferred_start_time=form.cleaned_data["preferred_start_time"],
                    preferred_end_time=form.cleaned_data["preferred_end_time"],
                    request_source=Lead.RequestSource.PUBLIC_BOOKING,
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                    company_name=form.cleaned_data["company_name"],
                    email=form.cleaned_data["email"],
                    phone=form.cleaned_data["phone"],
                    street_address=form.cleaned_data["street_address"],
                    district=form.cleaned_data.get("district") or "",
                    country=form.cleaned_data.get("country") or "Sint Maarten",
                    postal_code=form.cleaned_data.get("postal_code") or "N/A",
                    message=form.cleaned_data.get("message") or "",
                    notes=_build_public_booking_lead_notes(
                        booking_intent=booking_intent,
                        staff_member=staff_member,
                    ),
                    consent_to_contact=form.cleaned_data["consent_to_contact"],
                )
                client, _created = sync_client_from_lead(lead)
                if wants_appointment:
                    appointment = Appointment.objects.create(
                        business=business,
                        client=client,
                        service=service,
                        source_lead=lead,
                        staff_member=staff_member,
                        title=_build_public_booking_title(
                            lead=lead,
                            client=client,
                            service=service,
                        ),
                        start_time=lead.preferred_start_time,
                        end_time=lead.preferred_end_time,
                        location=_build_public_booking_location(lead, client),
                        notes=_build_public_booking_appointment_notes(lead),
                    )
            request_url = request.build_absolute_uri(reverse("staff_lead_detail", args=[lead.id]))
            if appointment is not None:
                send_appointment_confirmation_email(appointment)
            else:
                send_public_booking_request_received_email(lead)
            send_internal_booking_notification_email(lead, request_url=request_url)
            return redirect("public_booking_thank_you", business_slug=business.slug)
    else:
        form = PublicBookingForm(
            business=business,
            booking_settings=booking_settings,
            selected_service_id=selected_service_id,
            appointments_enabled=appointments_enabled,
        )

    return render(
        request,
        "crm/forms/public_booking.html",
        {
            "form": form,
            "public_business": business,
            "booking_settings": booking_settings,
            "appointments_enabled": appointments_enabled,
            "slot_picker_data": _public_booking_slot_picker_data(
                business=business,
                booking_settings=booking_settings,
                form=form,
            ),
        },
    )


@require_http_methods(["GET"])
def public_booking_thank_you(request: HttpRequest, business_slug: str) -> HttpResponse:
    business = get_object_or_404(Business, slug=business_slug, is_active=True)
    return render(
        request,
        "crm/success_fail/public_booking_thank_you.html",
        {"public_business": business},
    )


@require_http_methods(["GET"])
def public_thank_you(request: HttpRequest) -> HttpResponse:
    """Render the public request success page."""
    return render(request, "crm/success_fail/success.html")


# Functions below relate to client/leads management for staff users.
@business_role_required(
    *LEAD_MANAGE_ROLES,
    redirect_url_name="staff_lead_list",
    permission_message="You do not have permission to create or edit service requests.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def staff_lead_create(request: HttpRequest) -> HttpResponse:
    """
    Create a new service request for staff.
    """
    current_business = request.current_business

    if request.method == "POST":
        form = PrivateLeadForm(request.POST, business=current_business)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.business = current_business
            lead.save()
            messages.success(request, "Service request created successfully.")
            return redirect("staff_lead_list")
    else:
        form = PrivateLeadForm(business=current_business)

    context = {
        "form": form,
        "page_title": "Create a new service request",
        "submit_label": "Create service request",
    }

    return render(request, "crm/forms/lead_create.html", context)


@business_role_required(
    *ALL_WORKSPACE_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to view service requests.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def staff_lead_list(request: HttpRequest) -> HttpResponse:
    """
    List service requests for staff with optional filtering by status, type, and search query.
    """
    current_business = request.current_business
    qs: QuerySet[Lead] = _lead_queryset_for_business(current_business)

    status: str = (request.GET.get("status") or "").strip()
    status_group: str = (request.GET.get("status_group") or "active").strip()
    lead_type: str = (request.GET.get("lead_type") or "").strip()
    query: str = (request.GET.get("q") or "").strip()
    if status:
        qs = qs.filter(status=status)
        status_group = ""
    elif status_group == "all":
        pass
    elif status_group == "completed":
        qs = qs.filter(status__in=SERVICE_REQUEST_COMPLETED_STATUSES)
    else:
        status_group = "active"
        qs = qs.filter(status__in=SERVICE_REQUEST_ACTIVE_STATUSES)

    if lead_type:
        qs = qs.filter(lead_type=lead_type)
    if query:
        qs = qs.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(phone__icontains=query)
            | Q(requested_service__name__icontains=query)
        )

    context: dict[str, Any] = {
        "leads": _order_service_requests_for_followup(qs),
        "filters": {
            "status": status,
            "status_group": status_group or (request.GET.get("status_group") or "active"),
            "lead_type": lead_type,
            "q": query,
        },
        "status_group_links": {
            "active": _query_string_with(request, status_group="active", status=None),
            "completed": _query_string_with(request, status_group="completed", status=None),
            "all": _query_string_with(request, status_group="all", status=None),
        },
    }
    return render(request, "crm/main/lead_list.html", context)


@business_role_required(
    *CLIENT_MANAGE_ROLES,
    redirect_url_name="staff_client_list",
    permission_message="You do not have permission to create or edit clients.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def staff_client_create(request: HttpRequest) -> HttpResponse:
    """
    Create a new client for staff.
    """
    current_business = request.current_business

    if request.method == "POST":
        form = PrivateClientForm(request.POST, business=current_business)
        if form.is_valid():
            client = form.save(commit=False)
            client.business = current_business
            client.save()
            form.save_m2m()
            messages.success(request, "Client created successfully.")
            return redirect("staff_client_list")
    else:
        form = PrivateClientForm(business=current_business)

    context = {"form": form}
    return render(request, "crm/forms/client_create.html", context)


@business_role_required(
    *ALL_WORKSPACE_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to view clients.",
    raise_exception=False,
)
@require_http_methods(["GET"])
def staff_client_list(request: HttpRequest) -> HttpResponse:
    """
    List clients for staff with optional filtering by:
      - is_active (true/false)
      - district
      - search query (first/last/email/phone/company)
    """
    current_business = request.current_business
    qs: QuerySet[Client] = _client_queryset_for_business(current_business)

    # filters
    is_active_param: str = (request.GET.get("is_active") or "").strip().lower()
    district: str = (request.GET.get("district") or "").strip()
    query: str = (request.GET.get("q") or "").strip()

    # is_active: accept "true/false/1/0"
    if is_active_param in {"true", "1"}:
        qs = qs.filter(is_active=True)
    elif is_active_param in {"false", "0"}:
        qs = qs.filter(is_active=False)

    if district:
        qs = qs.filter(district=district)

    if query:
        qs = qs.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(phone__icontains=query)
            | Q(company_name__icontains=query)
        )

    if uses_sint_maarten_districts(current_business):
        district_choices = Client.DistrictChoices.choices
        district_filter_label = "District"
        district_filter_empty_label = "All districts"
    else:
        district_choices = [
            (value, value)
            for value in qs.model.objects.filter(business=current_business)
            .exclude(district="")
            .order_by("district")
            .values_list("district", flat=True)
            .distinct()
        ]
        district_filter_label = "Locality"
        district_filter_empty_label = "All localities"

    context: dict[str, Any] = {
        "clients": qs,
        "filters": {
            "is_active": is_active_param,
            "district": district,
            "q": query,
        },
        "district_filter_choices": district_choices,
        "district_filter_label": district_filter_label,
        "district_filter_empty_label": district_filter_empty_label,
    }
    return render(request, "crm/main/client_list.html", context)


@business_role_required(
    *CLIENT_MANAGE_ROLES,
    redirect_url_name="staff_client_list",
    permission_message="You do not have permission to create or edit clients.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def staff_client_update(request: HttpRequest, client_id: int) -> HttpResponse:
    """Update a client record with tabbed form interface."""
    current_business = request.current_business
    client = get_object_or_404(_client_queryset_for_business(current_business), pk=client_id)

    if request.method == "POST":
        form = PrivateClientForm(request.POST, instance=client, business=current_business)
        if form.is_valid():
            client = form.save(commit=False)
            client.business = current_business
            client.save()
            form.save_m2m()
            messages.success(request, "Client updated successfully.")
            return redirect("staff_client_detail", client_id=client.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = PrivateClientForm(instance=client, business=current_business)

    context: dict[str, Any] = {
        "client": client,
        "form": form,
    }
    return render(request, "crm/forms/client_update.html", context)


@business_role_required(
    *ALL_WORKSPACE_ROLES,
    redirect_url_name="staff_client_list",
    permission_message="You do not have permission to view clients.",
    raise_exception=False,
)
@require_http_methods(["GET"])
def staff_client_detail(request: HttpRequest, client_id: int) -> HttpResponse:
    """Display staff-facing details for a single client."""
    current_business = request.current_business
    client = get_object_or_404(_client_queryset_for_business(current_business), pk=client_id)
    upcoming_appointments = Appointment.objects.none()
    recent_appointment_history = Appointment.objects.none()

    if can_use_module(current_business, "appointments"):
        client_appointments = _appointment_queryset_for_business(current_business).filter(
            client=client,
        )
        upcoming_appointments = client_appointments.filter(
            start_time__gte=timezone.now(),
        ).order_by("start_time", "pk")[:5]
        recent_appointment_history = client_appointments.filter(
            status__in=(
                Appointment.Status.COMPLETED,
                Appointment.Status.CANCELLED,
            ),
        ).order_by("-start_time", "-pk")[:5]

    context: dict[str, Any] = {
        "clients": [client],
        "total_clients": 1,
        "single_client": client,
        "client_upcoming_appointments": upcoming_appointments,
        "client_recent_appointment_history": recent_appointment_history,
    }
    return render(request, "crm/main/client_detail.html", context)


@business_role_required(
    *ALL_WORKSPACE_ROLES,
    redirect_url_name="staff_lead_list",
    permission_message="You do not have permission to view service requests.",
    raise_exception=False,
)
@require_http_methods(["GET"])
def staff_lead_detail(request: HttpRequest, lead_id: int) -> HttpResponse:
    """Display staff-facing details for a single lead."""
    current_business = request.current_business
    lead = get_object_or_404(_lead_queryset_for_business(current_business), pk=lead_id)
    matched_client = None
    missing_client_fields: list[str] = []
    request_appointment = None
    request_ready_for_appointment = False
    if lead.lead_type == Lead.LeadType.REQUEST:
        matched_client = find_matching_client_for_lead(lead)
        if matched_client is None:
            missing_client_fields = get_missing_client_required_field_labels_for_lead(lead)
        request_ready_for_appointment = matched_client is not None or not missing_client_fields
        request_appointment = (
            Appointment.objects.filter(
                business=current_business,
                source_lead=lead,
            )
            .select_related("client", "service", "staff_member")
            .order_by("-start_time", "-pk")
            .first()
        )
    context: dict[str, Any] = {
        "lead": lead,
        "matched_client": matched_client,
        "missing_client_fields": missing_client_fields,
        "request_appointment": request_appointment,
        "request_ready_for_appointment": request_ready_for_appointment,
    }
    return render(request, "crm/main/lead_detail.html", context)


@business_role_required(
    *LEAD_MANAGE_ROLES,
    redirect_url_name="staff_lead_list",
    permission_message="You do not have permission to create or edit service requests.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def staff_lead_update(request: HttpRequest, lead_id: int) -> HttpResponse:
    current_business = request.current_business
    lead = get_object_or_404(_lead_queryset_for_business(current_business), pk=lead_id)

    if request.method == "POST":
        form = PrivateLeadForm(request.POST, instance=lead, business=current_business)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.business = current_business
            lead.save()
            messages.success(request, "Service request updated successfully.")
            return redirect("staff_lead_detail", lead_id=lead.id)
        messages.error(request, "Please correct the errors below.")
    else:
        form = PrivateLeadForm(instance=lead, business=current_business)

    context: dict[str, Any] = {
        "form": form,
        "lead": lead,
        "page_title": f"Edit service request: {lead.first_name} {lead.last_name}",
        "submit_label": "Save changes",
    }
    return render(request, "crm/forms/lead_create.html", context)


@business_role_required(
    *CLIENT_MANAGE_ROLES,
    redirect_url_name="staff_lead_list",
    permission_message="You do not have permission to convert service requests into clients.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def staff_lead_convert_to_client(request: HttpRequest, lead_id: int) -> HttpResponse:
    current_business = request.current_business
    lead = get_object_or_404(
        _lead_queryset_for_business(current_business).filter(lead_type=Lead.LeadType.REQUEST),
        pk=lead_id,
    )
    matched_client = find_matching_client_for_lead(lead)

    if matched_client is not None:
        messages.info(
            request,
            "This service request already matches a client in the current workspace.",
        )
        return redirect("staff_client_detail", client_id=matched_client.id)

    if request.method == "POST":
        form = LeadClientConversionForm(request.POST, instance=lead)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.business = current_business
            lead.save()
            client, created = sync_client_from_lead(lead)
            if created:
                messages.success(request, "Client created from service request successfully.")
            else:
                messages.success(
                    request,
                    "Service request matched an existing client in this workspace.",
                )
            return redirect("staff_client_detail", client_id=client.id)
        messages.error(request, "Please complete the required client details below.")
    else:
        form = LeadClientConversionForm(instance=lead)

    context: dict[str, Any] = {
        "form": form,
        "lead": lead,
        "missing_client_fields": get_missing_client_required_field_labels_for_lead(lead),
    }
    return render(request, "crm/forms/request_convert_to_client.html", context)


@business_role_required(
    *BILLING_MANAGE_ROLES,
    redirect_url_name="staff_lead_list",
    permission_message="You do not have permission to manage invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["GET"])
def staff_lead_create_invoice(request: HttpRequest, lead_id: int) -> HttpResponse:
    current_business = request.current_business
    lead = get_object_or_404(
        _lead_queryset_for_business(current_business).filter(lead_type=Lead.LeadType.REQUEST),
        pk=lead_id,
    )
    matched_client = find_matching_client_for_lead(lead)

    if matched_client is None:
        messages.info(
            request,
            "Complete this service request as a client before starting an invoice.",
        )
        return redirect("staff_lead_convert_to_client", lead_id=lead.id)

    return redirect("invoice_create_from_client", client_id=matched_client.id)


@business_role_required(
    *ALL_WORKSPACE_ROLES,
    redirect_url_name="staff_client_list",
    permission_message="You do not have permission to view clients.",
    raise_exception=False,
)
@require_http_methods(["GET"])
def client_detail_view(request: HttpRequest) -> HttpResponse:
    """
    Display a detailed view of active clients for the current business only.
    """
    current_business = request.current_business
    clients = (
        _client_queryset_for_business(current_business)
        .filter(is_active=True)
        .order_by("-created_at")
    )

    context: dict[str, Any] = {
        "clients": clients,
        "total_clients": clients.count(),
    }

    return render(request, "crm/main/client_detail.html", context)


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["GET"])
def business_service_category_list(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business
    categories = _service_category_queryset_for_business(current_business)

    context: dict[str, Any] = {
        "categories": categories,
        "business": current_business,
        "active_category_count": categories.filter(is_active=True).count(),
        "archived_category_count": categories.filter(is_active=False).count(),
    }
    return render(request, "crm/settings/service_category_list.html", context)


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def business_service_category_create(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business

    if request.method == "POST":
        form = ServiceCategoryForm(request.POST, business=current_business)
        if form.is_valid():
            form.save()
            messages.success(request, "Service category created.")
            return redirect("business_service_category_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = ServiceCategoryForm(business=current_business)

    context: dict[str, Any] = {
        "form": form,
        "business": current_business,
        "page_title": "Create service category",
        "submit_label": "Create category",
    }
    return render(request, "crm/settings/service_category_form.html", context)


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def business_service_category_update(request: HttpRequest, category_id: int) -> HttpResponse:
    current_business = request.current_business
    category = get_object_or_404(
        _service_category_queryset_for_business(current_business),
        pk=category_id,
    )

    if request.method == "POST":
        form = ServiceCategoryForm(
            request.POST,
            instance=category,
            business=current_business,
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Service category updated.")
            return redirect("business_service_category_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = ServiceCategoryForm(instance=category, business=current_business)

    context: dict[str, Any] = {
        "form": form,
        "business": current_business,
        "category": category,
        "page_title": f"Edit service category: {category.name}",
        "submit_label": "Save changes",
    }
    return render(request, "crm/settings/service_category_form.html", context)


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["POST"])
def business_service_category_archive(request: HttpRequest, category_id: int) -> HttpResponse:
    current_business = request.current_business
    category = get_object_or_404(
        _service_category_queryset_for_business(current_business),
        pk=category_id,
    )

    if category.is_active:
        category.is_active = False
        category.save(update_fields=["is_active", "updated_at", "code"])
        messages.success(request, f"{category.name} was archived.")
    else:
        messages.info(request, f"{category.name} is already archived.")

    return redirect("business_service_category_list")


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["GET"])
def business_service_list(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business
    services = _business_service_queryset_for_business(current_business)
    public_booking_allowed = can_use_module(current_business, "public_booking")

    context: dict[str, Any] = {
        "business": current_business,
        "services": services,
        "active_service_count": services.filter(is_active=True).count(),
        "archived_service_count": services.filter(is_active=False).count(),
        "bookable_service_count": services.filter(
            is_active=True,
            is_bookable_online=True,
        ).count(),
        "public_booking_allowed": public_booking_allowed,
        "public_booking_unavailable_message": (
            ""
            if public_booking_allowed
            else get_business_module_unavailable_message(current_business, "public_booking")
        ),
    }
    return render(request, "crm/settings/business_service_list.html", context)


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def business_service_create(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business

    if request.method == "POST":
        form = BusinessServiceForm(request.POST, business=current_business)
        if form.is_valid():
            form.save()
            messages.success(request, "Service created.")
            return redirect("business_service_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = BusinessServiceForm(business=current_business)

    context: dict[str, Any] = {
        "form": form,
        "business": current_business,
        "page_title": "Create service",
        "submit_label": "Create service",
        "public_booking_allowed": can_use_module(current_business, "public_booking"),
    }
    if not context["public_booking_allowed"]:
        context["public_booking_unavailable_message"] = get_business_module_unavailable_message(
            current_business,
            "public_booking",
        )
    return render(request, "crm/settings/business_service_form.html", context)


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def business_service_update(request: HttpRequest, service_id: int) -> HttpResponse:
    current_business = request.current_business
    service = get_object_or_404(
        _business_service_queryset_for_business(current_business),
        pk=service_id,
    )

    if request.method == "POST":
        form = BusinessServiceForm(
            request.POST,
            instance=service,
            business=current_business,
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Service updated.")
            return redirect("business_service_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = BusinessServiceForm(instance=service, business=current_business)

    context: dict[str, Any] = {
        "form": form,
        "business": current_business,
        "service": service,
        "page_title": f"Edit service: {service.name}",
        "submit_label": "Save changes",
        "public_booking_allowed": can_use_module(current_business, "public_booking"),
    }
    if not context["public_booking_allowed"]:
        context["public_booking_unavailable_message"] = get_business_module_unavailable_message(
            current_business,
            "public_booking",
        )
    return render(request, "crm/settings/business_service_form.html", context)


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["POST"])
def business_service_archive(request: HttpRequest, service_id: int) -> HttpResponse:
    current_business = request.current_business
    service = get_object_or_404(
        _business_service_queryset_for_business(current_business),
        pk=service_id,
    )

    if service.is_active:
        service.is_active = False
        service.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"{service.name} was archived.")
    else:
        messages.info(request, f"{service.name} is already archived.")

    return redirect("business_service_list")


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["GET", "POST"])
def business_service_import(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business
    import_errors: list[str] = []

    if request.method == "POST":
        form = BusinessServiceCSVImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                results = _import_business_services_from_csv(
                    business=current_business,
                    uploaded_file=form.cleaned_data["csv_file"],
                )
            except ValidationError as exc:
                import_errors = exc.messages
                messages.error(request, "The CSV import could not be completed.")
            else:
                messages.success(
                    request,
                    (
                        f"Imported services for {current_business.name}: "
                        f"{results['created_count']} created, "
                        f"{results['updated_count']} updated, "
                        f"{results['created_category_count']} categories created."
                    ),
                )
                return redirect("business_service_list")
        else:
            messages.error(request, "Please upload a CSV file.")
    else:
        form = BusinessServiceCSVImportForm()

    context: dict[str, Any] = {
        "business": current_business,
        "form": form,
        "import_errors": import_errors,
        "import_columns": _service_import_columns(),
        "sample_rows": _service_import_example_rows(current_business),
        "sample_csv_text": _service_import_example_csv_text(current_business),
        "price_input_example": localized_price_input_example(current_business),
    }
    return render(request, "crm/settings/business_service_import.html", context)


@business_role_required(
    *SERVICE_MANAGEMENT_ROLES,
    redirect_url_name="business_settings",
    permission_message="You do not have permission to manage services or categories.",
    raise_exception=False,
)
@require_http_methods(["GET"])
def business_service_sample_csv(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business
    response = HttpResponse(
        _service_import_example_csv_text(current_business), content_type="text/csv"
    )
    response["Content-Disposition"] = 'attachment; filename="motionmate_services_sample.csv"'
    return response
