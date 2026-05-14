from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import BusinessSettingsForm
from .models import BusinessUser
from .utils import business_role_required, get_current_business


@login_required(login_url="agent_login")
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
    }
    return render(request, "businesses/settings.html", context)
