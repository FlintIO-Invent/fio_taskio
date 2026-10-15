"""Nonblocking capacity warnings in the existing subscription email outbox."""

from hashlib import sha256

from django.urls import reverse
from django.utils import timezone

from apps.businesses.models import Business, BusinessUser, SubscriptionNotification

from .subscription_usage import logistics_subscription_usage

WARNING_TYPE = "logistics_capacity_warning"


def enqueue_usage_warnings(*, business, snapshot=None, dry_run=False):
    if business.vertical != Business.Vertical.LOGISTICS or not business.is_active:
        return {"created": 0, "duplicates": 0, "candidates": 0}
    usage = snapshot or logistics_subscription_usage(business=business)
    if usage["business_id"] != business.pk:
        raise ValueError("Usage snapshot belongs to another business.")
    recipients = BusinessUser.objects.filter(
        business=business,
        is_active=True,
        user__is_active=True,
        role__in=(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN),
    ).select_related("user")
    result = {"created": 0, "duplicates": 0, "candidates": 0}
    for row in usage["warnings"]:
        threshold = 100 if row["state"] == "full" else 80
        for member in recipients:
            email = member.user.email.strip().lower()
            recipient_key = sha256(email.encode()).hexdigest()[:24]
            key = f"logistics:capacity:{business.pk}:{row['name']}:{usage['period']}:{threshold}:{recipient_key}"
            result["candidates"] += 1
            if dry_run:
                result["duplicates"] += SubscriptionNotification.objects.filter(
                    deduplication_key=key
                ).exists()
                continue
            _, created = SubscriptionNotification.objects.get_or_create(
                deduplication_key=key,
                defaults={
                    "business": business,
                    "subscription_id": usage["subscription_id"],
                    "recipient_email": email,
                    "recipient_user": member.user,
                    "notification_type": WARNING_TYPE,
                    "context_summary": {
                        "metric": row["name"],
                        "metric_label": row["label"],
                        "used": row["used"],
                        "allowance": row["allowance"],
                        "threshold": threshold,
                        "period": usage["period"],
                        "monthly": row["monthly"],
                        "reset_display": usage["reset_display"],
                        "plan_name": usage["plan_name"],
                        "action_path": reverse("business_subscription"),
                        "action_label": "Review workspace usage",
                    },
                },
            )
            result["created" if created else "duplicates"] += 1
    return result


def obsolete_usage_warning(notification):
    """Do not send old-period, resolved, cross-tenant or former-admin notices."""
    business = notification.business
    if (
        business.vertical != Business.Vertical.LOGISTICS
        or notification.subscription.business_id != business.pk
    ):
        return "Capacity warning no longer belongs to a Logistics subscription."
    eligible = BusinessUser.objects.filter(
        business=business,
        user_id=notification.recipient_user_id,
        is_active=True,
        user__is_active=True,
        user__email__iexact=notification.recipient_email,
        role__in=(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN),
    ).exists()
    if not eligible:
        return "Capacity warning recipient is no longer an active owner or admin."
    usage = logistics_subscription_usage(business=business, now=timezone.now())
    summary = notification.context_summary or {}
    if (
        usage["period"] != summary.get("period")
        or usage["subscription_id"] != notification.subscription_id
    ):
        return "Capacity warning reporting period or subscription has changed."
    row = next((row for row in usage["warnings"] if row["name"] == summary.get("metric")), None)
    threshold = summary.get("threshold")
    if threshold not in (80, 100) or row is None or (threshold == 100 and row["state"] != "full"):
        return "Capacity warning resolved before delivery."
    if row["allowance"] != summary.get("allowance"):
        return "Capacity warning allowance changed before delivery."
    return ""
