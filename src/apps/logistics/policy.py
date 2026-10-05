"""Typed pilot review thresholds. These are eligibility rules, not plan limits."""

import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalized_identity(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKC", value).casefold() if char.isalnum()
    )


class LogisticsUsageReviewPolicy(BaseModel):
    """Optional operational signals, independent of approval and plan limits."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    approaching_ratio: float = Field(default=0.8, gt=0, le=1)
    monthly_event_review_threshold: int | None = Field(default=None, ge=0)


class LogisticsEligibilityPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_version: str = Field(default="pilot-v1", min_length=1, max_length=100)
    auto_approve_monthly_parcels: int = Field(default=1000, ge=0)
    review_above_monthly_parcels: int = Field(default=5000, ge=0)
    high_resource_monthly_parcels: int = Field(default=10000, ge=1)
    auto_approve_staff_count: int = Field(default=10, ge=1)
    auto_approve_location_count: int = Field(default=1, ge=1)
    supported_territories: tuple[str, ...] = ()
    registration_required_for_auto_approval: bool = True

    @field_validator("rule_version")
    @classmethod
    def clean_version(cls, value):
        if not value.strip():
            raise ValueError("A nonempty eligibility rule version is required.")
        return value.strip()

    @field_validator("supported_territories")
    @classmethod
    def clean_territories(cls, values):
        return tuple(
            sorted({normalized_identity(value) for value in values if normalized_identity(value)})
        )

    @model_validator(mode="after")
    def ordered_volume_thresholds(self):
        if (
            not self.auto_approve_monthly_parcels
            <= self.review_above_monthly_parcels
            < self.high_resource_monthly_parcels
        ):
            raise ValueError(
                "Logistics volume thresholds must satisfy auto <= review < high-resource."
            )
        return self
