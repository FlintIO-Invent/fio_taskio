"""Technical submission throttle, separate from subscription entitlements.

Uses the project's public-tracking add/incr pattern, with independent keys.
The default cache is per process; use a shared configured cache for a fleet.
"""

import ipaddress
import os
import time

from django.conf import settings
from django.core.cache import caches
from django.utils.crypto import salted_hmac


def allow_booking_submission(request, business_id):
    try:
        mode = getattr(settings, "SERVICES_BOOKING_CLIENT_IP_MODE", "direct")
        if mode == "heroku" and os.environ.get("DYNO"):
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            if len(forwarded) > 4096:
                return False
            raw_address = forwarded.rsplit(",", 1)[-1].strip()
        elif mode == "direct":
            raw_address = request.META.get("REMOTE_ADDR", "")
        else:
            return False
        address = ipaddress.ip_address(raw_address)
        identity = str(getattr(address, "ipv4_mapped", None) or address)
        peer = salted_hmac("services.booking.peer", identity).hexdigest()
        cache = caches[getattr(settings, "SERVICES_BOOKING_CACHE_ALIAS", "default")]
        key = f"services:booking:{business_id}:{int(time.time()) // 60}:{peer}"
        if cache.add(key, 1, timeout=120):
            return True
        return cache.incr(key) <= 30
    except Exception:
        return False
