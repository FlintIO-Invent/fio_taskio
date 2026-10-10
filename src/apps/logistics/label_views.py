"""Authenticated, tenant/location-scoped label exports; no files are stored."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from apps.businesses.utils import business_module_required, business_role_required
from apps.crm.models import Client

from .parcel_policy import PARCEL_MANAGE_ROLES, PARCEL_VIEW_ROLES
from .parcel_services import parcels_for_business, require_parcel_access
from .shipping_labels import (
    client_shipping_prefill,
    render_shipping_label_pdf,
    render_shipping_label_svg,
    shipping_label_filename,
    shipping_label_font_css,
)


def _label_context(request, parcel_id):
    parcel = get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user).select_related(
            "business", "origin_location", "destination_location"
        ),
        pk=parcel_id,
    )
    shipment = None
    if parcel.shipment_id:
        from .shipment_services import shipments_for_business

        try:
            shipment = (
                shipments_for_business(business=request.current_business, actor=request.user)
                .filter(pk=parcel.shipment_id)
                .first()
            )
        except PermissionDenied:
            pass
    return {"parcel": parcel, "shipment": shipment}


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@business_module_required("parcels", access="read")
@business_module_required("tracking", access="read")
@business_role_required(*PARCEL_VIEW_ROLES)
@require_safe
def shipping_label_preview(request, parcel_id):
    context = _label_context(request, parcel_id)
    try:
        context["label_svg"] = render_shipping_label_svg(
            **context, current_business=request.current_business
        )
        context["label_font_css"] = shipping_label_font_css()
    except ValidationError as exc:
        context["label_error"] = " ".join(exc.messages)
    context["print_on_load"] = request.GET.get("print") == "1" and not context.get("label_error")
    return _private(
        render(
            request,
            "logistics/shipping_label.html",
            context,
            status=422 if context.get("label_error") else 200,
        )
    )


@never_cache
@business_module_required("parcels", access="read")
@business_module_required("tracking", access="read")
@business_role_required(*PARCEL_VIEW_ROLES)
@require_safe
def shipping_label_pdf(request, parcel_id):
    context = _label_context(request, parcel_id)
    try:
        content = render_shipping_label_pdf(**context, current_business=request.current_business)
    except ValidationError as exc:
        return _private(
            render(
                request,
                "logistics/shipping_label.html",
                {**context, "label_error": " ".join(exc.messages)},
                status=422,
            )
        )
    response = HttpResponse(content, content_type="application/pdf")
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{shipping_label_filename(context["parcel"])}"'
    )
    return _private(response)


@never_cache
@business_module_required("parcels")
@business_module_required("tracking")
@business_module_required("crm", access="read")
@business_role_required(*PARCEL_MANAGE_ROLES)
@require_safe
def shipping_client_prefill(request):
    require_parcel_access(business=request.current_business, actor=request.user, write=True)
    try:
        client_id = int(request.GET.get("client", ""))
    except ValueError:
        client_id = None
    client = get_object_or_404(Client, pk=client_id, business=request.current_business)
    return _private(JsonResponse(client_shipping_prefill(client)))
