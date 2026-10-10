from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.businesses.models import BusinessUser
from apps.businesses.utils import business_module_required, business_role_required

from .location_access import WIDE_ROLES
from .location_access_forms import HandlingSiteForm, LocationAssignmentForm
from .location_access_services import (
    review_location_access,
    select_work_location,
    set_handling_site,
    set_location_assignment,
)
from .models import LogisticsHandlingSite, LogisticsLocationAssignment, LogisticsProfile
from .parcel_policy import PARCEL_VIEW_ROLES


@never_cache
@business_role_required(*WIDE_ROLES)
@business_module_required("parcels")
@business_module_required("tracking")
@require_http_methods(["GET", "POST"])
def location_access_settings(request):
    business = request.current_business
    action = request.POST.get("action") if request.method == "POST" else None
    assignment_form = LocationAssignmentForm(
        request.POST if action == "assignment" else None, business=business, prefix="assignment"
    )
    handling_form = HandlingSiteForm(
        request.POST if action == "handling" else None, business=business, prefix="handling"
    )
    if action in ("assignment", "handling"):
        form, service = (
            (assignment_form, set_location_assignment)
            if action == "assignment"
            else (handling_form, set_handling_site)
        )
        if form.is_valid():
            try:
                service(business=business, actor=request.user, **form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Logistics location access saved.")
                return redirect("logistics_location_access")
    elif action == "review":
        if request.POST.get("confirm_review") != "yes":
            messages.error(
                request,
                "Confirm that existing worker assignments and operating-site associations have been reviewed.",
            )
        else:
            review_location_access(business=business, actor=request.user)
            messages.success(
                request, "Location access reviewed. Unassigned workers have no operational access."
            )
            return redirect("logistics_location_access")
    elif action is not None:
        raise PermissionDenied("Unsupported location access operation.")
    return render(
        request,
        "logistics/location_access.html",
        {
            "assignment_form": assignment_form,
            "handling_form": handling_form,
            "access_reviewed": LogisticsProfile.objects.filter(
                business=business, location_access_reviewed_at__isnull=False
            ).exists(),
            "assignments": LogisticsLocationAssignment.objects.filter(
                business=business
            ).select_related("membership__user", "location"),
            "handling_sites": LogisticsHandlingSite.objects.filter(
                business=business
            ).select_related("location", "parcel", "shipment"),
            "unassigned_workers": BusinessUser.objects.filter(
                business=business, role=BusinessUser.Role.STAFF, is_active=True
            ).exclude(logistics_location_assignments__location__is_active=True),
        },
    )


@never_cache
@business_role_required(*PARCEL_VIEW_ROLES)
@business_module_required("parcels", access="read")
@business_module_required("tracking", access="read")
@require_POST
def work_location(request):
    # No submitted tenant, membership or redirect is accepted.
    select_work_location(
        business=request.current_business, actor=request.user, location=request.POST.get("location")
    )
    return redirect("logistics_parcel_scan")
