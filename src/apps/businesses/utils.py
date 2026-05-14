from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from .models import Business, BusinessUser


CURRENT_BUSINESS_SESSION_KEY = "current_business_id"
_CURRENT_BUSINESS_RESOLVED_ATTR = "_current_business_resolved"
_CURRENT_BUSINESS_CACHE_ATTR = "_cached_current_business"

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
