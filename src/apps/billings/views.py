from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.businesses.models import Business
from apps.businesses.utils import business_required
from apps.crm.models import ActivityLog, Client
from apps.crm.services import log_activity

from .models import Invoice, InvoiceLine
from .services import create_invoice_for_client


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
    invoice.subtotal = subtotal
    invoice.total = subtotal + (invoice.tax or Decimal("0.00"))
    invoice.save()


def _client_queryset_for_business(business: Business):
    return Client.objects.filter(business=business)


def _invoice_queryset_for_business(business: Business):
    return Invoice.objects.filter(business=business).select_related("client", "business")


@business_required()
@require_http_methods(["GET", "POST"])
def invoice_create_from_client(request: HttpRequest, client_id: int) -> HttpResponse:
    current_business = request.current_business
    client = get_object_or_404(_client_queryset_for_business(current_business), pk=client_id)

    if request.method == "POST":
        invoice = create_invoice_for_client(actor=request.user, client=client)
        return redirect("invoice_detail", invoice_id=invoice.id)

    context: dict[str, Any] = {"client": client, "current_business": current_business}
    return render(request, "billings/invoice_create.html", context)


@business_required()
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


@business_required()
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


@business_required()
@require_http_methods(["GET", "POST"])
def invoice_edit(request: HttpRequest, invoice_id: int) -> HttpResponse:
    current_business = request.current_business
    invoice = get_object_or_404(
        _invoice_queryset_for_business(current_business).prefetch_related("lines"),
        pk=invoice_id,
    )

    if invoice.status != Invoice.Status.DRAFT:
        return redirect("invoice_detail", invoice_id=invoice.id)

    if request.method == "POST":
        existing_lines = {str(line.pk): line for line in invoice.lines.all()}

        with transaction.atomic():
            invoice.notes = request.POST.get("notes", "").strip()

            kept_line_ids: set[int] = set()
            for line_id, description, quantity, unit_price in zip(
                request.POST.getlist("line_id"),
                request.POST.getlist("description"),
                request.POST.getlist("quantity"),
                request.POST.getlist("unit_price"),
            ):
                line = existing_lines.get(line_id)
                if line is None:
                    continue

                line.description = description.strip()
                line.quantity = _parse_decimal(quantity)
                line.unit_price = _parse_decimal(unit_price)
                line.save()
                kept_line_ids.add(line.pk)

            line_qs = InvoiceLine.objects.filter(invoice=invoice)
            if kept_line_ids:
                line_qs.exclude(pk__in=kept_line_ids).delete()
            else:
                line_qs.delete()

            for description, quantity, unit_price in zip(
                request.POST.getlist("new_description"),
                request.POST.getlist("new_quantity"),
                request.POST.getlist("new_unit_price"),
            ):
                description = description.strip()
                if not description and not quantity and not unit_price:
                    continue

                InvoiceLine.objects.create(
                    invoice=invoice,
                    description=description or "Line item",
                    quantity=_parse_decimal(quantity, default=Decimal("1.00")),
                    unit_price=_parse_decimal(unit_price),
                )

            _recalculate_invoice_totals(invoice)

        return redirect("invoice_detail", invoice_id=invoice.id)

    context: dict[str, Any] = {"invoice": invoice}
    return render(request, "billings/invoice_edit.html", context)


@business_required()
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
