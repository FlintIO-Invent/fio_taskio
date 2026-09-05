from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .business_data_inventory import BusinessDataInventory, build_business_data_inventory
from .business_sessions import (
    BusinessSessionInvalidationSummary,
    SelectiveSessionInvalidationUnavailable,
    invalidate_business_sessions,
    plan_business_session_invalidation,
)
from .models import Business, BusinessDataOperation, SubscriptionNotification

REASON_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
DEACTIVATABLE_NOTIFICATION_STATUSES = (
    SubscriptionNotification.Status.PENDING,
    SubscriptionNotification.Status.PROCESSING,
    SubscriptionNotification.Status.FAILED,
)
INACTIVE_NOTIFICATION_REASON = "Delivery cancelled because workspace is inactive."


class BusinessDeactivationError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class BusinessDeactivationPlan:
    business_id: int
    business_slug: str
    business_is_active: bool
    inventory: BusinessDataInventory
    pending_notification_count: int
    session_summary: BusinessSessionInvalidationSummary

    @property
    def change_required(self) -> bool:
        return self.business_is_active


@dataclass(frozen=True, slots=True)
class BusinessDeactivationResult:
    plan: BusinessDeactivationPlan
    changed: bool
    notification_count_cancelled: int
    session_summary: BusinessSessionInvalidationSummary
    audit_operation_id: str | None


def plan_business_deactivation(
    business_id: int,
    *,
    reason_reference: str | None = None,
) -> BusinessDeactivationPlan:
    """Build a read-only deactivation plan for one exact Business primary key."""
    business_id = _validate_business_id(business_id)
    if reason_reference is not None:
        _validate_reason_reference(reason_reference)
    try:
        business = Business.objects.get(pk=business_id)
    except Business.DoesNotExist as exc:
        raise BusinessDeactivationError(
            "business_not_found",
            "No business exists with the supplied exact primary key.",
        ) from exc
    return _build_deactivation_plan(business)


def deactivate_business(
    *,
    business_id: int,
    reason_reference: str,
    operator_id: int | None = None,
) -> BusinessDeactivationResult:
    """Deactivate a Business without deleting tenant, user, plan, or billing data."""
    business_id = _validate_business_id(business_id)
    reason_reference = _validate_reason_reference(reason_reference)
    operator_id = _validate_operator_id(operator_id)

    existing = Business.objects.filter(pk=business_id).only("id", "is_active").first()
    if existing is None:
        raise BusinessDeactivationError(
            "business_not_found",
            "No business exists with the supplied exact primary key.",
        )
    if not existing.is_active:
        plan = _build_deactivation_plan(existing)
        return BusinessDeactivationResult(
            plan=plan,
            changed=False,
            notification_count_cancelled=0,
            session_summary=plan.session_summary,
            audit_operation_id=None,
        )

    operation = BusinessDataOperation.objects.create(
        business_id_snapshot=business_id,
        operator_id_snapshot=operator_id,
        mode=BusinessDataOperation.Mode.DEACTIVATE,
        status=BusinessDataOperation.Status.STARTED,
        reason_reference=reason_reference,
        record_counts={},
    )

    try:
        with transaction.atomic():
            try:
                business = Business.objects.select_for_update().get(pk=business_id)
            except Business.DoesNotExist as exc:
                raise BusinessDeactivationError(
                    "business_disappeared",
                    "The selected business no longer exists.",
                ) from exc

            plan = _build_deactivation_plan(business)
            if not business.is_active:
                record_counts = _audit_record_counts(
                    plan.inventory,
                    notification_count_cancelled=0,
                    session_summary=plan.session_summary,
                )
                _complete_operation(operation, record_counts)
                return BusinessDeactivationResult(
                    plan=plan,
                    changed=False,
                    notification_count_cancelled=0,
                    session_summary=plan.session_summary,
                    audit_operation_id=str(operation.operation_id),
                )

            if plan.inventory.summary.cross_tenant_integrity_blocker_count:
                raise BusinessDeactivationError(
                    "cross_tenant_integrity_blockers",
                    "Cross-tenant integrity blockers must be resolved before deactivation.",
                )

            notification_count_cancelled = _cancel_pending_notifications(business_id)
            session_summary = invalidate_business_sessions(business_id)

            business.is_active = False
            business.save(update_fields=["is_active", "updated_at"])

            record_counts = _audit_record_counts(
                plan.inventory,
                notification_count_cancelled=notification_count_cancelled,
                session_summary=session_summary,
            )
            _complete_operation(operation, record_counts)
    except BusinessDeactivationError as exc:
        _fail_operation(operation, exc.error_code)
        raise
    except SelectiveSessionInvalidationUnavailable as exc:
        error = BusinessDeactivationError(
            "session_backend_unsupported",
            "Selective session invalidation is unavailable for the configured backend.",
        )
        _fail_operation(operation, error.error_code)
        raise error from exc
    except Exception as exc:
        error = BusinessDeactivationError(
            "deactivation_failed",
            "Business deactivation failed safely; no tenant records were deleted.",
        )
        _fail_operation(operation, error.error_code)
        raise error from exc

    return BusinessDeactivationResult(
        plan=plan,
        changed=True,
        notification_count_cancelled=notification_count_cancelled,
        session_summary=session_summary,
        audit_operation_id=str(operation.operation_id),
    )


def _build_deactivation_plan(business: Business) -> BusinessDeactivationPlan:
    inventory = build_business_data_inventory(business)
    if business.is_active:
        try:
            session_summary = plan_business_session_invalidation(business.pk)
        except SelectiveSessionInvalidationUnavailable as exc:
            raise BusinessDeactivationError(
                "session_backend_unsupported",
                "Selective session invalidation is unavailable for the configured backend.",
            ) from exc
        pending_notification_count = SubscriptionNotification.objects.filter(
            business_id=business.pk,
            status__in=DEACTIVATABLE_NOTIFICATION_STATUSES,
        ).count()
    else:
        session_summary = BusinessSessionInvalidationSummary(0, 0, 0, 0)
        pending_notification_count = 0

    return BusinessDeactivationPlan(
        business_id=business.pk,
        business_slug=business.slug,
        business_is_active=business.is_active,
        inventory=inventory,
        pending_notification_count=pending_notification_count,
        session_summary=session_summary,
    )


def _cancel_pending_notifications(business_id: int) -> int:
    return SubscriptionNotification.objects.filter(
        business_id=business_id,
        status__in=DEACTIVATABLE_NOTIFICATION_STATUSES,
    ).update(
        status=SubscriptionNotification.Status.CANCELLED,
        last_error=INACTIVE_NOTIFICATION_REASON,
        updated_at=timezone.now(),
    )


def _audit_record_counts(
    inventory: BusinessDataInventory,
    *,
    notification_count_cancelled: int,
    session_summary: BusinessSessionInvalidationSummary,
) -> dict[str, int]:
    record_counts = {record.key: record.total_count for record in inventory.records}
    record_counts.update(
        {
            "total_owned_records": (inventory.summary.total_directly_and_indirectly_owned_records),
            "cross_tenant_integrity_blockers": (
                inventory.summary.cross_tenant_integrity_blocker_count
            ),
            "notifications_cancelled": notification_count_cancelled,
            **session_summary.to_record_counts(),
        }
    )
    return record_counts


def _complete_operation(
    operation: BusinessDataOperation,
    record_counts: dict[str, int],
) -> None:
    operation.status = BusinessDataOperation.Status.COMPLETED
    operation.record_counts = record_counts
    operation.completed_at = timezone.now()
    operation.error_code = ""
    operation.save(update_fields=["status", "record_counts", "completed_at", "error_code"])


def _fail_operation(operation: BusinessDataOperation, error_code: str) -> None:
    BusinessDataOperation.objects.filter(pk=operation.pk).update(
        status=BusinessDataOperation.Status.FAILED,
        completed_at=timezone.now(),
        error_code=error_code,
        record_counts={},
    )


def _validate_business_id(value: object) -> int:
    if isinstance(value, bool):
        raise BusinessDeactivationError(
            "invalid_business_id",
            "Business ID must be a positive integer.",
        )
    try:
        business_id = int(str(value))
    except (TypeError, ValueError) as exc:
        raise BusinessDeactivationError(
            "invalid_business_id",
            "Business ID must be a positive integer.",
        ) from exc
    if business_id <= 0:
        raise BusinessDeactivationError(
            "invalid_business_id",
            "Business ID must be a positive integer.",
        )
    return business_id


def _validate_operator_id(value: object) -> int | None:
    if value is None:
        return None
    operator_id = _validate_business_id(value)
    return operator_id


def _validate_reason_reference(value: object) -> str:
    normalized = str(value or "").strip()
    if not REASON_REFERENCE_PATTERN.fullmatch(normalized):
        raise BusinessDeactivationError(
            "invalid_reason_reference",
            "Reason reference must be 1-120 reference characters without spaces or email text.",
        )
    return normalized
