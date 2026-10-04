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
        "business_link_present": False,
        "subscription_link_present": False,
        "application_deletion_protected_by_decisions": application.decisions.exists(),
        "business_purge_owns_application": False,
    }
