from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.billings.models import Invoice
from apps.businesses.utils import (
    APPOINTMENT_MANAGE_ROLES,
    APPOINTMENT_VIEW_ROLES,
    business_module_required,
    business_role_required,
    can_use_module,
)
from apps.crm.models import BusinessService, Client, Lead
from apps.crm.services import (
    find_matching_client_for_lead,
    get_missing_client_required_field_labels_for_lead,
    sync_client_from_lead,
)

from .forms import AppointmentForm
from .models import Appointment

STATUS_TRANSITIONS: dict[str, set[str]] = {
    Appointment.Status.SCHEDULED: {
        Appointment.Status.COMPLETED,
        Appointment.Status.CANCELLED,
        Appointment.Status.NO_SHOW,
    },
    Appointment.Status.COMPLETED: set(),
    Appointment.Status.CANCELLED: set(),
    Appointment.Status.NO_SHOW: set(),
}


def _appointment_queryset_for_business(current_business):
    return Appointment.objects.filter(business=current_business).select_related(
        "business",
        "client",
        "service",
        "source_lead",
        "source_lead__category",
        "staff_member",
    )


def _request_lead_queryset_for_business(current_business):
    return Lead.objects.filter(
        business=current_business,
        lead_type=Lead.LeadType.REQUEST,
    ).select_related("business", "category", "requested_service")


def _invoice_queryset_for_business(current_business):
    return Invoice.objects.filter(business=current_business).select_related(
        "appointment",
        "business",
        "client",
    )


def _client_queryset_for_business(current_business):
    return Client.objects.filter(
        business=current_business,
        is_active=True,
    ).order_by("first_name", "last_name", "pk")


def _infer_service_from_request(current_business, lead: Lead) -> BusinessService | None:
    if (
        lead.requested_service_id is not None
        and lead.requested_service is not None
        and lead.requested_service.business_id == current_business.id
        and lead.requested_service.is_active
    ):
        return lead.requested_service

    if lead.category_id is None:
        return None

    matching_services = list(
        BusinessService.objects.filter(
            business=current_business,
            is_active=True,
            category=lead.category,
        )
        .select_related("category", "business")
        .order_by("name", "pk")[:2]
    )
    if len(matching_services) == 1:
        return matching_services[0]
    return None


def _display_name_for_request_client(lead: Lead, client) -> str:
    if client.company_name:
        return client.company_name

    full_name = " ".join(
        part for part in [client.first_name, client.last_name] if part
    ).strip()
    if full_name:
        return full_name

    if lead.company_name:
        return lead.company_name

    return str(lead)


def _build_appointment_title_from_request(lead: Lead, client) -> str:
    if lead.requested_service_id and lead.requested_service is not None:
        service_label = lead.requested_service.name
    elif lead.category_id and lead.category:
        service_label = lead.category.name
    else:
        service_label = "Service request"
    client_label = _display_name_for_request_client(lead, client)
    return f"{service_label} - {client_label}"[:160]


def _build_location_from_request(lead: Lead, client) -> str:
    request_location_parts = [
        part
        for part in [
            (lead.street_address or "").strip(),
            lead.get_district_display() if lead.district else "",
            (lead.country or "").strip(),
            (lead.postal_code or "").strip(),
        ]
        if part
    ]
    if request_location_parts:
        return ", ".join(request_location_parts)[:255]

    client_location_parts = [
        part
        for part in [
            (client.street_address or "").strip(),
            client.get_district_display() if client.district else "",
            (client.country or "").strip(),
            (client.postal_code or "").strip(),
        ]
        if part
    ]
    return ", ".join(client_location_parts)[:255]


def _build_notes_from_request(lead: Lead) -> str:
    notes: list[str] = [f"Scheduled from service request #{lead.pk}."]

    if lead.requested_service_id and lead.requested_service is not None:
        notes.append(f"Requested service: {lead.requested_service.name}")
    elif lead.category_id and lead.category is not None:
        notes.append(f"Requested service: {lead.category.name}")
    if lead.preferred_start_time:
        notes.append(f"Preferred start: {lead.preferred_start_time:%Y-%m-%d %H:%M}")
    if lead.message.strip():
        notes.append(f"Request details: {lead.message.strip()}")
    if lead.notes.strip():
        notes.append(f"Internal lead notes: {lead.notes.strip()}")

    return "\n\n".join(notes)


def _display_name_for_client(client: Client) -> str:
    if client.company_name:
        return client.company_name

    return " ".join(
        part for part in [client.first_name, client.last_name] if part
    ).strip() or client.email


def _build_location_from_client(client: Client) -> str:
    client_location_parts = [
        part
        for part in [
            (client.street_address or "").strip(),
            client.get_district_display() if client.district else "",
            (client.country or "").strip(),
            (client.postal_code or "").strip(),
        ]
        if part
    ]
    return ", ".join(client_location_parts)[:255]


def _build_initial_appointment_data_from_client(client: Client) -> dict[str, str | int]:
    return {
        "client": client.pk,
        "title": f"Visit - {_display_name_for_client(client)}"[:160],
        "location": _build_location_from_client(client),
    }


def _get_source_client_for_create(request: HttpRequest, current_business) -> Client | None:
    client_id = (request.GET.get("client_id") or "").strip()
    if not client_id:
        return None

    try:
        client_pk = int(client_id)
    except ValueError:
        return None

    return _client_queryset_for_business(current_business).filter(pk=client_pk).first()


def _build_initial_appointment_data_from_request(lead: Lead, client) -> dict[str, str | int]:
    inferred_service = _infer_service_from_request(lead.business, lead)
    return {
        "client": client.pk,
        "service": inferred_service.pk if inferred_service is not None else "",
        "title": _build_appointment_title_from_request(lead, client),
        "location": _build_location_from_request(lead, client),
        "notes": _build_notes_from_request(lead),
    }


def _prepare_client_for_request_scheduling(lead: Lead):
    matched_client = find_matching_client_for_lead(lead)
    if matched_client is not None:
        return matched_client, []

    missing_client_fields = get_missing_client_required_field_labels_for_lead(lead)
    if missing_client_fields:
        return None, missing_client_fields

    client, _created = sync_client_from_lead(lead)
    return client, []


@business_role_required(
    *APPOINTMENT_VIEW_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to view appointments.",
    raise_exception=False,
)
@business_module_required("appointments")
@require_http_methods(["GET"])
def appointment_list(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business
    appointments = _appointment_queryset_for_business(current_business)

    status_filter = (request.GET.get("status") or "").strip()
    query = (request.GET.get("q") or "").strip()

    if status_filter:
        appointments = appointments.filter(status=status_filter)

    if query:
        appointments = appointments.filter(
            models.Q(title__icontains=query)
            | models.Q(service_name__icontains=query)
            | models.Q(client__first_name__icontains=query)
            | models.Q(client__last_name__icontains=query)
            | models.Q(client__company_name__icontains=query)
        )

    context: dict[str, Any] = {
        "appointments": appointments,
        "status_choices": Appointment.Status.choices,
        "current_status": status_filter,
        "query": query,
    }
    return render(request, "appointments/list.html", context)


@business_role_required(
    *APPOINTMENT_VIEW_ROLES,
    redirect_url_name="agent_dashboard",
    permission_message="You do not have permission to view appointments.",
    raise_exception=False,
)
@business_module_required("appointments")
@require_http_methods(["GET"])
def appointment_detail(request: HttpRequest, appointment_id: int) -> HttpResponse:
    appointment = get_object_or_404(
        _appointment_queryset_for_business(request.current_business),
        pk=appointment_id,
    )
    linked_invoice = None
    if can_use_module(request.current_business, "invoicing"):
        linked_invoice = (
            _invoice_queryset_for_business(request.current_business)
            .filter(appointment=appointment)
            .order_by("-created_at", "-pk")
            .first()
        )
    context: dict[str, Any] = {
        "appointment": appointment,
        "available_statuses": STATUS_TRANSITIONS.get(appointment.status, set()),
        "linked_invoice": linked_invoice,
    }
    return render(request, "appointments/detail.html", context)


@business_role_required(
    *APPOINTMENT_MANAGE_ROLES,
    redirect_url_name="appointment_list",
    permission_message="You do not have permission to manage appointments.",
    raise_exception=False,
)
@business_module_required("appointments")
@require_http_methods(["GET", "POST"])
def appointment_create(request: HttpRequest) -> HttpResponse:
    current_business = request.current_business
    source_client = _get_source_client_for_create(request, current_business)

    if request.method == "POST":
        form = AppointmentForm(request.POST, current_business=current_business)
        if form.is_valid():
            appointment = form.save()
            messages.success(request, "Appointment created successfully.")
            return redirect("appointment_detail", appointment_id=appointment.id)
        messages.error(request, "Please correct the errors below.")
    else:
        initial: dict[str, str | int] = {}
        if source_client is not None:
            initial.update(_build_initial_appointment_data_from_client(source_client))
        form = AppointmentForm(initial=initial, current_business=current_business)

    context: dict[str, Any] = {
        "form": form,
        "appointment": None,
        "page_title": "Create appointment",
        "submit_label": "Create appointment",
        "source_client": source_client,
    }
    return render(request, "appointments/form.html", context)


@business_role_required(
    *APPOINTMENT_MANAGE_ROLES,
    redirect_url_name="appointment_list",
    permission_message="You do not have permission to manage appointments.",
    raise_exception=False,
)
@business_module_required("appointments")
@require_http_methods(["GET", "POST"])
def appointment_create_from_request(request: HttpRequest, lead_id: int) -> HttpResponse:
    current_business = request.current_business
    lead = get_object_or_404(
        _request_lead_queryset_for_business(current_business),
        pk=lead_id,
    )
    client, missing_client_fields = _prepare_client_for_request_scheduling(lead)

    if client is None:
        messages.info(
            request,
            "Complete the client details before scheduling an appointment.",
        )
        return redirect("staff_lead_convert_to_client", lead_id=lead.id)

    if request.method == "POST":
        form = AppointmentForm(request.POST, current_business=current_business)
        if form.is_valid():
            appointment = form.save(commit=False)
            appointment.source_lead = lead
            appointment.save()
            messages.success(request, "Appointment created successfully from service request.")
            return redirect("appointment_detail", appointment_id=appointment.id)
        messages.error(request, "Please correct the errors below.")
    else:
        form = AppointmentForm(
            initial=_build_initial_appointment_data_from_request(lead, client),
            current_business=current_business,
        )

    context: dict[str, Any] = {
        "form": form,
        "appointment": None,
        "page_title": "Schedule appointment from request",
        "submit_label": "Create appointment",
        "source_lead": lead,
        "request_client": client,
        "missing_client_fields": missing_client_fields,
    }
    return render(request, "appointments/form.html", context)


@business_role_required(
    *APPOINTMENT_MANAGE_ROLES,
    redirect_url_name="appointment_list",
    permission_message="You do not have permission to manage appointments.",
    raise_exception=False,
)
@business_module_required("appointments")
@require_http_methods(["GET", "POST"])
def appointment_update(request: HttpRequest, appointment_id: int) -> HttpResponse:
    current_business = request.current_business
    appointment = get_object_or_404(
        _appointment_queryset_for_business(current_business),
        pk=appointment_id,
    )

    if request.method == "POST":
        form = AppointmentForm(
            request.POST,
            instance=appointment,
            current_business=current_business,
        )
        if form.is_valid():
            appointment = form.save()
            messages.success(request, "Appointment updated successfully.")
            return redirect("appointment_detail", appointment_id=appointment.id)
        messages.error(request, "Please correct the errors below.")
    else:
        form = AppointmentForm(instance=appointment, current_business=current_business)

    context: dict[str, Any] = {
        "form": form,
        "appointment": appointment,
        "page_title": f"Edit appointment: {appointment.title}",
        "submit_label": "Save changes",
    }
    return render(request, "appointments/form.html", context)


@business_role_required(
    *APPOINTMENT_MANAGE_ROLES,
    redirect_url_name="appointment_list",
    permission_message="You do not have permission to manage appointments.",
    raise_exception=False,
)
@business_module_required("appointments")
@require_http_methods(["POST"])
def appointment_change_status(request: HttpRequest, appointment_id: int) -> HttpResponse:
    appointment = get_object_or_404(
        _appointment_queryset_for_business(request.current_business),
        pk=appointment_id,
    )
    next_status = request.POST.get("status", "").strip()
    allowed_statuses = STATUS_TRANSITIONS.get(appointment.status, set())

    if next_status not in allowed_statuses:
        messages.info(request, "That appointment status change is not available.")
        return redirect("appointment_detail", appointment_id=appointment.id)

    appointment.status = next_status
    appointment.save(update_fields=["status", "updated_at"])
    messages.success(
        request,
        f"Appointment marked as {Appointment.Status(next_status).label.lower()}.",
    )
    return redirect("appointment_detail", appointment_id=appointment.id)
