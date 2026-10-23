import logging

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_safe

from apps.businesses.models import Business, BusinessUser
from apps.businesses.stripe_checkout import StripeCheckoutAlreadyCompleted, StripeCheckoutError
from apps.businesses.stripe_config import StripeConfigurationError
from apps.businesses.utils import (
    business_module_required,
    business_role_required,
    can_use_module,
    can_view_module,
    set_current_business,
)
from apps.crm.forms import QuickClientForm

from .billing import checkout_for_application
from .enrollment import enroll_application, enroll_new_pilot_application, inspect_enrollment_link
from .forms import (
    EnrollmentForm,
    LogisticsSignupForm,
    ParcelEditForm,
    ParcelEventForm,
    ParcelFilterForm,
    ParcelMetadataForm,
    ParcelRegistrationForm,
)
from .location_access import can_operate_record, lock_actor_membership, membership_for
from .models import LogisticsApplication, ParcelEvent
from .parcel_policy import PARCEL_MANAGE_ROLES, PARCEL_VIEW_ROLES
from .parcel_services import (
    edit_parcel,
    parcels_for_business,
    record_parcel_event,
    register_and_receive_parcel,
    register_parcel,
    require_parcel_intake_site,
)
from .shipment_policy import ASSIGNABLE_PARCEL_STATUSES

logger = logging.getLogger(__name__)


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
        # Only our safe wrapper message/code and local identifiers. Never log the
        # chained provider exception, request data, keys or provider response.
        logger.warning(
            "Logistics checkout rejected application=%s business=%s reason=%s: %s",
            application.pk,
            application.business_id,
            exc.code,
            str(exc),
        )
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
    ).select_related("client", "shipment")
    filters = ParcelFilterForm(request.GET, business=request.current_business)
    if filters.is_valid():
        query = filters.cleaned_data["q"]
        if query:
            parcels = parcels.filter(
                Q(tracking_code__icontains=query)
                | Q(internal_reference__icontains=query)
                | Q(origin__icontains=query)
                | Q(destination__icontains=query)
                | Q(package_description__icontains=query)
                | Q(client__first_name__icontains=query)
                | Q(client__last_name__icontains=query)
                | Q(client__email__icontains=query)
            )
        if filters.cleaned_data["status"]:
            parcels = parcels.filter(current_status=filters.cleaned_data["status"])
        if filters.cleaned_data["client"]:
            parcels = parcels.filter(client=filters.cleaned_data["client"])
    else:
        parcels = parcels.none()
    pagination_query = request.GET.copy()
    pagination_query.pop("page", None)
    from .workflow_summary import resolve_parcel_workflows

    page = Paginator(parcels, 50).get_page(request.GET.get("page"))
    parcels_on_page = list(page.object_list)
    summaries = resolve_parcel_workflows(
        business=request.current_business,
        actor=request.user,
        parcel_ids=[parcel.pk for parcel in parcels_on_page],
        include_history=False,
    ).by_parcel_id
    for parcel in parcels_on_page:
        parcel.workflow_summary = summaries[parcel.pk]
    return render(
        request,
        "logistics/parcel_list.html",
        {
            "page_obj": page,
            "filter_form": filters,
            "visible_shipment_ids": _visible_shipment_ids(request),
            "filters_active": any(request.GET.get(key) for key in ("q", "status", "client")),
            "pagination_query": pagination_query.urlencode(),
        },
    )


@business_module_required("parcels", access="read")
@business_module_required("tracking", access="read")
@business_role_required(*PARCEL_VIEW_ROLES)
@require_safe
def parcel_detail(request, parcel_id):
    parcel = get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user).select_related(
            "client", "created_by"
        ),
        pk=parcel_id,
    )
    events = list(
        ParcelEvent.objects.filter(business=request.current_business, parcel=parcel)
        .select_related("actor")
        .order_by("timestamp", "pk")
    )
    from .billing_views import billing_context
    from .shipment_services import shipments_for_business
    from .workflow_summary import resolve_parcel_workflow

    workflow = resolve_parcel_workflow(
        business=request.current_business, actor=request.user, parcel=parcel
    )

    metadata_form = ParcelMetadataForm(
        instance=parcel, business=request.current_business, actor=request.user
    )
    detail_sections = []
    for section in metadata_form.sections:
        fields = []
        for field in section["fields"]:
            value = getattr(parcel, field.name)
            fields.append(
                {
                    "label": field.label,
                    "value": ("Yes" if value else "No") if isinstance(value, bool) else value,
                }
            )
        detail_sections.append({"title": section["title"], "fields": fields})
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
        {
            **(
                billing_context(request, parcel)
                if workflow.financial["visibility"] == "DETAILED"
                else {}
            ),
            "workflow_summary": workflow,
            "parcel": parcel,
            "can_operate_parcel": can_operate_record(
                parcel, business=request.current_business, actor=request.user
            ),
            "events": events,
            "recent_events": list(reversed(events))[:3],
            "shipment": shipment,
            "detail_sections": detail_sections,
            "latest_location": next((event for event in reversed(events) if event.location), None),
            "latest_status_event": next(
                (event for event in reversed(events) if event.status), None
            ),
            "can_view_client": can_view_module(request.current_business, "crm"),
            "parcel_can_be_assigned": parcel.shipment_id is None
            and parcel.current_status in ASSIGNABLE_PARCEL_STATUSES,
            "cancellation_can_manage": membership_for(request.current_business, request.user).role
            in ("owner", "admin", "accountant"),
        },
    )


@business_module_required("parcels")
@business_module_required("tracking")
@business_role_required(*PARCEL_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def parcel_edit(request, parcel_id):
    parcel = get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user).select_related(
            "client"
        ),
        pk=parcel_id,
    )
    form = ParcelEditForm(
        request.POST if request.method == "POST" else None,
        instance=parcel,
        business=request.current_business,
        actor=request.user,
        initial={"expected_updated_at": parcel.updated_at.isoformat()},
    )
    if request.method == "POST" and form.is_valid():
        try:
            edit_parcel(
                business=request.current_business,
                parcel=parcel,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("logistics_parcel_detail", parcel_id=parcel.pk)
    return render(
        request,
        "logistics/parcel_form.html",
        {
            "form": form,
            "parcel": parcel,
            "title": "Edit parcel",
            "editing_metadata": True,
            "can_prefill_shipping": can_view_module(request.current_business, "crm"),
        },
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
        actor=request.user,
        initial={"idempotency_key": uuid.uuid4()},
    )
    if request.method == "GET" and request.GET.get("client"):
        try:
            form.initial["client"] = form.fields["client"].to_python(request.GET["client"])
        except ValidationError as exc:
            raise Http404("Client is unavailable in this workspace.") from exc
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                business = Business.objects.select_for_update().get(pk=request.current_business.pk)
                lock_actor_membership(business, request.user)
                try:
                    intake_site = require_parcel_intake_site(business=business, actor=request.user)
                except PermissionDenied:
                    intake_site = None
                # Choose intake under the same locks as registration, so a work-site
                # change cannot silently turn physical hub receipt into pre-advice.
                receive_at_hub = bool(intake_site) or request.POST.get("save_and_receive") == "1"
                create = register_and_receive_parcel if receive_at_hub else register_parcel
                parcel = create(business=business, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                (
                    "Parcel registered and received. Preview, print or download its shipping label below."
                    if receive_at_hub
                    else "Parcel registered. Preview, print or download its shipping label below."
                ),
            )
            if request.POST.get("continue_registration") == "1":
                return redirect("logistics_parcel_registration", parcel_id=parcel.pk)
            return redirect("logistics_parcel_detail", parcel_id=parcel.pk)
    try:
        intake_site = require_parcel_intake_site(
            business=request.current_business, actor=request.user
        )
    except PermissionDenied:
        intake_site = None
    return render(
        request,
        "logistics/parcel_form.html",
        {
            "form": form,
            "title": "Register parcel",
            "intake_site": intake_site,
            "quick_client_form": QuickClientForm(prefix="new_client"),
            "has_clients": form.fields["client"].queryset.exists(),
            "can_add_client": can_use_module(request.current_business, "crm"),
            "can_prefill_shipping": can_view_module(request.current_business, "crm"),
        },
    )


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
        actor=request.user,
        initial={"idempotency_key": uuid.uuid4(), "expected_status": parcel.current_status},
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                current = Business.objects.select_for_update().get(pk=request.current_business.pk)
                lock_actor_membership(current, request.user)
                status = form.cleaned_data["status"] or None
                replay = ParcelEvent.objects.filter(
                    business=current, idempotency_key=form.cleaned_data["idempotency_key"]
                ).exists()
                if status in ("IN_TRANSIT", "DELIVERED") and not replay:
                    from .workflow_summary import resolve_parcel_workflow

                    workflow = resolve_parcel_workflow(
                        business=current, actor=request.user, parcel=parcel
                    )
                    # The event service validates the submitted site/role and any
                    # explicit audited route override. Summary capabilities use
                    # the default route; an override never relaxes clearance.
                    if not (
                        workflow.financial["clearance"]["cleared"]
                        and workflow.operational["evidence_complete"]
                    ):
                        raise ValidationError(
                            "Current workflow evidence, financial clearance or site access does not permit this action."
                        )
                record_parcel_event(
                    business=current,
                    parcel=parcel,
                    actor=request.user,
                    **{**form.cleaned_data, "status": status},
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


def _visible_shipment_ids(request):
    from .shipment_services import shipments_for_business

    try:
        return set(
            shipments_for_business(
                business=request.current_business, actor=request.user
            ).values_list("pk", flat=True)
        )
    except PermissionDenied:
        return set()
