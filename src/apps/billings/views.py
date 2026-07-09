import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.appointments.models import Appointment
from apps.businesses.localization import format_money_for_business
from apps.businesses.models import Business
from apps.businesses.utils import (
    BILLING_MANAGE_ROLES,
    BILLING_VIEW_ROLES,
    OWNER_ADMIN_ROLES,
    business_limit_reached,
    business_module_required,
    business_role_required,
    get_business_limit_reached_message,
)
from apps.crm.models import ActivityLog, BusinessService, Client, ServiceCategory
from apps.crm.services import log_activity
from apps.notifications.emails import send_invoice_email

from .models import Invoice, InvoiceLine
from .pdf import invoice_pdf_filename, render_invoice_pdf
from .services import calculate_tax_amount, create_invoice_for_client, generate_invoice_number

logger = logging.getLogger(__name__)

STATUS_TRANSITIONS: dict[str, set[str]] = {
    Invoice.Status.DRAFT: {Invoice.Status.SENT, Invoice.Status.CANCELLED},
    Invoice.Status.SENT: {Invoice.Status.PAID, Invoice.Status.CANCELLED},
    Invoice.Status.PAID: set(),
    Invoice.Status.CANCELLED: set(),
}
INVOICE_LINE_DESCRIPTION_MAX_LENGTH = InvoiceLine._meta.get_field("description").max_length
BUSINESS_SERVICE_NAME_MAX_LENGTH = BusinessService._meta.get_field("name").max_length
SERVICE_CATEGORY_NAME_MAX_LENGTH = ServiceCategory._meta.get_field("name").max_length


def _parse_decimal(value: str | None, *, default: Decimal = Decimal("0.00")) -> Decimal:
    try:
        return Decimal(value or str(default))
    except (InvalidOperation, TypeError):
        return default


def _parse_optional_decimal(value: str | None) -> Decimal | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return Decimal(str(value).strip())
    except (InvalidOperation, TypeError):
        return None


def _recalculate_invoice_totals(invoice: Invoice) -> None:
    subtotal = sum(
        (line.line_total for line in InvoiceLine.objects.filter(invoice=invoice).only("line_total")),
        start=Decimal("0.00"),
    )
    business = invoice.business
    tax_rate = business.tax_rate if business is not None else Decimal("0.00")

    invoice.subtotal = subtotal
    invoice.tax = calculate_tax_amount(subtotal=subtotal, tax_rate=tax_rate)
    invoice.total = invoice.subtotal + invoice.tax
    invoice.save(update_fields=["subtotal", "tax", "total"])


def _client_queryset_for_business(business: Business):
    return Client.objects.filter(business=business)


def _service_queryset_for_business(business: Business):
    return BusinessService.for_business(business)


def _service_category_queryset_for_business(business: Business):
    return ServiceCategory.for_business(business)


def _invoice_queryset_for_business(business: Business):
    return Invoice.objects.filter(business=business).select_related(
        "appointment",
        "client",
        "business",
    )


def _appointment_queryset_for_business(business: Business):
    return Appointment.objects.filter(business=business).select_related(
        "business",
        "client",
        "service",
        "source_lead",
    )


def _whatsapp_digits(value: str | None) -> str:
    return "".join(re.findall(r"\d+", value or ""))


def _invoice_whatsapp_share_url(invoice: Invoice) -> str:
    client = invoice.client
    business = invoice.business
    client_name = " ".join(
        part for part in [client.first_name, client.last_name] if part
    ).strip()
    greeting = f"Hello {client_name}," if client_name else "Hello,"
    total = format_money_for_business(invoice.total, business)
    message = (
        f"{greeting} invoice {invoice.invoice_number} from {business.name} is ready. "
        f"Total: {total}. Please contact us if you have any questions."
    )
    whatsapp_number = _whatsapp_digits(client.whatsapp_number) or _whatsapp_digits(client.phone)
    whatsapp_url = f"https://wa.me/{whatsapp_number}" if whatsapp_number else "https://wa.me/"
    return f"{whatsapp_url}?text={quote(message)}"


def _posted_value(values: list[str], index: int, default: str = "") -> str:
    if index < len(values):
        return values[index]
    return default


def _build_line_rows_from_post(
    request: HttpRequest,
    *,
    field_prefix: str = "",
    include_line_ids: bool = False,
    default_blank_row: bool = False,
) -> list[dict[str, Any]]:
    line_ids = request.POST.getlist("line_id") if include_line_ids else []
    service_ids = request.POST.getlist(f"{field_prefix}service_id")
    descriptions = request.POST.getlist(f"{field_prefix}description")
    quantities = request.POST.getlist(f"{field_prefix}quantity")
    unit_prices = request.POST.getlist(f"{field_prefix}unit_price")
    save_as_services = request.POST.getlist(f"{field_prefix}save_as_service")
    service_category_ids = request.POST.getlist(f"{field_prefix}service_category_id")
    new_service_category_names = request.POST.getlist(f"{field_prefix}new_service_category_name")

    row_count = max(
        len(line_ids),
        len(service_ids),
        len(descriptions),
        len(quantities),
        len(unit_prices),
        len(save_as_services),
        len(service_category_ids),
        len(new_service_category_names),
    )
    if row_count == 0 and default_blank_row:
        row_count = 1

    rows: list[dict[str, Any]] = []
    for index in range(row_count):
        row = {
            "service_id": _posted_value(service_ids, index),
            "description": _posted_value(descriptions, index),
            "quantity": _posted_value(quantities, index),
            "unit_price": _posted_value(unit_prices, index),
            "save_as_service": _posted_value(save_as_services, index),
            "service_category_id": _posted_value(service_category_ids, index),
            "new_service_category_name": _posted_value(new_service_category_names, index),
        }
        if include_line_ids:
            row["line_id"] = _posted_value(line_ids, index)
        rows.append(row)
    return rows


def _invoice_line_rows(invoice: Invoice) -> list[dict[str, Any]]:
    return [
        {
            "line_id": str(line.pk),
            "service_id": str(line.service_id or ""),
            "description": line.description,
            "quantity": line.quantity,
            "unit_price": line.unit_price,
            "save_as_service": "",
            "service_category_id": "",
            "new_service_category_name": "",
        }
        for line in invoice.lines.all()
    ]


def _new_line_rows(default_blank_row: bool = False) -> list[dict[str, Any]]:
    if not default_blank_row:
        return []
    return [
        {
            "service_id": "",
            "description": "",
            "quantity": "",
            "unit_price": "",
            "save_as_service": "",
            "service_category_id": "",
            "new_service_category_name": "",
        }
    ]


def _service_snapshot_description(service: BusinessService) -> str:
    return (service.description or "").strip() or service.name


def _service_snapshot_unit_price(
    service: BusinessService,
    *,
    posted_unit_price: str = "",
) -> Decimal:
    if service.unit_price != Decimal("0.00"):
        return service.unit_price

    return _parse_optional_decimal(posted_unit_price) or Decimal("0.00")


def _should_refresh_existing_service_snapshot(
    *,
    existing_line: InvoiceLine,
    service: BusinessService,
    posted_description: str,
    posted_unit_price: str,
) -> bool:
    snapshot_description = _service_snapshot_description(service)
    posted_price = _parse_optional_decimal(posted_unit_price)

    if posted_description != snapshot_description:
        return False
    if posted_price != service.unit_price:
        return False

    return (
        existing_line.description != snapshot_description
        or existing_line.unit_price != service.unit_price
    )


def _truthy_post_value(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_posted_service_category(
    *,
    business: Business,
    category_id: str,
) -> ServiceCategory | None:
    category_id = str(category_id or "").strip()
    if not category_id:
        return None

    try:
        return _service_category_queryset_for_business(business).filter(pk=category_id).first()
    except (TypeError, ValueError):
        return None


def _get_or_create_manual_service_category(
    *,
    business: Business,
    category: ServiceCategory | None,
    new_category_name: str,
) -> ServiceCategory | None:
    if category is not None:
        return category

    new_category_name = new_category_name.strip()
    if not new_category_name:
        return None

    existing_category = ServiceCategory.objects.filter(
        business=business,
        name__iexact=new_category_name,
    ).first()
    if existing_category is not None:
        return existing_category

    return ServiceCategory.objects.create(
        business=business,
        name=new_category_name,
        is_active=True,
    )


def _create_manual_business_service(
    *,
    business: Business,
    line_row: dict[str, Any],
) -> BusinessService:
    category = _get_or_create_manual_service_category(
        business=business,
        category=line_row["manual_service_category"],
        new_category_name=line_row["new_service_category_name"],
    )
    return BusinessService.objects.create(
        business=business,
        category=category,
        name=line_row["description"],
        description=line_row["description"],
        unit_price=line_row["unit_price"],
        tax_rate=business.tax_rate or Decimal("0.00"),
        is_active=True,
    )


def _service_for_invoice_line(
    *,
    business: Business,
    line_row: dict[str, Any],
) -> BusinessService | None:
    if line_row["service"] is not None:
        return line_row["service"]
    if not line_row["save_as_service"]:
        return None

    return _create_manual_business_service(
        business=business,
        line_row=line_row,
    )


def _clean_line_rows(
    *,
    rows: list[dict[str, Any]],
    active_services_by_id: dict[str, BusinessService],
    business: Business,
    line_label: str,
    existing_lines_by_id: dict[str, InvoiceLine] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    cleaned_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, row in enumerate(rows, start=1):
        service_id = str(row.get("service_id", "")).strip()
        description = str(row.get("description", "")).strip()
        quantity = str(row.get("quantity", "")).strip()
        unit_price = str(row.get("unit_price", "")).strip()
        save_as_service = _truthy_post_value(row.get("save_as_service"))
        service_category_id = str(row.get("service_category_id", "")).strip()
        new_service_category_name = str(row.get("new_service_category_name", "")).strip()

        if (
            not service_id
            and not description
            and not quantity
            and not unit_price
            and not save_as_service
            and not service_category_id
            and not new_service_category_name
        ):
            continue

        service = None
        manual_service_category = None
        if service_id:
            service = active_services_by_id.get(service_id)
            if service is None:
                errors.append(
                    f"{line_label} {index}: selected service is not available in this workspace."
                )
                continue
            existing_line = None
            if existing_lines_by_id is not None and "line_id" in row:
                existing_line = existing_lines_by_id.get(str(row["line_id"]))

            if existing_line is not None and existing_line.service_id == service.pk:
                if _should_refresh_existing_service_snapshot(
                    existing_line=existing_line,
                    service=service,
                    posted_description=description,
                    posted_unit_price=unit_price,
                ):
                    description_value = _service_snapshot_description(service)
                    unit_price_value = _service_snapshot_unit_price(
                        service,
                        posted_unit_price=unit_price,
                    )
                else:
                    description_value = existing_line.description
                    unit_price_value = existing_line.unit_price
            else:
                description_value = _service_snapshot_description(service)
                unit_price_value = _service_snapshot_unit_price(
                    service,
                    posted_unit_price=unit_price,
                )
        else:
            if save_as_service and not description:
                errors.append(f"{line_label} {index}: enter a description to save as a service.")
                continue

            if save_as_service and len(description) > BUSINESS_SERVICE_NAME_MAX_LENGTH:
                errors.append(
                    f"{line_label} {index}: saved service name must be "
                    f"{BUSINESS_SERVICE_NAME_MAX_LENGTH} characters or fewer."
                )
                continue

            if save_as_service and service_category_id and new_service_category_name:
                errors.append(
                    f"{line_label} {index}: choose an existing category or enter a new category, not both."
                )
                continue

            if save_as_service and len(new_service_category_name) > SERVICE_CATEGORY_NAME_MAX_LENGTH:
                errors.append(
                    f"{line_label} {index}: new category name must be "
                    f"{SERVICE_CATEGORY_NAME_MAX_LENGTH} characters or fewer."
                )
                continue

            if save_as_service and service_category_id:
                manual_service_category = _resolve_posted_service_category(
                    business=business,
                    category_id=service_category_id,
                )
                if manual_service_category is None:
                    errors.append(
                        f"{line_label} {index}: selected service category is not available in this workspace."
                    )
                    continue

            description_value = description or "Line item"
            unit_price_value = _parse_decimal(unit_price)

        if (
            INVOICE_LINE_DESCRIPTION_MAX_LENGTH is not None
            and len(description_value) > INVOICE_LINE_DESCRIPTION_MAX_LENGTH
        ):
            errors.append(
                f"{line_label} {index}: description must be "
                f"{INVOICE_LINE_DESCRIPTION_MAX_LENGTH} characters or fewer."
            )
            continue

        cleaned_row = {
            "service": service,
            "description": description_value,
            "quantity": _parse_decimal(quantity, default=Decimal("1.00")),
            "unit_price": unit_price_value,
            "save_as_service": bool(save_as_service and service is None),
            "manual_service_category": manual_service_category,
            "service_category_id": str(manual_service_category.pk) if manual_service_category else "",
            "new_service_category_name": new_service_category_name,
        }
        if "line_id" in row:
            cleaned_row["line_id"] = str(row["line_id"])
        cleaned_rows.append(cleaned_row)

    return cleaned_rows, errors


def _existing_invoice_for_appointment(
    *,
    business: Business,
    appointment: Appointment,
) -> Invoice | None:
    return (
        _invoice_queryset_for_business(business)
        .filter(appointment=appointment)
        .order_by("-created_at", "-pk")
        .first()
    )


def _build_invoice_notes_for_appointment(appointment: Appointment) -> str:
    local_start = timezone.localtime(appointment.start_time)
    local_end = timezone.localtime(appointment.end_time)
    notes = [
        f"Created from appointment #{appointment.pk}.",
        f"Appointment time: {local_start:%b %d, %Y %H:%M} to {local_end:%H:%M}.",
        f"Appointment title: {appointment.title}",
    ]

    if appointment.location:
        notes.append(f"Location: {appointment.location}")
    if appointment.source_lead_id is not None:
        notes.append(f"Linked service request #{appointment.source_lead_id}.")

    return "\n".join(notes)


def _initial_line_rows_for_appointment(appointment: Appointment) -> list[dict[str, Any]]:
    if appointment.service_id is not None:
        return [
            {
                "service_id": str(appointment.service_id),
                "description": _service_snapshot_description(appointment.service),
                "quantity": "1",
                "unit_price": (
                    ""
                    if appointment.service.unit_price == Decimal("0.00")
                    else appointment.service.unit_price
                ),
            }
        ]

    if appointment.service_name.strip():
        return [
            {
                "service_id": "",
                "description": appointment.service_name.strip(),
                "quantity": "1",
                "unit_price": "",
            }
        ]

    return _new_line_rows(default_blank_row=True)


def _invoice_create_response(
    request: HttpRequest,
    *,
    client: Client | None = None,
    source_appointment: Appointment | None = None,
) -> HttpResponse:
    current_business = request.current_business
    if business_limit_reached(current_business, "invoices_per_month"):
        messages.error(
            request,
            get_business_limit_reached_message(current_business, "invoices_per_month"),
        )
        return redirect("invoice_list")

    available_clients = list(
        _client_queryset_for_business(current_business).order_by("first_name", "last_name", "pk")
    )
    available_services = list(_service_queryset_for_business(current_business))
    service_categories = list(_service_category_queryset_for_business(current_business))
    active_services_by_id = {str(service.pk): service for service in available_services}
    selected_client = client
    appointment_notes = (
        _build_invoice_notes_for_appointment(source_appointment)
        if source_appointment is not None
        else ""
    )
    line_rows = (
        _initial_line_rows_for_appointment(source_appointment)
        if source_appointment is not None
        else _new_line_rows(default_blank_row=True)
    )
    draft_notes = appointment_notes

    if request.method == "POST":
        line_rows = _build_line_rows_from_post(request, default_blank_row=True)
        draft_notes = request.POST.get("notes", "").strip() or appointment_notes
        client_errors: list[str] = []

        if selected_client is None:
            client_id = request.POST.get("client_id", "").strip()
            if client_id:
                try:
                    selected_client = _client_queryset_for_business(current_business).filter(
                        pk=client_id
                    ).first()
                except (TypeError, ValueError):
                    selected_client = None
            if selected_client is None:
                client_errors.append("Select a client before creating the invoice.")

        cleaned_line_rows, line_errors = _clean_line_rows(
            rows=line_rows,
            active_services_by_id=active_services_by_id,
            business=current_business,
            line_label="Line item",
        )
        errors = [*client_errors, *line_errors]

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            with transaction.atomic():
                invoice = create_invoice_for_client(
                    actor=request.user,
                    client=selected_client,
                    appointment=source_appointment,
                    notes=draft_notes,
                )

                for line_row in cleaned_line_rows:
                    InvoiceLine.objects.create(
                        invoice=invoice,
                        service=_service_for_invoice_line(
                            business=current_business,
                            line_row=line_row,
                        ),
                        description=line_row["description"],
                        quantity=line_row["quantity"],
                        unit_price=line_row["unit_price"],
                    )

                if cleaned_line_rows:
                    _recalculate_invoice_totals(invoice)

            return redirect("invoice_detail", invoice_id=invoice.id)

    context: dict[str, Any] = {
        "client": selected_client,
        "available_clients": available_clients,
        "current_business": current_business,
        "draft_notes": draft_notes,
        "invoice_number_preview": generate_invoice_number(business=current_business),
        "available_services": available_services,
        "service_categories": service_categories,
        "line_rows": line_rows,
        "blank_line_row": _new_line_rows(default_blank_row=True)[0],
        "source_appointment": source_appointment,
        "client_is_locked": client is not None or source_appointment is not None,
    }
    return render(request, "billings/invoice_create.html", context)


@business_role_required(
    *BILLING_MANAGE_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["GET", "POST"])
def invoice_create(request: HttpRequest) -> HttpResponse:
    return _invoice_create_response(request)


@business_role_required(
    *BILLING_MANAGE_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["GET", "POST"])
def invoice_create_from_client(request: HttpRequest, client_id: int) -> HttpResponse:
    current_business = request.current_business
    client = get_object_or_404(_client_queryset_for_business(current_business), pk=client_id)
    return _invoice_create_response(request, client=client)


@business_role_required(
    *BILLING_MANAGE_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to manage invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["GET", "POST"])
def invoice_create_from_appointment(request: HttpRequest, appointment_id: int) -> HttpResponse:
    current_business = request.current_business
    appointment = get_object_or_404(
        _appointment_queryset_for_business(current_business),
        pk=appointment_id,
    )
    existing_invoice = _existing_invoice_for_appointment(
        business=current_business,
        appointment=appointment,
    )
    if existing_invoice is not None:
        messages.info(
            request,
            f"Invoice {existing_invoice.invoice_number} is already linked to this appointment.",
        )
        return redirect("invoice_detail", invoice_id=existing_invoice.id)

    return _invoice_create_response(
        request,
        client=appointment.client,
        source_appointment=appointment,
    )


@business_role_required(
    *BILLING_VIEW_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to view invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["GET"])
def invoice_detail(request: HttpRequest, invoice_id: int) -> HttpResponse:
    """
    Display invoice details.

    Args:
        request: Incoming HTTP request.
        invoice_id: Primary key of the Invoice.

    Returns:
        Rendered invoice detail page.
    """
    current_business = request.current_business
    invoice = get_object_or_404(
        _invoice_queryset_for_business(current_business).prefetch_related("lines"),
        pk=invoice_id,
    )

    context: dict[str, Any] = {
        "invoice": invoice,
        "whatsapp_share_url": _invoice_whatsapp_share_url(invoice),
    }
    return render(request, "billings/invoice_detail.html", context)


@business_role_required(
    *BILLING_VIEW_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to view invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["GET"])
def invoice_pdf_download(request: HttpRequest, invoice_id: int) -> HttpResponse:
    current_business = request.current_business
    invoice = get_object_or_404(
        _invoice_queryset_for_business(current_business).prefetch_related("lines"),
        pk=invoice_id,
    )

    try:
        pdf_bytes = render_invoice_pdf(invoice, current_business=current_business)
    except Exception:
        logger.exception("Failed to generate invoice PDF for invoice_id=%s", invoice.id)
        messages.error(request, "Invoice PDF could not be generated. Please try again.")
        return redirect("invoice_detail", invoice_id=invoice.id)

    filename = invoice_pdf_filename(invoice)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@business_role_required(
    *BILLING_MANAGE_ROLES,
    redirect_url_name="invoice_list",
    permission_message="You do not have permission to manage invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["POST"])
def invoice_email_send(request: HttpRequest, invoice_id: int) -> HttpResponse:
    current_business = request.current_business
    invoice = get_object_or_404(
        _invoice_queryset_for_business(current_business).prefetch_related("lines"),
        pk=invoice_id,
    )
    recipient = (invoice.client.email or "").strip()

    try:
        validate_email(recipient)
    except ValidationError:
        messages.error(
            request,
            "This client does not have a valid email address. Add one before sending the invoice.",
        )
        return redirect("invoice_detail", invoice_id=invoice.id)

    try:
        pdf_bytes = render_invoice_pdf(
            invoice,
            current_business=current_business,
            include_notes=False,
        )
    except Exception:
        logger.exception("Failed to generate invoice email PDF for invoice_id=%s", invoice.id)
        messages.error(request, "Invoice PDF could not be generated, so no email was sent.")
        return redirect("invoice_detail", invoice_id=invoice.id)

    filename = invoice_pdf_filename(invoice)
    if not send_invoice_email(invoice, pdf_bytes=pdf_bytes, filename=filename):
        messages.error(
            request,
            "Invoice email could not be sent. Check email settings and try again.",
        )
        return redirect("invoice_detail", invoice_id=invoice.id)

    now = timezone.now()
    Invoice.objects.filter(pk=invoice.pk).update(
        emailed_at=now,
        emailed_to=recipient,
        email_send_count=F("email_send_count") + 1,
    )
    log_activity(
        actor=request.user,
        action_type=ActivityLog.ActionType.EMAIL_SENT,
        business=invoice.business,
        client=invoice.client,
        summary=f"Invoice {invoice.invoice_number} emailed to {recipient}",
        payload={
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "emailed_to": recipient,
        },
    )
    messages.success(request, f"Invoice emailed to {recipient}.")
    return redirect("invoice_detail", invoice_id=invoice.id)


@business_role_required(
    *BILLING_VIEW_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to view invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["GET"])
def invoice_list(request: HttpRequest) -> HttpResponse:
    """
    Display list of all invoices.

    Args:
        request: Incoming HTTP request.

    Returns:
        Rendered invoice list page.
    """
    current_business = request.current_business
    invoices = _invoice_queryset_for_business(current_business).order_by("-created_at")

    # Filter by status if provided
    status_filter = request.GET.get("status")
    if status_filter:
        invoices = invoices.filter(status=status_filter)

    context: dict[str, Any] = {
        "invoices": invoices,
        "status_choices": Invoice.Status.choices,
        "current_status": status_filter,
    }
    return render(request, "billings/invoice_list.html", context)


@business_role_required(
    *BILLING_MANAGE_ROLES,
    redirect_url_name="invoice_list",
    permission_message="You do not have permission to manage invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["GET", "POST"])
def invoice_edit(request: HttpRequest, invoice_id: int) -> HttpResponse:
    current_business = request.current_business
    invoice = get_object_or_404(
        _invoice_queryset_for_business(current_business).prefetch_related("lines"),
        pk=invoice_id,
    )
    available_services = list(_service_queryset_for_business(current_business))
    service_categories = list(_service_category_queryset_for_business(current_business))
    active_services_by_id = {str(service.pk): service for service in available_services}
    existing_line_rows = _invoice_line_rows(invoice)
    new_line_rows = _new_line_rows()
    draft_notes = invoice.notes

    if invoice.status != Invoice.Status.DRAFT:
        return redirect("invoice_detail", invoice_id=invoice.id)

    if request.method == "POST":
        existing_lines = {str(line.pk): line for line in invoice.lines.all()}
        existing_line_rows = _build_line_rows_from_post(request, include_line_ids=True)
        new_line_rows = _build_line_rows_from_post(request, field_prefix="new_")
        draft_notes = request.POST.get("notes", "").strip()
        cleaned_existing_rows, existing_errors = _clean_line_rows(
            rows=existing_line_rows,
            active_services_by_id=active_services_by_id,
            business=current_business,
            line_label="Saved line",
            existing_lines_by_id=existing_lines,
        )
        cleaned_new_rows, new_errors = _clean_line_rows(
            rows=new_line_rows,
            active_services_by_id=active_services_by_id,
            business=current_business,
            line_label="New line",
        )

        errors = [*existing_errors, *new_errors]
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            with transaction.atomic():
                invoice.notes = draft_notes
                invoice.save(update_fields=["notes"])

                kept_line_ids: set[int] = set()
                for line_row in cleaned_existing_rows:
                    line = existing_lines.get(str(line_row["line_id"]))
                    if line is None:
                        continue

                    line.service = _service_for_invoice_line(
                        business=current_business,
                        line_row=line_row,
                    )
                    line.description = line_row["description"]
                    line.quantity = line_row["quantity"]
                    line.unit_price = line_row["unit_price"]
                    line.save()
                    kept_line_ids.add(line.pk)

                line_qs = InvoiceLine.objects.filter(invoice=invoice)
                if kept_line_ids:
                    line_qs.exclude(pk__in=kept_line_ids).delete()
                else:
                    line_qs.delete()

                for line_row in cleaned_new_rows:
                    InvoiceLine.objects.create(
                        invoice=invoice,
                        service=_service_for_invoice_line(
                            business=current_business,
                            line_row=line_row,
                        ),
                        description=line_row["description"],
                        quantity=line_row["quantity"],
                        unit_price=line_row["unit_price"],
                    )

                _recalculate_invoice_totals(invoice)

            return redirect("invoice_detail", invoice_id=invoice.id)

    context: dict[str, Any] = {
        "invoice": invoice,
        "available_services": available_services,
        "service_categories": service_categories,
        "existing_line_rows": existing_line_rows,
        "new_line_rows": new_line_rows,
        "blank_line_row": _new_line_rows(default_blank_row=True)[0],
        "draft_notes": draft_notes,
    }
    return render(request, "billings/invoice_edit.html", context)


@business_role_required(
    *OWNER_ADMIN_ROLES,
    redirect_url_name="invoice_list",
    permission_message="You do not have permission to delete invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["POST"])
def invoice_delete(request: HttpRequest, invoice_id: int) -> HttpResponse:
    current_business = request.current_business
    invoice = get_object_or_404(_invoice_queryset_for_business(current_business), pk=invoice_id)
    invoice_number = invoice.invoice_number

    invoice.delete()
    messages.success(request, f"Invoice {invoice_number} was deleted.")
    return redirect("invoice_list")


@business_role_required(
    *BILLING_MANAGE_ROLES,
    redirect_url_name="invoice_list",
    permission_message="You do not have permission to manage invoices.",
    raise_exception=False,
)
@business_module_required("invoicing")
@require_http_methods(["POST"])
def invoice_change_status(request: HttpRequest, invoice_id: int) -> HttpResponse:
    current_business = request.current_business
    invoice = get_object_or_404(_invoice_queryset_for_business(current_business), pk=invoice_id)
    next_status = request.POST.get("status", "")
    allowed_statuses = STATUS_TRANSITIONS.get(invoice.status, set())

    if next_status not in allowed_statuses:
        return redirect("invoice_detail", invoice_id=invoice.id)

    previous_status = invoice.status
    invoice.status = next_status
    invoice.save()

    log_activity(
        actor=request.user,
        action_type=ActivityLog.ActionType.STATUS_CHANGED,
        business=invoice.business,
        client=invoice.client,
        summary=(
            f"Invoice {invoice.invoice_number} status changed from "
            f"{Invoice.Status(previous_status).label} to {Invoice.Status(next_status).label}"
        ),
        payload={
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "from_status": previous_status,
            "to_status": next_status,
        },
    )

    return redirect("invoice_detail", invoice_id=invoice.id)
