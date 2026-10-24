from django.http import JsonResponse
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin

from .usage_limits import QuotaError


class QuotaErrorMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        if not isinstance(exception, QuotaError):
            return None
        message = " ".join(exception.messages)
        if (
            "application/json" in request.headers.get("Accept", "")
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or (
                getattr(request.resolver_match, "url_name", "") == "invoice_quick_create_client"
                and getattr(getattr(request, "current_business", None), "vertical", "") == "SERVICE"
            )
        ):
            return JsonResponse({"errors": {"__all__": [message]}}, status=409)
        if getattr(request.resolver_match, "url_name", "") in {
            "public_booking",
            "public_request",
        }:
            return render(
                request,
                "crm/success_fail/public_booking_unavailable.html",
                {"availability_message": message},
                status=409,
            )
        return render(
            request, "businesses/quota_exceeded.html", {"quota_message": message}, status=409
        )
