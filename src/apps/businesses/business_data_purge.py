from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice, InvoiceLine
from apps.crm.models import ActivityLog, BusinessService, Client, Lead, ServiceCategory

from .business_data_inventory import (
    DIRECT_BUSINESS_RELATION_REGISTRY,
    BusinessDataInventory,
    build_business_data_inventory,
)
from .business_data_operations import REASON_REFERENCE_PATTERN
from .business_resolution import BusinessResolutionError, resolve_business_candidates
from .business_sessions import (
    BusinessSessionInvalidationSummary,
    SelectiveSessionInvalidationUnavailable,
    invalidate_business_sessions,
    plan_business_session_invalidation,
)
from .models import (
    Business,
    BusinessBookingSettings,
    BusinessDataOperation,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    SubscriptionNotification,
    UserOnboardingState,
    WeeklyAvailability,
)

PURGE_DELETION_ORDER = (
    "invoice_lines",
    "invoices",
    "appointments",
    "activity_logs",
    "leads",
    "clients",
    "business_services",
    "service_categories",
    "business_invitations",
    "user_onboarding_states",
    "weekly_availability",
    "subscription_notifications",
    "business_subscription",
    "business_booking_settings",
    "business_users",
    "eligible_users",
    "business",
)


class BusinessPurgeError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class UserPurgeDecision:
    user_id: int
    delete: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BusinessPurgePlan:
    business_id: int
    business_slug: str
    business_is_active: bool
    inventory: BusinessDataInventory
    session_summary: BusinessSessionInvalidationSummary
    user_decisions: tuple[UserPurgeDecision, ...]
    confirm_test_financial_data: bool
    delete_eligible_users: bool

    @property
    def invoice_confirmation_required(self) -> bool:
        return bool(
            self.inventory.billing_assessment.invoice_count and not self.confirm_test_financial_data
        )

    @property
    def has_stripe_references(self) -> bool:
        billing = self.inventory.billing_assessment
        return bool(
            billing.provider_customer_id_present
            or billing.provider_subscription_id_present
            or billing.provider_checkout_id_present
            or billing.correlated_webhook_event_count
        )

    @property
    def has_inventory_registry_blocker(self) -> bool:
        return any(
            check.check_code == "inventory_registry_unregistered_business_relation"
            and check.affected_count
            for check in self.inventory.integrity_checks
        )

    @property
    def blocking_error_codes(self) -> tuple[str, ...]:
        blockers = []
        if self.business_is_active:
            blockers.append("business_active")
        if self.inventory.summary.cross_tenant_integrity_blocker_count:
            blockers.append("cross_tenant_integrity_blockers")
        if self.has_inventory_registry_blocker:
            blockers.append("inventory_registry_incomplete")
        if self.has_stripe_references:
            blockers.append("stripe_references_present")
        if self.invoice_confirmation_required:
            blockers.append("test_financial_data_confirmation_required")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class BusinessPurgeResult:
    business_id: int
    purged: bool
    already_absent: bool
    deletion_counts: dict[str, int]
    user_decisions: tuple[UserPurgeDecision, ...]
    session_summary: BusinessSessionInvalidationSummary
    audit_operation_id: str | None


def plan_business_purge(
    business_id: int,
    *,
    confirm_test_financial_data: bool = False,
    delete_eligible_users: bool = False,
    operator_id: int | None = None,
) -> BusinessPurgePlan | None:
    """Return a read-only purge plan selected only by exact Business primary key."""
    business_id = _validate_positive_id(business_id, "invalid_business_id")
    operator_id = _validate_optional_operator_id(operator_id)
    try:
        candidates = resolve_business_candidates(business_id=str(business_id))
    except BusinessResolutionError as exc:
        raise BusinessPurgeError("invalid_business_id", str(exc)) from exc
    if not candidates:
        return None

    business = Business.objects.get(pk=candidates[0].business_id)
    return _build_purge_plan(
        business,
        confirm_test_financial_data=confirm_test_financial_data,
        delete_eligible_users=delete_eligible_users,
        operator_id=operator_id,
    )


def purge_business(
    *,
    business_id: int,
    reason_reference: str,
    confirm_test_financial_data: bool = False,
    delete_eligible_users: bool = False,
    operator_id: int | None = None,
) -> BusinessPurgeResult:
    """Permanently purge one inactive test/demo tenant after all safety gates pass."""
    business_id = _validate_positive_id(business_id, "invalid_business_id")
    reason_reference = _validate_reason_reference(reason_reference)
    operator_id = _validate_optional_operator_id(operator_id)

    pending_error: BusinessPurgeError | None = None
    with transaction.atomic():
        business = Business.objects.select_for_update().filter(pk=business_id).first()
        if business is None:
            return _absent_result(business_id)

        operation = BusinessDataOperation.objects.create(
            business_id_snapshot=business_id,
            operator_id_snapshot=operator_id,
            mode=BusinessDataOperation.Mode.PURGE,
            status=BusinessDataOperation.Status.STARTED,
            reason_reference=reason_reference,
            record_counts={},
        )

        try:
            # The savepoint rolls tenant changes back while allowing the outer
            # transaction to preserve a machine-readable failed audit record.
            with transaction.atomic():
                plan = _build_purge_plan(
                    business,
                    confirm_test_financial_data=confirm_test_financial_data,
                    delete_eligible_users=delete_eligible_users,
                    operator_id=operator_id,
                )
                _enforce_purge_safety(plan)

                session_summary = invalidate_business_sessions(business_id)
                deletion_counts = _delete_business_records(
                    business=business,
                    user_decisions=plan.user_decisions,
                )
                _verify_purge_complete(business_id)

                record_counts = _audit_record_counts(
                    inventory=plan.inventory,
                    deletion_counts=deletion_counts,
                    session_summary=session_summary,
                    user_decisions=plan.user_decisions,
                )
                _complete_operation(operation, record_counts)
        except BusinessPurgeError as exc:
            pending_error = exc
        except SelectiveSessionInvalidationUnavailable as exc:
            pending_error = BusinessPurgeError(
                "session_backend_unsupported",
                "Selective session invalidation is unavailable for the configured backend.",
            )
            pending_error.__cause__ = exc
        except Exception as exc:
            pending_error = BusinessPurgeError(
                "purge_failed",
                "Business purge failed safely and tenant-data changes were rolled back.",
            )
            pending_error.__cause__ = exc

        if pending_error is not None:
            _fail_operation(operation, pending_error.error_code)

    if pending_error is not None:
        raise pending_error

    return BusinessPurgeResult(
        business_id=business_id,
        purged=True,
        already_absent=False,
        deletion_counts=deletion_counts,
        user_decisions=plan.user_decisions,
        session_summary=session_summary,
        audit_operation_id=str(operation.operation_id),
    )


def _build_purge_plan(
    business: Business,
    *,
    confirm_test_financial_data: bool,
    delete_eligible_users: bool,
    operator_id: int | None,
) -> BusinessPurgePlan:
    inventory = build_business_data_inventory(business)
    try:
        session_summary = plan_business_session_invalidation(business.pk)
    except SelectiveSessionInvalidationUnavailable as exc:
        raise BusinessPurgeError(
            "session_backend_unsupported",
            "Selective session invalidation is unavailable for the configured backend.",
        ) from exc
    return BusinessPurgePlan(
        business_id=business.pk,
        business_slug=business.slug,
        business_is_active=business.is_active,
        inventory=inventory,
        session_summary=session_summary,
        user_decisions=_build_user_purge_decisions(
            business_id=business.pk,
            delete_eligible_users=delete_eligible_users,
            operator_id=operator_id,
        ),
        confirm_test_financial_data=confirm_test_financial_data,
        delete_eligible_users=delete_eligible_users,
    )


def _enforce_purge_safety(plan: BusinessPurgePlan) -> None:
    messages = {
        "business_active": "The business must be deactivated before permanent purge.",
        "cross_tenant_integrity_blockers": (
            "Cross-tenant integrity blockers must be resolved before permanent purge."
        ),
        "inventory_registry_incomplete": (
            "The tenant-data inventory registry is incomplete; purge is not safe."
        ),
        "stripe_references_present": (
            "Stripe customer, subscription, checkout, or webhook references block purge."
        ),
        "test_financial_data_confirmation_required": (
            "Invoices require --confirm-test-financial-data and may only be purged when "
            "they are approved test/demo records."
        ),
    }
    if plan.blocking_error_codes:
        error_code = plan.blocking_error_codes[0]
        raise BusinessPurgeError(error_code, messages[error_code])


def _build_user_purge_decisions(
    *,
    business_id: int,
    delete_eligible_users: bool,
    operator_id: int | None,
) -> tuple[UserPurgeDecision, ...]:
    memberships = list(
        BusinessUser.objects.filter(business_id=business_id)
        .select_related("user")
        .order_by("user_id")
    )
    decisions = []
    for membership in memberships:
        user = membership.user
        reasons: list[str] = []
        if not delete_eligible_users:
            reasons.append("preserved_by_default")
        else:
            if (
                BusinessUser.objects.filter(user_id=user.pk)
                .exclude(business_id=business_id)
                .exists()
            ):
                reasons.append("other_memberships")
            if user.is_staff:
                reasons.append("staff_user")
            if user.is_superuser:
                reasons.append("superuser")
            if operator_id is not None and user.pk == operator_id:
                reasons.append("command_operator")
            if _has_cross_business_operational_references(
                user_id=user.pk,
                business_id=business_id,
            ):
                reasons.append("cross_business_operational_references")
        decisions.append(
            UserPurgeDecision(
                user_id=user.pk,
                delete=delete_eligible_users and not reasons,
                reason_codes=tuple(reasons),
            )
        )
    return tuple(decisions)


def _has_cross_business_operational_references(*, user_id: int, business_id: int) -> bool:
    reference_specs = (
        (WeeklyAvailability, "staff_member_id"),
        (Appointment, "staff_member_id"),
        (Client, "assigned_to_id"),
        (ActivityLog, "actor_id"),
        (UserOnboardingState, "user_id"),
        (SubscriptionNotification, "recipient_user_id"),
        (BusinessInvitation, "invited_by_id"),
        (BusinessInvitation, "accepted_by_id"),
    )
    return any(
        model._default_manager.filter(**{user_field: user_id})
        .exclude(business_id=business_id)
        .exists()
        for model, user_field in reference_specs
    )


def _delete_business_records(
    *,
    business: Business,
    user_decisions: tuple[UserPurgeDecision, ...],
) -> dict[str, int]:
    business_id = business.pk
    deletion_counts = {
        "invoice_lines": _delete_queryset(
            InvoiceLine.objects.filter(invoice__business_id=business_id)
        ),
        "invoices": _delete_queryset(Invoice.objects.filter(business_id=business_id)),
        "appointments": _delete_queryset(Appointment.objects.filter(business_id=business_id)),
        "activity_logs": _delete_queryset(ActivityLog.objects.filter(business_id=business_id)),
        "leads": _delete_queryset(Lead.objects.filter(business_id=business_id)),
        "clients": _delete_queryset(Client.objects.filter(business_id=business_id)),
        "business_services": _delete_queryset(
            BusinessService.objects.filter(business_id=business_id)
        ),
        "service_categories": _delete_queryset(
            ServiceCategory.objects.filter(business_id=business_id)
        ),
        "business_invitations": _delete_queryset(
            BusinessInvitation.objects.filter(business_id=business_id)
        ),
        "user_onboarding_states": _delete_queryset(
            UserOnboardingState.objects.filter(business_id=business_id)
        ),
        "weekly_availability": _delete_queryset(
            WeeklyAvailability.objects.filter(business_id=business_id)
        ),
        "subscription_notifications": _delete_queryset(
            SubscriptionNotification.objects.filter(business_id=business_id)
        ),
        "business_subscription": _delete_queryset(
            BusinessSubscription.objects.filter(business_id=business_id)
        ),
        "business_booking_settings": _delete_queryset(
            BusinessBookingSettings.objects.filter(business_id=business_id)
        ),
        "business_users": _delete_queryset(BusinessUser.objects.filter(business_id=business_id)),
    }
    eligible_user_ids = tuple(decision.user_id for decision in user_decisions if decision.delete)
    deletion_counts["eligible_users"] = _delete_queryset(
        TaskIOUser.objects.filter(pk__in=eligible_user_ids)
    )
    deletion_counts["business"] = _delete_queryset(Business.objects.filter(pk=business_id))
    return deletion_counts


def _delete_queryset(queryset) -> int:
    count = queryset.count()
    queryset.delete()
    return count


def _verify_purge_complete(business_id: int) -> None:
    remaining = []
    if Business.objects.filter(pk=business_id).exists():
        remaining.append("business")
    for registration in DIRECT_BUSINESS_RELATION_REGISTRY:
        model = apps.get_model(registration.model_label)
        if model._default_manager.filter(
            **{f"{registration.business_field}_id": business_id}
        ).exists():
            remaining.append(registration.key)
    if InvoiceLine.objects.filter(invoice__business_id=business_id).exists():
        remaining.append("invoice_lines")
    session_summary = plan_business_session_invalidation(business_id)
    if session_summary.target_business_sessions:
        remaining.append("sessions")
    if remaining:
        raise BusinessPurgeError(
            "purge_verification_failed",
            "Registered tenant-owned records remain after purge execution.",
        )


def _audit_record_counts(
    *,
    inventory: BusinessDataInventory,
    deletion_counts: dict[str, int],
    session_summary: BusinessSessionInvalidationSummary,
    user_decisions: tuple[UserPurgeDecision, ...],
) -> dict[str, int]:
    counts = {f"inventory_{record.key}": record.total_count for record in inventory.records}
    counts.update({f"deleted_{key}": value for key, value in deletion_counts.items()})
    counts.update(session_summary.to_record_counts())
    counts["users_preserved"] = sum(not decision.delete for decision in user_decisions)
    counts["users_deleted"] = sum(decision.delete for decision in user_decisions)
    counts["cross_tenant_integrity_blockers"] = (
        inventory.summary.cross_tenant_integrity_blocker_count
    )
    return counts


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


def _absent_result(business_id: int) -> BusinessPurgeResult:
    return BusinessPurgeResult(
        business_id=business_id,
        purged=False,
        already_absent=True,
        deletion_counts={},
        user_decisions=(),
        session_summary=BusinessSessionInvalidationSummary(0, 0, 0, 0),
        audit_operation_id=None,
    )


def _validate_positive_id(value: object, error_code: str) -> int:
    if isinstance(value, bool):
        raise BusinessPurgeError(error_code, "ID must be a positive integer.")
    try:
        normalized = int(str(value))
    except (TypeError, ValueError) as exc:
        raise BusinessPurgeError(error_code, "ID must be a positive integer.") from exc
    if normalized <= 0:
        raise BusinessPurgeError(error_code, "ID must be a positive integer.")
    return normalized


def _validate_optional_operator_id(value: object) -> int | None:
    if value is None:
        return None
    return _validate_positive_id(value, "invalid_operator_id")


def _validate_reason_reference(value: object) -> str:
    normalized = str(value or "").strip()
    if not REASON_REFERENCE_PATTERN.fullmatch(normalized):
        raise BusinessPurgeError(
            "invalid_reason_reference",
            "Reason reference must be 1-120 reference characters without spaces or email text.",
        )
    return normalized
