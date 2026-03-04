from __future__ import annotations
from typing import Any
from django.contrib.auth.decorators import login_required
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from .forms import PublicLeadForm, PrivateClientForm
from .models import Lead, Client
from .services import send_lead_email
from helpers import upsert_client_from_lead

# Fucntions below relate to public-facing lead capture and agent dashboard
@login_required
@require_http_methods(["GET"])
def agent_dashboard(request: HttpRequest) -> HttpResponse:
    """Render the agent dashboard."""
    context: dict[str, Any] = {}
    return render(request, "crm/agent_dashboard/agent_dashboard.html", context)


@require_http_methods(["GET", "POST"])
def public_request(request: HttpRequest) -> HttpResponse:
    """
    Create a public lead request.

    - Always creates a Lead.
    - If lead_type == REQUEST: auto-create/update Client.
    - If lead_type == INTEREST: keep as Lead only.
    """
    if request.method == "POST":
        form = PublicLeadForm(request.POST)
        if form.is_valid():
            lead: Lead = form.save()  # get the saved lead object

            if lead.lead_type == Lead.LeadType.REQUEST:
                upsert_client_from_lead(lead)

            return redirect("public_thank_you")
    else:
        form = PublicLeadForm()

    return render(request, "crm/forms/public_request.html", {"form": form})


@require_http_methods(["GET"])
def public_thank_you(request: HttpRequest) -> HttpResponse:
    """Render the public request success page."""
    return render(request, "crm/success_fail/success.html")


# Functions below relate to client/leads management for staff users. 

@login_required
@require_http_methods(["GET", "POST"])
def staff_lead_create(request: HttpRequest) -> HttpResponse:
    """
    Create a new lead for staff.
    """
    # if request.method == "POST":
    #     form = PublicLeadForm(request.POST)
    #     if form.is_valid():
    #         form.save()
    #         return redirect("staff_lead_list")
    # else:
    #     form = PublicLeadForm()

    context={}

    return render(request, "crm/forms/lead_create.html", context)    


@login_required
@require_http_methods(["GET"])
def staff_client_create(request: HttpRequest) -> HttpResponse:
    """
    Create a new client for staff.
    """
    # customer_form = CustomerForm(request.POST, prefix="customer") if customer_status == "unregistered_user" else None
    # if request.method == "POST":
    #     form = PublicLeadForm(request.POST)
    #     if form.is_valid():
    #         form.save()
    #         return redirect("staff_client_list")
    # else:
    #     form = PublicLeadForm()

    context={}
    return render(request, "crm/forms/client_create.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def staff_lead_list(request: HttpRequest) -> HttpResponse:
    """
    List leads for staff with optional filtering by status, lead type, and search query.
    """
    qs: QuerySet[Lead] = Lead.objects.select_related("category").all()

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


@login_required
@require_http_methods(["GET"])
def staff_client_list(request: HttpRequest) -> HttpResponse:
    """
    List clients for staff with optional filtering by:
      - is_active (true/false)
      - district
      - search query (first/last/email/phone/company)
    """
    qs: QuerySet[Client] = Client.objects.all()

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


@login_required
@require_http_methods(["GET"])
def staff_lead_detail(request: HttpRequest, lead_id: int) -> HttpResponse:
    """Display staff-facing details for a single lead."""
    lead = get_object_or_404(Lead, pk=lead_id)
    return render(request, "staff/lead_detail.html", {"lead": lead})


@login_required
@require_http_methods(["GET", "POST"])
def staff_lead_email(request: HttpRequest, lead_id: int) -> HttpResponse:
    """
    Compose and send an email to a lead.

    - GET: Show compose form with sensible defaults.
    - POST: Validate and send, then redirect back to lead detail.
    """
    lead = get_object_or_404(Lead, pk=lead_id)

    if request.method == "POST":
        form = StaffEmailForm(request.POST)
        if form.is_valid():
            send_lead_email(
                actor=request.user,
                lead=lead,
                subject=form.cleaned_data["subject"],
                body=form.cleaned_data["body"],
            )
            return redirect("staff_lead_detail", lead_id=lead.id)
    else:
        form = StaffEmailForm(
            initial={
                "subject": f"Re: {lead.category.name}",
                "body": f"Hi {lead.first_name},\n\n",
            }
        )

    context: dict[str, Any] = {"lead": lead, "form": form}
    return render(request, "staff/email_compose.html", context)