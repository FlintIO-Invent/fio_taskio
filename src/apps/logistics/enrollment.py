"""Application-bound enrollment. No Stripe calls or operational activation."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import SaaSUserProfile
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan

from .models import LogisticsApplication, LogisticsEnrollmentToken
from .services import _require_reviewer

TOKEN_LIFETIME = timedelta(days=7)
INVALID_LINK = "This enrollment link is unavailable. Contact Motionmate for a new link."


def _digest(secret):
    if not isinstance(secret, str) or not 32 <= len(secret) <= 128:
        raise ValidationError(INVALID_LINK)
    return hashlib.sha256(secret.encode()).hexdigest()


def _require_approved(application, revision):
    if (
        application.status != LogisticsApplication.Status.APPROVED
        or application.revision != revision
        or application.approved_revision != revision
        or application.evaluated_revision != revision
    ):
        raise ValidationError(INVALID_LINK)


@transaction.atomic
def issue_enrollment_link(application_id, *, actor, expected_revision):
    """Reviewers must deliver this single-use link privately to the applicant email."""
    _require_reviewer(actor)
    application = LogisticsApplication.objects.select_for_update().get(pk=application_id)
    _require_approved(application, expected_revision)
    if application.converted_at is not None:
        raise ValidationError("This application has already been enrolled.")
    now = timezone.now()
    application.enrollment_tokens.filter(revoked_at__isnull=True).update(revoked_at=now)
    secret = secrets.token_urlsafe(32)
    LogisticsEnrollmentToken.objects.create(
        application=application,
        token_digest=_digest(secret),
        application_revision=application.revision,
        expires_at=now + TOKEN_LIFETIME,
        issued_by=actor,
    )
    return secret


@transaction.atomic
def revoke_enrollment_links(application_id, *, actor):
    _require_reviewer(actor)
    application = LogisticsApplication.objects.select_for_update().get(pk=application_id)
    return application.enrollment_tokens.filter(revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def _load(secret, *, lock=False):
    digest = _digest(secret)
    # All writers lock application before grant to avoid lock-order inversions.
    grant = LogisticsEnrollmentToken.objects.filter(token_digest=digest).first()
    if grant is None:
        raise ValidationError(INVALID_LINK)
    applications = LogisticsApplication.objects
    grants = LogisticsEnrollmentToken.objects
    if lock:
        applications = applications.select_for_update()
        grants = grants.select_for_update()
    application = applications.get(pk=grant.application_id)
    grant = grants.get(pk=grant.pk)
    if application.converted_at is not None and application.business_id is None:
        raise ValidationError(INVALID_LINK)
    if grant.revoked_at is not None or grant.expires_at <= timezone.now():
        raise ValidationError(INVALID_LINK)
    _require_approved(application, grant.application_revision)
    return application, grant


def inspect_enrollment_link(secret):
    """Non-mutating display check; provisioning always repeats it under a row lock."""
    return _load(secret)[0]


@dataclass(frozen=True)
class EnrollmentResult:
    user: object
    business: Business
    subscription: BusinessSubscription
    reused: bool


@transaction.atomic
def enroll_application(secret, *, authenticated_user=None, password=None):
    application, grant = _load(secret, lock=True)
    User = get_user_model()
    verified = None
    if authenticated_user is not None and authenticated_user.is_authenticated:
        verified = (
            User.objects.select_for_update()
            .filter(pk=authenticated_user.pk, is_active=True, email__iexact=application.email)
            .first()
        )
        if verified is None:
            raise PermissionDenied("Authenticate as the applicant account to enroll.")

    if application.converted_at is not None:
        # The bearer cannot replay a consumed grant to gain account access. Only
        # its authenticated owner can receive the previous result on a retry.
        if not grant.used_at or not verified or verified.pk != application.enrolled_user_id:
            raise PermissionDenied("Authenticate as the enrolled account to continue.")
        return EnrollmentResult(
            verified, application.business, application.business.subscription, True
        )
    if grant.used_at is not None:
        raise ValidationError(INVALID_LINK)

    matches = list(User.objects.select_for_update().filter(email__iexact=application.email))
    if len(matches) > 1 or (matches and (verified is None or matches[0].pk != verified.pk)):
        raise PermissionDenied("Authenticate as the applicant account to enroll.")
    user = verified
    new_user = user is None
    if new_user:
        if not password:
            raise ValidationError("Set a password for your new account.")
        candidate = User(
            email=application.email,
            first_name=application.contact_first_name[:30],
            last_name=application.contact_last_name[:30],
        )
        validate_password(password, candidate)
        try:
            # The savepoint makes duplicate-email races fail without partial rows.
            with transaction.atomic():
                user = User.objects.create_user(
                    email=application.email,
                    first_name=candidate.first_name,
                    last_name=candidate.last_name,
                    company_name=application.business_name[:100],
                    incorporation_status="UNINCORPORATED",
                    password=password,
                )
        except IntegrityError as exc:
            raise ValidationError(
                "An account may already exist. Sign in and retry enrollment."
            ) from exc
        # Serialize all conversions for this identity, including different applications.
        user = User.objects.select_for_update().get(pk=user.pk)
    if BusinessUser.objects.filter(user=user, is_active=True, business__is_active=True).exists():
        raise ValidationError(
            "This account already has an active workspace. Contact Motionmate for review."
        )

    plan = ClarivoPlan.objects.filter(slug="logistics", family=ClarivoPlan.Family.LOGISTICS).first()
    if plan is None:
        raise ValidationError("The Logistics offering is unavailable. Contact Motionmate.")
    # Inactive/unpriced offerings may be staged here. Checkout must enforce Block 2
    # activation and Price configuration before any payment or operational access.
    business = Business.objects.create(
        name=application.business_name,
        slug=f"{slugify(application.business_name)[:100] or 'logistics'}-{uuid.uuid4().hex}",
        vertical=Business.Vertical.LOGISTICS,
        email=application.email,
        phone=application.phone,
        address=application.business_address,
        country=application.country,
        currency=application.preferred_currency,
        timezone=application.timezone,
    )
    BusinessUser.objects.create(user=user, business=business, role=BusinessUser.Role.OWNER)
    profile = SaaSUserProfile.get_or_create_for_user(user)
    if new_user:
        profile.workspace_name = business.name
        profile.billing_email = business.email
        profile.currency_code = business.currency
        profile.save(
            update_fields=["workspace_name", "billing_email", "currency_code", "updated_at"]
        )
    subscription = BusinessSubscription.objects.create(
        business=business,
        plan=plan,
        status=BusinessSubscription.Status.PENDING_CHECKOUT,
        payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
        billing_interval=BusinessSubscription.BillingInterval.YEARLY,
        billing_currency=application.preferred_currency.lower(),
    )
    now = timezone.now()
    LogisticsApplication.objects.filter(pk=application.pk).update(
        business=business,
        business_id_snapshot=business.pk,
        enrolled_user=user,
        converted_at=now,
        converted_revision=application.revision,
        updated_at=now,
    )
    grant.used_at = now
    grant.save(update_fields=["used_at"])
    return EnrollmentResult(user, business, subscription, False)
