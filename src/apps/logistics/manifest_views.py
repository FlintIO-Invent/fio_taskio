"""On-demand, authenticated registration manifest downloads."""

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from apps.businesses.utils import business_module_required, business_role_required

from .label_views import _private
from .manifest_forms import ManifestPeriodForm
from .manifest_pdf import manifest_filename, render_parcel_manifest_pdf
from .parcel_policy import PARCEL_VIEW_ROLES
from .parcel_services import require_parcel_access
from .shipment_services import require_shipment_access


@never_cache
@business_module_required("parcels", access="read")
@business_module_required("tracking", access="read")
@business_module_required("shipments", access="read")
@business_module_required("manifests", access="read")
@business_role_required(*PARCEL_VIEW_ROLES)
@require_safe
def parcel_manifest(request):
    business = request.current_business
    require_parcel_access(business=business, actor=request.user)
    require_shipment_access(business=business, actor=request.user, manifest=True)
    now = timezone.now()
    data = request.GET.copy() if request.GET else None
    if data is not None and "period" not in data:
        data["period"] = "today"
    form = ManifestPeriodForm(data, business=business, now=now)
    if request.GET.get("download") == "pdf" and form.is_valid():
        content = render_parcel_manifest_pdf(
            business=business, actor=request.user, period=form.cleaned_data, generated_at=now
        )
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{manifest_filename(business, form.cleaned_data)}"'
        )
        return _private(response)
    return _private(
        render(
            request,
            "logistics/parcel_manifest.html",
            {"form": form},
            status=400 if form.is_bound and not form.is_valid() else 200,
        )
    )
