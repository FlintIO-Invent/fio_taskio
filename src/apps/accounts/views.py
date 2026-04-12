from apps.accounts.models import TaskIOUser
from .forms import CustomerForm
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpRequest, HttpResponse
from typing import Any, Optional
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from loguru import logger


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
        - Assumes a custom user model with a `role` field.
        - Only users with roles 'EMPLOYEE' or 'MANAGEMENT' may log in here.
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


@login_required
@require_http_methods(["GET", "POST"])
def company_update(request: HttpRequest, company_id: int) -> HttpResponse:
    company = get_object_or_404(CompanyProfile, pk=company_id)

    if request.method == "POST":
        form = CompanyProfileForm(request.POST, instance=company)
        if form.is_valid():
            form.save()
            return redirect("company_detail", company_id=company.id)
    else:
        form = CompanyProfileForm(instance=company)

    context: dict[str, Any] = {"form": form, "company": company, "mode": "Edit"}
    return render(request, "accounts/main/company_form.html", context)

