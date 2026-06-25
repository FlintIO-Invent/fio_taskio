from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import (
    BusinessBookingSettingsForm,
    BusinessInvitationForm,
    BusinessSettingsForm,
    BusinessSubscriptionPlanForm,
    WeeklyAvailabilityForm,
)
from .models import (
    BusinessBookingSettings,
    BusinessInvitation,
    BusinessUser,
    ClarivoPlan,
    WeeklyAvailability,
)
from .utils import (
    MULTI_WORKSPACE_EMAIL_MESSAGE,
    SAME_WORKSPACE_EMAIL_MESSAGE,
    assign_business_subscription_plan,
    business_role_required,
    can_use_module,
    create_or_refresh_business_invitation,
    get_business_module_unavailable_message,
    get_business_subscription,
    get_current_business,
    get_other_active_business_membership_for_email,
)


@login_required(login_url="business_login")
@require_http_methods(["GET"])
def business_setup(request: HttpRequest) -> HttpResponse:
    current_business = get_current_business(request)
    if current_business is not None:
        return redirect("business_settings")

    return render(request, "businesses/setup_required.html", {})


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
@require_http_methods(["GET", "POST"])
def business_settings(request: HttpRequest) -> HttpResponse:
    business = request.current_business
    membership = request.current_business_membership

    if request.method == "POST":
        form = BusinessSettingsForm(request.POST, instance=business)
        if form.is_valid():
            form.save()
            messages.success(request, "Business settings updated.")
            return redirect("business_settings")
    else:
        form = BusinessSettingsForm(instance=business)

    context = {
        "business": business,
        "membership": membership,
        "form": form,
        "service_category_count": business.service_categories.count(),
        "active_service_category_count": business.service_categories.filter(is_active=True).count(),
        "business_service_count": business.business_services.count(),
        "active_business_service_count": business.business_services.filter(is_active=True).count(),
    }
    return render(request, "businesses/settings.html", context)


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
@require_http_methods(["GET", "POST"])
def business_booking_settings(request: HttpRequest) -> HttpResponse:
    business = request.current_business
    membership = request.current_business_membership
    booking_settings, _created = BusinessBookingSettings.objects.get_or_create(
        business=business,
    )
    availability_blocks = business.weekly_availability.filter(is_active=True)
    public_booking_allowed = can_use_module(business, "public_booking")
    unavailable_message = ""
    if not public_booking_allowed:
        unavailable_message = get_business_module_unavailable_message(
            business,
            "public_booking",
        )

    if request.method == "POST":
        form_kind = request.POST.get("form_kind", "settings")

        if form_kind == "availability":
            settings_form = BusinessBookingSettingsForm(
                instance=booking_settings,
                business=business,
            )
            availability_form = WeeklyAvailabilityForm(
                request.POST,
                business=business,
            )
            if availability_form.is_valid():
                availability_form.save()
                messages.success(request, "Weekly availability block added.")
                return redirect("business_booking_settings")
            messages.error(request, "Please correct the availability errors below.")
        else:
            settings_form = BusinessBookingSettingsForm(
                request.POST,
                instance=booking_settings,
                business=business,
            )
            availability_form = WeeklyAvailabilityForm(business=business)
            if settings_form.is_valid():
                settings_form.save()
                messages.success(request, "Booking settings updated.")
                return redirect("business_booking_settings")
            messages.error(request, "Please correct the booking settings errors below.")
    else:
        settings_form = BusinessBookingSettingsForm(
            instance=booking_settings,
            business=business,
        )
        availability_form = WeeklyAvailabilityForm(
            business=business,
            initial={"is_active": True},
        )

    context = {
        "business": business,
        "membership": membership,
        "booking_settings": booking_settings,
        "settings_form": settings_form,
        "availability_form": availability_form,
        "availability_blocks": availability_blocks,
        "inactive_availability_count": business.weekly_availability.filter(
            is_active=False,
        ).count(),
        "public_booking_allowed": public_booking_allowed,
        "unavailable_message": unavailable_message,
    }
    return render(request, "businesses/booking_settings.html", context)


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
@require_http_methods(["POST"])
def business_weekly_availability_deactivate(
    request: HttpRequest,
    availability_id: int,
) -> HttpResponse:
    availability_block = get_object_or_404(
        WeeklyAvailability.objects.filter(
            business=request.current_business,
            is_active=True,
        ),
        pk=availability_id,
    )
    availability_block.is_active = False
    availability_block.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "Weekly availability block deactivated.")
    return redirect("business_booking_settings")


@business_role_required(BusinessUser.Role.OWNER)
@require_http_methods(["GET", "POST"])
def business_subscription(request: HttpRequest) -> HttpResponse:
    business = request.current_business
    membership = request.current_business_membership
    subscription = get_business_subscription(business)
    available_plans = ClarivoPlan.objects.filter(is_active=True).order_by("created_at", "pk")

    if request.method == "POST":
        form = BusinessSubscriptionPlanForm(request.POST, plans=available_plans)
        if form.is_valid():
            selected_plan = form.cleaned_data["plan"]

            if subscription is not None and subscription.plan_id == selected_plan.id:
                messages.info(request, f"{selected_plan.name} is already the active plan for this workspace.")
            else:
                updated_subscription = assign_business_subscription_plan(business, selected_plan)
                if updated_subscription.status == updated_subscription.Status.TRIALING:
                    messages.success(
                        request,
                        f"Workspace plan updated to {selected_plan.name}. The current trial remains active.",
                    )
                else:
                    messages.success(
                        request,
                        f"Workspace plan updated to {selected_plan.name}.",
                    )
            return redirect("business_subscription")
    else:
        form = BusinessSubscriptionPlanForm(plans=available_plans)

    context = {
        "business": business,
        "membership": membership,
        "subscription": subscription,
        "available_plans": available_plans,
        "plan_form": form,
    }
    return render(request, "businesses/subscription.html", context)


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
@require_http_methods(["GET", "POST"])
def business_team_members(request: HttpRequest) -> HttpResponse:
    business = request.current_business
    membership = request.current_business_membership

    BusinessInvitation.objects.filter(
        business=business,
        status=BusinessInvitation.Status.PENDING,
        expires_at__lte=timezone.now(),
    ).update(status=BusinessInvitation.Status.EXPIRED, updated_at=timezone.now())

    if request.method == "POST":
        invite_form = BusinessInvitationForm(
            request.POST,
            business=business,
            membership=membership,
        )
        if invite_form.is_valid():
            if BusinessUser.objects.filter(
                business=business,
                user__email__iexact=invite_form.cleaned_data["email"],
            ).exists():
                messages.info(request, SAME_WORKSPACE_EMAIL_MESSAGE)
                return redirect("business_team_members")

            if get_other_active_business_membership_for_email(
                email=invite_form.cleaned_data["email"],
                business=business,
            ) is not None:
                messages.error(request, MULTI_WORKSPACE_EMAIL_MESSAGE)
                return redirect("business_team_members")

            invitation, created = create_or_refresh_business_invitation(
                business=business,
                email=invite_form.cleaned_data["email"],
                role=invite_form.cleaned_data["role"],
                invited_by=request.user,
            )
            if created:
                messages.success(request, "Invitation created successfully.")
            else:
                messages.info(request, "A pending invitation was refreshed for this email.")
            return redirect("business_team_members")
    else:
        invite_form = BusinessInvitationForm(business=business, membership=membership)

    context = {
        "business": business,
        "membership": membership,
        "invite_form": invite_form,
        "team_memberships": business.memberships.select_related("user").order_by(
            "user__first_name", "user__last_name", "user__email"
        ),
        "pending_invitations": business.invitations.select_related("invited_by").filter(
            status=BusinessInvitation.Status.PENDING,
        ),
    }
    return render(request, "businesses/team_members.html", context)
