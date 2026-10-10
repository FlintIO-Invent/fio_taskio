import csv
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.businesses.utils import business_module_required, business_role_required, can_use_module

from .billing_views import billing_context
from .location_access import can_operate_record
from .models import Shipment
from .parcel_services import parcels_for_business
from .shipment_forms import (
    ShipmentAssignmentForm,
    ShipmentFilterForm,
    ShipmentForm,
    ShipmentStatusForm,
    ShipmentWriteForm,
)
from .shipment_policy import (
    ASSIGNABLE_SHIPMENT_STATUSES,
    SHIPMENT_MANAGE_ROLES,
    SHIPMENT_VIEW_ROLES,
)
from .shipment_references import SHIPMENT_REFERENCE_FIELDS
from .shipment_services import (
    SHIPMENT_INPUT_FIELDS,
    assign_parcel,
    change_shipment_status,
    create_shipment,
    generate_manifest,
    remove_parcel,
    shipments_for_business,
    update_shipment,
)


def _get_shipment(request, shipment_id):
    return get_object_or_404(
        shipments_for_business(business=request.current_business, actor=request.user),
        pk=shipment_id,
    )


def _can_assign_parcels(request):
    return all(
        can_use_module(request.current_business, module) for module in ("parcels", "tracking")
    )


def _initial_parcel(request):
    if request.method != "GET" or not request.GET.get("parcel"):
        return None
    if not _can_assign_parcels(request):
        raise Http404("Parcel assignment is unavailable in this workspace.")
    try:
        return (
            ShipmentAssignmentForm(business=request.current_business, actor=request.user)
            .fields["parcel"]
            .to_python(request.GET["parcel"])
        )
    except ValidationError as exc:
        raise Http404("Parcel is unavailable for assignment in this workspace.") from exc


def _detail(request, shipment, *, error=None, assignment_form=None, status_form=None):
    parcels = (
        parcels_for_business(business=request.current_business, actor=request.user)
        .filter(shipment=shipment)
        .select_related("client")
        .order_by("tracking_code")
    )
    for parcel in parcels:
        parcel.shipment_remove_form = ShipmentWriteForm(shipment=shipment)
    if assignment_form is None:
        assignment_form = ShipmentAssignmentForm(
            business=request.current_business,
            actor=request.user,
            shipment=shipment,
            initial={"parcel": _initial_parcel(request)},
        )
    return render(
        request,
        "logistics/shipment_detail.html",
        {
            **billing_context(request, shipment),
            "shipment": shipment,
            "operation_history": list(reversed(shipment.operation_history[-10:])),
            "can_operate_shipment": can_operate_record(
                shipment, business=request.current_business, actor=request.user
            ),
            "parcels": parcels,
            "status_actions": ShipmentStatusForm(shipment=shipment, actor=request.user)
            .fields["status"]
            .choices,
            "error": error,
            "can_assign": shipment.status in ASSIGNABLE_SHIPMENT_STATUSES,
            "assignment_form": assignment_form,
            "has_eligible_parcels": (
                assignment_form.fields["parcel"].queryset.exists()
                if _can_assign_parcels(request)
                else False
            ),
            "status_form": (
                status_form
                if status_form is not None
                else ShipmentStatusForm(shipment=shipment, actor=request.user)
            ),
        },
        status=400 if error else 200,
    )


@never_cache
@business_module_required("shipments", access="read")
@business_role_required(*SHIPMENT_VIEW_ROLES)
@require_safe
def shipment_list(request):
    shipments = (
        shipments_for_business(business=request.current_business, actor=request.user)
        .annotate(
            parcel_count=Count(
                "parcels",
                filter=Q(
                    parcels__pk__in=parcels_for_business(
                        business=request.current_business, actor=request.user
                    ).values("pk"),
                    parcels__business=request.current_business,
                    parcels__client__business=request.current_business,
                ),
            )
        )
        .order_by("-created_at", "-pk")
    )
    parcel = _initial_parcel(request)
    if parcel:
        shipments = shipments.filter(status__in=ASSIGNABLE_SHIPMENT_STATUSES)
    filter_form = ShipmentFilterForm(request.GET)
    if filter_form.is_valid():
        mode = filter_form.cleaned_data["transport_mode"]
        if mode:
            shipments = shipments.filter(transport_mode=None if mode == "UNKNOWN" else mode)
    else:
        shipments = shipments.none()
    pagination_query = request.GET.copy()
    pagination_query.pop("page", None)
    return render(
        request,
        "logistics/shipment_list.html",
        {
            "page_obj": Paginator(shipments, 50).get_page(request.GET.get("page")),
            "assignment_parcel": parcel,
            "pagination_query": pagination_query.urlencode(),
            "filter_form": filter_form,
        },
    )


@never_cache
@business_module_required("shipments", access="read")
@business_role_required(*SHIPMENT_VIEW_ROLES)
@require_safe
def shipment_detail(request, shipment_id):
    return _detail(request, _get_shipment(request, shipment_id))


@never_cache
@business_module_required("shipments")
@business_role_required(*SHIPMENT_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def shipment_create(request):
    parcel = _initial_parcel(request)
    initial = (
        {"parcel": parcel, "origin": parcel.origin, "destination": parcel.destination}
        if parcel
        else None
    )
    refresh_fields = request.method == "POST" and "refresh_transport_fields" in request.POST
    form = ShipmentForm(
        request.POST if request.method == "POST" and not refresh_fields else None,
        business=request.current_business,
        actor=request.user,
        allow_assignment=_can_assign_parcels(request),
        initial=request.POST.dict() if refresh_fields else initial,
    )
    if request.method == "POST" and not refresh_fields and form.is_valid():
        try:
            shipment = create_shipment(
                business=request.current_business,
                actor=request.user,
                idempotency_key=form.cleaned_data["idempotency_key"],
                parcel=form.cleaned_data.get("parcel"),
                **{
                    key: form.cleaned_data[key]
                    for key in SHIPMENT_INPUT_FIELDS
                    if key not in ("transport_mode", *SHIPMENT_REFERENCE_FIELDS)
                    or key in request.POST
                },
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("logistics_shipment_detail", shipment_id=shipment.pk)
    return render(
        request,
        "logistics/shipment_form.html",
        {
            "form": form,
            "title": "Create shipment",
            "has_eligible_parcels": (
                form.fields["parcel"].queryset.exists() if "parcel" in form.fields else False
            ),
        },
    )


@never_cache
@business_module_required("shipments")
@business_role_required(*SHIPMENT_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def shipment_edit(request, shipment_id):
    shipment = _get_shipment(request, shipment_id)
    refresh_fields = request.method == "POST" and "refresh_transport_fields" in request.POST
    if shipment.status != Shipment.Status.DRAFT and (request.method == "GET" or refresh_fields):
        return _detail(request, shipment, error="Only draft shipment details can be edited.")
    form = ShipmentForm(
        request.POST if request.method == "POST" and not refresh_fields else None,
        instance=shipment,
        business=request.current_business,
        actor=request.user,
        allow_assignment=_can_assign_parcels(request),
        initial=request.POST.dict() if refresh_fields else None,
    )
    if request.method == "POST" and not refresh_fields and form.is_valid():
        try:
            update_shipment(
                business=request.current_business,
                shipment=shipment,
                actor=request.user,
                expected_revision=form.cleaned_data["expected_revision"],
                idempotency_key=form.cleaned_data["idempotency_key"],
                parcel=form.cleaned_data.get("parcel"),
                **{
                    key: form.cleaned_data[key]
                    for key in SHIPMENT_INPUT_FIELDS
                    if key not in ("transport_mode", *SHIPMENT_REFERENCE_FIELDS)
                    or key in request.POST
                },
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("logistics_shipment_detail", shipment_id=shipment.pk)
    return render(
        request,
        "logistics/shipment_form.html",
        {
            "form": form,
            "title": "Edit draft shipment",
            "has_eligible_parcels": (
                form.fields["parcel"].queryset.exists() if "parcel" in form.fields else False
            ),
        },
    )


@never_cache
@business_module_required("shipments")
@business_module_required("parcels")
@business_module_required("tracking")
@business_role_required(*SHIPMENT_MANAGE_ROLES)
@require_POST
def shipment_assign(request, shipment_id):
    shipment = _get_shipment(request, shipment_id)
    form = ShipmentAssignmentForm(
        request.POST, business=request.current_business, actor=request.user, shipment=shipment
    )
    if not form.is_valid():
        return _detail(
            request,
            shipment,
            error="Select an available parcel in this workspace.",
            assignment_form=form,
        )
    try:
        assign_parcel(
            business=request.current_business,
            shipment=shipment,
            actor=request.user,
            **form.cleaned_data,
        )
    except ValidationError as exc:
        form.add_error(None, "; ".join(exc.messages))
        return _detail(request, shipment, error="; ".join(exc.messages), assignment_form=form)
    return redirect("logistics_shipment_detail", shipment_id=shipment.pk)


@never_cache
@business_module_required("shipments")
@business_module_required("parcels")
@business_module_required("tracking")
@business_role_required(*SHIPMENT_MANAGE_ROLES)
@require_POST
def shipment_remove(request, shipment_id, parcel_id):
    shipment = _get_shipment(request, shipment_id)
    parcel = get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user),
        pk=parcel_id,
    )
    form = ShipmentWriteForm(request.POST, shipment=shipment)
    if not form.is_valid():
        return _detail(
            request,
            shipment,
            error="The shipment write token is missing or invalid. Reload before removing the parcel.",
        )
    try:
        remove_parcel(
            business=request.current_business,
            shipment=shipment,
            parcel=parcel,
            actor=request.user,
            **form.cleaned_data,
        )
    except ValidationError as exc:
        return _detail(request, shipment, error="; ".join(exc.messages))
    return redirect("logistics_shipment_detail", shipment_id=shipment.pk)


@never_cache
@business_module_required("shipments")
@business_role_required(*SHIPMENT_MANAGE_ROLES)
@require_POST
def shipment_status(request, shipment_id):
    shipment = _get_shipment(request, shipment_id)
    form = ShipmentStatusForm(request.POST, shipment=shipment, actor=request.user)
    if not form.is_valid():
        return _detail(
            request,
            shipment,
            error="Select a valid shipment transition and reload if needed.",
            status_form=form,
        )
    try:
        change_shipment_status(
            business=request.current_business,
            shipment=shipment,
            actor=request.user,
            **form.cleaned_data,
        )
    except ValidationError as exc:
        return _detail(request, shipment, error="; ".join(exc.messages), status_form=form)
    return redirect("logistics_shipment_detail", shipment_id=shipment.pk)


def _csv_value(value):
    # Neutralize spreadsheet formulas in user-supplied operational text.
    if isinstance(value, str) and (
        value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value


@never_cache
@business_module_required("shipments", access="read")
@business_module_required("manifests", access="read")
@business_role_required(*SHIPMENT_VIEW_ROLES)
@require_safe
def shipment_manifest(request, shipment_id):
    shipment = _get_shipment(request, shipment_id)
    manifest = generate_manifest(
        business=request.current_business, shipment=shipment, actor=request.user
    )
    if request.GET.get("download") == "csv":
        output = StringIO()
        writer = csv.writer(output)
        for key, label in (
            ("reference", "Shipment reference"),
            ("transport_mode_label", "Transportation mode"),
            ("origin", "Origin"),
            ("destination", "Destination"),
            ("departure_at", "Departure"),
            ("estimated_arrival_at", "ETA"),
            ("parcel_count", "Parcel count"),
            ("total_quantity", "Total quantity"),
            ("total_known_weight_kg", "Known weight (kg)"),
            ("unknown_weight_count", "Parcels without weight"),
        ):
            value = manifest[key]
            writer.writerow(
                [label, _csv_value(value.isoformat() if hasattr(value, "isoformat") else value)]
            )
        for detail in manifest["transportation_details"]:
            writer.writerow([detail["label"], _csv_value(detail["value"])])
        writer.writerow([])
        writer.writerow(
            ["Tracking code", "Client name", "Package description", "Quantity", "Weight (kg)"]
        )
        for row in manifest["parcels"]:
            writer.writerow(
                [
                    _csv_value(row[key])
                    for key in (
                        "tracking_code",
                        "client_name",
                        "package_description",
                        "quantity",
                        "weight_kg",
                    )
                ]
            )
        response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="{manifest["reference"]}-manifest.csv"'
        )
    else:
        response = render(
            request,
            "logistics/shipment_manifest.html",
            {"manifest": manifest, "shipment_id": shipment.pk},
        )
    response["X-Content-Type-Options"] = "nosniff"
    return response
