from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.businesses.utils import (
    APPOINTMENT_MANAGE_ROLES,
    APPOINTMENT_VIEW_ROLES,
    business_module_required,
    business_role_required,
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
        "staff_member",
    )


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
    context: dict[str, Any] = {
        "appointment": appointment,
        "available_statuses": STATUS_TRANSITIONS.get(appointment.status, set()),
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

    if request.method == "POST":
        form = AppointmentForm(request.POST, current_business=current_business)
        if form.is_valid():
            appointment = form.save()
            messages.success(request, "Appointment created successfully.")
            return redirect("appointment_detail", appointment_id=appointment.id)
        messages.error(request, "Please correct the errors below.")
    else:
        form = AppointmentForm(current_business=current_business)

    context: dict[str, Any] = {
        "form": form,
        "appointment": None,
        "page_title": "Create appointment",
        "submit_label": "Create appointment",
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
