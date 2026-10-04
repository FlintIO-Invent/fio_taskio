"""Application lifecycle services. No tenant provisioning, billing or notifications."""

from dataclasses import asdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.businesses.models import Business

from .eligibility import RelationshipSignals, evaluate_eligibility
from .models import LogisticsApplication, LogisticsApplicationDecision
from .policy import LogisticsEligibilityPolicy


def current_policy() -> LogisticsEligibilityPolicy:
    value = settings.LOGISTICS_ELIGIBILITY_POLICY
    return (
        value
        if isinstance(value, LogisticsEligibilityPolicy)
        else LogisticsEligibilityPolicy.model_validate(value)
    )


def relationship_signals(application: LogisticsApplication) -> RelationshipSignals:
    business_match = Q(email__iexact=application.email) | Q(name__iexact=application.business_name)
    if application.trading_name:
        business_match |= Q(name__iexact=application.trading_name)
    duplicates = Q(normalized_email=application.normalized_email) | Q(
        normalized_business_name=application.normalized_business_name
    )
    if application.normalized_registration_number:
        duplicates |= Q(
            normalized_registration_number=application.normalized_registration_number,
            country__iexact=application.country,
        )
    return RelationshipSignals(
        existing_user=get_user_model().objects.filter(email__iexact=application.email).exists(),
        existing_business=Business.objects.filter(business_match).exists(),
        duplicate_application=LogisticsApplication.objects.exclude(pk=application.pk)
        .filter(
            duplicates,
            status__in=[
                LogisticsApplication.Status.SUBMITTED,
                LogisticsApplication.Status.UNDER_REVIEW,
                LogisticsApplication.Status.APPROVED,
            ],
        )
        .exists(),
    )


def _record_decision(application, *, result=None, actor=None, override_reason=""):
    manual = result is not None
    policy = current_policy()
    inputs = application.material_inputs()
    signals = relationship_signals(application)
    evaluated = evaluate_eligibility(inputs, policy, signals)
    result = result or evaluated.result
    evaluated_at = timezone.now()
    snapshot = policy.model_dump(mode="json")
    # Record operational rule inputs without duplicating contact/address data in
    # the decision ledger. Registration presence is sufficient for this rule.
    operational_inputs = {
        key: value
        for key, value in inputs.items()
        if key
        in {
            "country",
            "operation_type",
            "monthly_parcel_estimate",
            "expected_staff_count",
            "location_count",
            "current_process_method",
            "customer_tracking_needed",
            "manifest_needed",
            "api_integration_needed",
            "custom_workflow",
            "multi_jurisdiction",
            "custom_pricing_requested",
        }
    }
    operational_inputs["registration_number_present"] = bool(application.registration_number)
    operational_inputs["custom_workflow_details_present"] = bool(
        application.custom_workflow_details
    )
    decision = LogisticsApplicationDecision.objects.create(
        application=application,
        application_revision=application.revision,
        result=result,
        evaluated_result=evaluated.result,
        reason_codes=list(evaluated.reason_codes),
        evaluated_at=evaluated_at,
        rule_version=policy.rule_version,
        threshold_snapshot=snapshot,
        evaluated_inputs=operational_inputs,
        relationship_snapshot=asdict(signals),
        resource_classification=evaluated.resource_classification,
        source=(
            LogisticsApplicationDecision.Source.MANUAL
            if manual
            else LogisticsApplicationDecision.Source.AUTOMATIC
        ),
        actor=actor,
        actor_identifier=actor.pk if actor else None,
        override_reason=override_reason,
    )
    LogisticsApplication.objects.filter(pk=application.pk).update(
        status=result,
        decision_result=result,
        reason_codes=list(evaluated.reason_codes),
        evaluated_at=evaluated_at,
        evaluated_revision=application.revision,
        rule_version=policy.rule_version,
        threshold_snapshot=snapshot,
        approved_revision=(
            application.revision if result == LogisticsApplication.Status.APPROVED else None
        ),
        updated_at=evaluated_at,
    )
    return decision


@transaction.atomic
def reevaluate_application(application_id, *, expected_revision=None, actor=None):
    if actor is not None:
        _require_reviewer(actor)
    application = LogisticsApplication.objects.select_for_update().get(pk=application_id)
    _check_revision(application, expected_revision)
    if application.status == LogisticsApplication.Status.WITHDRAWN:
        raise ValidationError("Withdrawn applications cannot be reevaluated.")
    return _record_decision(application, actor=actor)


@transaction.atomic
def review_application(application_id, *, result, actor, reason, expected_revision):
    _require_reviewer(actor)
    if expected_revision is None:
        raise ValidationError("The reviewed application revision is required.")
    if result not in {
        LogisticsApplication.Status.APPROVED,
        LogisticsApplication.Status.DECLINED,
        LogisticsApplication.Status.WITHDRAWN,
    }:
        raise ValidationError("Choose approve, decline or withdraw for a manual decision.")
    reason = str(reason or "").strip()
    if not reason or len(reason) > 3000:
        raise ValidationError("A manual review reason of 1–3000 characters is required.")
    application = LogisticsApplication.objects.select_for_update().get(pk=application_id)
    _check_revision(application, expected_revision)
    if application.status == LogisticsApplication.Status.WITHDRAWN:
        raise ValidationError("Withdrawn applications cannot be reviewed.")
    return _record_decision(application, result=result, actor=actor, override_reason=reason)


def _require_reviewer(actor):
    if (
        not actor
        or not actor.is_active
        or not actor.is_authenticated
        or not actor.has_perm("logistics.change_logisticsapplication")
    ):
        raise PermissionDenied("Logistics application review permission is required.")


def _check_revision(application, expected_revision):
    if expected_revision is not None and application.revision != expected_revision:
        raise ValidationError(
            "Application details changed. Reload and review the current revision."
        )
