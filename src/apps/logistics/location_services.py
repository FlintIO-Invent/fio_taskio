from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.businesses.models import Business, BusinessUser

from .location_forms import LogisticsLocationForm
from .models import LogisticsLocation
from .parcel_services import require_parcel_access


@transaction.atomic
def save_location(*, business, actor, location=None, **fields):
    current = Business.objects.select_for_update().filter(pk=getattr(business, "pk", None)).first()
    current = require_parcel_access(business=current, actor=actor, write=True)
    if not BusinessUser.objects.filter(
        business=current,
        user=actor,
        is_active=True,
        role__in=(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN),
    ).exists():
        raise PermissionDenied("Only workspace owners and administrators can manage locations.")
    if set(fields) - set(LogisticsLocationForm.Meta.fields):
        raise ValidationError("Unsupported location fields.")
    if location is None:
        item = LogisticsLocation(business=current)
    else:
        item = (
            LogisticsLocation.objects.select_for_update()
            .filter(business=current, pk=getattr(location, "pk", location))
            .first()
        )
        if item is None:
            raise ValidationError("Location is unavailable in this workspace.")
    for name, value in fields.items():
        setattr(item, name, value)
    item.save()
    return item
