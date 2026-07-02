from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import timedelta
from functools import wraps
from typing import Any, TypeVar

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from helpers import build_public_url

from .models import (
    Business,
    BusinessBookingSettings,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
)

CURRENT_BUSINESS_SESSION_KEY = "current_business_id"
_CURRENT_BUSINESS_RESOLVED_ATTR = "_current_business_resolved"
_CURRENT_BUSINESS_CACHE_ATTR = "_cached_current_business"
_CURRENT_BUSINESS_MEMBERSHIP_CACHE_ATTR = "_cached_current_business_membership"

ViewFunc = TypeVar("ViewFunc", bound=Callable[..., HttpResponse])

ALL_WORKSPACE_ROLES = tuple(role for role, _label in BusinessUser.Role.choices)
OWNER_ADMIN_ROLES = (
    BusinessUser.Role.OWNER,
    BusinessUser.Role.ADMIN,
)
CLIENT_MANAGE_ROLES = (
    BusinessUser.Role.OWNER,
    BusinessUser.Role.ADMIN,
    BusinessUser.Role.STAFF,
    BusinessUser.Role.ACCOUNTANT,
)
LEAD_MANAGE_ROLES = (
    BusinessUser.Role.OWNER,
    BusinessUser.Role.ADMIN,
    BusinessUser.Role.STAFF,
)
APPOINTMENT_VIEW_ROLES = ALL_WORKSPACE_ROLES
APPOINTMENT_MANAGE_ROLES = (
    BusinessUser.Role.OWNER,
    BusinessUser.Role.ADMIN,
    BusinessUser.Role.STAFF,
)
BOOKING_AVAILABILITY_MANAGE_ROLES = (
    BusinessUser.Role.OWNER,
    BusinessUser.Role.ADMIN,
    BusinessUser.Role.STAFF,
)
BILLING_VIEW_ROLES = (
    BusinessUser.Role.OWNER,
    BusinessUser.Role.ADMIN,
    BusinessUser.Role.STAFF,
    BusinessUser.Role.ACCOUNTANT,
    BusinessUser.Role.VIEWER,
)
BILLING_MANAGE_ROLES = (
    BusinessUser.Role.OWNER,
    BusinessUser.Role.ADMIN,
    BusinessUser.Role.STAFF,
    BusinessUser.Role.ACCOUNTANT,
)
SERVICE_MANAGEMENT_ROLES = OWNER_ADMIN_ROLES
SAME_WORKSPACE_EMAIL_MESSAGE = "This email is already connected to the current workspace."
MULTI_WORKSPACE_EMAIL_MESSAGE = (
    "This email is already connected to another workspace. "
    "Please invite the employee using their company-specific email address."
)


def membership_has_any_role(
    membership: BusinessUser | None,
    allowed_roles: tuple[str, ...] | list[str] | set[str],
) -> bool:
    return bool(membership is not None and membership.role in set(allowed_roles))


def set_current_business(request: HttpRequest, business: Business | None) -> None:
    request.current_business = business
    setattr(request, _CURRENT_BUSINESS_CACHE_ATTR, business)
    setattr(request, _CURRENT_BUSINESS_RESOLVED_ATTR, True)

    if not hasattr(request, "session"):
        return

    if business is None:
        request.session.pop(CURRENT_BUSINESS_SESSION_KEY, None)
        return

    request.session[CURRENT_BUSINESS_SESSION_KEY] = business.id


def get_current_business(request: HttpRequest) -> Business | None:
    if getattr(request, _CURRENT_BUSINESS_RESOLVED_ATTR, False):
        return getattr(request, _CURRENT_BUSINESS_CACHE_ATTR, None)

    business: Business | None = None

    if getattr(request.user, "is_authenticated", False):
        memberships = (
            BusinessUser.objects.filter(
                user=request.user,
                is_active=True,
                business__is_active=True,
            )
            .select_related("business")
            .order_by("created_at", "pk")
        )

        session_business_id = None
        if hasattr(request, "session"):
            session_business_id = request.session.get(CURRENT_BUSINESS_SESSION_KEY)

        if session_business_id:
            membership = memberships.filter(business_id=session_business_id).first()
            if membership is not None:
                business = membership.business

        if business is None:
            fallback_membership = memberships.first()
            if fallback_membership is not None:
                # Motionmate MVP does not expose a workspace switcher. We keep this
                # first-membership fallback for legacy multi-workspace accounts
                # until they can be cleaned up safely.
                business = fallback_membership.business

    set_current_business(request, business)
    return business


def get_current_business_membership(request: HttpRequest) -> BusinessUser | None:
    if hasattr(request, _CURRENT_BUSINESS_MEMBERSHIP_CACHE_ATTR):
        return getattr(request, _CURRENT_BUSINESS_MEMBERSHIP_CACHE_ATTR)

    membership: BusinessUser | None = None
    business = get_current_business(request)

    if getattr(request.user, "is_authenticated", False) and business is not None:
        membership = (
            BusinessUser.objects.select_related("business", "user")
            .filter(
                user=request.user,
                business=business,
                is_active=True,
                business__is_active=True,
            )
            .first()
        )

    setattr(request, _CURRENT_BUSINESS_MEMBERSHIP_CACHE_ATTR, membership)
    request.current_business_membership = membership
    return membership


def generate_business_slug(name: str) -> str:
    base_slug = slugify(name).strip("-") or "business"
    max_base_length = 150
    candidate = base_slug[:max_base_length]
    suffix = 2

    while Business.objects.filter(slug=candidate).exists():
        suffix_text = f"-{suffix}"
        trimmed_base = base_slug[: max_base_length - len(suffix_text)].strip("-") or "business"
        candidate = f"{trimmed_base}{suffix_text}"
        suffix += 1

    return candidate


def business_required(
    view_func: ViewFunc | None = None,
    *,
    login_url: str = "business_login",
    setup_url_name: str = "business_setup",
) -> ViewFunc | Callable[[ViewFunc], ViewFunc]:
    def decorator(func: ViewFunc) -> ViewFunc:
        @wraps(func)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            business = get_current_business(request)
            if business is None:
                return redirect(setup_url_name)
            request.current_business = business
            return func(request, *args, **kwargs)

        return login_required(wrapped, login_url=login_url)  # type: ignore[return-value]

    if view_func is None:
        return decorator
    return decorator(view_func)


def business_role_required(
    *allowed_roles: str,
    login_url: str = "business_login",
    setup_url_name: str = "business_setup",
    redirect_url_name: str | None = None,
    permission_message: str = "You do not have permission to perform this action.",
    raise_exception: bool = True,
) -> Callable[[ViewFunc], ViewFunc]:
    allowed_role_set = set(allowed_roles)

    def decorator(func: ViewFunc) -> ViewFunc:
        @wraps(func)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            membership = get_current_business_membership(request)
            if membership is None:
                return redirect(setup_url_name)

            if membership.role not in allowed_role_set:
                if redirect_url_name is not None or not raise_exception:
                    messages.error(request, permission_message)
                    return redirect(redirect_url_name or "agent_dashboard")

                raise PermissionDenied(permission_message)

            request.current_business_membership = membership
            return func(request, *args, **kwargs)

        return business_required(
            login_url=login_url,
            setup_url_name=setup_url_name,
        )(wrapped)

    return decorator


def get_business_subscription(business: Business | None) -> BusinessSubscription | None:
    if business is None:
        return None

    try:
        return business.subscription
    except BusinessSubscription.DoesNotExist:
        return None


def business_has_active_subscription(business: Business | None) -> bool:
    subscription = get_business_subscription(business)
    return bool(subscription and subscription.has_access)


def business_is_trialing(business: Business | None) -> bool:
    subscription = get_business_subscription(business)
    return bool(subscription and subscription.is_trialing)


def can_use_module(business: Business | None, module_name: str) -> bool:
    subscription = get_business_subscription(business)
    return bool(subscription and subscription.can_use_module(module_name))


PLAN_LIMIT_FIELDS = {
    "users": "max_users",
    "clients": "max_clients",
    "invoices_per_month": "max_invoices_per_month",
    "appointments_per_month": "max_appointments_per_month",
    "public_bookings_per_month": "max_public_bookings_per_month",
}
PLAN_LIMIT_LABELS = {
    "users": "team users",
    "clients": "clients",
    "invoices_per_month": "invoices this month",
    "appointments_per_month": "appointments this month",
    "public_bookings_per_month": "public bookings this month",
}
PLAN_CHANGE_MODULES = (
    "invoicing",
    "appointments",
    "public_booking",
)


def _normalize_plan_limit_name(limit_name: str) -> str:
    return limit_name.strip().lower().replace("-", "_")


def get_business_plan_limit(business: Business | None, limit_name: str) -> int | None:
    normalized_name = _normalize_plan_limit_name(limit_name)
    field_name = PLAN_LIMIT_FIELDS.get(normalized_name)
    if field_name is None:
        return None

    subscription = get_business_subscription(business)
    if subscription is None or not subscription.has_access:
        return None

    return getattr(subscription.plan, field_name, None)


def get_plan_limit(plan: ClarivoPlan | None, limit_name: str) -> int | None:
    normalized_name = _normalize_plan_limit_name(limit_name)
    field_name = PLAN_LIMIT_FIELDS.get(normalized_name)
    if field_name is None or plan is None:
        return None

    return getattr(plan, field_name, None)


def _format_limit_value(limit: int | None) -> str:
    if limit is None:
        return "Unlimited"
    return str(limit)


def _current_month_bounds():
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)
    return month_start, next_month_start


def get_business_usage_count(
    business: Business | None,
    limit_name: str,
    *,
    include_pending_invitations: bool = False,
) -> int:
    if business is None:
        return 0

    normalized_name = _normalize_plan_limit_name(limit_name)
    if normalized_name == "users":
        user_count = business.memberships.filter(is_active=True).count()
        if include_pending_invitations:
            user_count += business.invitations.filter(
                status=BusinessInvitation.Status.PENDING,
                expires_at__gt=timezone.now(),
            ).count()
        return user_count

    if normalized_name == "clients":
        return business.clients.count()

    if normalized_name == "invoices_per_month":
        month_start, next_month_start = _current_month_bounds()
        return business.invoices.filter(
            created_at__gte=month_start,
            created_at__lt=next_month_start,
        ).count()

    if normalized_name == "appointments_per_month":
        month_start, next_month_start = _current_month_bounds()
        return business.appointments.filter(
            created_at__gte=month_start,
            created_at__lt=next_month_start,
        ).count()

    if normalized_name == "public_bookings_per_month":
        month_start, next_month_start = _current_month_bounds()
        return business.leads.filter(
            request_source__in=("public_booking", "public_request"),
            created_at__gte=month_start,
            created_at__lt=next_month_start,
        ).count()

    return 0


def get_business_plan_usage_summary(
    business: Business | None,
    plan: ClarivoPlan | None,
    *,
    include_pending_invitations: bool = True,
) -> list[dict[str, Any]]:
    usage_summary = []
    for limit_name in PLAN_LIMIT_FIELDS:
        limit = get_plan_limit(plan, limit_name)
        usage_count = get_business_usage_count(
            business,
            limit_name,
            include_pending_invitations=include_pending_invitations,
        )
        usage_summary.append(
            {
                "name": limit_name,
                "label": PLAN_LIMIT_LABELS.get(limit_name, "items"),
                "usage": usage_count,
                "limit": limit,
                "limit_display": _format_limit_value(limit),
                "exceeded": limit is not None and usage_count > limit,
                "at_limit": limit is not None and usage_count == limit,
            }
        )

    return usage_summary


def get_business_plan_module_losses(
    business: Business | None,
    target_plan: ClarivoPlan | None,
) -> list[dict[str, str]]:
    subscription = get_business_subscription(business)
    if subscription is None or target_plan is None or subscription.plan_id == target_plan.id:
        return []

    current_plan = subscription.plan
    return [
        {
            "name": module_name,
            "label": get_module_display_name(module_name),
        }
        for module_name in PLAN_CHANGE_MODULES
        if current_plan.allows_module(module_name) and not target_plan.allows_module(module_name)
    ]


def get_business_plan_change_impact(
    business: Business | None,
    target_plan: ClarivoPlan | None,
) -> dict[str, Any]:
    usage_summary = get_business_plan_usage_summary(business, target_plan)
    over_limit_usage = [usage for usage in usage_summary if usage["exceeded"]]
    module_losses = get_business_plan_module_losses(business, target_plan)

    return {
        "target_plan": target_plan,
        "usage_summary": usage_summary,
        "over_limit_usage": over_limit_usage,
        "module_losses": module_losses,
        "requires_confirmation": bool(over_limit_usage or module_losses),
    }


def business_limit_reached(
    business: Business | None,
    limit_name: str,
    *,
    include_pending_invitations: bool = False,
) -> bool:
    limit = get_business_plan_limit(business, limit_name)
    if limit is None:
        return False

    usage_count = get_business_usage_count(
        business,
        limit_name,
        include_pending_invitations=include_pending_invitations,
    )
    return usage_count >= limit


def get_business_limit_reached_message(business: Business | None, limit_name: str) -> str:
    normalized_name = _normalize_plan_limit_name(limit_name)
    limit = get_business_plan_limit(business, normalized_name)
    subscription = get_business_subscription(business)
    plan_name = subscription.plan.name if subscription is not None else "current"
    limit_label = PLAN_LIMIT_LABELS.get(normalized_name, "items")

    if limit is None:
        return f"This workspace cannot add more {limit_label} right now."

    return (
        f"This workspace has reached the {plan_name} plan limit of "
        f"{limit} {limit_label}. Upgrade your Motionmate plan to add more."
    )


def get_module_display_name(module_name: str) -> str:
    normalized_name = module_name.strip().lower().replace("-", "_")
    display_names = {
        "client_management": "Client Management",
        "invoicing": "Invoicing",
        "public_request_form": "Public Bookings",
        "public_request": "Public Bookings",
        "public_booking": "Public Bookings",
        "public_booking_requests": "Public Bookings",
        "appointments": "Appointments",
    }
    if normalized_name in display_names:
        return display_names[normalized_name]
    return normalized_name.replace("_", " ").title()


def get_business_module_unavailable_message(
    business: Business | None,
    module_name: str,
) -> str:
    module_label = get_module_display_name(module_name)

    if business is None or not business.is_active:
        return f"{module_label} is not available for this workspace."

    subscription = get_business_subscription(business)
    if subscription is None:
        return (
            f"{module_label} is not available because this workspace does not have "
            "an active Motionmate subscription yet."
        )

    if not subscription.has_access:
        return (
            f"{module_label} is not available because this workspace subscription "
            "is not active."
        )

    return f"{module_label} is not included in the current workspace plan."


def get_public_booking_share_context(
    request: HttpRequest,
    business: Business,
    *,
    booking_settings: BusinessBookingSettings | None = None,
) -> dict[str, Any]:
    if booking_settings is None:
        try:
            booking_settings = business.booking_settings
        except BusinessBookingSettings.DoesNotExist:
            booking_settings = None

    public_booking_allowed = can_use_module(business, "public_booking")
    booking_enabled = bool(booking_settings and booking_settings.booking_enabled)
    bookable_service_count = business.business_services.filter(
        is_active=True,
        is_bookable_online=True,
    ).count()
    active_availability_count = business.weekly_availability.filter(is_active=True).count()

    setup_items = []
    if not public_booking_allowed:
        setup_items.append("Upgrade to a plan with Public Bookings.")
    if not booking_enabled:
        setup_items.append("Enable public bookings.")
    if bookable_service_count == 0:
        setup_items.append("Add at least one active service that is bookable online.")
    if active_availability_count == 0:
        setup_items.append("Add at least one active weekly availability block.")

    public_booking_path = reverse("public_booking", args=[business.slug])

    return {
        "public_booking_url": build_public_url(public_booking_path, request=request),
        "public_booking_path": public_booking_path,
        "public_booking_allowed": public_booking_allowed,
        "public_booking_enabled": booking_enabled,
        "public_booking_bookable_service_count": bookable_service_count,
        "public_booking_active_availability_count": active_availability_count,
        "public_booking_share_ready": not setup_items,
        "public_booking_setup_items": setup_items,
    }


def redirect_for_unavailable_business_module(
    request: HttpRequest,
    module_name: str,
) -> HttpResponse:
    membership = get_current_business_membership(request)
    message = get_business_module_unavailable_message(
        getattr(request, "current_business", None),
        module_name,
    )

    if membership is not None and membership.role == BusinessUser.Role.OWNER:
        messages.error(request, f"{message} Review your subscription to upgrade access.")
        return redirect("business_subscription")

    messages.error(request, f"{message} Please contact your workspace owner.")
    return redirect("agent_dashboard")


def business_module_required(
    module_name: str,
    *,
    login_url: str = "business_login",
    setup_url_name: str = "business_setup",
) -> Callable[[ViewFunc], ViewFunc]:
    def decorator(func: ViewFunc) -> ViewFunc:
        @wraps(func)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            # UI hiding helps discovery, but it is not a security boundary.
            # Route handlers must enforce plan access on the backend as well.
            if not can_use_module(request.current_business, module_name):
                return redirect_for_unavailable_business_module(request, module_name)

            return func(request, *args, **kwargs)

        return business_required(
            login_url=login_url,
            setup_url_name=setup_url_name,
        )(wrapped)

    return decorator


def create_default_trial_subscription(
    business: Business,
    *,
    trial_days: int = 14,
) -> BusinessSubscription | None:
    existing_subscription = get_business_subscription(business)
    if existing_subscription is not None:
        return existing_subscription

    plan = ClarivoPlan.objects.filter(
        is_active=True,
        slug="pro",
    ).first()
    if plan is None:
        plan = (
            ClarivoPlan.objects.filter(is_active=True)
            .order_by("created_at", "pk")
            .first()
        )

    if plan is None:
        return None

    trial_start = timezone.now()
    trial_end = trial_start + timedelta(days=trial_days)

    subscription, _created = BusinessSubscription.objects.get_or_create(
        business=business,
        defaults={
            "plan": plan,
            "status": BusinessSubscription.Status.TRIALING,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "current_period_start": trial_start,
            "current_period_end": trial_end,
        },
    )
    return subscription


def get_other_active_business_membership_for_email(
    *,
    email: str,
    business: Business,
) -> BusinessUser | None:
    normalized_email = email.strip().lower()
    if not normalized_email:
        return None

    return (
        BusinessUser.objects.select_related("business", "user")
        .filter(
            user__email__iexact=normalized_email,
            is_active=True,
            business__is_active=True,
        )
        .exclude(business=business)
        .order_by("created_at", "pk")
        .first()
    )


def get_other_active_business_membership_for_user(
    user,
    business: Business,
) -> BusinessUser | None:
    return (
        BusinessUser.objects.select_related("business", "user")
        .filter(
            user=user,
            is_active=True,
            business__is_active=True,
        )
        .exclude(business=business)
        .order_by("created_at", "pk")
        .first()
    )


def assign_business_subscription_plan(
    business: Business,
    plan: ClarivoPlan,
    *,
    trial_days: int = 14,
) -> BusinessSubscription:
    subscription = get_business_subscription(business)
    now = timezone.now()

    if subscription is None:
        trial_end = now + timedelta(days=trial_days)
        return BusinessSubscription.objects.create(
            business=business,
            plan=plan,
            status=BusinessSubscription.Status.TRIALING,
            trial_start=now,
            trial_end=trial_end,
            current_period_start=now,
            current_period_end=trial_end,
        )

    subscription.plan = plan
    subscription.cancel_at_period_end = False

    if subscription.status == BusinessSubscription.Status.TRIALING:
        if subscription.trial_start is None:
            subscription.trial_start = now
        if subscription.trial_end is None:
            subscription.trial_end = subscription.trial_start + timedelta(days=trial_days)
        if subscription.current_period_start is None:
            subscription.current_period_start = subscription.trial_start
        if subscription.current_period_end is None:
            subscription.current_period_end = subscription.trial_end
    else:
        if subscription.current_period_start is None:
            subscription.current_period_start = now

    # TODO: Replace direct plan swaps with Stripe Checkout and webhook-driven subscription updates.
    subscription.save(
        update_fields=[
            "plan",
            "cancel_at_period_end",
            "trial_start",
            "trial_end",
            "current_period_start",
            "current_period_end",
            "updated_at",
        ]
    )
    return subscription


def get_assignable_business_roles(membership: BusinessUser | None) -> tuple[str, ...]:
    if membership is None:
        return ()

    if membership.role == BusinessUser.Role.OWNER:
        return tuple(role for role, _label in BusinessUser.Role.choices)

    if membership.role == BusinessUser.Role.ADMIN:
        return (
            BusinessUser.Role.STAFF,
            BusinessUser.Role.ACCOUNTANT,
            BusinessUser.Role.VIEWER,
        )

    return ()


def can_assign_business_role(membership: BusinessUser | None, role: str) -> bool:
    return role in get_assignable_business_roles(membership)


def generate_business_invitation_token() -> str:
    while True:
        token = secrets.token_urlsafe(32)
        if not BusinessInvitation.objects.filter(token=token).exists():
            return token


def expire_business_invitation_if_needed(invitation: BusinessInvitation) -> bool:
    if invitation.is_expired:
        invitation.status = BusinessInvitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        return True
    return invitation.status == BusinessInvitation.Status.EXPIRED


def create_or_refresh_business_invitation(
    *,
    business: Business,
    email: str,
    role: str,
    invited_by,
    expiry_days: int = 7,
) -> tuple[BusinessInvitation, bool]:
    normalized_email = email.strip().lower()
    expires_at = timezone.now() + timedelta(days=expiry_days)
    invitation = (
        BusinessInvitation.objects.filter(
            business=business,
            email__iexact=normalized_email,
            status=BusinessInvitation.Status.PENDING,
        )
        .order_by("-created_at", "-pk")
        .first()
    )

    if invitation is not None and expire_business_invitation_if_needed(invitation):
        invitation = None

    if invitation is not None:
        invitation.role = role
        invitation.invited_by = invited_by
        invitation.expires_at = expires_at
        invitation.save(update_fields=["role", "invited_by", "expires_at", "updated_at"])
        return invitation, False

    invitation = BusinessInvitation.objects.create(
        business=business,
        email=normalized_email,
        role=role,
        token=generate_business_invitation_token(),
        invited_by=invited_by,
        status=BusinessInvitation.Status.PENDING,
        expires_at=expires_at,
    )
    return invitation, True


@transaction.atomic
def accept_business_invitation_for_user(
    invitation: BusinessInvitation,
    user,
) -> tuple[BusinessUser, bool, bool]:
    if expire_business_invitation_if_needed(invitation):
        raise ValueError("This invitation has expired.")

    if invitation.status != BusinessInvitation.Status.PENDING:
        raise ValueError("This invitation is no longer available.")

    if (getattr(user, "email", "") or "").strip().lower() != invitation.email.lower():
        raise ValueError("This invitation must be accepted with the invited email address.")

    membership = BusinessUser.objects.filter(
        user=user,
        business=invitation.business,
    ).first()
    other_active_membership = get_other_active_business_membership_for_user(
        user,
        invitation.business,
    )
    created = False
    already_member = False

    if membership is None:
        if other_active_membership is not None:
            raise ValueError(MULTI_WORKSPACE_EMAIL_MESSAGE)
        membership = BusinessUser.objects.create(
            user=user,
            business=invitation.business,
            role=invitation.role,
            is_active=True,
        )
        created = True
    elif membership.is_active:
        already_member = True
    else:
        if other_active_membership is not None:
            raise ValueError(MULTI_WORKSPACE_EMAIL_MESSAGE)
        membership.role = invitation.role
        membership.is_active = True
        membership.save(update_fields=["role", "is_active", "updated_at"])

    invitation.status = BusinessInvitation.Status.ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["status", "accepted_at", "accepted_by", "updated_at"])

    return membership, created, already_member
