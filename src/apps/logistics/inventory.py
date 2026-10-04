"""Application inventory; identity matches are not ownership or purge links."""

from .models import LogisticsApplication


def application_inventory(application_id):
    application = LogisticsApplication.objects.get(pk=application_id)
    return {
        "application_id": str(application.pk),
        "status": application.status,
        "revision": application.revision,
        "approved_revision": application.approved_revision,
        "evaluated_revision": application.evaluated_revision,
        "reason_codes": application.reason_codes,
        "rule_version": application.rule_version,
        "evaluated_at": application.evaluated_at.isoformat() if application.evaluated_at else None,
        "decision_count": application.decisions.count(),
        "business_link_present": application.business_id is not None,
        "business_id": application.business_id,
        "enrolled_user_id": application.enrolled_user_id,
        "converted_revision": application.converted_revision,
        "converted_at": application.converted_at.isoformat() if application.converted_at else None,
        "subscription_link_present": bool(
            application.business_id and hasattr(application.business, "subscription")
        ),
        "enrollment_token_count": application.enrollment_tokens.count(),
        "application_deletion_protected_by_decisions": application.decisions.exists(),
        "business_purge_owns_application": False,
    }
