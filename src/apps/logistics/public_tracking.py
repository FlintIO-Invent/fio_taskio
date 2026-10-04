"""Anonymous, read-only tracking boundary, reusable by future presentation clients."""

import re
import time

from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_variables

from apps.businesses.models import Business, BusinessSubscription

from .models import Parcel, ParcelEvent

TRACKING_CODE_PATTERN = re.compile(r"[A-F0-9]{48}")
LOOKUP_LIMIT = 30
LOOKUP_WINDOW_SECONDS = 60


def allow_tracking_lookup(remote_address):
    """Fixed-window, per-peer throttle. Never trust forwarded headers or store raw IPs.

    Uses atomic cache add/incr where supported. LocMemCache is per-process;
    a shared cache is needed for a deployment-wide limit. Cache failure denies
    lookups instead of silently removing protection. No parcel/code enters a key.
    """
    window = int(time.time()) // LOOKUP_WINDOW_SECONDS
    peer = salted_hmac("logistics.public_tracking.peer", remote_address or "unknown").hexdigest()
    key = f"logistics:public-tracking:{window}:{peer}"
    try:
        if cache.add(key, 1, timeout=LOOKUP_WINDOW_SECONDS * 2):
            return True
        return cache.incr(key) <= LOOKUP_LIMIT
    except Exception:
        return False


@sensitive_variables()
def lookup_public_tracking(tracking_code):
    """Return only JSON-compatible public values, or None for every unavailable case.

    Codes are exact bearer secrets, independent of database IDs. Only nonblank
    public_message events are customer-visible. Unclassified route/location
    text and business contact fields are deliberately absent from this allowlist.
    """
    if not isinstance(tracking_code, str) or not TRACKING_CODE_PATTERN.fullmatch(tracking_code):
        return None
    parcel = (
        Parcel.objects.filter(
            tracking_code=tracking_code,
            business__is_active=True,
            business__vertical=Business.Vertical.LOGISTICS,
            client__business_id=F("business_id"),
        )
        .values("tracking_code", "current_status", "business_id", "business__name")
        .first()
    )
    if parcel is None or parcel["tracking_code"] != tracking_code:
        return None
    subscription = (
        BusinessSubscription.objects.select_related("business", "plan")
        .filter(business_id=parcel["business_id"])
        .first()
    )
    now = timezone.now()
    if subscription is None or not all(
        subscription.can_use_module_at(module, now) for module in ("parcels", "tracking")
    ):
        return None

    events = []
    for event in (
        ParcelEvent.objects.filter(
            parcel__tracking_code=tracking_code,
            business_id=parcel["business_id"],
            parcel__business_id=F("business_id"),
        )
        .exclude(public_message="")
        .order_by("timestamp", "pk")
        .values("status", "timestamp", "public_message")
    ):
        if event["public_message"].strip():
            events.append(
                {
                    "status": event["status"],
                    "status_label": Parcel.Status(event["status"]).label if event["status"] else "",
                    "timestamp": event["timestamp"].isoformat(),
                    "message": event["public_message"],
                }
            )
    return {
        "tracking_code": parcel["tracking_code"],
        "status": parcel["current_status"],
        "status_label": Parcel.Status(parcel["current_status"]).label,
        "business": {"name": parcel["business__name"]},
        "events": events,
    }
