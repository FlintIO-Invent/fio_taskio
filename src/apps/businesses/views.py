from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .utils import get_current_business


@login_required(login_url="agent_login")
@require_http_methods(["GET"])
def business_setup(request: HttpRequest) -> HttpResponse:
    current_business = get_current_business(request)
    if current_business is not None:
        return redirect("saas_profile")

    return render(request, "businesses/setup_required.html", {})
