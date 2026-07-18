from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULT_SUBSCRIPTION_PAYMENT_GRACE_DAYS = 7
MIN_SUBSCRIPTION_PAYMENT_GRACE_DAYS = 0
MAX_SUBSCRIPTION_PAYMENT_GRACE_DAYS = 30

SUBSCRIPTION_CHECK_INVALID_PAYMENT_GRACE_DAYS = "motionmate_subscription.E001"


@dataclass(frozen=True)
class SubscriptionGraceConfigurationIssue:
    id: str
    message: str


def get_subscription_payment_grace_days() -> int:
    issues = validate_subscription_grace_configuration()
    if issues:
        raise ImproperlyConfigured(issues[0].message)
    return _parse_grace_days(_raw_grace_days())


def get_subscription_payment_grace_duration() -> timedelta:
    return timedelta(days=get_subscription_payment_grace_days())


def validate_subscription_grace_configuration() -> list[SubscriptionGraceConfigurationIssue]:
    raw_value = _raw_grace_days()
    try:
        parsed = _parse_grace_days(raw_value)
    except (TypeError, ValueError):
        return [
            SubscriptionGraceConfigurationIssue(
                SUBSCRIPTION_CHECK_INVALID_PAYMENT_GRACE_DAYS,
                "SUBSCRIPTION_PAYMENT_GRACE_DAYS must be a whole number from 0 to 30.",
            )
        ]

    if not (MIN_SUBSCRIPTION_PAYMENT_GRACE_DAYS <= parsed <= MAX_SUBSCRIPTION_PAYMENT_GRACE_DAYS):
        return [
            SubscriptionGraceConfigurationIssue(
                SUBSCRIPTION_CHECK_INVALID_PAYMENT_GRACE_DAYS,
                "SUBSCRIPTION_PAYMENT_GRACE_DAYS must be between 0 and 30.",
            )
        ]

    return []


def _raw_grace_days() -> object:
    return getattr(
        settings,
        "SUBSCRIPTION_PAYMENT_GRACE_DAYS",
        DEFAULT_SUBSCRIPTION_PAYMENT_GRACE_DAYS,
    )


def _parse_grace_days(value: object) -> int:
    if value is None:
        return DEFAULT_SUBSCRIPTION_PAYMENT_GRACE_DAYS
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return DEFAULT_SUBSCRIPTION_PAYMENT_GRACE_DAYS
        if not cleaned.isdecimal():
            raise ValueError("Grace days must be a non-negative integer.")
        return int(cleaned)
    if isinstance(value, bool):
        raise ValueError("Grace days must not be a boolean.")
    if isinstance(value, int):
        return value
    raise ValueError("Grace days must be a whole number.")
