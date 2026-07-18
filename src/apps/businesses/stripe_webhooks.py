from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import BillingProviderWebhookEvent, BusinessSubscription
from .plan_catalog import normalize_public_paid_plan_slug
from .stripe_config import (
    StripeConfigurationError,
    StripePriceMetadata,
    configure_stripe_sdk,
    resolve_stripe_price_id,
)
from .subscription_grace import get_subscription_payment_grace_duration

logger = logging.getLogger(__name__)

SUPPORTED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
        "invoice.paid",
        "invoice.payment_failed",
        "checkout.session.expired",
        "invoice.payment_action_required",
    }
)

SUBSCRIPTION_EVENT_TYPES = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
    }
)

IGNORED_EVENT_TYPES = frozenset(
    {
        "checkout.session.expired",
        "invoice.payment_action_required",
    }
)

STRIPE_STATUS_TO_LOCAL_STATUS = {
    "trialing": BusinessSubscription.Status.TRIALING,
    "active": BusinessSubscription.Status.ACTIVE,
    "past_due": BusinessSubscription.Status.PAST_DUE,
    "unpaid": BusinessSubscription.Status.PAST_DUE,
    "canceled": BusinessSubscription.Status.CANCELLED,
    "incomplete": BusinessSubscription.Status.PENDING_CHECKOUT,
    "incomplete_expired": BusinessSubscription.Status.CANCELLED,
    "paused": BusinessSubscription.Status.PAST_DUE,
}

LOCAL_CHECKOUT_COMPATIBLE_STATUSES = frozenset(
    {
        BusinessSubscription.Status.PENDING_CHECKOUT,
        BusinessSubscription.Status.TRIALING,
        BusinessSubscription.Status.ACTIVE,
        BusinessSubscription.Status.PAST_DUE,
        BusinessSubscription.Status.EXPIRED,
    }
)

MAX_ERROR_LENGTH = 1000


@dataclass(frozen=True)
class StripeWebhookProcessResult:
    message: str


@dataclass(frozen=True)
class _LocalMetadata:
    business_id: int
    subscription_id: int


class StripeWebhookProcessingError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class StripeWebhookIgnored(Exception):
    pass


def begin_stripe_webhook_event(
    event: Any,
) -> tuple[BillingProviderWebhookEvent, bool]:
    event_id = _required_string(_stripe_value(event, "id"), "Stripe event ID is missing.")
    event_type = _required_string(_stripe_value(event, "type"), "Stripe event type is missing.")
    event_object = _event_data_object(event)
    object_id = str(_stripe_value(event_object, "id") or "")
    payload_summary = _payload_summary(event)

    defaults = {
        "provider": BillingProviderWebhookEvent.Provider.STRIPE,
        "event_type": event_type,
        "object_id": object_id,
        "api_version": str(_stripe_value(event, "api_version") or ""),
        "livemode": bool(_stripe_value(event, "livemode") or False),
        "payload_summary": payload_summary,
    }

    try:
        with transaction.atomic():
            event_record, _created = (
                BillingProviderWebhookEvent.objects.select_for_update().get_or_create(
                    provider=BillingProviderWebhookEvent.Provider.STRIPE,
                    event_id=event_id,
                    defaults=defaults,
                )
            )
            if event_record.status in (
                BillingProviderWebhookEvent.Status.PROCESSED,
                BillingProviderWebhookEvent.Status.IGNORED,
            ):
                return event_record, True

            event_record.event_type = event_type
            event_record.object_id = object_id
            event_record.api_version = defaults["api_version"]
            event_record.livemode = defaults["livemode"]
            event_record.payload_summary = payload_summary
            event_record.status = BillingProviderWebhookEvent.Status.PROCESSING
            event_record.attempt_count = F("attempt_count") + 1
            event_record.last_error = ""
            event_record.processed_at = None
            event_record.save(
                update_fields=[
                    "event_type",
                    "object_id",
                    "api_version",
                    "livemode",
                    "payload_summary",
                    "status",
                    "attempt_count",
                    "last_error",
                    "processed_at",
                    "updated_at",
                ]
            )
            event_record.refresh_from_db(fields=["attempt_count"])
            return event_record, False
    except IntegrityError:
        with transaction.atomic():
            event_record = BillingProviderWebhookEvent.objects.select_for_update().get(
                provider=BillingProviderWebhookEvent.Provider.STRIPE,
                event_id=event_id,
            )
            if event_record.status in (
                BillingProviderWebhookEvent.Status.PROCESSED,
                BillingProviderWebhookEvent.Status.IGNORED,
            ):
                return event_record, True

            event_record.status = BillingProviderWebhookEvent.Status.PROCESSING
            event_record.attempt_count = F("attempt_count") + 1
            event_record.last_error = ""
            event_record.processed_at = None
            event_record.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "last_error",
                    "processed_at",
                    "updated_at",
                ]
            )
            event_record.refresh_from_db(fields=["attempt_count"])
            return event_record, False


def mark_stripe_webhook_processed(
    event_record: BillingProviderWebhookEvent,
    result: StripeWebhookProcessResult,
) -> None:
    _finish_event(
        event_record=event_record,
        status=BillingProviderWebhookEvent.Status.PROCESSED,
        message=result.message,
    )


def mark_stripe_webhook_ignored(
    event_record: BillingProviderWebhookEvent,
    reason: str,
) -> None:
    _finish_event(
        event_record=event_record,
        status=BillingProviderWebhookEvent.Status.IGNORED,
        message=reason,
    )


def mark_stripe_webhook_failed(
    event_record: BillingProviderWebhookEvent,
    error: Exception,
) -> None:
    _finish_event(
        event_record=event_record,
        status=BillingProviderWebhookEvent.Status.FAILED,
        message=_truncate_error(str(error)),
    )


def process_stripe_webhook_event(
    event: Any,
    event_record: BillingProviderWebhookEvent,
) -> StripeWebhookProcessResult:
    event_type = str(_stripe_value(event, "type") or "")
    provider_event_at = _event_provider_datetime(event)
    event_object = _event_data_object(event)
    object_id = str(_stripe_value(event_object, "id") or "")

    logger.info(
        "stripe_webhook.event_received",
        extra={
            "stripe_event_id": event_record.event_id,
            "stripe_event_type": event_type,
            "stripe_object_id": object_id,
        },
    )

    if event_type not in SUPPORTED_EVENT_TYPES:
        raise StripeWebhookIgnored("Unsupported Stripe event type ignored.")

    if event_type in IGNORED_EVENT_TYPES:
        raise StripeWebhookIgnored(f"{event_type} does not change local subscription access.")

    if event_type == "checkout.session.completed":
        return _process_checkout_session_completed(
            session=event_object,
            provider_event_at=provider_event_at,
        )

    if event_type in SUBSCRIPTION_EVENT_TYPES:
        return _sync_subscription_object(
            provider_subscription=event_object,
            provider_event_at=provider_event_at,
            source=event_type,
        )

    if event_type == "invoice.paid":
        return _process_invoice_event(
            invoice=event_object,
            provider_event_at=provider_event_at,
            source=event_type,
            payment_failed=False,
        )

    if event_type == "invoice.payment_failed":
        return _process_invoice_event(
            invoice=event_object,
            provider_event_at=provider_event_at,
            source=event_type,
            payment_failed=True,
        )

    raise StripeWebhookIgnored("Stripe event type ignored.")


def _process_checkout_session_completed(
    *,
    session: Any,
    provider_event_at: datetime,
) -> StripeWebhookProcessResult:
    session_id = _required_string(
        _stripe_value(session, "id"),
        "Checkout Session ID is missing.",
    )
    mode = str(_stripe_value(session, "mode") or "").strip().lower()
    if mode != "subscription":
        raise StripeWebhookIgnored("Checkout Session is not a subscription session.")

    metadata = _metadata_dict(_stripe_value(session, "metadata"))
    local_metadata = _local_metadata_from_metadata(metadata)
    provider_subscription_id = _required_string(
        _stripe_value(session, "subscription"),
        "Checkout Session is missing a Stripe subscription ID.",
        retryable=True,
    )
    provider_customer_id = _required_string(
        _stripe_value(session, "customer"),
        "Checkout Session is missing a Stripe customer ID.",
        retryable=True,
    )

    provider_subscription = _retrieve_stripe_subscription(provider_subscription_id)
    return _sync_subscription_object(
        provider_subscription=provider_subscription,
        provider_event_at=provider_event_at,
        source="checkout.session.completed",
        local_metadata=local_metadata,
        session_id=session_id,
        customer_id=provider_customer_id,
        client_reference_id=str(_stripe_value(session, "client_reference_id") or ""),
    )


def _process_invoice_event(
    *,
    invoice: Any,
    provider_event_at: datetime,
    source: str,
    payment_failed: bool,
) -> StripeWebhookProcessResult:
    provider_subscription_id = _invoice_subscription_id(invoice)
    if not provider_subscription_id:
        raise StripeWebhookIgnored("Invoice has no Stripe subscription ID.")

    if not BusinessSubscription.objects.filter(
        payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
        provider_subscription_id=provider_subscription_id,
    ).exists():
        raise StripeWebhookIgnored("Invoice subscription is not known locally.")

    provider_subscription = _retrieve_stripe_subscription(provider_subscription_id)
    failure_context = _invoice_failure_context(invoice, provider_event_at) if payment_failed else {}
    return _sync_subscription_object(
        provider_subscription=provider_subscription,
        provider_event_at=provider_event_at,
        source=source,
        failure_context=failure_context,
    )


def _sync_subscription_object(
    *,
    provider_subscription: Any,
    provider_event_at: datetime,
    source: str,
    local_metadata: _LocalMetadata | None = None,
    session_id: str = "",
    customer_id: str = "",
    client_reference_id: str = "",
    failure_context: dict[str, Any] | None = None,
) -> StripeWebhookProcessResult:
    provider_subscription_id = _required_string(
        _stripe_value(provider_subscription, "id"),
        "Stripe subscription ID is missing.",
    )
    provider_customer_id = _required_string(
        customer_id or _stripe_value(provider_subscription, "customer"),
        "Stripe subscription customer ID is missing.",
    )
    subscription_metadata = _metadata_dict(_stripe_value(provider_subscription, "metadata"))
    resolved_metadata = local_metadata or _local_metadata_from_metadata(
        subscription_metadata,
        allow_missing=True,
    )
    failure_context = failure_context or {}

    with transaction.atomic():
        local_subscription = _locked_local_subscription(
            provider_subscription_id=provider_subscription_id,
            local_metadata=resolved_metadata,
        )
        if local_subscription is None:
            raise StripeWebhookIgnored("Stripe subscription is not known locally.")

        _validate_public_local_subscription(local_subscription)
        _validate_local_subscription_matches_metadata(
            local_subscription=local_subscription,
            metadata=subscription_metadata,
        )
        if local_metadata is not None:
            _validate_local_subscription_matches_metadata(
                local_subscription=local_subscription,
                metadata={
                    "motionmate_business_id": str(local_metadata.business_id),
                    "motionmate_subscription_id": str(local_metadata.subscription_id),
                },
            )
        _validate_client_reference_id(
            local_subscription=local_subscription,
            client_reference_id=client_reference_id,
        )
        price_metadata = _validated_subscription_price_metadata(provider_subscription)
        local_status = _local_status_for_provider_subscription(provider_subscription)
        date_values = _subscription_date_values(provider_subscription)
        _validate_price_matches_local_subscription(
            local_subscription=local_subscription,
            price_metadata=price_metadata,
        )
        _validate_provider_ids(
            local_subscription=local_subscription,
            provider_subscription_id=provider_subscription_id,
            provider_customer_id=provider_customer_id,
        )
        if source == "checkout.session.completed":
            _validate_checkout_compatible_state(local_subscription)

        update_fields = _update_provider_identity_fields(
            local_subscription=local_subscription,
            provider_subscription_id=provider_subscription_id,
            provider_customer_id=provider_customer_id,
            provider_price_id=price_metadata.price_id,
            session_id=session_id,
        )

        if _incoming_event_is_stale(
            local_subscription=local_subscription,
            provider_event_at=provider_event_at,
        ):
            if update_fields:
                local_subscription.save(update_fields=[*update_fields, "updated_at"])
            return StripeWebhookProcessResult(
                f"{source} ignored because a newer Stripe event was already applied."
            )

        update_fields.extend(
            _update_subscription_state_fields(
                local_subscription=local_subscription,
                local_status=local_status,
                provider_event_at=provider_event_at,
                date_values=date_values,
                failure_context=failure_context,
            )
        )

        if update_fields:
            local_subscription.save(update_fields=[*sorted(set(update_fields)), "updated_at"])

    return StripeWebhookProcessResult(f"{source} synchronized local subscription.")


def _retrieve_stripe_subscription(provider_subscription_id: str) -> Any:
    try:
        stripe_client = configure_stripe_sdk()
        return stripe_client.Subscription.retrieve(
            provider_subscription_id,
            expand=["items.data.price"],
        )
    except StripeConfigurationError as exc:
        raise StripeWebhookProcessingError(str(exc), retryable=True) from exc
    except Exception as exc:
        raise StripeWebhookProcessingError(
            "Stripe subscription could not be retrieved.",
            retryable=True,
        ) from exc


def _locked_local_subscription(
    *,
    provider_subscription_id: str,
    local_metadata: _LocalMetadata | None,
) -> BusinessSubscription | None:
    queryset = BusinessSubscription.objects.select_for_update().select_related("business", "plan")
    local_subscription = queryset.filter(
        payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
        provider_subscription_id=provider_subscription_id,
    ).first()
    if local_subscription is not None:
        if local_metadata is not None and (
            local_subscription.pk != local_metadata.subscription_id
            or local_subscription.business_id != local_metadata.business_id
        ):
            raise StripeWebhookProcessingError(
                "Stripe subscription metadata does not match the local subscription."
            )
        return local_subscription

    if local_metadata is None:
        return None

    return queryset.filter(
        pk=local_metadata.subscription_id,
        business_id=local_metadata.business_id,
    ).first()


def _validate_public_local_subscription(local_subscription: BusinessSubscription) -> None:
    if local_subscription.plan is None or not local_subscription.plan.is_active:
        raise StripeWebhookProcessingError("Local subscription plan is not active.")
    if normalize_public_paid_plan_slug(local_subscription.plan.slug) is None:
        raise StripeWebhookIgnored("Local subscription is not a public paid Stripe plan.")
    if local_subscription.payment_provider not in (
        "",
        BusinessSubscription.PaymentProvider.STRIPE,
    ):
        raise StripeWebhookProcessingError("Local subscription uses a different provider.")


def _validate_local_subscription_matches_metadata(
    *,
    local_subscription: BusinessSubscription,
    metadata: dict[str, str],
) -> None:
    if not metadata:
        return

    expected_values = {
        "motionmate_business_id": str(local_subscription.business_id),
        "motionmate_subscription_id": str(local_subscription.pk),
        "plan_slug": local_subscription.plan.slug,
        "billing_interval": local_subscription.billing_interval,
        "billing_currency": local_subscription.billing_currency,
    }
    for key, expected_value in expected_values.items():
        actual_value = metadata.get(key)
        if actual_value is not None and str(actual_value) != expected_value:
            raise StripeWebhookProcessingError(
                "Stripe metadata does not match the local subscription."
            )


def _validate_client_reference_id(
    *,
    local_subscription: BusinessSubscription,
    client_reference_id: str,
) -> None:
    if not client_reference_id:
        return
    expected = f"business:{local_subscription.business_id}:subscription:{local_subscription.pk}"
    if client_reference_id != expected:
        raise StripeWebhookProcessingError("Checkout Session reference does not match locally.")


def _validate_price_matches_local_subscription(
    *,
    local_subscription: BusinessSubscription,
    price_metadata: StripePriceMetadata,
) -> None:
    if local_subscription.plan.slug != price_metadata.plan_slug:
        raise StripeWebhookProcessingError("Stripe Price does not match the local plan.")
    if local_subscription.billing_interval != price_metadata.billing_interval:
        raise StripeWebhookProcessingError("Stripe Price does not match the local interval.")
    if local_subscription.billing_currency != price_metadata.currency:
        raise StripeWebhookProcessingError("Stripe Price does not match the local currency.")
    if (
        local_subscription.provider_price_id
        and local_subscription.provider_price_id != price_metadata.price_id
    ):
        raise StripeWebhookProcessingError("Stripe Price does not match the stored local Price ID.")


def _validate_provider_ids(
    *,
    local_subscription: BusinessSubscription,
    provider_subscription_id: str,
    provider_customer_id: str,
) -> None:
    if (
        local_subscription.provider_subscription_id
        and local_subscription.provider_subscription_id != provider_subscription_id
    ):
        raise StripeWebhookProcessingError("Stripe subscription ID conflicts with local state.")
    if (
        local_subscription.provider_customer_id
        and local_subscription.provider_customer_id != provider_customer_id
    ):
        raise StripeWebhookProcessingError("Stripe customer ID conflicts with local state.")


def _validate_checkout_compatible_state(local_subscription: BusinessSubscription) -> None:
    if local_subscription.status not in LOCAL_CHECKOUT_COMPATIBLE_STATUSES:
        raise StripeWebhookProcessingError("Local subscription is not compatible with checkout.")


def _update_provider_identity_fields(
    *,
    local_subscription: BusinessSubscription,
    provider_subscription_id: str,
    provider_customer_id: str,
    provider_price_id: str,
    session_id: str,
) -> list[str]:
    update_fields: list[str] = []
    desired_values = {
        "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
        "provider_subscription_id": provider_subscription_id,
        "provider_customer_id": provider_customer_id,
        "provider_price_id": provider_price_id,
    }
    if session_id:
        desired_values["provider_checkout_session_id"] = session_id

    for field_name, value in desired_values.items():
        if getattr(local_subscription, field_name) != value:
            setattr(local_subscription, field_name, value)
            update_fields.append(field_name)

    return update_fields


def _update_subscription_state_fields(
    *,
    local_subscription: BusinessSubscription,
    local_status: str,
    provider_event_at: datetime,
    date_values: dict[str, datetime | bool | None],
    failure_context: dict[str, Any],
) -> list[str]:
    update_fields: list[str] = []
    desired_values: dict[str, Any] = {
        "status": local_status,
        "provider_updated_at": provider_event_at,
        **date_values,
    }
    if failure_context:
        failure_at = failure_context.get("failure_at", provider_event_at)
    else:
        failure_at = provider_event_at

    if local_status == BusinessSubscription.Status.PAST_DUE:
        past_due_since = local_subscription.past_due_since or failure_at
        desired_values["past_due_since"] = past_due_since
        desired_values["grace_period_ends_at"] = (
            local_subscription.grace_period_ends_at
            or past_due_since + get_subscription_payment_grace_duration()
        )
        if failure_context and (
            local_subscription.last_payment_failure_at is None
            or failure_at > local_subscription.last_payment_failure_at
        ):
            desired_values["last_payment_failure_at"] = failure_at
            desired_values["last_payment_failure_reason"] = failure_context.get(
                "failure_reason",
                "",
            )
    elif local_status in (
        BusinessSubscription.Status.TRIALING,
        BusinessSubscription.Status.ACTIVE,
        BusinessSubscription.Status.PENDING_CHECKOUT,
        BusinessSubscription.Status.CANCELLED,
        BusinessSubscription.Status.EXPIRED,
    ):
        desired_values["past_due_since"] = None
        desired_values["grace_period_ends_at"] = None

    for field_name, value in desired_values.items():
        if getattr(local_subscription, field_name) != value:
            setattr(local_subscription, field_name, value)
            update_fields.append(field_name)

    return update_fields


def _incoming_event_is_stale(
    *,
    local_subscription: BusinessSubscription,
    provider_event_at: datetime,
) -> bool:
    return (
        local_subscription.provider_updated_at is not None
        and provider_event_at < local_subscription.provider_updated_at
    )


def _validated_subscription_price_metadata(provider_subscription: Any) -> StripePriceMetadata:
    price = _single_subscription_price(provider_subscription)
    price_id = _required_string(_stripe_value(price, "id"), "Stripe subscription Price ID missing.")

    try:
        price_metadata = resolve_stripe_price_id(price_id)
    except StripeConfigurationError as exc:
        raise StripeWebhookProcessingError(str(exc), retryable=True) from exc

    price_currency = _stripe_value(price, "currency")
    if price_currency and str(price_currency).strip().lower() != price_metadata.currency:
        raise StripeWebhookProcessingError("Stripe Price currency does not match configuration.")

    recurring = _stripe_value(price, "recurring") or {}
    price_interval = _stripe_value(recurring, "interval")
    if price_interval:
        normalized_interval = _stripe_interval_to_local(price_interval)
        if normalized_interval != price_metadata.billing_interval:
            raise StripeWebhookProcessingError(
                "Stripe Price interval does not match configuration."
            )

    return price_metadata


def _single_subscription_price(provider_subscription: Any) -> Any:
    items = _stripe_value(provider_subscription, "items") or {}
    item_data = _stripe_value(items, "data") or []
    recurring_items = []
    for item in item_data:
        price = _stripe_value(item, "price")
        if price is None:
            continue
        recurring = _stripe_value(price, "recurring")
        if recurring is None:
            continue
        recurring_items.append(price)

    if len(recurring_items) != 1:
        raise StripeWebhookProcessingError(
            "Stripe subscription must contain exactly one recurring Price."
        )
    return recurring_items[0]


def _local_status_for_provider_subscription(provider_subscription: Any) -> str:
    provider_status = str(_stripe_value(provider_subscription, "status") or "").strip().lower()
    local_status = STRIPE_STATUS_TO_LOCAL_STATUS.get(provider_status)
    if local_status is None:
        raise StripeWebhookProcessingError(
            f"Unsupported Stripe subscription status: {provider_status}."
        )
    return local_status


def _subscription_date_values(provider_subscription: Any) -> dict[str, datetime | bool | None]:
    stripe_cancelled_at = _stripe_value(provider_subscription, "canceled_at")
    return {
        "trial_start": _stripe_timestamp_to_datetime(
            _stripe_value(provider_subscription, "trial_start")
        ),
        "trial_end": _stripe_timestamp_to_datetime(
            _stripe_value(provider_subscription, "trial_end")
        ),
        "current_period_start": _stripe_timestamp_to_datetime(
            _stripe_value(provider_subscription, "current_period_start")
        ),
        "current_period_end": _stripe_timestamp_to_datetime(
            _stripe_value(provider_subscription, "current_period_end")
        ),
        "cancel_at_period_end": bool(_stripe_value(provider_subscription, "cancel_at_period_end")),
        "cancelled_at": _stripe_timestamp_to_datetime(stripe_cancelled_at),
    }


def _invoice_subscription_id(invoice: Any) -> str:
    subscription_id = _stripe_value(invoice, "subscription")
    if subscription_id:
        return str(subscription_id)

    parent = _stripe_value(invoice, "parent") or {}
    subscription_details = _stripe_value(parent, "subscription_details") or {}
    subscription = _stripe_value(subscription_details, "subscription")
    if isinstance(subscription, dict):
        return str(subscription.get("id") or "")
    return str(subscription or "")


def _invoice_failure_context(invoice: Any, provider_event_at: datetime) -> dict[str, Any]:
    return {
        "failure_at": provider_event_at,
        "failure_reason": "payment_failed",
    }


def _payload_summary(event: Any) -> dict[str, Any]:
    event_object = _event_data_object(event)
    metadata = _metadata_dict(_stripe_value(event_object, "metadata"))
    provider_subscription_id = (
        _stripe_value(event_object, "subscription") or _stripe_value(event_object, "id")
        if str(_stripe_value(event_object, "object") or "") == "subscription"
        else _stripe_value(event_object, "subscription")
    )
    return {
        "type": str(_stripe_value(event, "type") or ""),
        "object": str(_stripe_value(event_object, "object") or ""),
        "object_id": str(_stripe_value(event_object, "id") or ""),
        "provider_subscription_id": str(provider_subscription_id or ""),
        "motionmate_business_id": metadata.get("motionmate_business_id", ""),
        "motionmate_subscription_id": metadata.get("motionmate_subscription_id", ""),
    }


def _finish_event(
    *,
    event_record: BillingProviderWebhookEvent,
    status: str,
    message: str,
) -> None:
    now = timezone.now()
    with transaction.atomic():
        locked_event = BillingProviderWebhookEvent.objects.select_for_update().get(
            pk=event_record.pk
        )
        summary = dict(locked_event.payload_summary or {})
        summary["result"] = message
        locked_event.status = status
        locked_event.processed_at = now
        locked_event.last_error = (
            message if status == BillingProviderWebhookEvent.Status.FAILED else ""
        )
        locked_event.payload_summary = summary
        locked_event.save(
            update_fields=[
                "status",
                "processed_at",
                "last_error",
                "payload_summary",
                "updated_at",
            ]
        )


def _local_metadata_from_metadata(
    metadata: dict[str, str],
    *,
    allow_missing: bool = False,
) -> _LocalMetadata | None:
    business_id = metadata.get("motionmate_business_id")
    subscription_id = metadata.get("motionmate_subscription_id")
    if not business_id and not subscription_id:
        if allow_missing:
            return None
        raise StripeWebhookIgnored("Stripe object is not tagged for Motionmate.")
    if not business_id or not subscription_id:
        raise StripeWebhookProcessingError("Stripe Motionmate metadata is incomplete.")

    try:
        return _LocalMetadata(
            business_id=int(business_id),
            subscription_id=int(subscription_id),
        )
    except (TypeError, ValueError) as exc:
        raise StripeWebhookProcessingError("Stripe Motionmate metadata is invalid.") from exc


def _event_provider_datetime(event: Any) -> datetime:
    provider_timestamp = _stripe_timestamp_to_datetime(_stripe_value(event, "created"))
    if provider_timestamp is None:
        raise StripeWebhookProcessingError("Stripe event timestamp is missing.")
    return provider_timestamp


def _event_data_object(event: Any) -> Any:
    data = _stripe_value(event, "data") or {}
    return _stripe_value(data, "object") or {}


def _metadata_dict(metadata: Any) -> dict[str, str]:
    if metadata is None:
        return {}
    if hasattr(metadata, "to_dict_recursive"):
        metadata = metadata.to_dict_recursive()
    elif hasattr(metadata, "to_dict"):
        metadata = metadata.to_dict()
    if not isinstance(metadata, dict):
        return {}
    return {str(key): str(value) for key, value in metadata.items()}


def _stripe_value(stripe_object: Any, field_name: str) -> Any:
    if isinstance(stripe_object, dict):
        return stripe_object.get(field_name)
    return getattr(stripe_object, field_name, None)


def _stripe_timestamp_to_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError) as exc:
        raise StripeWebhookProcessingError("Stripe timestamp could not be parsed.") from exc


def _stripe_interval_to_local(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "month":
        return BusinessSubscription.BillingInterval.MONTHLY
    if normalized == "year":
        return BusinessSubscription.BillingInterval.YEARLY
    raise StripeWebhookProcessingError("Stripe Price interval is unsupported.")


def _required_string(
    value: Any,
    message: str,
    *,
    retryable: bool = False,
) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise StripeWebhookProcessingError(message, retryable=retryable)
    return cleaned


def _truncate_error(value: str) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned[:MAX_ERROR_LENGTH]
