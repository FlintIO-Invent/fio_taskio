from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.db.models import Q, QuerySet, Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from loguru import logger

from apps.businesses.models import Business
from apps.businesses.utils import business_required, get_current_business
from apps.billings.models import Invoice
from .forms import PrivateClientForm, PrivateLeadForm, PublicLeadForm
from .models import Lead, Client
from .services import send_lead_email
from helpers import upsert_client_from_lead


def _client_queryset_for_business(business: Business) -> QuerySet[Client]:
    return Client.objects.filter(business=business).select_related("assigned_to")


def _lead_queryset_for_business(business: Business) -> QuerySet[Lead]:
    return Lead.objects.filter(business=business).select_related("category")


# Fucntions below relate to public-facing lead capture and agent dashboard
@business_required()
@require_http_methods(["GET"])
def agent_dashboard(request: HttpRequest) -> HttpResponse:
    """Render the agent dashboard."""
    current_business = request.current_business
    clients = _client_queryset_for_business(current_business)
    service_requests = _lead_queryset_for_business(current_business).filter(
        lead_type=Lead.LeadType.REQUEST
    )
    invoices = Invoice.objects.filter(business=current_business).select_related("client", "business")
    unpaid_statuses = [Invoice.Status.DRAFT, Invoice.Status.SENT]
    paid_invoices = invoices.filter(status=Invoice.Status.PAID)
    paid_invoice_total = paid_invoices.aggregate(total=Sum("total"))["total"] or Decimal("0.00")
    recent_service_requests = service_requests.select_related("category")[:5]
    recent_invoices = invoices.order_by("-created_at")[:5]

    context: dict[str, Any] = {
        "current_business": current_business,
        "client_count": clients.count(),
        "service_request_count": service_requests.count(),
        "open_service_request_count": service_requests.exclude(status=Lead.Status.CLOSED).count(),
        "new_service_request_count": service_requests.filter(status=Lead.Status.NEW).count(),
        "recent_service_requests": recent_service_requests,
        "invoice_count": invoices.count(),
        "unpaid_invoice_count": invoices.filter(status__in=unpaid_statuses).count(),
        "paid_invoice_count": paid_invoices.count(),
        "paid_invoice_total": paid_invoice_total,
        "recent_invoices": recent_invoices,
    }
    return render(request, "crm/agent_dashboard/agent_dashboard.html", context)


@require_http_methods(["GET"])
def public_request_entry(request: HttpRequest) -> HttpResponse:
    current_business = get_current_business(request)
    if current_business is None:
        raise Http404("A business-specific request link is required.")
    return redirect("public_request", business_slug=current_business.slug)


@require_http_methods(["GET", "POST"])
def public_request(request: HttpRequest, business_slug: str) -> HttpResponse:
    """
    Create a public lead request.

    - Always creates a Lead.
    - If lead_type == REQUEST: auto-create/update Client.
    - If lead_type == INTEREST: keep as Lead only.
    """
    business = get_object_or_404(Business, slug=business_slug, is_active=True)

    if request.method == "POST":
        form = PublicLeadForm(request.POST)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.business = business
            lead.save()

            if lead.lead_type == Lead.LeadType.REQUEST:
                logger.info("Lead is of type REQUEST; creating/updating client")
                upsert_client_from_lead(lead)
            elif lead.lead_type == Lead.LeadType.INTEREST:
                logger.debug("Lead is of type INTEREST; creating lead without client")
            return redirect("public_thank_you")
    else:
        form = PublicLeadForm()

    return render(
        request,
        "crm/forms/public_request.html",
        {"form": form, "public_business": business},
    )


@require_http_methods(["GET"])
def public_thank_you(request: HttpRequest) -> HttpResponse:
    """Render the public request success page."""
    return render(request, "crm/success_fail/success.html")


# Functions below relate to client/leads management for staff users. 
@business_required()
@require_http_methods(["GET", "POST"])
def staff_lead_create(request: HttpRequest) -> HttpResponse:
    """
    Create a new lead for staff.
    """
    current_business = request.current_business

    if request.method == "POST":
        form = PrivateLeadForm(request.POST)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.business = current_business
            lead.save()
            messages.success(request, "Lead created successfully.")
            return redirect("staff_lead_list")
    else:
        form = PrivateLeadForm()

    context = {
        "form": form,
        "page_title": "Create a new lead",
        "submit_label": "Create lead",
    }

    return render(request, "crm/forms/lead_create.html", context)


@business_required()
@require_http_methods(["GET", "POST"])
def staff_lead_list(request: HttpRequest) -> HttpResponse:
    """
    List leads for staff with optional filtering by status, lead type, and search query.
    """
    current_business = request.current_business
    qs: QuerySet[Lead] = _lead_queryset_for_business(current_business)


    status: str = (request.GET.get("status") or "").strip()
    lead_type: str = (request.GET.get("lead_type") or "").strip()
    query: str = (request.GET.get("q") or "").strip()

    if status:
        qs = qs.filter(status=status)
    if lead_type:
        qs = qs.filter(lead_type=lead_type)
    if query:
        qs = qs.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(phone__icontains=query)
        )

    context: dict[str, Any] = {
        "leads": qs,
        "filters": {"status": status, "lead_type": lead_type, "q": query},
    }
    return render(request, "crm/main/lead_list.html", context)


@business_required()
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

    context={"form": form}
    return render(request, "crm/forms/client_create.html", context)


@business_required()
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

    context: dict[str, Any] = {
        "clients": qs,
        "filters": {
            "is_active": is_active_param,
            "district": district,
            "q": query,
        },
        # handy for your template dropdown
        "district_choices": Client.DistrictChoices.choices,
    }
    return render(request, "crm/main/client_list.html", context)


@business_required()
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


@business_required()
@require_http_methods(["GET"])
def staff_client_detail(request: HttpRequest, client_id: int) -> HttpResponse:
    """Display staff-facing details for a single client."""
    current_business = request.current_business
    client = get_object_or_404(_client_queryset_for_business(current_business), pk=client_id)
    context: dict[str, Any] = {
        "clients": [client],
        "total_clients": 1,
        "single_client": client,
    }
    return render(request, "crm/main/client_detail.html", context)


@business_required()
@require_http_methods(["GET"])
def staff_lead_detail(request: HttpRequest, lead_id: int) -> HttpResponse:
    """Display staff-facing details for a single lead."""
    current_business = request.current_business
    lead = get_object_or_404(_lead_queryset_for_business(current_business), pk=lead_id)
    context: dict[str, Any] = {
        "lead": lead,
    }
    return render(request, "crm/main/lead_detail.html", context)


@business_required()
@require_http_methods(["GET", "POST"])
def staff_lead_update(request: HttpRequest, lead_id: int) -> HttpResponse:
    current_business = request.current_business
    lead = get_object_or_404(_lead_queryset_for_business(current_business), pk=lead_id)

    if request.method == "POST":
        form = PrivateLeadForm(request.POST, instance=lead)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.business = current_business
            lead.save()
            messages.success(request, "Lead updated successfully.")
            return redirect("staff_lead_detail", lead_id=lead.id)
        messages.error(request, "Please correct the errors below.")
    else:
        form = PrivateLeadForm(instance=lead)

    context: dict[str, Any] = {
        "form": form,
        "lead": lead,
        "page_title": f"Edit lead: {lead.first_name} {lead.last_name}",
        "submit_label": "Save changes",
    }
    return render(request, "crm/forms/lead_create.html", context)


@business_required()
@require_http_methods(["GET"])
def client_detail_view(request: HttpRequest) -> HttpResponse:
    """
    Display a detailed view of active clients for the current business only.
    """
    current_business = request.current_business
    clients = _client_queryset_for_business(current_business).filter(is_active=True).order_by("-created_at")

    context: dict[str, Any] = {
        "clients": clients,
        "total_clients": clients.count(),
    }

    return render(request, "crm/main/client_detail.html", context)
