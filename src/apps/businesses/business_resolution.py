from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .models import Business, BusinessUser


class BusinessResolutionError(ValueError):
    """Raised when a business candidate lookup is not well formed."""


class BusinessMatchKind(StrEnum):
    PRIMARY_KEY = "business_id"
    SLUG = "slug"
    MEMBER_EMAIL = "member_email"
    CONTACT_EMAIL = "business_contact_email"


@dataclass(frozen=True, slots=True)
class BusinessCandidateMatch:
    matched_by: BusinessMatchKind
    membership_role: str | None = None
    membership_is_active: bool | None = None


@dataclass(frozen=True, slots=True)
class BusinessCandidate:
    business_id: int
    business_name: str
    slug: str
    business_contact_email: str
    is_active: bool
    matches: tuple[BusinessCandidateMatch, ...]


@dataclass(slots=True)
class _CandidateBuilder:
    business_id: int
    business_name: str
    slug: str
    business_contact_email: str
    is_active: bool
    matches: list[BusinessCandidateMatch] = field(default_factory=list)

    def add_match(self, match: BusinessCandidateMatch) -> None:
        if match not in self.matches:
            self.matches.append(match)

    def build(self) -> BusinessCandidate:
        return BusinessCandidate(
            business_id=self.business_id,
            business_name=self.business_name,
            slug=self.slug,
            business_contact_email=self.business_contact_email,
            is_active=self.is_active,
            matches=tuple(self.matches),
        )


def resolve_business_candidates(
    *,
    business_id: object | None = None,
    slug: str | None = None,
    email: str | None = None,
) -> tuple[BusinessCandidate, ...]:
    """Return all businesses matching exactly one read-only lookup.

    Email lookup intentionally checks member login email and business contact
    email as separate sources. Results are merged by Business primary key; this
    function never selects one candidate on the caller's behalf.
    """

    provided_lookups = [
        business_id is not None,
        slug is not None,
        email is not None,
    ]
    if sum(provided_lookups) != 1:
        raise BusinessResolutionError("Provide exactly one of business_id, slug, or email.")

    if business_id is not None:
        normalized_business_id = _normalize_business_id(business_id)
        return _resolve_direct(
            queryset=Business.objects.filter(pk=normalized_business_id),
            matched_by=BusinessMatchKind.PRIMARY_KEY,
        )

    if slug is not None:
        normalized_slug = slug.strip()
        if not normalized_slug:
            raise BusinessResolutionError("Business slug cannot be empty.")
        return _resolve_direct(
            queryset=Business.objects.filter(slug=normalized_slug),
            matched_by=BusinessMatchKind.SLUG,
        )

    normalized_email = (email or "").strip()
    if not normalized_email:
        raise BusinessResolutionError("Email cannot be empty.")
    return _resolve_email(normalized_email)


def _normalize_business_id(value: object) -> int:
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BusinessResolutionError("Business ID must be a positive integer.") from exc
    if normalized <= 0:
        raise BusinessResolutionError("Business ID must be a positive integer.")
    return normalized


def _resolve_direct(*, queryset, matched_by: BusinessMatchKind) -> tuple[BusinessCandidate, ...]:
    row = queryset.values("id", "name", "slug", "email", "is_active").order_by("pk").first()
    if row is None:
        return ()

    return (
        BusinessCandidate(
            business_id=row["id"],
            business_name=row["name"],
            slug=row["slug"],
            business_contact_email=row["email"],
            is_active=row["is_active"],
            matches=(BusinessCandidateMatch(matched_by=matched_by),),
        ),
    )


def _resolve_email(email: str) -> tuple[BusinessCandidate, ...]:
    candidates: dict[int, _CandidateBuilder] = {}

    memberships = (
        BusinessUser.objects.filter(user__email__iexact=email)
        .values(
            "business_id",
            "business__name",
            "business__slug",
            "business__email",
            "business__is_active",
            "role",
            "is_active",
        )
        .order_by("business_id", "pk")
    )
    for membership in memberships:
        candidate = _get_or_create_builder(
            candidates,
            business_id=membership["business_id"],
            business_name=membership["business__name"],
            slug=membership["business__slug"],
            business_contact_email=membership["business__email"],
            is_active=membership["business__is_active"],
        )
        candidate.add_match(
            BusinessCandidateMatch(
                matched_by=BusinessMatchKind.MEMBER_EMAIL,
                membership_role=membership["role"],
                membership_is_active=membership["is_active"],
            )
        )

    contact_businesses = (
        Business.objects.filter(email__iexact=email)
        .values("id", "name", "slug", "email", "is_active")
        .order_by("pk")
    )
    for business in contact_businesses:
        candidate = _get_or_create_builder(
            candidates,
            business_id=business["id"],
            business_name=business["name"],
            slug=business["slug"],
            business_contact_email=business["email"],
            is_active=business["is_active"],
        )
        candidate.add_match(BusinessCandidateMatch(matched_by=BusinessMatchKind.CONTACT_EMAIL))

    return tuple(candidates[business_id].build() for business_id in sorted(candidates))


def _get_or_create_builder(
    candidates: dict[int, _CandidateBuilder],
    *,
    business_id: int,
    business_name: str,
    slug: str,
    business_contact_email: str,
    is_active: bool,
) -> _CandidateBuilder:
    candidate = candidates.get(business_id)
    if candidate is None:
        candidate = _CandidateBuilder(
            business_id=business_id,
            business_name=business_name,
            slug=slug,
            business_contact_email=business_contact_email,
            is_active=is_active,
        )
        candidates[business_id] = candidate
    return candidate
