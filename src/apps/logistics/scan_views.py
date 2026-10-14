"""Thin HTML adapter for authenticated Logistics scan/act/next-scan operations."""

import uuid

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from apps.businesses.utils import business_module_required, business_role_required

from .location_access import require_record_operation
from .location_operations import validate_transition_location
from .models import ParcelEvent
from .parcel_policy import PARCEL_MANAGE_ROLES, PARCEL_VIEW_ROLES
from .parcel_services import parcels_for_business, record_parcel_event, require_parcel_access
from .scan import ScanActionForm, ScanLookupForm, resolve_scanned_parcel
from .shipment_services import shipments_for_business
from .workflow_summary import _read_snapshot, resolve_parcel_workflow

NOT_FOUND = "Parcel not found in this workspace. Check the tracking code and try again."


def _context(request, *, lookup_form=None, parcel=None, error="", confirmation=""):
    if parcel is not None:
        parcel = get_object_or_404(
            parcels_for_business(
                business=request.current_business, actor=request.user
            ).select_related("client"),
            pk=parcel.pk,
        )
    context = {
        "lookup_form": lookup_form if lookup_form is not None else ScanLookupForm(),
        "parcel": parcel,
        "scan_error": error,
        "scan_confirmation": confirmation,
    }
    if parcel is not None:
        workflow = resolve_parcel_workflow(
            business=request.current_business,
            actor=request.user,
            parcel=parcel,
        )
        context["workflow_summary"] = workflow
        context["recent_event"] = (
            ParcelEvent.objects.filter(business=request.current_business, parcel=parcel)
            .select_related("actor", "operational_location")
            .order_by("-timestamp", "-pk")
            .first()
        )
        context["shipment"] = None
        if parcel.shipment_id:
            try:
                context["shipment"] = (
                    shipments_for_business(business=request.current_business, actor=request.user)
                    .filter(pk=parcel.shipment_id)
                    .first()
                )
            except PermissionDenied:
                pass
        try:
            require_parcel_access(business=request.current_business, actor=request.user, write=True)
            require_record_operation(parcel, business=request.current_business, actor=request.user)
        except PermissionDenied:
            context["scan_actions"] = []
        else:
            action_form = ScanActionForm(
                parcel=parcel,
                initial={"idempotency_key": uuid.uuid4(), "expected_status": parcel.current_status},
            )
            context["action_form"] = action_form
            context["scan_actions"] = [
                (value, label)
                for value, label in action_form.fields["status"].widget.choices
                if value
            ]
            available = []
            for value, label in context["scan_actions"]:
                try:
                    validate_transition_location(
                        parcel, business=request.current_business, actor=request.user, status=value
                    )
                except (PermissionDenied, ValidationError):
                    continue
                available.append((value, label))
            context["scan_actions"] = available
            executable = {
                action["status"]
                for action in workflow.executable_actions
                if action["kind"] == "OPERATIONAL"
            }
            context["scan_actions"] = [
                (value, label) for value, label in context["scan_actions"] if value in executable
            ]
    return context


def _render(request, *, status=200, **kwargs):
    with _read_snapshot():
        context = _context(request, **kwargs)
    template = (
        "logistics/includes/scan_panel.html"
        if request.headers.get("X-Requested-With") == "XMLHttpRequest"
        else "logistics/scan.html"
    )
    return render(request, template, context, status=status)


@never_cache
@business_module_required("parcels", access="read")
@business_module_required("tracking", access="read")
@business_role_required(*PARCEL_VIEW_ROLES)
@sensitive_post_parameters("tracking_code")
@require_http_methods(["GET", "POST"])
def scan_parcel(request):
    if request.method == "GET":
        return _render(request)
    form = ScanLookupForm(request.POST)
    if not form.is_valid():
        return _render(
            request, lookup_form=form, error=" ".join(form.errors["tracking_code"]), status=400
        )
    parcel = resolve_scanned_parcel(
        business=request.current_business,
        actor=request.user,
        code=form.cleaned_data["tracking_code"],
    )
    if parcel is None:
        return _render(request, lookup_form=form, error=NOT_FOUND, status=404)
    return _render(request, lookup_form=form, parcel=parcel)


@never_cache
@business_module_required("parcels")
@business_module_required("tracking")
@business_role_required(*PARCEL_MANAGE_ROLES)
@require_POST
def scan_action(request, parcel_id):
    parcel = get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user), pk=parcel_id
    )
    form = ScanActionForm(request.POST, parcel=parcel)
    if form.is_valid():
        try:
            with transaction.atomic():
                from apps.businesses.models import Business

                from .location_access import lock_actor_membership

                current = Business.objects.select_for_update().get(pk=request.current_business.pk)
                lock_actor_membership(current, request.user)
                workflow = resolve_parcel_workflow(
                    business=current, actor=request.user, parcel=parcel
                )
                executable = {
                    action["status"]
                    for action in workflow.executable_actions
                    if action["kind"] == "OPERATIONAL"
                }
                replay = ParcelEvent.objects.filter(
                    business=current, idempotency_key=form.cleaned_data["idempotency_key"]
                ).exists()
                if not replay:
                    parcel.refresh_from_db()
                    require_record_operation(parcel, business=current, actor=request.user)
                    validate_transition_location(
                        parcel,
                        business=current,
                        actor=request.user,
                        status=form.cleaned_data["status"],
                    )
                if not replay and form.cleaned_data["status"] not in executable:
                    raise ValidationError(
                        "Current workflow evidence, financial clearance or site access does not permit this action."
                    )
                event = record_parcel_event(
                    business=current, parcel=parcel, actor=request.user, **form.cleaned_data
                )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            confirmation = f"{event.get_status_display()} recorded for {parcel.tracking_code}. Ready for the next scan."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return _render(request, confirmation=confirmation)
            messages.success(request, confirmation)
            return redirect("logistics_parcel_scan")
    parcel.refresh_from_db()
    error = " ".join(message for errors in form.errors.values() for message in errors)
    return _render(
        request,
        lookup_form=ScanLookupForm(initial={"tracking_code": parcel.tracking_code}),
        parcel=parcel,
        error=error,
        status=400,
    )
