"""Explicit reviewed fixtures for older tests that exercise non-admin role rules."""

from django.utils import timezone

from .models import (
    LogisticsHandlingSite,
    LogisticsLocation,
    LogisticsLocationAssignment,
    LogisticsProfile,
)


def approve_test_site(*, business, membership, parcel=None):
    site, _ = LogisticsLocation.objects.get_or_create(
        business=business,
        code="TEST-SITE",
        defaults={
            "name": "Approved test site",
            "location_type": "HUB",
            "country_code": "US",
        },
    )
    LogisticsLocationAssignment.objects.get_or_create(
        business=business,
        membership=membership,
        location=site,
        defaults={"can_operate": True, "is_current": True},
    )
    profile, _ = LogisticsProfile.objects.get_or_create(business=business)
    profile.location_access_reviewed_at = timezone.now()
    profile.save(update_fields=["location_access_reviewed_at"])
    if parcel is not None:
        LogisticsHandlingSite.objects.get_or_create(
            business=business, parcel=parcel, location=site, kind="STOP"
        )
    return site
