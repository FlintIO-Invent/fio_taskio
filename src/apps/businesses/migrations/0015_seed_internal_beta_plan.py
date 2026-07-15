from decimal import Decimal

from django.db import migrations

BETA_PLAN_SLUG = "beta"
BETA_PLAN_NAME = "Beta — Free Early Access (Limited Availability)"

PRO_EQUIVALENT_LIMITS = {
    "max_users": 5,
    "max_clients": 60,
    "max_invoices_per_month": 200,
    "max_appointments_per_month": 150,
    "max_public_bookings_per_month": 250,
    "allow_invoicing": True,
    "allow_appointments": True,
    "allow_memberships": True,
    "allow_public_booking": True,
    "allow_public_request_form": True,
}
COPY_FROM_PRO_FIELDS = tuple(PRO_EQUIVALENT_LIMITS.keys())
ZERO_REGIONAL_PRICES = {
    "usd": {
        "currency": "USD",
        "monthly": "0.00",
        "yearly": "0.00",
        "tax_note": "",
    },
    "eur": {
        "currency": "EUR",
        "monthly": "0.00",
        "yearly": "0.00",
        "tax_note": "",
    },
    "caribbean_international": {
        "currency": "USD",
        "monthly": "0.00",
        "yearly": "0.00",
        "tax_note": "",
    },
    "netherlands": {
        "currency": "EUR",
        "monthly": "0.00",
        "yearly": "0.00",
        "tax_note": "",
    },
}


def seed_internal_beta_plan(apps, schema_editor):
    ClarivoPlan = apps.get_model("businesses", "ClarivoPlan")
    db_alias = schema_editor.connection.alias
    pro_plan = ClarivoPlan.objects.using(db_alias).filter(slug="pro").first()

    defaults = {
        "name": BETA_PLAN_NAME,
        "description": "Internal free early access plan for invited Motionmate Beta businesses.",
        "price_monthly": Decimal("0.00"),
        "price_yearly": Decimal("0.00"),
        "regional_prices": ZERO_REGIONAL_PRICES,
        "is_recommended": False,
        "is_active": True,
    }
    for field_name in COPY_FROM_PRO_FIELDS:
        defaults[field_name] = (
            getattr(pro_plan, field_name)
            if pro_plan is not None
            else PRO_EQUIVALENT_LIMITS[field_name]
        )

    ClarivoPlan.objects.using(db_alias).update_or_create(
        slug=BETA_PLAN_SLUG,
        defaults=defaults,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("businesses", "0014_useronboardingstate"),
    ]

    operations = [
        migrations.RunPython(
            seed_internal_beta_plan,
            migrations.RunPython.noop,
        ),
    ]
