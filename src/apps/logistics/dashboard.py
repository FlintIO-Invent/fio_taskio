"""Read-only workspace presentation; lifecycle decisions stay in domain services."""

from copy import copy
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, Exists, OuterRef, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.billings.models import Invoice, InvoiceCancellationCredit, InvoicePayment
from apps.billings.payment_services import _invoice_settlement
from apps.businesses.utils import BILLING_VIEW_ROLES, can_view_module, membership_has_any_role

from .financial_access import scope_invoices
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
    invoices_enabled = can_view_module(business, "invoicing") and membership_has_any_role(
        membership, BILLING_VIEW_ROLES
    )
    context = {
        "logistics_dashboard": True,
        "dashboard_parcels_enabled": parcels_enabled,
        "dashboard_shipments_enabled": shipments_enabled,
        "dashboard_invoices_enabled": invoices_enabled,
    }
    if parcels_enabled or invoices_enabled:
        local_now = now.astimezone(ZoneInfo(business.timezone))
        month_start = datetime(local_now.year, local_now.month, 1, tzinfo=local_now.tzinfo)
        month_end = datetime(
            local_now.year + (local_now.month == 12),
            local_now.month % 12 + 1,
            1,
            tzinfo=local_now.tzinfo,
        )
    if invoices_enabled:
        # Status totals describe invoice value, not payment receipts: invoices have no paid_at.
        invoices = scope_invoices(
            Invoice.objects.filter(business=business, client__business=business),
            business=business,
            actor=actor,
        )
        buckets = (
            invoices.annotate(
                finance_currency=Coalesce("currency_snapshot", Value(business.currency))
            )
            .values("finance_currency")
            .annotate(
                invoiced_this_month_total=Sum(
                    "total",
                    filter=Q(
                        status__in=(Invoice.Status.SENT, Invoice.Status.PAID),
                        created_at__gte=month_start,
                        created_at__lt=month_end,
                    ),
                ),
                draft_invoice_total=Sum("total", filter=Q(status=Invoice.Status.DRAFT)),
            )
        )
        keys = (
            "invoiced_this_month_total",
            "outstanding_invoice_total",
            "paid_invoice_total",
            "draft_invoice_total",
        )
        context.update({key: Decimal("0.00") for key in keys})
        receipt_totals = {}
        refund_totals = {}
        refund_review_count = 0
        review_count = 0
        for invoice in (
            invoices.annotate(
                has_refund=Exists(
                    InvoicePayment.objects.filter(invoice_id=OuterRef("pk"), kind="REFUND")
                ),
                has_cancellation_credit=Exists(
                    InvoiceCancellationCredit.objects.filter(
                        obligation__line__invoice_id=OuterRef("pk")
                    )
                ),
            )
            .filter(
                Q(status__in=[Invoice.Status.SENT, Invoice.Status.PAID])
                | Q(has_refund=True)
                | Q(has_cancellation_credit=True)
            )
            .select_related("business")
            .prefetch_related("payments")
        ):
            balance = _invoice_settlement(invoice)
            if balance.issues:
                if invoice.status in (Invoice.Status.SENT, Invoice.Status.PAID):
                    review_count += 1
                if invoice.has_refund or invoice.has_cancellation_credit:
                    refund_review_count += 1
                continue
            refunds = [
                entry
                for entry in invoice.payments.all()
                if entry.kind == InvoicePayment.Kind.REFUND
            ]
            if balance.refund_due or refunds:
                values = refund_totals.setdefault(
                    balance.currency,
                    {
                        "refund_due_total": Decimal("0.00"),
                        "refund_due_invoice_count": 0,
                        "recorded_refund_total": Decimal("0.00"),
                        "recorded_refund_count": 0,
                    },
                )
                values["refund_due_total"] += balance.refund_due
                values["refund_due_invoice_count"] += bool(balance.refund_due)
                values["recorded_refund_total"] += sum(
                    (entry.amount for entry in refunds), Decimal("0.00")
                )
                values["recorded_refund_count"] += len(refunds)
            if invoice.status not in (Invoice.Status.SENT, Invoice.Status.PAID):
                continue
            if balance.legacy_paid_unverified or invoice.snapshot_is_legacy:
                review_count += 1
            values = receipt_totals.setdefault(
                balance.currency,
                {
                    "outstanding_invoice_total": Decimal("0.00"),
                    "paid_invoice_total": Decimal("0.00"),
                },
            )
            values["outstanding_invoice_total"] += balance.outstanding
            values["paid_invoice_total"] += balance.net_paid
        context["payment_review_invoice_count"] = review_count
        refund_currencies = []
        for currency, totals in sorted(refund_totals.items()):
            money_business = copy(business)
            money_business.currency = currency
            refund_currencies.append(
                {**totals, "currency": currency, "billing_business": money_business}
            )
        context["refund_currency_totals"] = refund_currencies
        context["refund_review_invoice_count"] = refund_review_count
        other_currencies = []
        for bucket in buckets.order_by("finance_currency"):
            values = {key: bucket.get(key) or Decimal("0.00") for key in keys}
            values.update(
                receipt_totals.get(
                    bucket["finance_currency"],
                    {
                        "outstanding_invoice_total": Decimal("0.00"),
                        "paid_invoice_total": Decimal("0.00"),
                    },
                )
            )
            if bucket["finance_currency"] == business.currency:
                context.update(values)
            else:
                money_business = copy(business)
                money_business.currency = bucket["finance_currency"]
                other_currencies.append(
                    {
                        **values,
                        "currency": bucket["finance_currency"],
                        "billing_business": money_business,
                    }
                )
        context["other_currency_invoice_totals"] = other_currencies
    if parcels_enabled:
        parcels = parcels_for_business(business=business, actor=actor)
        status_counts = dict(
            parcels.order_by()
            .values("current_status")
            .annotate(total=Count("pk"))
            .values_list("current_status", "total")
        )
        events = ParcelEvent.objects.filter(
            business=business,
            parcel__in=parcels,
            parcel__business=business,
            parcel__client__business=business,
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
    if parcels_enabled:
        from .workflow_summary import resolve_parcel_workflows

        attention = list(context["parcels_requiring_attention"])
        deliveries = list(context["recent_deliveries"])
        summaries = resolve_parcel_workflows(
            business=business,
            actor=actor,
            parcel_ids=[item.pk for item in attention] + [event.parcel_id for event in deliveries],
            include_history=False,
        ).by_parcel_id
        for parcel in attention:
            parcel.workflow_summary = summaries[parcel.pk]
        for event in deliveries:
            event.parcel.workflow_summary = summaries[event.parcel_id]
        context["parcels_requiring_attention"] = attention
        context["recent_deliveries"] = deliveries
    return context
