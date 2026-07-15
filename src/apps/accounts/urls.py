from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordChangeDoneView,
    PasswordResetCompleteView,
    PasswordResetDoneView,
)
from django.urls import path, reverse_lazy

from .forms import (
    MotionmatePasswordChangeForm,
    MotionmatePasswordResetForm,
    MotionmateSetPasswordForm,
)
from .views import (
    MotionmatePasswordChangeView,
    MotionmatePasswordResetConfirmView,
    MotionmatePasswordResetView,
    accept_business_invitation,
    account_logout,
    agent_login,
    business_login,
    customer_registration,
    register_business,
    register_business_beta,
    saas_profile,
)

urlpatterns = [
    path(
        "invitations/accept/<str:token>/",
        accept_business_invitation,
        name="accept_business_invitation",
    ),
    path("login/", business_login, name="business_login"),
    path("logout/", account_logout, name="logout"),
    path(
        "password-reset/",
        MotionmatePasswordResetView.as_view(
            form_class=MotionmatePasswordResetForm,
            template_name="accounts/forms/password_reset_form.html",
            email_template_name="accounts/emails/password_reset_email.txt",
            html_email_template_name="accounts/emails/password_reset_email.html",
            subject_template_name="accounts/emails/password_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        PasswordResetDoneView.as_view(
            template_name="accounts/forms/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        MotionmatePasswordResetConfirmView.as_view(
            form_class=MotionmateSetPasswordForm,
            template_name="accounts/forms/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        PasswordResetCompleteView.as_view(
            template_name="accounts/forms/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    path(
        "password-change/",
        login_required(
            MotionmatePasswordChangeView.as_view(
                form_class=MotionmatePasswordChangeForm,
                template_name="accounts/forms/password_change_form.html",
                success_url=reverse_lazy("password_change_done"),
            ),
            login_url="business_login",
        ),
        name="password_change",
    ),
    path(
        "password-change/done/",
        login_required(
            PasswordChangeDoneView.as_view(
                template_name="accounts/forms/password_change_done.html",
            ),
            login_url="business_login",
        ),
        name="password_change_done",
    ),
    path("agent_login", agent_login, name="agent_login"),
    path("customer_registration", customer_registration, name="customer_registration"),
    path("register-business/", register_business, name="register_business"),
    path(
        "register-business/beta/<str:token>/",
        register_business_beta,
        name="register_business_beta",
    ),
    path("profile", saas_profile, name="saas_profile"),
]
