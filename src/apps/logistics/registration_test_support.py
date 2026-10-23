"""Disposable test fixtures for current admission and pre-retirement history."""

from importlib import import_module

from apps.businesses.models import BusinessSubscription, ClarivoPlan

from .models import LogisticsApplication


def activate_logistics_tiers():
    seed = import_module("apps.businesses.migrations.0029_logistics_capacity_plans")
    for slug, name, amount, capacities in seed.TIERS:
        defaults = seed.tier_defaults(name, amount, capacities)
        defaults["is_active"] = True
        ClarivoPlan.objects.update_or_create(slug=slug, defaults=defaults)


def restore_legacy_fixture(application):
    """Reconstruct historical rows; never use current admission to create legacy."""
    application.refresh_from_db()
    LogisticsApplication.objects.filter(pk=application.pk).update(selected_plan_slug="logistics")
    for decision in application.decisions.all():
        inputs = {**decision.evaluated_inputs, "selected_plan_slug": "logistics"}
        application.decisions.filter(pk=decision.pk).update(evaluated_inputs=inputs)
    application.enrollment_tokens.update(selected_plan_slug="logistics")
    if application.business_id:
        BusinessSubscription.objects.filter(business_id=application.business_id).update(
            plan=ClarivoPlan.objects.get(slug="logistics")
        )
    application.refresh_from_db()
