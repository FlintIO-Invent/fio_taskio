from __future__ import annotations

from apps.businesses.models import Business
from apps.businesses.usage_limits import lock_capacity_scope


def lock_client_capacity_scope(business: Business) -> Business:
    """Lock the shared rows used to coordinate Client quota writers.

    Callers must already be inside ``transaction.atomic()``. All cooperating
    Client writers lock Business first and its optional subscription second.
    """

    return lock_capacity_scope(business.pk, using=business._state.db or "default")[0]
