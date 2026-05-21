from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.businesses.models import Business
from apps.businesses.utils import (
    BILLING_MANAGE_ROLES,
    BILLING_VIEW_ROLES,
    business_module_required,
    business_role_required,
)
from apps.crm.models import ActivityLog, BusinessService, Client
from apps.crm.services import log_activity

from .models import Invoice, InvoiceLine
from .services import calculate_tax_amount, create_invoice_for_client, generate_invoice_number


STATUS_TRANSITIONS: dict[str, set[str]] = {
    Invoice.Status.DRAFT: {Invoice.Status.SENT, Invoice.Status.CANCELLED},
    Invoice.Status.SENT: {Invoice.Status.PAID, Invoice.Status.CANCELLED},
    Invoice.Status.PAID: set(),
    Invoice.Status.CANCELLED: set(),
}


def _parse_decimal(value: str | None, *, default: Decimal = Decimal("0.00")) -> Decimal:
    try:
        return Decimal(value or str(default))
    except (InvalidOperation, TypeError):
        return default


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


def _invoice_queryset_for_business(business: Business):
    return Invoice.objects.filter(business=business).select_related("client", "business")


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

    row_count = max(
        len(line_ids),
        len(service_ids),
        len(descriptions),
        len(quantities),
        len(unit_prices),
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
        }
    ]


def _service_snapshot_description(service: BusinessService) -> str:
    return (service.description or "").strip() or service.name


def _clean_line_rows(
    *,
    rows: list[dict[str, Any]],
    active_services_by_id: dict[str, BusinessService],
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

        if not service_id and not description and not quantity and not unit_price:
            continue

        service = None
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
                description_value = existing_line.description
                unit_price_value = existing_line.unit_price
            else:
                description_value = _service_snapshot_description(service)
                unit_price_value = service.unit_price
        else:
            description_value = description or "Line item"
            unit_price_value = _parse_decimal(unit_price)

        cleaned_row = {
            "service": service,
            "description": description_value,
            "quantity": _parse_decimal(quantity, default=Decimal("1.00")),
            "unit_price": unit_price_value,
        }
        if "line_id" in row:
            cleaned_row["line_id"] = str(row["line_id"])
        cleaned_rows.append(cleaned_row)

    return cleaned_rows, errors


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
    available_services = list(_service_queryset_for_business(current_business))
    active_services_by_id = {str(service.pk): service for service in available_services}
    line_rows = _new_line_rows(default_blank_row=True)

    if request.method == "POST":
        line_rows = _build_line_rows_from_post(request, default_blank_row=True)
        cleaned_line_rows, errors = _clean_line_rows(
            rows=line_rows,
            active_services_by_id=active_services_by_id,
            line_label="Line item",
        )

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            with transaction.atomic():
                invoice = create_invoice_for_client(actor=request.user, client=client)

                for line_row in cleaned_line_rows:
                    InvoiceLine.objects.create(
                        invoice=invoice,
                        service=line_row["service"],
                        description=line_row["description"],
                        quantity=line_row["quantity"],
                        unit_price=line_row["unit_price"],
                    )

                if cleaned_line_rows:
                    _recalculate_invoice_totals(invoice)

            return redirect("invoice_detail", invoice_id=invoice.id)

    context: dict[str, Any] = {
        "client": client,
        "current_business": current_business,
        "invoice_number_preview": generate_invoice_number(business=current_business),
        "available_services": available_services,
        "line_rows": line_rows,
    }
    return render(request, "billings/invoice_create.html", context)


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

    context: dict[str, Any] = {"invoice": invoice}
    return render(request, "billings/invoice_detail.html", context)


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
            line_label="Saved line",
            existing_lines_by_id=existing_lines,
        )
        cleaned_new_rows, new_errors = _clean_line_rows(
            rows=new_line_rows,
            active_services_by_id=active_services_by_id,
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

                    line.service = line_row["service"]
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
                        service=line_row["service"],
                        description=line_row["description"],
                        quantity=line_row["quantity"],
                        unit_price=line_row["unit_price"],
                    )

                _recalculate_invoice_totals(invoice)

            return redirect("invoice_detail", invoice_id=invoice.id)

    context: dict[str, Any] = {
        "invoice": invoice,
        "available_services": available_services,
        "existing_line_rows": existing_line_rows,
        "new_line_rows": new_line_rows,
        "draft_notes": draft_notes,
    }
    return render(request, "billings/invoice_edit.html", context)


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
