"""Deterministic, UI-independent evaluation of validated application inputs."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .policy import LogisticsEligibilityPolicy, normalized_identity


class ReasonCode(StrEnum):
    HIGH_MONTHLY_VOLUME = "HIGH_MONTHLY_VOLUME"
    HIGH_STAFF_COUNT = "HIGH_STAFF_COUNT"
    CUSTOM_WORKFLOW = "CUSTOM_WORKFLOW"
    MULTI_BRANCH = "MULTI_BRANCH"
    MULTI_JURISDICTION = "MULTI_JURISDICTION"
    API_INTEGRATION_REQUIRED = "API_INTEGRATION_REQUIRED"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    EXISTING_MOTIONMATE_RELATIONSHIP = "EXISTING_MOTIONMATE_RELATIONSHIP"
    INCOMPLETE_BUSINESS_REGISTRATION = "INCOMPLETE_BUSINESS_REGISTRATION"
    UNSUPPORTED_TERRITORY = "UNSUPPORTED_TERRITORY"
    CUSTOM_PRICING_REQUESTED = "CUSTOM_PRICING_REQUESTED"
    HIGH_RESOURCE_INTENSITY = "HIGH_RESOURCE_INTENSITY"


@dataclass(frozen=True)
class RelationshipSignals:
    existing_user: bool = False
    existing_business: bool = False
    duplicate_application: bool = False


@dataclass(frozen=True)
class EligibilityDecision:
    result: str
    reason_codes: tuple[str, ...]
    resource_classification: str


def evaluate_eligibility(
    inputs: Mapping[str, Any],
    policy: LogisticsEligibilityPolicy,
    relationships: RelationshipSignals | None = None,
) -> EligibilityDecision:
    relationships = relationships or RelationshipSignals()
    reasons = set()
    volume = inputs["monthly_parcel_estimate"]
    if volume > policy.review_above_monthly_parcels:
        reasons.add(ReasonCode.HIGH_MONTHLY_VOLUME)
    if inputs["expected_staff_count"] > policy.auto_approve_staff_count:
        reasons.add(ReasonCode.HIGH_STAFF_COUNT)
    if inputs["location_count"] > policy.auto_approve_location_count:
        reasons.add(ReasonCode.MULTI_BRANCH)
    custom = inputs["custom_workflow"] or bool(inputs["custom_workflow_details"].strip())
    if custom:
        reasons.add(ReasonCode.CUSTOM_WORKFLOW)
    if inputs["multi_jurisdiction"]:
        reasons.add(ReasonCode.MULTI_JURISDICTION)
    if inputs["api_integration_needed"]:
        reasons.add(ReasonCode.API_INTEGRATION_REQUIRED)
    if inputs["custom_pricing_requested"]:
        reasons.add(ReasonCode.CUSTOM_PRICING_REQUESTED)
    if relationships.existing_user or relationships.existing_business:
        reasons.add(ReasonCode.EXISTING_MOTIONMATE_RELATIONSHIP)
    if relationships.duplicate_application or relationships.existing_business:
        reasons.add(ReasonCode.POSSIBLE_DUPLICATE)
    if policy.registration_required_for_auto_approval and not inputs["registration_number"].strip():
        reasons.add(ReasonCode.INCOMPLETE_BUSINESS_REGISTRATION)
    if normalized_identity(inputs["country"]) not in policy.supported_territories:
        reasons.add(ReasonCode.UNSUPPORTED_TERRITORY)

    # Standard tracking and manifests are ordinary Logistics requirements. Unknown
    # operations/processes and high-volume combinations cannot be sized confidently.
    unknown = inputs["operation_type"] == "OTHER" or inputs["current_process_method"] == "OTHER"
    intense = (
        volume >= policy.high_resource_monthly_parcels
        or (
            volume > policy.auto_approve_monthly_parcels
            and (custom or inputs["api_integration_needed"])
        )
        or (
            volume > policy.review_above_monthly_parcels
            and (inputs["customer_tracking_needed"] or inputs["manifest_needed"])
        )
    )
    if unknown or intense:
        reasons.add(ReasonCode.HIGH_RESOURCE_INTENSITY)
    resource_review = intense or any(
        code in reasons
        for code in (
            ReasonCode.HIGH_MONTHLY_VOLUME,
            ReasonCode.HIGH_STAFF_COUNT,
            ReasonCode.MULTI_BRANCH,
            ReasonCode.CUSTOM_WORKFLOW,
            ReasonCode.MULTI_JURISDICTION,
            ReasonCode.API_INTEGRATION_REQUIRED,
        )
    )
    resource = "UNKNOWN" if unknown else "REQUIRES_REVIEW" if resource_review else "STANDARD"
    # The middle band is approved only when every other dimension is simple.
    # No uncertain input produces an automatic decline.
    return EligibilityDecision(
        "UNDER_REVIEW" if reasons else "APPROVED",
        tuple(code.value for code in ReasonCode if code in reasons),
        resource,
    )
