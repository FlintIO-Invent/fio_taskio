from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from django.apps import apps
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.billings.models import Invoice, InvoiceLine
from apps.crm.models import ActivityLog, BusinessService, Client, Lead, ServiceCategory

from .business_sessions import decode_session_data_safely
from .models import (
    BillingProviderWebhookEvent,
    Business,
    BusinessDataOperation,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    SubscriptionNotification,
    UserOnboardingState,
    WeeklyAvailability,
)


class InventoryClassification(StrEnum):
    TENANT_ROOT = "tenant_root"
    CASCADE = "cascade"
    SET_NULL_ORPHAN_RISK = "set_null_orphan_risk"
    PROTECT_BLOCKER = "protect_blocker"
    INDIRECT = "indirect"
    EXTERNAL_REFERENCE = "external_reference"
    SHARED = "shared"


class IntegritySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class FuturePurgeReadiness(StrEnum):
    READY_FOR_PLANNING = "READY_FOR_PLANNING"
    BLOCKED_BY_INTEGRITY = "BLOCKED_BY_INTEGRITY"
    BLOCKED_BY_FINANCIAL_RETENTION = "BLOCKED_BY_FINANCIAL_RETENTION"
    REQUIRES_EXTERNAL_BILLING_CLOSURE = "REQUIRES_EXTERNAL_BILLING_CLOSURE"


@dataclass(frozen=True, slots=True)
class InventoryRegistration:
    key: str
    model_label: str
    business_field: str
    relationship_path: str
    classification: InventoryClassification
    explicit_deletion_required: bool
    financially_or_legally_sensitive: bool
    active_lookup: str | None = None
    active_values: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    key: str
    app_label: str
    model_name: str
    relationship_path: str
    classification: InventoryClassification
    active_count: int | None
    archived_inactive_count: int | None
    total_count: int
    explicit_deletion_required: bool
    financially_or_legally_sensitive: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "app_label": self.app_label,
            "model_name": self.model_name,
            "relationship_path": self.relationship_path,
            "classification": self.classification.value,
            "active_count": self.active_count,
            "archived_inactive_count": self.archived_inactive_count,
            "total_count": self.total_count,
            "explicit_deletion_required": self.explicit_deletion_required,
            "financially_or_legally_sensitive": self.financially_or_legally_sensitive,
        }


@dataclass(frozen=True, slots=True)
class UserImpact:
    user_id: int
    is_active: bool
    is_staff: bool
    is_superuser: bool
    role: str
    membership_is_active: bool
    other_business_membership_count: int
    appears_shared: bool
    automatic_account_deletion_prohibited: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "is_active": self.is_active,
            "is_staff": self.is_staff,
            "is_superuser": self.is_superuser,
            "role": self.role,
            "membership_is_active": self.membership_is_active,
            "other_business_membership_count": self.other_business_membership_count,
            "appears_shared": self.appears_shared,
            "automatic_account_deletion_prohibited": (self.automatic_account_deletion_prohibited),
        }


@dataclass(frozen=True, slots=True)
class IntegrityCheck:
    check_code: str
    severity: IntegritySeverity
    model_relationship: str
    affected_count: int
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "check_code": self.check_code,
            "severity": self.severity.value,
            "model_relationship": self.model_relationship,
            "affected_count": self.affected_count,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class BillingAssessment:
    invoice_count: int
    invoice_line_count: int
    invoice_business_on_delete: str
    invoice_protect_would_block_delete: bool
    subscription_present: bool
    subscription_status: str | None
    provider_customer_id_present: bool
    provider_subscription_id_present: bool
    provider_checkout_id_present: bool
    provider_price_id_present: bool
    correlated_webhook_event_count: int
    future_stripe_closure_required: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "invoice_count": self.invoice_count,
            "invoice_line_count": self.invoice_line_count,
            "invoice_business_on_delete": self.invoice_business_on_delete,
            "invoice_protect_would_block_delete": self.invoice_protect_would_block_delete,
            "subscription_present": self.subscription_present,
            "subscription_status": self.subscription_status,
            "provider_customer_id_present": self.provider_customer_id_present,
            "provider_subscription_id_present": self.provider_subscription_id_present,
            "provider_checkout_id_present": self.provider_checkout_id_present,
            "provider_price_id_present": self.provider_price_id_present,
            "correlated_webhook_event_count": self.correlated_webhook_event_count,
            "future_stripe_closure_required": self.future_stripe_closure_required,
        }


@dataclass(frozen=True, slots=True)
class InventorySummary:
    selected_business_id: int
    business_slug: str
    business_is_active: bool
    total_directly_and_indirectly_owned_records: int
    shared_user_count: int
    protected_or_system_user_count: int
    protect_blocker_count: int
    set_null_orphan_risk_count: int
    cross_tenant_integrity_blocker_count: int
    correlated_webhook_event_count: int
    invoices_exist: bool
    stripe_closure_required: bool
    future_purge_readiness: FuturePurgeReadiness

    def to_dict(self) -> dict[str, object]:
        return {
            "selected_business_id": self.selected_business_id,
            "business_slug": self.business_slug,
            "business_is_active": self.business_is_active,
            "total_directly_and_indirectly_owned_records": (
                self.total_directly_and_indirectly_owned_records
            ),
            "shared_user_count": self.shared_user_count,
            "protected_or_system_user_count": self.protected_or_system_user_count,
            "protect_blocker_count": self.protect_blocker_count,
            "set_null_orphan_risk_count": self.set_null_orphan_risk_count,
            "cross_tenant_integrity_blocker_count": (self.cross_tenant_integrity_blocker_count),
            "correlated_webhook_event_count": self.correlated_webhook_event_count,
            "invoices_exist": self.invoices_exist,
            "stripe_closure_required": self.stripe_closure_required,
            "future_purge_readiness": self.future_purge_readiness.value,
        }


@dataclass(frozen=True, slots=True)
class BusinessDataInventory:
    business_id: int
    business_name: str
    business_slug: str
    business_is_active: bool
    records: tuple[InventoryRecord, ...]
    user_impact: tuple[UserImpact, ...]
    integrity_checks: tuple[IntegrityCheck, ...]
    billing_assessment: BillingAssessment
    summary: InventorySummary

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "selected_business": {
                "business_id": self.business_id,
                "business_name": self.business_name,
                "slug": self.business_slug,
                "is_active": self.business_is_active,
            },
            "records": [record.to_dict() for record in self.records],
            "user_impact": [impact.to_dict() for impact in self.user_impact],
            "integrity_checks": [check.to_dict() for check in self.integrity_checks],
            "billing_assessment": self.billing_assessment.to_dict(),
            "summary": self.summary.to_dict(),
            "informational_only": True,
        }


DIRECT_BUSINESS_RELATION_REGISTRY: tuple[InventoryRegistration, ...] = (
    InventoryRegistration(
        "business_booking_settings",
        "businesses.BusinessBookingSettings",
        "business",
        "Business.booking_settings",
        InventoryClassification.CASCADE,
        False,
        False,
    ),
    InventoryRegistration(
        "weekly_availability",
        "businesses.WeeklyAvailability",
        "business",
        "Business.weekly_availability",
        InventoryClassification.CASCADE,
        False,
        False,
        "is_active",
        (True,),
    ),
    InventoryRegistration(
        "business_subscription",
        "businesses.BusinessSubscription",
        "business",
        "Business.subscription",
        InventoryClassification.CASCADE,
        False,
        True,
        "status",
        (
            BusinessSubscription.Status.PENDING_CHECKOUT,
            BusinessSubscription.Status.TRIALING,
            BusinessSubscription.Status.ACTIVE,
            BusinessSubscription.Status.PAST_DUE,
        ),
    ),
    InventoryRegistration(
        "subscription_notifications",
        "businesses.SubscriptionNotification",
        "business",
        "Business.subscription_notifications",
        InventoryClassification.CASCADE,
        False,
        True,
        "status",
        (
            SubscriptionNotification.Status.PENDING,
            SubscriptionNotification.Status.PROCESSING,
        ),
    ),
    InventoryRegistration(
        "business_users",
        "businesses.BusinessUser",
        "business",
        "Business.memberships",
        InventoryClassification.CASCADE,
        False,
        True,
        "is_active",
        (True,),
    ),
    InventoryRegistration(
        "user_onboarding_states",
        "businesses.UserOnboardingState",
        "business",
        "Business.onboarding_states",
        InventoryClassification.CASCADE,
        False,
        True,
    ),
    InventoryRegistration(
        "business_invitations",
        "businesses.BusinessInvitation",
        "business",
        "Business.invitations",
        InventoryClassification.CASCADE,
        False,
        True,
        "status",
        (BusinessInvitation.Status.PENDING,),
    ),
    InventoryRegistration(
        "service_categories",
        "crm.ServiceCategory",
        "business",
        "Business.service_categories",
        InventoryClassification.SET_NULL_ORPHAN_RISK,
        True,
        False,
        "is_active",
        (True,),
    ),
    InventoryRegistration(
        "business_services",
        "crm.BusinessService",
        "business",
        "Business.business_services",
        InventoryClassification.CASCADE,
        False,
        False,
        "is_active",
        (True,),
    ),
    InventoryRegistration(
        "leads",
        "crm.Lead",
        "business",
        "Business.leads",
        InventoryClassification.SET_NULL_ORPHAN_RISK,
        True,
        True,
        "is_active",
        (True,),
    ),
    InventoryRegistration(
        "clients",
        "crm.Client",
        "business",
        "Business.clients",
        InventoryClassification.SET_NULL_ORPHAN_RISK,
        True,
        True,
        "is_active",
        (True,),
    ),
    InventoryRegistration(
        "activity_logs",
        "crm.ActivityLog",
        "business",
        "Business.activity_logs",
        InventoryClassification.SET_NULL_ORPHAN_RISK,
        True,
        True,
    ),
    InventoryRegistration(
        "appointments",
        "appointments.Appointment",
        "business",
        "Business.appointments",
        InventoryClassification.CASCADE,
        False,
        True,
        "status",
        (Appointment.Status.SCHEDULED,),
    ),
    InventoryRegistration(
        "invoices",
        "billings.Invoice",
        "business",
        "Business.invoices",
        InventoryClassification.PROTECT_BLOCKER,
        True,
        True,
    ),
)

# No direct Business relationship is intentionally excluded today. Snapshot IDs,
# generic relations, user-owned profiles, sessions, and webhook JSON correlations
# are deliberately outside this direct-FK registry and are inventoried separately.
INTENTIONAL_DIRECT_BUSINESS_RELATION_EXCLUSIONS: dict[tuple[str, str], str] = {}


def find_unregistered_direct_business_relations(
    registry: Iterable[InventoryRegistration] = DIRECT_BUSINESS_RELATION_REGISTRY,
) -> tuple[str, ...]:
    registered = {(entry.model_label, entry.business_field) for entry in registry}
    excluded = set(INTENTIONAL_DIRECT_BUSINESS_RELATION_EXCLUSIONS)
    discovered: set[tuple[str, str]] = set()

    for model in apps.get_models():
        for field in model._meta.local_fields:
            if not isinstance(field, (models.ForeignKey, models.OneToOneField)):
                continue
            if field.remote_field.model is Business:
                discovered.add((model._meta.label, field.name))

    missing = discovered - registered - excluded
    return tuple(f"{model_label}.{field_name}" for model_label, field_name in sorted(missing))


def build_business_data_inventory(business: Business | int) -> BusinessDataInventory:
    selected_business = _get_exact_business(business)
    business_id = selected_business.pk

    records = [_business_root_record(selected_business)]
    for registration in DIRECT_BUSINESS_RELATION_REGISTRY:
        records.append(_registered_record(registration, business_id))

    invoice_lines = InvoiceLine.objects.filter(invoice__business_id=business_id)
    records.append(
        _queryset_record(
            key="invoice_lines",
            queryset=invoice_lines,
            relationship_path="Business.invoices -> Invoice.lines",
            classification=InventoryClassification.INDIRECT,
            explicit_deletion_required=False,
            financially_or_legally_sensitive=True,
        )
    )

    subscription = BusinessSubscription.objects.filter(business_id=business_id).first()
    webhook_queryset = _correlated_webhook_events(selected_business, subscription)
    records.append(
        _queryset_record(
            key="billing_provider_webhook_events",
            queryset=webhook_queryset,
            relationship_path="Safe structured webhook correlation",
            classification=InventoryClassification.EXTERNAL_REFERENCE,
            explicit_deletion_required=False,
            financially_or_legally_sensitive=True,
            active_lookup="status",
            active_values=(
                BillingProviderWebhookEvent.Status.RECEIVED,
                BillingProviderWebhookEvent.Status.PROCESSING,
            ),
        )
    )

    records.append(
        _queryset_record(
            key="business_data_operations",
            queryset=BusinessDataOperation.objects.filter(business_id_snapshot=business_id),
            relationship_path="BusinessDataOperation.business_id_snapshot",
            classification=InventoryClassification.EXTERNAL_REFERENCE,
            explicit_deletion_required=False,
            financially_or_legally_sensitive=True,
            active_lookup="status",
            active_values=(BusinessDataOperation.Status.STARTED,),
        )
    )

    shared_plan_queryset = ClarivoPlan.objects.filter(
        subscriptions__business_id=business_id
    ).distinct()
    records.append(
        _queryset_record(
            key="shared_subscription_plan",
            queryset=shared_plan_queryset,
            relationship_path="Business.subscription -> shared plan",
            classification=InventoryClassification.SHARED,
            explicit_deletion_required=False,
            financially_or_legally_sensitive=False,
            active_lookup="is_active",
            active_values=(True,),
        )
    )

    member_user_ids = tuple(
        BusinessUser.objects.filter(business_id=business_id)
        .order_by("user_id")
        .values_list("user_id", flat=True)
    )
    session_record, session_checks = _session_inventory(business_id, member_user_ids)
    records.append(session_record)

    cross_user_ids, cross_user_checks = _cross_business_user_references(
        business_id,
        member_user_ids,
    )
    user_impact, protected_user_count = _user_impact(
        business_id,
        cross_user_ids,
    )

    integrity_checks = list(_relationship_integrity_checks(business_id))
    integrity_checks.extend(cross_user_checks)
    integrity_checks.extend(_null_business_legacy_checks())
    integrity_checks.extend(session_checks)
    integrity_checks.append(_inventory_completeness_check())

    record_by_key = {record.key: record for record in records}
    invoice_count = record_by_key["invoices"].total_count
    invoice_line_count = record_by_key["invoice_lines"].total_count
    webhook_count = record_by_key["billing_provider_webhook_events"].total_count
    billing_assessment = _billing_assessment(
        subscription=subscription,
        invoice_count=invoice_count,
        invoice_line_count=invoice_line_count,
        correlated_webhook_event_count=webhook_count,
    )

    owned_classifications = {
        InventoryClassification.TENANT_ROOT,
        InventoryClassification.CASCADE,
        InventoryClassification.SET_NULL_ORPHAN_RISK,
        InventoryClassification.PROTECT_BLOCKER,
        InventoryClassification.INDIRECT,
    }
    total_owned = sum(
        record.total_count for record in records if record.classification in owned_classifications
    )
    set_null_count = sum(
        record.total_count
        for record in records
        if record.classification == InventoryClassification.SET_NULL_ORPHAN_RISK
    )
    cross_tenant_blocker_count = sum(
        1
        for check in integrity_checks
        if check.severity == IntegritySeverity.BLOCKER
        and check.check_code.startswith("cross_tenant_")
        and check.affected_count
    )
    has_integrity_blocker = any(
        check.severity == IntegritySeverity.BLOCKER and check.affected_count
        for check in integrity_checks
    )
    readiness = _future_purge_readiness(
        has_integrity_blocker=has_integrity_blocker,
        invoice_protect_would_block=billing_assessment.invoice_protect_would_block_delete,
        stripe_closure_required=billing_assessment.future_stripe_closure_required,
    )
    summary = InventorySummary(
        selected_business_id=business_id,
        business_slug=selected_business.slug,
        business_is_active=selected_business.is_active,
        total_directly_and_indirectly_owned_records=total_owned,
        shared_user_count=sum(impact.appears_shared for impact in user_impact),
        protected_or_system_user_count=protected_user_count,
        protect_blocker_count=invoice_count,
        set_null_orphan_risk_count=set_null_count,
        cross_tenant_integrity_blocker_count=cross_tenant_blocker_count,
        correlated_webhook_event_count=webhook_count,
        invoices_exist=invoice_count > 0,
        stripe_closure_required=billing_assessment.future_stripe_closure_required,
        future_purge_readiness=readiness,
    )

    return BusinessDataInventory(
        business_id=business_id,
        business_name=selected_business.name,
        business_slug=selected_business.slug,
        business_is_active=selected_business.is_active,
        records=tuple(records),
        user_impact=user_impact,
        integrity_checks=tuple(integrity_checks),
        billing_assessment=billing_assessment,
        summary=summary,
    )


def _get_exact_business(business: Business | int) -> Business:
    if isinstance(business, Business):
        if business.pk is None:
            raise ValueError("Business must be saved before it can be inventoried.")
        return business
    return Business.objects.get(pk=business)


def _business_root_record(business: Business) -> InventoryRecord:
    return InventoryRecord(
        key="business",
        app_label=business._meta.app_label,
        model_name=business._meta.object_name,
        relationship_path="Business tenant root",
        classification=InventoryClassification.TENANT_ROOT,
        active_count=int(business.is_active),
        archived_inactive_count=int(not business.is_active),
        total_count=1,
        explicit_deletion_required=True,
        financially_or_legally_sensitive=True,
    )


def _registered_record(
    registration: InventoryRegistration,
    business_id: int,
) -> InventoryRecord:
    model = apps.get_model(registration.model_label)
    queryset = model._default_manager.filter(**{f"{registration.business_field}_id": business_id})
    return _queryset_record(
        key=registration.key,
        queryset=queryset,
        relationship_path=registration.relationship_path,
        classification=registration.classification,
        explicit_deletion_required=registration.explicit_deletion_required,
        financially_or_legally_sensitive=registration.financially_or_legally_sensitive,
        active_lookup=registration.active_lookup,
        active_values=registration.active_values,
    )


def _queryset_record(
    *,
    key: str,
    queryset: models.QuerySet,
    relationship_path: str,
    classification: InventoryClassification,
    explicit_deletion_required: bool,
    financially_or_legally_sensitive: bool,
    active_lookup: str | None = None,
    active_values: tuple[object, ...] = (),
) -> InventoryRecord:
    total_count = queryset.count()
    active_count: int | None = None
    archived_inactive_count: int | None = None
    if active_lookup is not None:
        active_count = queryset.filter(**{f"{active_lookup}__in": active_values}).count()
        archived_inactive_count = total_count - active_count

    return InventoryRecord(
        key=key,
        app_label=queryset.model._meta.app_label,
        model_name=queryset.model._meta.object_name,
        relationship_path=relationship_path,
        classification=classification,
        active_count=active_count,
        archived_inactive_count=archived_inactive_count,
        total_count=total_count,
        explicit_deletion_required=explicit_deletion_required,
        financially_or_legally_sensitive=financially_or_legally_sensitive,
    )


def _correlated_webhook_events(
    business: Business,
    subscription: BusinessSubscription | None,
) -> models.QuerySet[BillingProviderWebhookEvent]:
    correlation = Q(payload_summary__motionmate_business_id=str(business.pk)) | Q(
        payload_summary__motionmate_business_id=business.pk
    )

    provider_object_ids: list[str] = []
    if subscription is not None:
        correlation |= Q(payload_summary__motionmate_subscription_id=str(subscription.pk))
        correlation |= Q(payload_summary__motionmate_subscription_id=subscription.pk)
        if subscription.provider_subscription_id:
            correlation |= Q(
                payload_summary__provider_subscription_id=(subscription.provider_subscription_id)
            )
        provider_object_ids.extend(
            value
            for value in (
                subscription.provider_customer_id,
                subscription.provider_subscription_id,
                subscription.provider_checkout_session_id,
            )
            if value
        )

    if provider_object_ids:
        correlation |= Q(object_id__in=provider_object_ids)

    notification_event_ids = tuple(
        SubscriptionNotification.objects.filter(business_id=business.pk)
        .exclude(source_provider_event_id="")
        .values_list("source_provider_event_id", flat=True)
    )
    if notification_event_ids:
        correlation |= Q(event_id__in=notification_event_ids)

    return BillingProviderWebhookEvent.objects.filter(correlation).distinct()


def _session_inventory(
    business_id: int,
    member_user_ids: tuple[int, ...],
) -> tuple[InventoryRecord, tuple[IntegrityCheck, ...]]:
    supported_backends = {
        "django.contrib.sessions.backends.db",
        "django.contrib.sessions.backends.cached_db",
    }
    if settings.SESSION_ENGINE not in supported_backends:
        return (
            _empty_session_record(),
            (
                IntegrityCheck(
                    "session_backend_not_inspectable",
                    IntegritySeverity.INFO,
                    "sessions.Session encoded session data",
                    0,
                    "The configured session backend cannot be reliably inventoried from the database.",
                ),
            ),
        )

    user_ids = set(member_user_ids)
    now = timezone.now()
    active_count = 0
    inactive_count = 0
    decode_failure_count = 0
    for session in (
        Session.objects.all().only("session_data", "expire_date").iterator(chunk_size=500)
    ):
        decoded = decode_session_data_safely(session.session_data)
        if decoded is None:
            decode_failure_count += 1
            continue

        session_user_id = _safe_positive_int(decoded.get("_auth_user_id"))
        session_business_id = _safe_positive_int(decoded.get("current_business_id"))
        if session_user_id not in user_ids and session_business_id != business_id:
            continue
        if session.expire_date > now:
            active_count += 1
        else:
            inactive_count += 1

    severity = IntegritySeverity.WARNING if decode_failure_count else IntegritySeverity.INFO
    checks = (
        IntegrityCheck(
            "session_decode_failures",
            severity,
            "sessions.Session encoded session data",
            decode_failure_count,
            "Undecodable sessions were excluded without exposing their contents.",
        ),
    )
    return (
        InventoryRecord(
            key="sessions",
            app_label=Session._meta.app_label,
            model_name=Session._meta.object_name,
            relationship_path="Decoded _auth_user_id or current_business_id correlation",
            classification=InventoryClassification.EXTERNAL_REFERENCE,
            active_count=active_count,
            archived_inactive_count=inactive_count,
            total_count=active_count + inactive_count,
            explicit_deletion_required=False,
            financially_or_legally_sensitive=True,
        ),
        checks,
    )


def _empty_session_record() -> InventoryRecord:
    return InventoryRecord(
        key="sessions",
        app_label=Session._meta.app_label,
        model_name=Session._meta.object_name,
        relationship_path="Session backend not inspectable",
        classification=InventoryClassification.EXTERNAL_REFERENCE,
        active_count=None,
        archived_inactive_count=None,
        total_count=0,
        explicit_deletion_required=False,
        financially_or_legally_sensitive=True,
    )


def _safe_positive_int(value: object) -> int | None:
    try:
        normalized = int(str(value))
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _user_impact(
    business_id: int,
    cross_business_operational_user_ids: set[int],
) -> tuple[tuple[UserImpact, ...], int]:
    memberships = tuple(
        BusinessUser.objects.filter(business_id=business_id)
        .select_related("user")
        .order_by("user_id")
    )
    user_ids = {membership.user_id for membership in memberships}
    other_membership_counts = {
        row["user_id"]: row["count"]
        for row in BusinessUser.objects.filter(user_id__in=user_ids)
        .exclude(business_id=business_id)
        .values("user_id")
        .annotate(count=models.Count("pk"))
    }

    impacts: list[UserImpact] = []
    protected_user_count = 0
    for membership in memberships:
        user = membership.user
        other_count = other_membership_counts.get(user.pk, 0)
        mandatory_protection = bool(
            other_count
            or user.is_staff
            or user.is_superuser
            or user.pk in cross_business_operational_user_ids
        )
        protected_user_count += int(mandatory_protection)
        impacts.append(
            UserImpact(
                user_id=user.pk,
                is_active=user.is_active,
                is_staff=user.is_staff,
                is_superuser=user.is_superuser,
                role=membership.role,
                membership_is_active=membership.is_active,
                other_business_membership_count=other_count,
                appears_shared=other_count > 0,
                # User deletion is prohibited by default even when no additional
                # mandatory-protection condition is currently observed.
                automatic_account_deletion_prohibited=True,
            )
        )
    return tuple(impacts), protected_user_count


def _cross_business_user_references(
    business_id: int,
    user_ids: tuple[int, ...],
) -> tuple[set[int], tuple[IntegrityCheck, ...]]:
    if not user_ids:
        return set(), ()

    reference_specs = (
        (WeeklyAvailability, "staff_member_id", "business_id", "weekly_availability"),
        (Appointment, "staff_member_id", "business_id", "appointments"),
        (Client, "assigned_to_id", "business_id", "assigned_clients"),
        (ActivityLog, "actor_id", "business_id", "activity_logs"),
        (UserOnboardingState, "user_id", "business_id", "onboarding_states"),
        (
            SubscriptionNotification,
            "recipient_user_id",
            "business_id",
            "subscription_notifications",
        ),
        (BusinessInvitation, "invited_by_id", "business_id", "sent_invitations"),
        (BusinessInvitation, "accepted_by_id", "business_id", "accepted_invitations"),
    )
    affected_user_ids: set[int] = set()
    checks: list[IntegrityCheck] = []
    for model, user_field, business_field, code_suffix in reference_specs:
        queryset = (
            model._default_manager.filter(**{f"{user_field}__in": user_ids})
            .exclude(**{business_field: business_id})
            .exclude(**{f"{business_field}__isnull": True})
        )
        count = queryset.count()
        affected_user_ids.update(queryset.values_list(user_field, flat=True))
        checks.append(
            _blocker_check(
                f"cross_tenant_user_{code_suffix}",
                f"{model._meta.label}.{user_field}",
                count,
                "Selected-business users have operational references in another business.",
            )
        )
    return affected_user_ids, tuple(checks)


def _relationship_integrity_checks(business_id: int) -> tuple[IntegrityCheck, ...]:
    selected_members = BusinessUser.objects.filter(business_id=business_id).values("user_id")
    checks = (
        _blocker_check(
            "cross_tenant_invoice_client",
            "billings.Invoice.client -> crm.Client.business",
            Invoice.objects.filter(business_id=business_id)
            .exclude(client__business_id=business_id)
            .count(),
            "Selected-business invoices reference clients without the same business.",
        ),
        _blocker_check(
            "cross_tenant_invoice_appointment",
            "billings.Invoice.appointment -> appointments.Appointment.business",
            Invoice.objects.filter(business_id=business_id, appointment__isnull=False)
            .exclude(appointment__business_id=business_id)
            .count(),
            "Selected-business invoices reference appointments from another business.",
        ),
        _blocker_check(
            "cross_tenant_invoice_appointment_client",
            "billings.Invoice.appointment.client",
            Invoice.objects.filter(business_id=business_id, appointment__isnull=False)
            .exclude(appointment__client_id=models.F("client_id"))
            .count(),
            "Invoice and linked appointment client relationships disagree.",
        ),
        _blocker_check(
            "cross_tenant_appointment_client",
            "appointments.Appointment.client -> crm.Client.business",
            Appointment.objects.filter(business_id=business_id)
            .exclude(client__business_id=business_id)
            .count(),
            "Selected-business appointments reference clients without the same business.",
        ),
        _blocker_check(
            "cross_tenant_appointment_service",
            "appointments.Appointment.service -> crm.BusinessService.business",
            Appointment.objects.filter(business_id=business_id, service__isnull=False)
            .exclude(service__business_id=business_id)
            .count(),
            "Selected-business appointments reference services from another business.",
        ),
        _blocker_check(
            "cross_tenant_appointment_source_lead",
            "appointments.Appointment.source_lead -> crm.Lead.business",
            Appointment.objects.filter(business_id=business_id, source_lead__isnull=False)
            .exclude(source_lead__business_id=business_id)
            .count(),
            "Selected-business appointments reference leads without the same business.",
        ),
        _blocker_check(
            "cross_tenant_appointment_staff_membership",
            "appointments.Appointment.staff_member -> businesses.BusinessUser",
            Appointment.objects.filter(business_id=business_id, staff_member__isnull=False)
            .exclude(staff_member_id__in=selected_members)
            .count(),
            "Selected-business appointments reference staff without a membership in the business.",
        ),
        _blocker_check(
            "cross_tenant_business_service_category",
            "crm.BusinessService.category -> crm.ServiceCategory.business",
            BusinessService.objects.filter(
                business_id=business_id,
                category__business_id__isnull=False,
            )
            .exclude(category__business_id=business_id)
            .count(),
            "Selected-business services reference categories owned by another business.",
        ),
        _blocker_check(
            "cross_tenant_lead_category",
            "crm.Lead.category -> crm.ServiceCategory.business",
            Lead.objects.filter(
                business_id=business_id,
                category__business_id__isnull=False,
            )
            .exclude(category__business_id=business_id)
            .count(),
            "Selected-business leads reference categories owned by another business.",
        ),
        _blocker_check(
            "cross_tenant_lead_requested_service",
            "crm.Lead.requested_service -> crm.BusinessService.business",
            Lead.objects.filter(business_id=business_id, requested_service__isnull=False)
            .exclude(requested_service__business_id=business_id)
            .count(),
            "Selected-business leads reference services from another business.",
        ),
        _blocker_check(
            "cross_tenant_activity_log_lead",
            "crm.ActivityLog.lead -> crm.Lead.business",
            ActivityLog.objects.filter(business_id=business_id, lead__isnull=False)
            .exclude(lead__business_id=business_id)
            .count(),
            "Selected-business activity logs reference leads without the same business.",
        ),
        _blocker_check(
            "cross_tenant_activity_log_client",
            "crm.ActivityLog.client -> crm.Client.business",
            ActivityLog.objects.filter(business_id=business_id, client__isnull=False)
            .exclude(client__business_id=business_id)
            .count(),
            "Selected-business activity logs reference clients without the same business.",
        ),
        _blocker_check(
            "cross_tenant_invoice_line_service",
            "billings.InvoiceLine.service -> crm.BusinessService.business",
            InvoiceLine.objects.filter(
                invoice__business_id=business_id,
                service__isnull=False,
            )
            .exclude(service__business_id=business_id)
            .count(),
            "Selected-business invoice lines reference services from another business.",
        ),
        _blocker_check(
            "cross_tenant_external_invoice_client",
            "other billings.Invoice.client -> selected crm.Client",
            Invoice.objects.filter(client__business_id=business_id)
            .exclude(business_id=business_id)
            .count(),
            "Another business has invoices referencing selected-business clients.",
        ),
        _blocker_check(
            "cross_tenant_external_invoice_appointment",
            "other billings.Invoice.appointment -> selected appointments.Appointment",
            Invoice.objects.filter(appointment__business_id=business_id)
            .exclude(business_id=business_id)
            .count(),
            "Another business has invoices referencing selected-business appointments.",
        ),
        _blocker_check(
            "cross_tenant_external_appointment_client",
            "other appointments.Appointment.client -> selected crm.Client",
            Appointment.objects.filter(client__business_id=business_id)
            .exclude(business_id=business_id)
            .count(),
            "Another business has appointments referencing selected-business clients.",
        ),
        _blocker_check(
            "cross_tenant_external_appointment_service",
            "other appointments.Appointment.service -> selected crm.BusinessService",
            Appointment.objects.filter(service__business_id=business_id)
            .exclude(business_id=business_id)
            .count(),
            "Another business has appointments referencing selected-business services.",
        ),
        _blocker_check(
            "cross_tenant_external_appointment_source_lead",
            "other appointments.Appointment.source_lead -> selected crm.Lead",
            Appointment.objects.filter(source_lead__business_id=business_id)
            .exclude(business_id=business_id)
            .count(),
            "Another business has appointments referencing selected-business leads.",
        ),
        _blocker_check(
            "cross_tenant_external_business_service_category",
            "other crm.BusinessService.category -> selected crm.ServiceCategory",
            BusinessService.objects.filter(category__business_id=business_id)
            .exclude(business_id=business_id)
            .count(),
            "Another business has services referencing selected-business categories.",
        ),
        _blocker_check(
            "cross_tenant_external_lead_category",
            "other crm.Lead.category -> selected crm.ServiceCategory",
            Lead.objects.filter(category__business_id=business_id)
            .exclude(business_id=business_id)
            .exclude(business_id__isnull=True)
            .count(),
            "Another business has leads referencing selected-business categories.",
        ),
        _blocker_check(
            "cross_tenant_external_lead_requested_service",
            "other crm.Lead.requested_service -> selected crm.BusinessService",
            Lead.objects.filter(requested_service__business_id=business_id)
            .exclude(business_id=business_id)
            .exclude(business_id__isnull=True)
            .count(),
            "Another business has leads referencing selected-business services.",
        ),
        _blocker_check(
            "cross_tenant_external_activity_log_lead",
            "other crm.ActivityLog.lead -> selected crm.Lead",
            ActivityLog.objects.filter(lead__business_id=business_id)
            .exclude(business_id=business_id)
            .exclude(business_id__isnull=True)
            .count(),
            "Another business has activity logs referencing selected-business leads.",
        ),
        _blocker_check(
            "cross_tenant_external_activity_log_client",
            "other crm.ActivityLog.client -> selected crm.Client",
            ActivityLog.objects.filter(client__business_id=business_id)
            .exclude(business_id=business_id)
            .exclude(business_id__isnull=True)
            .count(),
            "Another business has activity logs referencing selected-business clients.",
        ),
        _blocker_check(
            "cross_tenant_external_invoice_line_service",
            "other billings.InvoiceLine.service -> selected crm.BusinessService",
            InvoiceLine.objects.filter(service__business_id=business_id)
            .exclude(invoice__business_id=business_id)
            .count(),
            "Another business has invoice lines referencing selected-business services.",
        ),
    )
    return checks


def _null_business_legacy_checks() -> tuple[IntegrityCheck, ...]:
    models_with_nullable_business = (ServiceCategory, Lead, Client, ActivityLog)
    checks = []
    for model in models_with_nullable_business:
        count = model._default_manager.filter(business_id__isnull=True).count()
        checks.append(
            IntegrityCheck(
                check_code=f"legacy_null_business_{model._meta.label_lower.replace('.', '_')}",
                severity=(IntegritySeverity.WARNING if count else IntegritySeverity.INFO),
                model_relationship=f"{model._meta.label}.business",
                affected_count=count,
                explanation=(
                    "Global or unprovable business=NULL legacy records are reported separately "
                    "and are not included in the selected business totals."
                ),
            )
        )
    return tuple(checks)


def _inventory_completeness_check() -> IntegrityCheck:
    missing = find_unregistered_direct_business_relations()
    if missing:
        explanation = (
            "Direct Business relationships are missing from the explicit inventory registry: "
            + ", ".join(missing)
        )
        severity = IntegritySeverity.BLOCKER
    else:
        explanation = "All discovered direct Business relationships are explicitly registered."
        severity = IntegritySeverity.INFO
    return IntegrityCheck(
        "inventory_registry_unregistered_business_relation",
        severity,
        "Installed models -> Business direct relations",
        len(missing),
        explanation,
    )


def _blocker_check(
    check_code: str,
    model_relationship: str,
    affected_count: int,
    explanation: str,
) -> IntegrityCheck:
    return IntegrityCheck(
        check_code=check_code,
        severity=(IntegritySeverity.BLOCKER if affected_count else IntegritySeverity.INFO),
        model_relationship=model_relationship,
        affected_count=affected_count,
        explanation=explanation,
    )


def _billing_assessment(
    *,
    subscription: BusinessSubscription | None,
    invoice_count: int,
    invoice_line_count: int,
    correlated_webhook_event_count: int,
) -> BillingAssessment:
    customer_id_present = bool(subscription and subscription.provider_customer_id)
    subscription_id_present = bool(subscription and subscription.provider_subscription_id)
    checkout_id_present = bool(subscription and subscription.provider_checkout_session_id)
    price_id_present = bool(subscription and subscription.provider_price_id)
    stripe_closure_required = bool(
        subscription
        and (
            subscription.payment_provider == BusinessSubscription.PaymentProvider.STRIPE
            or customer_id_present
            or subscription_id_present
            or checkout_id_present
            or price_id_present
        )
    )
    return BillingAssessment(
        invoice_count=invoice_count,
        invoice_line_count=invoice_line_count,
        invoice_business_on_delete="PROTECT",
        invoice_protect_would_block_delete=invoice_count > 0,
        subscription_present=subscription is not None,
        subscription_status=subscription.status if subscription else None,
        provider_customer_id_present=customer_id_present,
        provider_subscription_id_present=subscription_id_present,
        provider_checkout_id_present=checkout_id_present,
        provider_price_id_present=price_id_present,
        correlated_webhook_event_count=correlated_webhook_event_count,
        future_stripe_closure_required=stripe_closure_required,
    )


def _future_purge_readiness(
    *,
    has_integrity_blocker: bool,
    invoice_protect_would_block: bool,
    stripe_closure_required: bool,
) -> FuturePurgeReadiness:
    if has_integrity_blocker:
        return FuturePurgeReadiness.BLOCKED_BY_INTEGRITY
    if invoice_protect_would_block:
        return FuturePurgeReadiness.BLOCKED_BY_FINANCIAL_RETENTION
    if stripe_closure_required:
        return FuturePurgeReadiness.REQUIRES_EXTERNAL_BILLING_CLOSURE
    return FuturePurgeReadiness.READY_FOR_PLANNING
