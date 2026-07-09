from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.notifications.emails import send_business_invitation_email
from helpers import build_public_url

from .forms import (
    BusinessBookingSettingsForm,
    BusinessInvitationForm,
    BusinessSettingsForm,
    BusinessSubscriptionPlanForm,
    WeeklyAvailabilityBulkForm,
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
    BOOKING_AVAILABILITY_MANAGE_ROLES,
    MULTI_WORKSPACE_EMAIL_MESSAGE,
    SAME_WORKSPACE_EMAIL_MESSAGE,
    assign_business_subscription_plan,
    business_limit_reached,
    business_role_required,
    can_assign_business_role,
    can_use_module,
    create_or_refresh_business_invitation,
    get_business_limit_reached_message,
    get_business_module_unavailable_message,
    get_business_plan_change_impact,
    get_business_plan_usage_summary,
    get_business_subscription,
    get_business_usage_count,
    get_current_business,
    get_other_active_business_membership_for_email,
    get_public_booking_share_context,
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
        **get_public_booking_share_context(request, business),
    }
    return render(request, "businesses/settings.html", context)


@business_role_required(*BOOKING_AVAILABILITY_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def business_booking_settings(request: HttpRequest) -> HttpResponse:
    business = request.current_business
    membership = request.current_business_membership
    can_manage_booking_rules = membership.role in (
        BusinessUser.Role.OWNER,
        BusinessUser.Role.ADMIN,
    )
    booking_settings, _created = BusinessBookingSettings.objects.get_or_create(
        business=business,
    )
    availability_blocks = business.weekly_availability.filter(is_active=True)
    if membership.role == BusinessUser.Role.STAFF:
        availability_blocks = availability_blocks.filter(staff_member=request.user)
    inactive_availability_blocks = business.weekly_availability.filter(is_active=False)
    if membership.role == BusinessUser.Role.STAFF:
        inactive_availability_blocks = inactive_availability_blocks.filter(
            staff_member=request.user,
        )
    public_booking_allowed = can_use_module(business, "public_booking")
    unavailable_message = ""
    if not public_booking_allowed:
        unavailable_message = get_business_module_unavailable_message(
            business,
            "public_booking",
        )

    availability_form_initial = {"is_active": True}
    bulk_availability_form_initial = {
        "days": [
            WeeklyAvailability.DayOfWeek.MONDAY,
            WeeklyAvailability.DayOfWeek.TUESDAY,
            WeeklyAvailability.DayOfWeek.WEDNESDAY,
            WeeklyAvailability.DayOfWeek.THURSDAY,
            WeeklyAvailability.DayOfWeek.FRIDAY,
        ],
        "is_active": True,
    }
    availability_form_kind = "single"

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
                user=request.user,
                membership=membership,
            )
            bulk_availability_form = WeeklyAvailabilityBulkForm(
                business=business,
                user=request.user,
                membership=membership,
                initial=bulk_availability_form_initial,
            )
            if availability_form.is_valid():
                availability_form.save()
                messages.success(request, "Weekly availability block added.")
                return redirect("business_booking_settings")
            messages.error(request, "Please correct the availability errors below.")
        elif form_kind == "bulk_availability":
            availability_form_kind = "bulk"
            settings_form = BusinessBookingSettingsForm(
                instance=booking_settings,
                business=business,
            )
            availability_form = WeeklyAvailabilityForm(
                business=business,
                user=request.user,
                membership=membership,
                initial=availability_form_initial,
            )
            bulk_availability_form = WeeklyAvailabilityBulkForm(
                request.POST,
                business=business,
                user=request.user,
                membership=membership,
            )
            if bulk_availability_form.is_valid():
                availability_blocks_created = bulk_availability_form.save()
                block_count = len(availability_blocks_created)
                block_label = "block" if block_count == 1 else "blocks"
                messages.success(
                    request,
                    f"{block_count} weekly availability {block_label} added.",
                )
                return redirect("business_booking_settings")
            messages.error(request, "Please correct the bulk availability errors below.")
        else:
            if not can_manage_booking_rules:
                raise PermissionDenied("Only workspace owners and admins can update booking rules.")
            settings_form = BusinessBookingSettingsForm(
                request.POST,
                instance=booking_settings,
                business=business,
            )
            availability_form = WeeklyAvailabilityForm(
                business=business,
                user=request.user,
                membership=membership,
                initial=availability_form_initial,
            )
            bulk_availability_form = WeeklyAvailabilityBulkForm(
                business=business,
                user=request.user,
                membership=membership,
                initial=bulk_availability_form_initial,
            )
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
            user=request.user,
            membership=membership,
            initial=availability_form_initial,
        )
        bulk_availability_form = WeeklyAvailabilityBulkForm(
            business=business,
            user=request.user,
            membership=membership,
            initial=bulk_availability_form_initial,
        )

    context = {
        "business": business,
        "membership": membership,
        "booking_settings": booking_settings,
        "settings_form": settings_form,
        "availability_form": availability_form,
        "bulk_availability_form": bulk_availability_form,
        "availability_form_kind": availability_form_kind,
        "availability_blocks": availability_blocks,
        "inactive_availability_count": inactive_availability_blocks.count(),
        "can_manage_booking_rules": can_manage_booking_rules,
        "unavailable_message": unavailable_message,
        **get_public_booking_share_context(
            request,
            business,
            booking_settings=booking_settings,
        ),
    }
    return render(request, "businesses/booking_settings.html", context)


@business_role_required(*BOOKING_AVAILABILITY_MANAGE_ROLES)
@require_http_methods(["POST"])
def business_weekly_availability_deactivate(
    request: HttpRequest,
    availability_id: int,
) -> HttpResponse:
    availability_queryset = WeeklyAvailability.objects.filter(
        business=request.current_business,
        is_active=True,
    )
    if request.current_business_membership.role == BusinessUser.Role.STAFF:
        availability_queryset = availability_queryset.filter(staff_member=request.user)

    availability_block = get_object_or_404(
        availability_queryset,
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
    available_plan_queryset = ClarivoPlan.motionmate_plans()
    available_plans = list(available_plan_queryset)
    ClarivoPlan.attach_display_pricing(available_plans, business=business)
    pending_plan_change = None

    if request.method == "POST":
        form = BusinessSubscriptionPlanForm(request.POST, plans=available_plan_queryset)
        if form.is_valid():
            selected_plan = form.cleaned_data["plan"]

            if subscription is not None and subscription.plan_id == selected_plan.id:
                messages.info(
                    request, f"{selected_plan.name} is already the active plan for this workspace."
                )
            else:
                plan_change_impact = get_business_plan_change_impact(business, selected_plan)
                plan_change_confirmed = request.POST.get("confirm_plan_change") == "1"

                if plan_change_impact["requires_confirmation"] and not plan_change_confirmed:
                    pending_plan_change = plan_change_impact
                    messages.warning(
                        request,
                        f"Review the limits before changing to {selected_plan.name}.",
                    )
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
                    if plan_change_impact["over_limit_usage"]:
                        messages.warning(
                            request,
                            (
                                "Existing records were kept, but new activity may be blocked "
                                f"until this workspace is within the {selected_plan.name} quotas."
                            ),
                        )
                    if plan_change_impact["module_losses"]:
                        module_labels = ", ".join(
                            module["label"] for module in plan_change_impact["module_losses"]
                        )
                        messages.warning(
                            request,
                            (
                                f"{module_labels} will no longer be available on the "
                                f"{selected_plan.name} plan."
                            ),
                        )
                    return redirect("business_subscription")
            if pending_plan_change is None:
                return redirect("business_subscription")
    else:
        form = BusinessSubscriptionPlanForm(plans=available_plan_queryset)

    current_usage_summary = []
    staff_capacity = None
    if subscription is not None:
        current_usage_summary = get_business_plan_usage_summary(
            business,
            subscription.plan,
            include_pending_invitations=True,
        )
        max_staff_accounts = subscription.plan.staff_account_limit
        active_user_count = get_business_usage_count(
            business,
            "users",
            include_pending_invitations=True,
        )
        used_staff_accounts = max(active_user_count - 1, 0)
        staff_capacity = {
            "limit": max_staff_accounts,
            "limit_display": (
                "Unlimited" if max_staff_accounts is None else str(max_staff_accounts)
            ),
            "used": used_staff_accounts,
            "available": (
                None
                if max_staff_accounts is None
                else max(max_staff_accounts - used_staff_accounts, 0)
            ),
            "available_display": (
                "Unlimited"
                if max_staff_accounts is None
                else str(max(max_staff_accounts - used_staff_accounts, 0))
            ),
        }

    context = {
        "business": business,
        "membership": membership,
        "subscription": subscription,
        "available_plans": available_plans,
        "plan_form": form,
        "pending_plan_change": pending_plan_change,
        "current_usage_summary": current_usage_summary,
        "staff_capacity": staff_capacity,
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
            invite_email = invite_form.cleaned_data["email"]
            if BusinessUser.objects.filter(
                business=business,
                user__email__iexact=invite_email,
            ).exists():
                messages.info(request, SAME_WORKSPACE_EMAIL_MESSAGE)
                return redirect("business_team_members")

            if (
                get_other_active_business_membership_for_email(
                    email=invite_email,
                    business=business,
                )
                is not None
            ):
                messages.error(request, MULTI_WORKSPACE_EMAIL_MESSAGE)
                return redirect("business_team_members")

            existing_pending_invitation = BusinessInvitation.objects.filter(
                business=business,
                email__iexact=invite_email,
                status=BusinessInvitation.Status.PENDING,
            ).exists()
            if not existing_pending_invitation and business_limit_reached(
                business,
                "users",
                include_pending_invitations=True,
            ):
                messages.error(request, get_business_limit_reached_message(business, "users"))
                return redirect("business_team_members")

            invitation, created = create_or_refresh_business_invitation(
                business=business,
                email=invite_email,
                role=invite_form.cleaned_data["role"],
                invited_by=request.user,
            )
            accept_url = build_public_url(
                reverse("accept_business_invitation", args=[invitation.token]),
                request=request,
            )
            email_sent = send_business_invitation_email(invitation, accept_url=accept_url)
            if created and email_sent:
                messages.success(
                    request,
                    "Invitation created and emailed successfully. The fallback link remains below.",
                )
            elif created:
                messages.warning(
                    request,
                    "Invitation created, but email could not be sent. Copy the fallback link below.",
                )
            elif email_sent:
                messages.info(
                    request,
                    "A pending invitation was refreshed and emailed again.",
                )
            else:
                messages.warning(
                    request,
                    "A pending invitation was refreshed, but email could not be sent. Copy the fallback link below.",
                )
            return redirect("business_team_members")
    else:
        invite_form = BusinessInvitationForm(business=business, membership=membership)

    pending_invitations = list(
        business.invitations.select_related("invited_by").filter(
            status=BusinessInvitation.Status.PENDING,
        )
    )
    for invitation in pending_invitations:
        invitation.public_accept_url = build_public_url(
            reverse("accept_business_invitation", args=[invitation.token]),
            request=request,
        )

    context = {
        "business": business,
        "membership": membership,
        "invite_form": invite_form,
        "team_memberships": business.memberships.select_related("user").order_by(
            "user__first_name", "user__last_name", "user__email"
        ),
        "pending_invitations": pending_invitations,
    }
    return render(request, "businesses/team_members.html", context)


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
@require_http_methods(["POST"])
def business_team_member_deactivate(request: HttpRequest, membership_id: int) -> HttpResponse:
    business = request.current_business
    acting_membership = request.current_business_membership
    team_membership = get_object_or_404(
        BusinessUser.objects.select_related("user").filter(business=business),
        pk=membership_id,
    )

    if team_membership.pk == acting_membership.pk:
        messages.error(request, "You cannot remove your own workspace membership.")
        return redirect("business_team_members")

    if not can_assign_business_role(acting_membership, team_membership.role):
        messages.error(request, "You do not have permission to remove that workspace role.")
        return redirect("business_team_members")

    active_owner_count = business.memberships.filter(
        role=BusinessUser.Role.OWNER,
        is_active=True,
    ).count()
    if team_membership.role == BusinessUser.Role.OWNER and active_owner_count <= 1:
        messages.error(request, "This workspace must keep at least one active owner.")
        return redirect("business_team_members")

    if not team_membership.is_active:
        messages.info(request, f"{team_membership.user.email} is already inactive.")
        return redirect("business_team_members")

    team_membership.is_active = False
    team_membership.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"{team_membership.user.email} was removed from the active team.")
    return redirect("business_team_members")
