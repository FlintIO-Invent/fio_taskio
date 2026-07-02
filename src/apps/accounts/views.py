from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetView,
)
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from loguru import logger

from apps.accounts.models import SaaSUserProfile, TaskIOUser
from apps.businesses.models import BusinessInvitation, BusinessUser
from apps.businesses.utils import (
    MULTI_WORKSPACE_EMAIL_MESSAGE,
    accept_business_invitation_for_user,
    expire_business_invitation_if_needed,
    get_current_business,
    get_other_active_business_membership_for_user,
    set_current_business,
)
from apps.notifications.emails import (
    send_password_change_confirmation_email,
    send_password_reset_complete_email,
)

from .forms import (
    BusinessLoginForm,
    BusinessRegistrationForm,
    InvitationAcceptanceSignupForm,
    InvitationExistingUserLoginForm,
    SaaSBasicInfoForm,
    SaaSInvoiceSettingsForm,
    SaaSWorkspaceSettingsForm,
)


class MotionmatePasswordResetView(PasswordResetView):
    def form_valid(self, form):
        original_context = self.extra_email_context or {}
        public_base_url = (
            getattr(settings, "MOTIONMATE_PUBLIC_BASE_URL", "") or ""
        ).strip().rstrip("/")
        self.extra_email_context = {
            **original_context,
            "motionmate_public_base_url": public_base_url,
        }
        return super().form_valid(form)


class MotionmatePasswordResetConfirmView(PasswordResetConfirmView):
    def form_valid(self, form):
        user = form.user
        response = super().form_valid(form)
        send_password_reset_complete_email(user)
        return response


class MotionmatePasswordChangeView(PasswordChangeView):
    def form_valid(self, form):
        user = form.user
        response = super().form_valid(form)
        send_password_change_confirmation_email(user)
        return response


@require_http_methods(["GET", "POST"])
def business_login(request: HttpRequest) -> HttpResponse:
    """
    Authenticate and log in a Motionmate business user with an active workspace membership.
    """
    if request.user.is_authenticated and get_current_business(request) is not None:
        return redirect("agent_dashboard")

    if request.method == "POST":
        form = BusinessLoginForm(request.POST)

        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]
            user_record = TaskIOUser.objects.filter(email__iexact=email).first()

            if user_record is not None and not user_record.is_active:
                logger.warning("Inactive business login attempt for email=%s", email)
                form.add_error(None, "This account is inactive. Please contact support.")
            else:
                user = authenticate(request, email=email, password=password)

                if user is None:
                    logger.warning("Invalid business login credentials for email=%s", email)
                    form.add_error(None, "Invalid email or password.")
                else:
                    membership = (
                        BusinessUser.objects.filter(
                            user=user,
                            is_active=True,
                            business__is_active=True,
                        )
                        .select_related("business")
                        .order_by("created_at", "pk")
                        .first()
                    )

                    if membership is None:
                        logger.warning(
                            "User %s denied business login - no active business membership",
                            user.email,
                        )
                        form.add_error(
                            None,
                            "This account does not have an active Motionmate workspace yet.",
                        )
                    else:
                        login(request, user)
                        set_current_business(request, membership.business)
                        logger.info(
                            "Business user %s logged in successfully for business %s.",
                            user.email,
                            membership.business.slug,
                        )
                        return redirect("agent_dashboard")
    else:
        form = BusinessLoginForm()

    return render(request, "accounts/forms/business_login.html", {"form": form})


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
    Redirect legacy standalone customer signup traffic to business workspace signup.
    """
    messages.info(
        request,
        "Standalone customer signup is now legacy. Start by creating a Motionmate workspace instead.",
    )
    return redirect("register_business")


@require_http_methods(["GET", "POST"])
def register_business(request: HttpRequest) -> HttpResponse:
    """
    Register a new Motionmate business owner and create the initial workspace.
    """
    if request.method == "POST":
        form = BusinessRegistrationForm(request.POST)

        if form.is_valid():
            user, business, _membership, subscription = form.save()

            login(request, user)
            set_current_business(request, business)
            logger.info(
                "New Motionmate business registered with owner_email={} and business_slug={}",
                user.email,
                business.slug,
            )
            if subscription is not None:
                messages.success(
                    request,
                    "Your Motionmate workspace has been created with a 14-day trial. You can now review your workspace settings.",
                )
            else:
                logger.warning(
                    "Business {} created without a default trial subscription because no active Motionmate plan is configured.",
                    business.slug,
                )
                messages.success(
                    request,
                    "Your Motionmate workspace has been created. Subscription setup is pending because no active trial plan is configured yet.",
                )
            return redirect("business_settings")

        logger.warning(
            "Business registration failed for email={}: {}",
            request.POST.get("email", ""),
            form.errors.as_json(),
        )
    else:
        form = BusinessRegistrationForm()

    return render(request, "accounts/forms/business_registration.html", {"form": form})


@require_http_methods(["GET", "POST"])
def accept_business_invitation(request: HttpRequest, token: str) -> HttpResponse:
    invitation = get_object_or_404(
        BusinessInvitation.objects.select_related("business", "invited_by", "accepted_by"),
        token=token,
    )
    existing_user = TaskIOUser.objects.filter(email__iexact=invitation.email).first()

    if expire_business_invitation_if_needed(invitation):
        messages.error(request, "This invitation has expired. Please ask your workspace owner for a new invite.")
    elif invitation.status == BusinessInvitation.Status.ACCEPTED:
        messages.info(request, "This invitation has already been accepted.")
    elif invitation.status == BusinessInvitation.Status.CANCELLED:
        messages.error(request, "This invitation has been cancelled.")

    invitation_is_available = invitation.status == BusinessInvitation.Status.PENDING
    wrong_authenticated_user = (
        request.user.is_authenticated
        and request.user.email.lower() != invitation.email.lower()
    )
    existing_workspace_membership = None
    if existing_user is not None:
        existing_workspace_membership = BusinessUser.objects.filter(
            user=existing_user,
            business=invitation.business,
        ).first()

    multi_workspace_membership_conflict = None
    if existing_user is not None and not (
        existing_workspace_membership is not None and existing_workspace_membership.is_active
    ):
        multi_workspace_membership_conflict = get_other_active_business_membership_for_user(
            existing_user,
            invitation.business,
        )

    login_form = None
    signup_form = None

    if invitation_is_available and request.method == "POST":
        if wrong_authenticated_user:
            messages.error(
                request,
                "You are signed in as a different user. Please sign out and accept this invite with the invited email address.",
            )
        elif multi_workspace_membership_conflict is not None:
            messages.error(request, MULTI_WORKSPACE_EMAIL_MESSAGE)
        elif existing_user is not None:
            if not existing_user.is_active:
                messages.error(
                    request,
                    "This invited account is inactive. Please contact support or your workspace owner.",
                )
            elif request.user.is_authenticated:
                try:
                    membership, created, already_member = accept_business_invitation_for_user(
                        invitation,
                        request.user,
                    )
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect("accept_business_invitation", token=invitation.token)
                SaaSUserProfile.get_or_create_for_user(request.user)
                set_current_business(request, membership.business)
                if already_member:
                    messages.info(request, "You already belong to this workspace.")
                elif created:
                    messages.success(request, "You have joined the workspace successfully.")
                else:
                    messages.success(request, "Your workspace access has been restored successfully.")
                return redirect("agent_dashboard")
            else:
                login_form = InvitationExistingUserLoginForm(request.POST)
                if login_form.is_valid():
                    user = authenticate(
                        request,
                        email=invitation.email,
                        password=login_form.cleaned_data["password"],
                    )
                    if user is None:
                        login_form.add_error("password", "Invalid password.")
                    elif not user.is_active:
                        login_form.add_error(None, "This account is inactive. Please contact support.")
                    else:
                        try:
                            membership, created, already_member = accept_business_invitation_for_user(
                                invitation,
                                user,
                            )
                        except ValueError as exc:
                            messages.error(request, str(exc))
                            return redirect("accept_business_invitation", token=invitation.token)
                        login(request, user)
                        SaaSUserProfile.get_or_create_for_user(user)
                        set_current_business(request, membership.business)
                        if already_member:
                            messages.info(request, "You already belong to this workspace.")
                        elif created:
                            messages.success(request, "You have joined the workspace successfully.")
                        else:
                            messages.success(request, "Your workspace access has been restored successfully.")
                        return redirect("agent_dashboard")
        else:
            signup_form = InvitationAcceptanceSignupForm(request.POST)
            if signup_form.is_valid():
                try:
                    with transaction.atomic():
                        user = signup_form.save(invitation)
                        membership, _created, already_member = accept_business_invitation_for_user(
                            invitation,
                            user,
                        )
                        SaaSUserProfile.get_or_create_for_user(user)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect("accept_business_invitation", token=invitation.token)
                login(request, user)
                set_current_business(request, membership.business)
                if already_member:
                    messages.info(request, "You already belong to this workspace.")
                else:
                    messages.success(request, "Your account has been created and joined to the workspace.")
                return redirect("agent_dashboard")

    if login_form is None and invitation_is_available and existing_user is not None and not request.user.is_authenticated:
        login_form = InvitationExistingUserLoginForm()

    if signup_form is None and invitation_is_available and existing_user is None:
        signup_form = InvitationAcceptanceSignupForm()

    context = {
        "invitation": invitation,
        "existing_user": existing_user,
        "invitation_is_available": invitation_is_available,
        "wrong_authenticated_user": wrong_authenticated_user,
        "multi_workspace_membership_conflict": multi_workspace_membership_conflict,
        "login_form": login_form,
        "signup_form": signup_form,
    }
    return render(request, "accounts/forms/accept_business_invitation.html", context)


@require_http_methods(["GET", "POST"])
def account_logout(request: HttpRequest) -> HttpResponse:
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("business_login")


@login_required(login_url="business_login")
@require_http_methods(["GET", "POST"])
def saas_profile(request: HttpRequest) -> HttpResponse:
    """
    View and update the account profile plus legacy compatibility settings.
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
                messages.success(request, "Legacy workspace contact settings updated.")
                return redirect(f"{reverse('saas_profile')}?section=workspace")

        elif section == "invoice":
            invoice_form = SaaSInvoiceSettingsForm(request.POST, instance=profile)
            if invoice_form.is_valid():
                invoice_form.save()
                messages.success(request, "Legacy invoice preferences updated.")
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
