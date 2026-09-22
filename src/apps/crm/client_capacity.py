from __future__ import annotations

from django.db import connection

from apps.businesses.models import Business, BusinessSubscription


def lock_client_capacity_scope(business: Business) -> Business:
    """Lock the shared rows used to coordinate Client quota writers.

    Callers must already be inside ``transaction.atomic()``. All cooperating
    Client writers lock Business first and its optional subscription second.
    """

    if not connection.in_atomic_block:
        raise RuntimeError("Client capacity locks require transaction.atomic().")

    locked_business = Business.objects.select_for_update().get(pk=business.pk)
    subscription = (
        BusinessSubscription.objects.select_for_update()
        .select_related("plan")
        .filter(business=locked_business)
        .first()
    )
    if subscription is not None:
        locked_business._state.fields_cache["subscription"] = subscription
    return locked_business
