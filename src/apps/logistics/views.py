from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from apps.businesses.stripe_checkout import StripeCheckoutAlreadyCompleted, StripeCheckoutError
from apps.businesses.stripe_config import StripeConfigurationError
from apps.businesses.utils import set_current_business

from .billing import checkout_for_application
from .enrollment import enroll_application, inspect_enrollment_link
from .forms import EnrollmentForm, LogisticsApplicationForm
from .models import LogisticsApplication


@require_http_methods(["GET", "POST"])
def application_create(request):
    form = LogisticsApplicationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        # Identical public response for all decisions and relationship signals.
        return redirect("logistics_application_received")
    return render(request, "logistics/application_form.html", {"form": form})


@require_safe
def application_received(request):
    return render(request, "logistics/application_received.html")


@never_cache
@require_http_methods(["GET", "POST"])
def application_enroll(request, token):
    try:
        application = inspect_enrollment_link(token)
    except ValidationError:
        response = render(request, "logistics/enrollment_unavailable.html", status=400)
    else:
        form = EnrollmentForm(
            request.POST if request.method == "POST" else None,
            application=application,
            request=request,
        )
        if request.method == "POST" and form.is_valid():
            try:
                result = enroll_application(
                    token,
                    authenticated_user=form.authenticated_user,
                    password=form.cleaned_data.get("password1"),
                )
            except (ValidationError, PermissionDenied) as exc:
                form.add_error(None, exc.messages if isinstance(exc, ValidationError) else str(exc))
            else:
                login(request, result.user)
                response = redirect("logistics_enrollment_complete")
                response["Referrer-Policy"] = "no-referrer"
                return response
        response = render(request, "logistics/enrollment.html", {"form": form})
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@require_safe
def enrollment_complete(request):
    application = None
    if request.user.is_authenticated:
        application = LogisticsApplication.objects.filter(
            enrolled_user=request.user,
            business__is_active=True,
            converted_at__isnull=False,
        ).first()
    return render(request, "logistics/enrollment_complete.html", {"application": application})


@never_cache
@login_required(login_url="business_login")
@require_http_methods(["POST"])
def application_checkout(request, application_id):
    application = LogisticsApplication.objects.filter(
        pk=application_id,
        enrolled_user=request.user,
        converted_at__isnull=False,
    ).first()
    if application is None:
        raise PermissionDenied
    if request.GET or set(request.POST) - {"csrfmiddlewaretoken"}:
        return render(
            request,
            "logistics/enrollment_complete.html",
            {
                "application": application,
                "checkout_error": "Checkout choices are fixed by your approved enrollment.",
            },
            status=400,
        )
    try:
        checkout_url = checkout_for_application(application.pk, request=request, user=request.user)
    except StripeCheckoutAlreadyCompleted:
        set_current_business(request, application.business)
        return redirect("billing_checkout_success")
    except (StripeConfigurationError, StripeCheckoutError) as exc:
        return render(
            request,
            "logistics/enrollment_complete.html",
            {
                "application": application,
                "checkout_error": str(exc),
            },
            status=503 if isinstance(exc, StripeConfigurationError) else 409,
        )
    set_current_business(request, application.business)
    return redirect(checkout_url)
