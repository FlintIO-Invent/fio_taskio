from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from loguru import logger

from apps.accounts.models import SaaSUserProfile, TaskIOUser
from apps.businesses.utils import set_current_business

from .forms import (
    BusinessRegistrationForm,
    CustomerRegistrationForm,
    SaaSBasicInfoForm,
    SaaSInvoiceSettingsForm,
    SaaSWorkspaceSettingsForm,
)

@require_http_methods(["GET", "POST"])
def agent_login(request: HttpRequest) -> HttpResponse:
    """
    Authenticate and log in an internal agent user (Employee or Management).

    This view handles authentication for users with internal roles. It validates
    submitted credentials, checks the user's role, and logs them into the system
    if authorized.

    Args:
        request: Incoming Django HTTP request object. Supports GET (render login)
            and POST (process credentials).

    Returns:
        The rendered login page on GET or failed authentication, or a redirect
        to the appropriate dashboard on successful login.

    Notes:
        - Uses Django's `authenticate()` and `login()`.
        - Uses staff or superuser status as the access gate for the agent portal.
    """
    context: dict[str, Any] = {}

    if request.method == "POST":
        email: str = (request.POST.get("email") or "").strip().lower()
        password: str = request.POST.get("password") or ""

        if not email or not password:
            logger.warning("Agent login attempt with missing email or password.")
            context["error"] = "Please enter both email and password."
            return render(request, "accounts/forms/agent_login.html", context)

        user = authenticate(request, email=email, password=password)

        if user is None:
            logger.warning("Invalid login credentials for email=%s", email)
            context["error"] = "Invalid email or password."
            return render(request, "accounts/forms/agent_login.html", context)

        if user.is_staff or user.is_superuser:
            login(request, user)
            logger.info("User %s logged in successfully.", user.email)
            return redirect("/crm/agent/dashboard/")

        logger.warning("User %s denied agent login - not staff or superuser", user.email)
        context["error"] = "You are not authorized to access this portal."
        return render(request, "accounts/forms/agent_login.html", context)

    return render(request, "accounts/forms/agent_login.html", context)


@require_http_methods(["GET", "POST"])
def customer_registration(request: HttpRequest) -> HttpResponse:
    """
    Register a new SaaS customer account.

    This first onboarding step captures the customer's account details and
    creates a login-ready user record with a hashed password.

    Args:
        request: Incoming Django HTTP request object.

    Returns:
        The rendered registration form or a redirect back to the form after
        successful account creation.
    """
    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)

        if form.is_valid():
            user: TaskIOUser = form.save()
            SaaSUserProfile.get_or_create_for_user(user)
            logger.info("New customer registered with email={}", user.email)
            messages.success(
                request,
                "Your account has been created. We can now use it for customer onboarding.",
            )
            return redirect("customer_registration")

        logger.warning(
            "Customer registration failed for email={}: {}",
            request.POST.get("email", ""),
            form.errors.as_json(),
        )

    else:
        form = CustomerRegistrationForm()

    return render(request, "accounts/forms/customer_registration.html", {"form": form})


@require_http_methods(["GET", "POST"])
def register_business(request: HttpRequest) -> HttpResponse:
    """
    Register a new Clarivo business owner and create the initial workspace.
    """
    if request.method == "POST":
        form = BusinessRegistrationForm(request.POST)

        if form.is_valid():
            user, business, _membership = form.save()

            login(request, user)
            set_current_business(request, business)
            logger.info(
                "New Clarivo business registered with owner_email={} and business_slug={}",
                user.email,
                business.slug,
            )
            messages.success(
                request,
                "Your Clarivo workspace has been created. You can now review your workspace settings.",
            )
            return redirect("saas_profile")

        logger.warning(
            "Business registration failed for email={}: {}",
            request.POST.get("email", ""),
            form.errors.as_json(),
        )
    else:
        form = BusinessRegistrationForm()

    return render(request, "accounts/forms/business_registration.html", {"form": form})


@login_required(login_url="agent_login")
@require_http_methods(["GET", "POST"])
def saas_profile(request: HttpRequest) -> HttpResponse:
    """
    View and update the SaaS account profile, workspace defaults, and invoice settings.
    """
    profile = SaaSUserProfile.get_or_create_for_user(request.user)
    active_section = (request.GET.get("section") or "basic").strip().lower()

    basic_form = SaaSBasicInfoForm(instance=request.user)
    workspace_form = SaaSWorkspaceSettingsForm(instance=profile)
    invoice_form = SaaSInvoiceSettingsForm(instance=profile)

    if request.method == "POST":
        section = (request.POST.get("section") or "basic").strip().lower()
        active_section = section

        if section == "basic":
            basic_form = SaaSBasicInfoForm(request.POST, instance=request.user)
            if basic_form.is_valid():
                basic_form.save()
                messages.success(request, "Basic profile details updated.")
                return redirect(f"{reverse('saas_profile')}?section=basic")

        elif section == "workspace":
            workspace_form = SaaSWorkspaceSettingsForm(request.POST, instance=profile)
            if workspace_form.is_valid():
                workspace_form.save()
                messages.success(request, "Workspace and billing settings updated.")
                return redirect(f"{reverse('saas_profile')}?section=workspace")

        elif section == "invoice":
            invoice_form = SaaSInvoiceSettingsForm(request.POST, instance=profile)
            if invoice_form.is_valid():
                invoice_form.save()
                messages.success(request, "Invoice defaults updated.")
                return redirect(f"{reverse('saas_profile')}?section=invoice")

        logger.warning(
            "SaaS profile update failed for user={} in section={}: basic={}, workspace={}, invoice={}",
            request.user.email,
            section,
            basic_form.errors.as_json(),
            workspace_form.errors.as_json(),
            invoice_form.errors.as_json(),
        )

    context: dict[str, Any] = {
        "active_section": active_section,
        "basic_form": basic_form,
        "workspace_form": workspace_form,
        "invoice_form": invoice_form,
        "profile": profile,
    }
    return render(request, "accounts/main/saas_profile.html", context)
