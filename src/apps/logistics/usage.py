"""Internal, read-only resource visibility, independent of any presentation client.

Approval thresholds are review signals, never commercial quotas. Locations are
application estimates; there is no operational location model yet.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils import timezone

from apps.businesses.models import Business, BusinessSubscription, BusinessUser
from apps.crm.models import Client

from .models import LogisticsApplication, Parcel, ParcelEvent, Shipment
from .policy import LogisticsEligibilityPolicy, LogisticsUsageReviewPolicy


def logistics_usage(*, business, now=None):
    """Count persisted tenant-owned usage, including for inactive businesses.

    Months use the Business timezone and a half-open calendar interval. Parcels
    use registration time; events and deliveries use event time. Seats require
    both an active membership and active user. Callers authorize internal access.
    """
    current = Business.objects.get(pk=getattr(business, "pk", business))
    if current.vertical != Business.Vertical.LOGISTICS:
        raise ValidationError("Logistics usage requires a Logistics business.")
    instant = now or timezone.now()
    if timezone.is_naive(instant):
        raise ValueError("Usage time must be timezone-aware.")
    zone = ZoneInfo(current.timezone)
    local = instant.astimezone(zone)
    start = datetime(local.year, local.month, 1, tzinfo=zone)
    end = datetime(local.year + (local.month == 12), local.month % 12 + 1, 1, tzinfo=zone)
    parcels = Parcel.objects.filter(business=current)
    parcel_counts = parcels.aggregate(
        parcels=Count("pk"),
        monthly_parcels=Count("pk", filter=Q(created_at__gte=start, created_at__lt=end)),
    )
    events = ParcelEvent.objects.filter(business=current, parcel__business=current)
    event_counts = events.aggregate(
        parcel_events=Count("pk"),
        monthly_parcel_events=Count("pk", filter=Q(timestamp__gte=start, timestamp__lt=end)),
        delivered_parcels_this_month=Count(
            "parcel_id",
            distinct=True,
            filter=Q(
                timestamp__gte=start,
                timestamp__lt=end,
                event_type=ParcelEvent.Type.STATUS,
                status=Parcel.Status.DELIVERED,
            ),
        ),
    )
    shipment_counts = Shipment.objects.filter(business=current).aggregate(
        shipments=Count("pk"),
        active_shipments=Count(
            "pk", filter=~Q(status__in=(Shipment.Status.COMPLETED, Shipment.Status.CANCELLED))
        ),
        completed_shipments=Count("pk", filter=Q(status=Shipment.Status.COMPLETED)),
    )
    status_counts = dict(
        parcels.order_by()
        .values("current_status")
        .annotate(total=Count("pk"))
        .values_list("current_status", "total")
    )
    application = LogisticsApplication.objects.filter(business=current).first()
    return {
        "business_id": current.pk,
        "month": start.strftime("%Y-%m"),
        "timezone": current.timezone,
        "month_start": start.isoformat(),
        "month_end_exclusive": end.isoformat(),
        "active_users": BusinessUser.objects.filter(
            business=current, is_active=True, user__is_active=True
        ).count(),
        "active_clients": Client.objects.filter(
            business=current, is_active=True, client_status=Client.ClientStatus.ACTIVE
        ).count(),
        **parcel_counts,
        **event_counts,
        **shipment_counts,
        "parcel_status_summary": {
            status: status_counts.get(status, 0) for status in Parcel.Status.values
        },
        "average_events_per_parcel": (
            round(event_counts["parcel_events"] / parcel_counts["parcels"], 2)
            if parcel_counts["parcels"]
            else 0.0
        ),
        "reported_locations": application.location_count if application else None,
        "location_source": "application_estimate" if application else "unavailable",
    }


def logistics_threshold_summary(*, usage):
    """Compare an internal usage snapshot to configured review thresholds only."""
    policy = settings.LOGISTICS_ELIGIBILITY_POLICY
    if not isinstance(policy, LogisticsEligibilityPolicy):
        policy = LogisticsEligibilityPolicy.model_validate(policy)
    review = getattr(settings, "LOGISTICS_USAGE_REVIEW_POLICY", LogisticsUsageReviewPolicy())
    if not isinstance(review, LogisticsUsageReviewPolicy):
        review = LogisticsUsageReviewPolicy.model_validate(review)

    def signal(metric, threshold, source):
        value = usage[metric]
        if threshold is None:
            state = "not_configured"
        elif value is None:
            state = "unavailable"
        elif value > threshold:
            state = "exceeded"
        elif value > 0 and value >= threshold * review.approaching_ratio:
            state = "approaching"
        else:
            state = "within"
        return {
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "state": state,
            "source": source,
        }

    signals = [
        signal("monthly_parcels", policy.auto_approve_monthly_parcels, "approval_auto_volume"),
        signal("monthly_parcels", policy.review_above_monthly_parcels, "approval_review_volume"),
        signal(
            "monthly_parcels", policy.high_resource_monthly_parcels, "approval_high_resource_volume"
        ),
        signal("active_users", policy.auto_approve_staff_count, "approval_staff"),
        signal(
            "reported_locations", policy.auto_approve_location_count, "approval_locations_estimate"
        ),
        signal(
            "monthly_parcel_events",
            review.monthly_event_review_threshold,
            "operational_event_review",
        ),
    ]
    return {
        "informational_only": True,
        "commercial_plan_limits": False,
        "rule_version": policy.rule_version,
        "approaching_ratio": review.approaching_ratio,
        "review_required": any(item["state"] in {"approaching", "exceeded"} for item in signals),
        "signals": signals,
    }


def logistics_operational_summary(*, business, now=None):
    usage = logistics_usage(business=business, now=now)
    subscription = (
        BusinessSubscription.objects.select_related("plan")
        .filter(business_id=usage["business_id"])
        .first()
    )
    application = (
        LogisticsApplication.objects.filter(business_id=usage["business_id"])
        .values("id", "status", "converted_revision")
        .first()
    )
    if application:
        application["id"] = str(application["id"])
    return {
        "plan": subscription.plan.slug if subscription else None,
        "billing_interval": subscription.billing_interval if subscription else None,
        "subscription_status": subscription.status if subscription else None,
        "application": application,
        "application_retained_on_purge": application is not None,
        "usage": usage,
        "threshold_review": logistics_threshold_summary(usage=usage),
    }
