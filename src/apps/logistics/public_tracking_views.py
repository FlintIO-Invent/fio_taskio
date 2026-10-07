"""Public tracking HTML; no workspace/session context or models reach the template."""

from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .public_tracking import (
    LOOKUP_WINDOW_SECONDS,
    allow_tracking_lookup,
    lookup_public_tracking,
    tracking_client_identity,
)

NOT_FOUND_MESSAGE = (
    "Tracking information is unavailable. Check your tracking code or try again later."
)


@never_cache
@sensitive_post_parameters("tracking_code")
@require_http_methods(["GET", "POST"])
def public_tracking(request):
    result = None
    error = ""
    status = 200
    if request.method == "POST":
        if not allow_tracking_lookup(tracking_client_identity(request)):
            status = 429
            error = "Too many tracking attempts. Please try again later."
        else:
            result = lookup_public_tracking(request.POST.get("tracking_code", ""))
            if result is None:
                status = 404
                error = NOT_FOUND_MESSAGE
    # Do not invoke authenticated workspace context processors on this public page.
    response = HttpResponse(
        render_to_string(
            "logistics/public_tracking.html",
            {"tracking": result, "error": error, "csrf_token": get_token(request)},
        ),
        status=status,
    )
    # no-referrer makes native form POSTs send Origin:null. Keep same-origin
    # CSRF checks working while suppressing referrers to other origins.
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    if status == 429:
        response["Retry-After"] = str(LOOKUP_WINDOW_SECONDS)
    return response
