from __future__ import annotations

import csv
import io
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods
from loguru import logger

from apps.businesses.models import Business, BusinessUser
from apps.businesses.utils import (
    business_required,
    business_role_required,
    get_current_business,
)
from apps.billings.models import Invoice
from .forms import (
    BusinessServiceCSVImportForm,
    BusinessServiceForm,
    PrivateClientForm,
    PrivateLeadForm,
    PublicLeadForm,
    ServiceCategoryForm,
)
from .models import BusinessService, Client, Lead, ServiceCategory
from .services import send_lead_email
from helpers import upsert_client_from_lead


def _client_queryset_for_business(business: Business) -> QuerySet[Client]:
    return Client.objects.filter(business=business).select_related("assigned_to")


def _lead_queryset_for_business(business: Business) -> QuerySet[Lead]:
    return Lead.objects.filter(business=business).select_related("category")


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


def _normalize_csv_fieldname(value: str | None) -> str:
    return (value or "").strip().lower()


def _parse_csv_decimal(value: str, *, row_number: int, field_name: str) -> Decimal:
    normalized_value = value.strip().replace(",", "")
    if not normalized_value:
        raise ValidationError(f"Row {row_number}: {field_name} is required.")

    try:
        return Decimal(normalized_value)
    except InvalidOperation as exc:
        raise ValidationError(
            f"Row {row_number}: {field_name} must be a valid decimal number."
        ) from exc


def _parse_csv_boolean(
    value: str,
    *,
    default: bool,
    row_number: int,
) -> bool:
    normalized_value = value.strip().lower()
    if not normalized_value:
        return default

    if normalized_value in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "n", "off"}:
        return False

    raise ValidationError(
        f"Row {row_number}: is_active must be one of true/false, yes/no, or 1/0."
    )


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
            )
            tax_rate_value = row.get("tax_rate", "")
            tax_rate = (
                _parse_csv_decimal(
                    tax_rate_value,
                    row_number=row_number,
                    field_name="tax_rate",
                )
                if tax_rate_value
                else business.tax_rate
            )
            is_active = _parse_csv_boolean(
                row.get("is_active", ""),
                default=True,
                row_number=row_number,
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
        form = PublicLeadForm(request.POST, business=business)
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
        form = PublicLeadForm(business=business)

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
        form = PrivateLeadForm(request.POST, business=current_business)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.business = current_business
            lead.save()
            messages.success(request, "Lead created successfully.")
            return redirect("staff_lead_list")
    else:
        form = PrivateLeadForm(business=current_business)

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
        form = PrivateLeadForm(request.POST, instance=lead, business=current_business)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.business = current_business
            lead.save()
            messages.success(request, "Lead updated successfully.")
            return redirect("staff_lead_detail", lead_id=lead.id)
        messages.error(request, "Please correct the errors below.")
    else:
        form = PrivateLeadForm(instance=lead, business=current_business)

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


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
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


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
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


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
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


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
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


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
@require_http_methods(["GET"])
def business_service_list(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business
    services = _business_service_queryset_for_business(current_business)

    context: dict[str, Any] = {
        "business": current_business,
        "services": services,
        "active_service_count": services.filter(is_active=True).count(),
        "archived_service_count": services.filter(is_active=False).count(),
    }
    return render(request, "crm/settings/business_service_list.html", context)


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
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
    }
    return render(request, "crm/settings/business_service_form.html", context)


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
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
    }
    return render(request, "crm/settings/business_service_form.html", context)


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
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


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
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
    }
    return render(request, "crm/settings/business_service_import.html", context)


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
@require_http_methods(["GET"])
def business_service_sample_csv(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "name",
            "unit_price",
            "description",
            "tax_rate",
            "category",
            "is_active",
            "external_code",
        ]
    )
    writer.writerow(
        [
            "Emergency Callout",
            "125.00",
            "After-hours emergency service call",
            f"{current_business.tax_rate:.2f}",
            "Urgent Response",
            "true",
            "EMERGENCY-001",
        ]
    )
    writer.writerow(
        [
            "Standard Consultation",
            "75.00",
            "Initial consultation visit",
            "",
            "",
            "true",
            "",
        ]
    )

    response = HttpResponse(output.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="clarivo_services_sample.csv"'
    return response
