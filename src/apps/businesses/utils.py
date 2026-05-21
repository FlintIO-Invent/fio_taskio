from __future__ import annotations

import secrets
from datetime import timedelta
from functools import wraps
from typing import Any, Callable, TypeVar

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.text import slugify

from .models import (
    Business,
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
) -> Callable[[ViewFunc], ViewFunc]:
    allowed_role_set = set(allowed_roles)

    def decorator(func: ViewFunc) -> ViewFunc:
        @wraps(func)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            membership = get_current_business_membership(request)
            if membership is None:
                return redirect(setup_url_name)

            if membership.role not in allowed_role_set:
                raise PermissionDenied("You do not have permission to manage this workspace.")

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


def get_module_display_name(module_name: str) -> str:
    normalized_name = module_name.strip().lower().replace("-", "_")
    display_names = {
        "invoicing": "Invoicing",
        "public_request_form": "Public Request Form",
        "public_request": "Public Request Form",
        "public_booking": "Public Booking",
        "appointments": "Appointments",
        "memberships": "Memberships",
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
            "an active Clarivo subscription yet."
        )

    if not subscription.has_access:
        return (
            f"{module_label} is not available because this workspace subscription "
            "is not active."
        )

    return f"{module_label} is not included in the current workspace plan."


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

    membership = BusinessUser.objects.filter(
        user=user,
        business=invitation.business,
    ).first()
    created = False
    already_member = False

    if membership is None:
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
        membership.role = invitation.role
        membership.is_active = True
        membership.save(update_fields=["role", "is_active", "updated_at"])

    invitation.status = BusinessInvitation.Status.ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["status", "accepted_at", "accepted_by", "updated_at"])

    return membership, created, already_member
