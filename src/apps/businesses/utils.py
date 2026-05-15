from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.text import slugify

from .models import Business, BusinessSubscription, BusinessUser


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
    login_url: str = "agent_login",
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
    login_url: str = "agent_login",
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
