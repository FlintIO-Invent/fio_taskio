"""Allowance-only rollout. Customized rows require explicit reconciliation."""

from django.db import migrations

FIELDS = ("max_users", "max_clients", "max_invoices_per_month", "max_appointments_per_month")
CONFIGURATIONS = {
    "starter": ((2, 15, 50, 35), (5, None, 200, 250)),
    "pro": ((5, 60, 200, 150), (10, None, 500, 750)),
    "business": ((10, 150, 500, 400), (15, None, 2000, 3000)),
    "beta": ((5, 60, 200, 150), (10, None, 500, 750)),
}


def configuration_state(plan):
    old, approved = CONFIGURATIONS[plan.slug]
    values = tuple(getattr(plan, field) for field in FIELDS)
    if not all(
        getattr(plan, field)
        for field in ("allow_invoicing", "allow_appointments", "allow_public_booking")
    ):
        return "customized"
    return "approved" if values == approved else "baseline" if values == old else "customized"


def update_allowances(apps, schema_editor):
    Plan = apps.get_model("businesses", "ClarivoPlan")
    alias = schema_editor.connection.alias
    plans = list(Plan.objects.using(alias).select_for_update().filter(slug__in=CONFIGURATIONS))
    found = {plan.slug for plan in plans}
    problems = [f"{slug}: missing" for slug in CONFIGURATIONS.keys() - found]
    problems += [
        f"{plan.slug}: wrong family or customized allowances/features"
        for plan in plans
        if plan.family != "SERVICE" or configuration_state(plan) == "customized"
    ]
    if problems:
        raise RuntimeError(
            "Services allowance rollout NOT completed; no plans updated. Reconcile explicitly: "
            + "; ".join(sorted(problems))
        )
    for plan in plans:
        if configuration_state(plan) == "baseline":
            Plan.objects.using(alias).filter(pk=plan.pk, family="SERVICE").update(
                **dict(zip(FIELDS, CONFIGURATIONS[plan.slug][1], strict=True))
            )


class Migration(migrations.Migration):
    dependencies = [("businesses", "0034_logistics_transport_defaults")]
    operations = [migrations.RunPython(update_allowances, migrations.RunPython.noop)]
