from decimal import Decimal

from django.db import migrations


def seed_logistics_offering(apps, schema_editor):
    Plan = apps.get_model("businesses", "ClarivoPlan")
    plan, _created = Plan.objects.using(schema_editor.connection.alias).get_or_create(
        slug="logistics",
        defaults={
            "name": "Logistics",
            "family": "LOGISTICS",
            "description": "Annual Logistics offering. Pricing and limits awaiting configuration; not for sale yet.",
            # Unset placeholders, not free commercial pricing. Activation is deliberate.
            "price_monthly": Decimal("0.00"),
            "price_yearly": Decimal("0.00"),
            "is_active": False,
            "allow_invoicing": True,
        },
    )
    if plan.family != "LOGISTICS":
        raise RuntimeError("The reserved logistics plan slug already belongs to another family.")


def remove_logistics_offering(apps, schema_editor):
    # PROTECT prevents rollback after a real subscription references this offering.
    plans = (
        apps.get_model("businesses", "ClarivoPlan")
        .objects.using(schema_editor.connection.alias)
        .filter(slug="logistics", family="LOGISTICS")
    )
    plan = plans.first()
    if plan is not None and (
        plan.is_active or plan.price_monthly or plan.price_yearly or plan.regional_prices
    ):
        raise RuntimeError(
            "Cannot roll back a configured Logistics offering; preserve its billing configuration."
        )
    plans.delete()


class Migration(migrations.Migration):
    dependencies = [("businesses", "0025_clarivoplan_family")]

    operations = [migrations.RunPython(seed_logistics_offering, remove_logistics_offering)]
