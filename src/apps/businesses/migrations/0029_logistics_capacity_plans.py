"""Seed staged tiers only; never rewrite an existing plan or subscription."""

from decimal import Decimal

from django.db import migrations

# Frozen migration values, independent of future application catalog changes.
TIERS = (
    ("logistics-core", "Logistics Core", 1700, (10, 2, 250, 300, 80, 100, 25, 3000, 300, 1)),
    ("logistics-growth", "Logistics Growth", 2300, (15, 4, 800, 900, 200, 300, 50, 9000, 900, 3)),
    (
        "logistics-scale",
        "Logistics Scale",
        3000,
        (25, 8, 2000, 1800, 400, 600, 100, 18000, 1800, 6),
    ),
)
CAPACITY_FIELDS = (
    "max_users",
    "max_locations",
    "max_clients",
    "max_parcels_per_month",
    "max_shipments_per_month",
    "max_invoices_per_month",
    "max_services",
    "parcel_events_per_month_budget",
    "transactional_emails_per_month_budget",
    "storage_planning_gb",
)


def tier_defaults(name, yearly_eur, capacities):
    amount = Decimal(yearly_eur).quantize(Decimal("0.01"))
    return {
        "name": name,
        "family": "LOGISTICS",
        "description": "Annual Logistics capacity tier. Staged; Stripe checkout is not enabled. "
        "Account capacity includes the owner. Events/email are monitoring budgets; storage is planning only.",
        "is_active": False,
        "is_recommended": False,
        # Monthly is an unused schema placeholder; annual-only policy/display
        # never exposes this as a monthly or free offer. No USD value is seeded.
        "price_monthly": Decimal("0.00"),
        "price_yearly": amount,
        "regional_prices": {"eur": {"currency": "EUR", "yearly": str(amount)}},
        "allow_invoicing": True,
        "allow_appointments": False,
        "allow_memberships": False,
        "allow_public_booking": False,
        "allow_public_request_form": False,
        "max_appointments_per_month": None,
        "max_public_bookings_per_month": None,
        **dict(zip(CAPACITY_FIELDS, capacities, strict=True)),
    }


def seed_tiers(apps, schema_editor):
    Plan = apps.get_model("businesses", "ClarivoPlan")
    for slug, name, yearly_eur, capacities in TIERS:
        defaults = tier_defaults(name, yearly_eur, capacities)
        plan, created = Plan.objects.using(schema_editor.connection.alias).get_or_create(
            slug=slug, defaults=defaults
        )
        if not created and any(getattr(plan, key) != value for key, value in defaults.items()):
            raise RuntimeError(
                f"Reserved Logistics tier slug {slug!r} already has different configuration; review manually."
            )


def remove_unused_tiers(apps, schema_editor):
    Plan = apps.get_model("businesses", "ClarivoPlan")
    Subscription = apps.get_model("businesses", "BusinessSubscription")
    alias = schema_editor.connection.alias
    removable = []
    for slug, name, yearly_eur, capacities in TIERS:
        plan = Plan.objects.using(alias).filter(slug=slug).first()
        if plan is None:
            continue
        defaults = tier_defaults(name, yearly_eur, capacities)
        if Subscription.objects.using(alias).filter(plan_id=plan.pk).exists() or any(
            getattr(plan, key) != value for key, value in defaults.items()
        ):
            raise RuntimeError(
                "Cannot reverse configured or subscribed Logistics tiers; roll back code and retain schema."
            )
        removable.append(plan.pk)
    Plan.objects.using(alias).filter(pk__in=removable).delete()


class Migration(migrations.Migration):
    dependencies = [("businesses", "0028_logistics_capacity_fields")]

    operations = [migrations.RunPython(seed_tiers, remove_unused_tiers)]
