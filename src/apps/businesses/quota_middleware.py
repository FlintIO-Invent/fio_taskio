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
        ):
            return JsonResponse({"errors": {"__all__": [message]}}, status=409)
        return render(
            request, "businesses/quota_exceeded.html", {"quota_message": message}, status=409
        )
