"""Read-only workspace presentation; lifecycle decisions stay in domain services."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Q

from apps.businesses.utils import can_view_module, membership_has_any_role

from .models import Parcel, ParcelEvent, Shipment
from .parcel_policy import PARCEL_VIEW_ROLES
from .parcel_services import parcels_for_business
from .shipment_policy import ASSIGNABLE_PARCEL_STATUSES, SHIPMENT_VIEW_ROLES
from .shipment_services import shipments_for_business


def get_logistics_dashboard_context(*, business, actor, membership, now):
    parcels_enabled = (
        can_view_module(business, "parcels")
        and can_view_module(business, "tracking")
        and membership_has_any_role(membership, PARCEL_VIEW_ROLES)
    )
    shipments_enabled = can_view_module(business, "shipments") and membership_has_any_role(
        membership, SHIPMENT_VIEW_ROLES
    )
    context = {
        "logistics_dashboard": True,
        "dashboard_parcels_enabled": parcels_enabled,
        "dashboard_shipments_enabled": shipments_enabled,
    }
    if parcels_enabled:
        local_now = now.astimezone(ZoneInfo(business.timezone))
        month_start = datetime(local_now.year, local_now.month, 1, tzinfo=local_now.tzinfo)
        month_end = datetime(
            local_now.year + (local_now.month == 12),
            local_now.month % 12 + 1,
            1,
            tzinfo=local_now.tzinfo,
        )
        parcels = parcels_for_business(business=business, actor=actor)
        status_counts = dict(
            parcels.order_by()
            .values("current_status")
            .annotate(total=Count("pk"))
            .values_list("current_status", "total")
        )
        events = ParcelEvent.objects.filter(
            business=business, parcel__business=business, parcel__client__business=business
        )
        delivered = (
            events.filter(
                event_type=ParcelEvent.Type.STATUS,
                status=Parcel.Status.DELIVERED,
                parcel__current_status=Parcel.Status.DELIVERED,
                timestamp__gte=now - timedelta(days=7),
                timestamp__lte=now,
            )
            .select_related("parcel", "parcel__client")
            .order_by("-timestamp", "-pk")
        )
        context.update(
            {
                "parcel_count": sum(status_counts.values()),
                "active_parcel_count": sum(
                    count
                    for status, count in status_counts.items()
                    if status not in (Parcel.Status.DELIVERED, Parcel.Status.CANCELLED)
                ),
                "parcel_status_counts": [
                    {"status": status, "label": label, "count": status_counts.get(status, 0)}
                    for status, label in Parcel.Status.choices
                ],
                "ready_parcel_count": status_counts.get(Parcel.Status.READY, 0),
                "received_waiting_parcel_count": sum(
                    status_counts.get(status, 0) for status in ASSIGNABLE_PARCEL_STATUSES
                ),
                "in_transit_parcel_count": status_counts.get(Parcel.Status.IN_TRANSIT, 0),
                "delivered_this_month_count": events.filter(
                    event_type=ParcelEvent.Type.STATUS,
                    status=Parcel.Status.DELIVERED,
                    timestamp__gte=month_start,
                    timestamp__lt=month_end,
                )
                .values("parcel_id")
                .distinct()
                .count(),
                "parcels_requiring_attention": parcels.filter(
                    Q(current_status=Parcel.Status.HOLD)
                    | Q(current_status__in=ASSIGNABLE_PARCEL_STATUSES, shipment__isnull=True)
                )
                .select_related("client")
                .order_by("created_at", "pk")[:5],
                "pending_movement_parcel_count": parcels.filter(
                    current_status__in=ASSIGNABLE_PARCEL_STATUSES, shipment__isnull=True
                ).count(),
                "recently_delivered_parcel_count": delivered.count(),
                "recent_deliveries": delivered[:5],
                "recent_tracking_events": events.select_related("parcel").order_by(
                    "-timestamp", "-pk"
                )[:5],
            }
        )
    if shipments_enabled:
        shipments = shipments_for_business(business=business, actor=actor)
        context.update(
            shipments.aggregate(
                shipment_count=Count("pk"),
                active_shipment_count=Count(
                    "pk",
                    filter=~Q(status__in=(Shipment.Status.COMPLETED, Shipment.Status.CANCELLED)),
                ),
            )
        )
        context["active_shipments"] = shipments.exclude(
            status__in=(Shipment.Status.COMPLETED, Shipment.Status.CANCELLED)
        ).order_by("-updated_at", "-pk")[:5]
    return context
