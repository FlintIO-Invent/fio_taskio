"""Anonymous, read-only tracking boundary, reusable by future presentation clients."""

import ipaddress
import os
import time

from django.conf import settings
from django.core.cache import cache, caches
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_variables

from apps.businesses.models import Business, BusinessSubscription

from .models import Parcel, ParcelEvent
from .tracking_codes import TRACKING_CODE_PATTERN

LOOKUP_LIMIT = 30
LOOKUP_WINDOW_SECONDS = 60
ATOMIC_SHARED_CACHES = {
    "django.core.cache.backends.redis.RedisCache": "redis",
    "django.core.cache.backends.memcached.PyMemcacheCache": "pymemcache",
    "django.core.cache.backends.memcached.PyLibMCCache": "pylibmc",
}


def tracking_client_identity(request):
    """Resolve only a socket peer or the verified Heroku router's appended IP.

    Heroku mode is an explicit deployment contract: the web dyno must only be
    reachable through its router. Left-hand XFF values belong to the client
    and are never identities. Missing/invalid identity denies the lookup.
    This policy is limited to tracking; it never rewrites request.META.
    """
    mode = getattr(settings, "LOGISTICS_TRACKING_CLIENT_IP_MODE", "direct")
    if mode == "heroku":
        if not os.environ.get("DYNO"):
            return None
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if not isinstance(forwarded, str) or len(forwarded) > 4096:
            return None
        address = forwarded.rsplit(",", 1)[-1].strip()
    elif mode == "direct":
        address = request.META.get("REMOTE_ADDR", "")
    else:
        return None
    try:
        peer = ipaddress.ip_address(address)
    except (ValueError, TypeError):
        return None
    # IPv4-mapped IPv6 must use the same counter as its IPv4 representation.
    return str(getattr(peer, "ipv4_mapped", None) or peer)


def allow_tracking_lookup(remote_address):
    """Fixed-window throttle for a resolved identity; never store raw IPs.

    Uses atomic cache add/incr where supported. LocMemCache is per-process;
    a shared cache is needed for a deployment-wide limit. Cache failure denies
    lookups instead of silently removing protection. No parcel/code enters a key.
    """
    if not remote_address:
        return False
    window = int(time.time()) // LOOKUP_WINDOW_SECONDS
    peer = salted_hmac("logistics.public_tracking.peer", remote_address).hexdigest()
    key = f"logistics:public-tracking:{window}:{peer}"
    try:
        alias = getattr(settings, "LOGISTICS_TRACKING_CACHE_ALIAS", "default")
        config = settings.CACHES.get(alias, {})
        if getattr(settings, "LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE", not settings.DEBUG) and (
            config.get("BACKEND") not in ATOMIC_SHARED_CACHES or not config.get("LOCATION")
        ):
            return False
        tracking_cache = cache if alias == "default" else caches[alias]
        if tracking_cache.add(key, 1, timeout=LOOKUP_WINDOW_SECONDS * 2):
            return True
        return tracking_cache.incr(key) <= LOOKUP_LIMIT
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
