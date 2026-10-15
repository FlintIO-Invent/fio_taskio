"""Read-only commercial usage, using the existing effective entitlement resolver."""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone

from apps.businesses.models import Business, BusinessSubscription, SubscriptionNotification
from apps.businesses.usage_limits import (
    MONTHLY_MODELS,
    monthly_usage,
    seat_usage,
    utc_month_bounds,
)
from apps.businesses.utils import get_business_usage_count, resolve_business_plan_limit

from .models import ParcelEvent

HARD_METRICS = (
    ("users", "Staff seats, including owner"),
    ("locations", "Active operating locations"),
    ("clients", "Active Clients"),
    ("services", "Logistics Services"),
    ("parcels_per_month", "Parcels created this month"),
    ("shipments_per_month", "Shipments created this month"),
    ("invoices_per_month", "Invoices created this month"),
)


def _metric(business, name, label, used, *, measured=True, note=""):
    entitlement = resolve_business_plan_limit(business, name)
    allowance = entitlement.limit if entitlement.available else None
    unlimited = entitlement.unlimited
    percent = None
    state = "within"
    if not entitlement.available:
        state = "unavailable"
    elif not measured:
        state = "not_measured"
    elif unlimited:
        state = "unlimited"
    elif used is None:
        state = "unavailable"
    elif allowance == 0:
        state = "full"
    else:
        percent = (Decimal(used) * 100 / allowance).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        # Thresholds use exact integer arithmetic, not rounded presentation.
        state = (
            "full"
            if used >= allowance
            else "approaching" if used * 5 >= allowance * 4 else "within"
        )
    return {
        "name": name,
        "label": label,
        "used": used,
        "used_display": (
            str(used) if used is not None else "Not measured" if not measured else "Unknown"
        ),
        "allowance": allowance,
        "allowance_display": (
            "Unlimited" if unlimited else str(allowance) if allowance is not None else "Unavailable"
        ),
        "available": entitlement.available,
        "measured": measured,
        "unlimited": unlimited,
        "percent": percent,
        "percent_display": (
            f"{percent}%"
            if percent is not None
            else (
                "No capacity"
                if state == "full"
                else (
                    "Not applicable"
                    if unlimited
                    else "Not measured" if not measured else "Unavailable"
                )
            )
        ),
        "bar_percent": str(min(percent or 0, 100)),
        "state": state,
        "monthly": name.endswith("_per_month"),
        "note": note,
    }


def logistics_subscription_usage(*, business, now=None):
    """One bounded snapshot per page/command; no writes, sends, or storage scans."""
    if business.vertical != Business.Vertical.LOGISTICS:
        raise ValueError("Logistics usage requires a Logistics business.")
    instant = now or timezone.now()
    start, end = utc_month_bounds(instant)
    subscription = (
        BusinessSubscription.objects.select_related("business", "plan")
        .filter(business_id=business.pk)
        .first()
    )
    current = subscription.business if subscription else business
    current._state.fields_cache["subscription"] = subscription
    hard = []
    for name, label in HARD_METRICS:
        note = ""
        try:
            if name in MONTHLY_MODELS:
                # Reuse C's persisted meter for capacity tiers. Legacy monthly
                # counts use the same UTC range without changing legacy billing.
                from apps.businesses.usage_limits import is_capacity_tier

                if is_capacity_tier(current, subscription):
                    used = monthly_usage(
                        current, subscription, name, instant=instant, refresh=False
                    )
                else:
                    from django.apps import apps

                    used = (
                        apps.get_model(MONTHLY_MODELS[name])
                        .objects.filter(
                            business_id=current.pk, created_at__gte=start, created_at__lt=end
                        )
                        .count()
                    )
            elif name == "users":
                active, reserved = seat_usage(current, include_details=True)
                used = active + reserved
                note = f"{active} active accounts; {reserved} pending invitation seats reserved."
            else:
                used = get_business_usage_count(current, name)
        except ValidationError:
            used = None
            note = "Usage could not be verified. Please contact support."
        hard.append(_metric(current, name, label, used, note=note))
    events = ParcelEvent.objects.filter(
        business_id=current.pk,
        parcel__business_id=F("business_id"),
        timestamp__gte=start,
        timestamp__lt=end,
    ).count()
    accepted = SubscriptionNotification.objects.filter(
        business_id=current.pk,
        subscription__business_id=F("business_id"),
        status=SubscriptionNotification.Status.SENT,
        sent_at__gte=start,
        sent_at__lt=end,
    ).count()
    monitoring = [
        _metric(
            current,
            "parcel_events_per_month",
            "ParcelEvents this month",
            events,
            note="Fair-use monitoring only. Status updates and deliveries remain available.",
        ),
        _metric(
            current,
            "transactional_emails_per_month",
            "Transactional emails this month",
            None,
            measured=False,
            note=f"{accepted} subscription emails accepted by the email backend this UTC month. This subset is not total delivery; queued and failed messages are excluded.",
        ),
        _metric(
            current,
            "storage_gb",
            "Storage planning (GB)",
            None,
            measured=False,
            note="Informational planning allowance. Per-business storage is not measured; no storage quota is enforced.",
        ),
    ]
    price = (
        subscription.plan.get_display_pricing(region=subscription.billing_currency)
        if subscription
        else None
    )
    return {
        "business_id": current.pk,
        "subscription_id": subscription.pk if subscription else None,
        "plan_name": subscription.plan.name if subscription else "No subscription",
        "price": price,
        "period": start.strftime("%Y-%m"),
        "month_start": start,
        "reset_at": end,
        "reset_display": end.strftime("%d %b %Y, 00:00 UTC"),
        "hard": hard,
        "monitoring": monitoring,
        "accepted_subscription_emails": accepted,
        "warnings": [row for row in hard if row["state"] in {"approaching", "full"}],
    }
