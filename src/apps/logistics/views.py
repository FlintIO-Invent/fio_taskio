from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_safe

from apps.businesses.models import BusinessUser
from apps.businesses.stripe_checkout import StripeCheckoutAlreadyCompleted, StripeCheckoutError
from apps.businesses.stripe_config import StripeConfigurationError
from apps.businesses.utils import (
    business_module_required,
    business_role_required,
    set_current_business,
)

from .billing import checkout_for_application
from .enrollment import enroll_application, enroll_new_pilot_application, inspect_enrollment_link
from .forms import EnrollmentForm, LogisticsSignupForm, ParcelEventForm, ParcelRegistrationForm
from .models import LogisticsApplication, ParcelEvent
from .parcel_policy import PARCEL_MANAGE_ROLES, PARCEL_VIEW_ROLES
from .parcel_services import parcels_for_business, record_parcel_event, register_parcel


@never_cache
@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "POST"])
def application_create(request):
    form = LogisticsSignupForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        # A session reference allows a retry to reuse its own unchanged application.
        # It stores no credentials and never authorizes access by email alone.
        previous_id = request.session.get("logistics_signup_application_id")
        application = (
            LogisticsApplication.objects.filter(pk=previous_id).first() if previous_id else None
        )
        if application is None or application.material_inputs() != form.instance.material_inputs():
            application = form.save()
            request.session["logistics_signup_application_id"] = str(application.pk)
        if application.converted_at is not None:
            if (
                request.user.is_authenticated
                and request.user.is_active
                and application.enrolled_user_id == request.user.pk
                and application.business_id is not None
                and BusinessUser.objects.filter(
                    user=request.user,
                    business=application.business,
                    is_active=True,
                    business__is_active=True,
                    role=BusinessUser.Role.OWNER,
                ).exists()
            ):
                set_current_business(request, application.business)
                return redirect("agent_dashboard")
        elif (
            form.new_account_password and application.status == LogisticsApplication.Status.APPROVED
        ):
            try:
                result = enroll_new_pilot_application(
                    application.pk, password=form.new_account_password
                )
            except (ValidationError, PermissionDenied):
                # Generic recovery for identity races, conflicts or unavailable offerings.
                # The approved application remains available to secure reviewer enrollment.
                pass
            else:
                login(request, result.user)
                set_current_business(request, result.business)
                request.session["logistics_signup_application_id"] = str(application.pk)
                return redirect("agent_dashboard")
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


@business_module_required("parcels", access="read")
@business_module_required("tracking", access="read")
@business_role_required(*PARCEL_VIEW_ROLES)
@require_safe
def parcel_list(request):
    parcels = parcels_for_business(
        business=request.current_business, actor=request.user
    ).select_related("client")
    return render(
        request,
        "logistics/parcel_list.html",
        {
            "page_obj": Paginator(parcels, 50).get_page(request.GET.get("page")),
        },
    )


@business_module_required("parcels", access="read")
@business_module_required("tracking", access="read")
@business_role_required(*PARCEL_VIEW_ROLES)
@require_safe
def parcel_detail(request, parcel_id):
    parcel = get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user).select_related(
            "client"
        ),
        pk=parcel_id,
    )
    events = (
        ParcelEvent.objects.filter(business=request.current_business, parcel=parcel)
        .select_related("actor")
        .order_by("timestamp", "pk")
    )
    from .shipment_services import shipments_for_business

    shipment = None
    if parcel.shipment_id:
        try:
            shipment = (
                shipments_for_business(business=request.current_business, actor=request.user)
                .filter(pk=parcel.shipment_id)
                .first()
            )
        except PermissionDenied:
            pass
    return render(
        request,
        "logistics/parcel_detail.html",
        {"parcel": parcel, "events": events, "shipment": shipment},
    )


@business_module_required("parcels")
@business_module_required("tracking")
@business_role_required(*PARCEL_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def parcel_register(request):
    import uuid

    form = ParcelRegistrationForm(
        request.POST if request.method == "POST" else None,
        business=request.current_business,
        initial={"idempotency_key": uuid.uuid4()},
    )
    if request.method == "POST" and form.is_valid():
        try:
            parcel = register_parcel(
                business=request.current_business, actor=request.user, **form.cleaned_data
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("logistics_parcel_detail", parcel_id=parcel.pk)
    return render(request, "logistics/parcel_form.html", {"form": form, "title": "Register parcel"})


@business_module_required("parcels")
@business_module_required("tracking")
@business_role_required(*PARCEL_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def parcel_update(request, parcel_id):
    import uuid

    parcel = get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user), pk=parcel_id
    )
    form = ParcelEventForm(
        request.POST if request.method == "POST" else None,
        parcel=parcel,
        initial={"idempotency_key": uuid.uuid4(), "expected_status": parcel.current_status},
    )
    if request.method == "POST" and form.is_valid():
        try:
            record_parcel_event(
                business=request.current_business,
                parcel=parcel,
                actor=request.user,
                **{**form.cleaned_data, "status": form.cleaned_data["status"] or None},
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("logistics_parcel_detail", parcel_id=parcel.pk)
    return render(
        request,
        "logistics/parcel_form.html",
        {"form": form, "parcel": parcel, "title": "Record parcel update"},
    )
