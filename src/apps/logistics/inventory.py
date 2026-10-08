"""Application inventory; identity matches are not ownership or purge links."""

from .models import LogisticsApplication, LogisticsApplicationDecision, LogisticsEnrollmentToken


def retained_application_user_ids(user_ids):
    """Preserve users referenced by application/enrollment history during tenant purge."""
    if not user_ids:
        return set()
    return (
        set(
            LogisticsApplication.objects.filter(enrolled_user_id__in=user_ids).values_list(
                "enrolled_user_id", flat=True
            )
        )
        | set(
            LogisticsApplicationDecision.objects.filter(actor_id__in=user_ids).values_list(
                "actor_id", flat=True
            )
        )
        | set(
            LogisticsEnrollmentToken.objects.filter(issued_by_id__in=user_ids).values_list(
                "issued_by_id", flat=True
            )
        )
    )


def application_inventory(application_id):
    application = LogisticsApplication.objects.get(pk=application_id)
    subscription = None
    if application.business_id:
        from apps.businesses.models import BusinessSubscription

        subscription = (
            BusinessSubscription.objects.select_related("plan")
            .filter(business_id=application.business_id)
            .first()
        )
    return {
        "application_id": str(application.pk),
        "status": application.status,
        "revision": application.revision,
        "approved_revision": application.approved_revision,
        "evaluated_revision": application.evaluated_revision,
        "operating_areas": application.operating_areas,
        "transportation_modes": application.transportation_modes,
        "reason_codes": application.reason_codes,
        "rule_version": application.rule_version,
        "evaluated_at": application.evaluated_at.isoformat() if application.evaluated_at else None,
        "decision_count": application.decisions.count(),
        "business_link_present": application.business_id is not None,
        "business_id": application.business_id,
        "business_id_snapshot": application.business_id_snapshot,
        "business_purged": application.converted_at is not None and application.business_id is None,
        "business_vertical": application.business.vertical if application.business_id else None,
        "business_is_active": application.business.is_active if application.business_id else None,
        "subscription_plan": subscription.plan.slug if subscription else None,
        "subscription_interval": subscription.billing_interval if subscription else None,
        "subscription_status": subscription.status if subscription else None,
        "enrolled_user_id": application.enrolled_user_id,
        "converted_revision": application.converted_revision,
        "converted_at": application.converted_at.isoformat() if application.converted_at else None,
        "subscription_link_present": subscription is not None,
        "enrollment_token_count": application.enrollment_tokens.count(),
        "application_deletion_protected_by_decisions": application.decisions.exists(),
        "business_purge_owns_application": False,
        "business_purge_retains_application_history": True,
    }
