from apps.accounts.models import TaskIOUser
from .forms import CustomerForm
from django.shortcuts import render
from django.shortcuts import redirect
from django.http import HttpRequest, HttpResponse
from typing import Any, Optional
from django.views.decorators.http import require_http_methods
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

        incorporation_status: Optional[str] = getattr(user, "incorporation_status", None)

        if incorporation_status == "CORPORATED":
            login(request, user)
            logger.info("User %s logged in successfully as MANAGEMENT.", user.email)
            return redirect("/crm/agent/dashboard/")

        logger.warning("User %s denied agent login due to incorporation_status=%s", user.email, incorporation_status)
        context["error"] = "You are not authorized to access this portal."
        return render(request, "accounts/forms/agent_login.html", context)

    return render(request, "accounts/forms/agent_login.html", context)



# def customer_view(request: HttpRequest) -> HttpResponse:
#     """
#     Display a list of customers ordered by most recent creation date.

#     Args:
#         request: Incoming HTTP request.

#     Returns:
#         Rendered customer list page.
#     """
#     customer_list = (
#         TaskIOUser.objects
#         .only("first_name", "last_name", "email", "created_at")
#         .order_by("-created_at")
#     )

#     context: dict[str, Any] = {"customer_list": customer_list}
#     return render(request, "main/customer_view.html", context)


# @require_http_methods(["GET", "POST"])
# def customer_registration(request: HttpRequest) -> HttpResponse:
#     """
#     Render and handle the customer registration form.

#     - GET: Show empty form.
#     - POST: Validate and save, then redirect to customer list.

#     Args:
#         request: Incoming HTTP request.

#     Returns:
#         Rendered registration page or redirect on success.
#     """
#     if request.method == "POST":
#         form = CustomerForm(request.POST)
#         if form.is_valid():
#             form.save()
#             return redirect("customer_view")
#     else:
#         form = CustomerForm()

#     context: dict[str, Any] = {"customer_form": form}
#     return render(request, "main/customer_registration.html", context)



