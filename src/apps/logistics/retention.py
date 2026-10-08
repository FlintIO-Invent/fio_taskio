"""Minimum application retention policy for the existing controlled tenant purge."""

from django.utils import timezone

from apps.businesses.models import Business

from .models import LogisticsApplication


def _lock_application_for_business_purge(business_id):
    # Enrollment/review/checkout lock the application first. Purge uses that order
    # too, before locking Business. The controlled purge owns the transaction.
    return LogisticsApplication.objects.select_for_update().filter(business_id=business_id).first()


def _release_application_for_business_purge(*, business):
    """Called only after every purge gate passes, inside the purge savepoint.

    Application inputs, immutable decisions, grants and enrolled User survive.
    The Business FK remains PROTECT for every ordinary deletion path. Only the
    controlled purge releases it while preserving its immutable identity.
    """
    application = LogisticsApplication.objects.filter(business=business).first()
    if application is None:
        return 0
    if business.is_active or business.vertical != Business.Vertical.LOGISTICS:
        raise ValueError("Application retention release requires an inactive Logistics tenant.")
    application.enrollment_tokens.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    LogisticsApplication.objects.filter(pk=application.pk, business=business).update(
        business_id_snapshot=business.pk, business=None
    )
    return 1
