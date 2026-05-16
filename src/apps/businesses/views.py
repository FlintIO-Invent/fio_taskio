from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import BusinessSettingsForm, BusinessSubscriptionPlanForm
from .models import BusinessUser, ClarivoPlan
from .utils import (
    assign_business_subscription_plan,
    business_role_required,
    get_business_subscription,
    get_current_business,
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
    }
    return render(request, "businesses/settings.html", context)


@business_role_required(BusinessUser.Role.OWNER)
@require_http_methods(["GET", "POST"])
def business_subscription(request: HttpRequest) -> HttpResponse:
    business = request.current_business
    membership = request.current_business_membership
    subscription = get_business_subscription(business)
    available_plans = ClarivoPlan.objects.filter(is_active=True).order_by("created_at", "pk")

    if request.method == "POST":
        form = BusinessSubscriptionPlanForm(request.POST, plans=available_plans)
        if form.is_valid():
            selected_plan = form.cleaned_data["plan"]

            if subscription is not None and subscription.plan_id == selected_plan.id:
                messages.info(request, f"{selected_plan.name} is already the active plan for this workspace.")
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
            return redirect("business_subscription")
    else:
        form = BusinessSubscriptionPlanForm(plans=available_plans)

    context = {
        "business": business,
        "membership": membership,
        "subscription": subscription,
        "available_plans": available_plans,
        "plan_form": form,
    }
    return render(request, "businesses/subscription.html", context)
