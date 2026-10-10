from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.businesses.models import BusinessUser
from apps.businesses.utils import business_module_required, business_role_required

from .location_forms import LogisticsLocationForm
from .location_services import save_location
from .models import LogisticsLocation


@business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
@business_module_required("parcels")
@require_http_methods(["GET", "POST"])
def location_settings(request, location_id=None):
    business = request.current_business
    item = (
        get_object_or_404(LogisticsLocation, business=business, pk=location_id)
        if location_id
        else None
    )
    form = LogisticsLocationForm(
        request.POST if request.method == "POST" else None, instance=item, business=business
    )
    if request.method == "POST" and form.is_valid():
        try:
            save_location(business=business, actor=request.user, location=item, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Operating location saved.")
            return redirect("logistics_location_settings")
    return render(
        request,
        "logistics/location_settings.html",
        {
            "form": form,
            "location": item,
            "locations": LogisticsLocation.objects.filter(business=business),
        },
    )
