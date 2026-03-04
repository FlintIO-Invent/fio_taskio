from apps.crm.models import Lead
from .services import create_invoice_from_lead
from typing import Any
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from .services import create_invoice_from_lead


@login_required
@require_http_methods(["GET", "POST"])
def invoice_create_from_lead(request: HttpRequest, lead_id: int) -> HttpResponse:
    """
    Create an invoice from a lead.

    - GET: Render a confirmation page.
    - POST: Create the invoice and redirect to the invoice detail page.

    Args:
        request: Incoming HTTP request.
        lead_id: Primary key of the Lead to invoice.

    Returns:
        Rendered confirmation page or a redirect to the created invoice.
    """
    lead = get_object_or_404(Lead, pk=lead_id)

    if request.method == "POST":
        invoice = create_invoice_from_lead(actor=request.user, lead=lead)
        return redirect("invoice_detail", invoice_id=invoice.id)

    context: dict[str, Any] = {"lead": lead}
    return render(request, "staff/invoice_create.html", context)


@login_required
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
    invoice = get_object_or_404(
        Invoice.objects.select_related("client", "lead"),
        pk=invoice_id,
    )

    context: dict[str, Any] = {"invoice": invoice}
    return render(request, "staff/invoice_detail.html", context)