from decimal import Decimal

from django.db import migrations


DEFAULT_PLANS = [
    {
        "slug": "starter",
        "name": "Starter",
        "description": "Essential Clarivo workspace for small teams getting started.",
        "price_monthly": Decimal("0.00"),
        "price_yearly": Decimal("0.00"),
        "is_active": True,
        "max_users": 2,
        "max_clients": 100,
        "max_invoices_per_month": 50,
        "allow_invoicing": True,
        "allow_appointments": False,
        "allow_memberships": False,
        "allow_public_booking": False,
        "allow_public_request_form": False,
    },
    {
        "slug": "pro",
        "name": "Pro",
        "description": "Growing Clarivo workspace with invoicing and scheduling access.",
        "price_monthly": Decimal("0.00"),
        "price_yearly": Decimal("0.00"),
        "is_active": True,
        "max_users": 5,
        "max_clients": 500,
        "max_invoices_per_month": 250,
        "allow_invoicing": True,
        "allow_appointments": True,
        "allow_memberships": False,
        "allow_public_booking": True,
        "allow_public_request_form": True,
    },
    {
        "slug": "business",
        "name": "Business",
        "description": "Expanded Clarivo workspace for larger teams and advanced modules.",
        "price_monthly": Decimal("0.00"),
        "price_yearly": Decimal("0.00"),
        "is_active": True,
        "max_users": 15,
        "max_clients": 2000,
        "max_invoices_per_month": 1000,
        "allow_invoicing": True,
        "allow_appointments": True,
        "allow_memberships": True,
        "allow_public_booking": True,
        "allow_public_request_form": False,
    },
]


def seed_default_clarivo_plans(apps, schema_editor):
    ClarivoPlan = apps.get_model("businesses", "ClarivoPlan")
    db_alias = schema_editor.connection.alias

    for plan_data in DEFAULT_PLANS:
        slug = plan_data["slug"]
        defaults = {key: value for key, value in plan_data.items() if key != "slug"}
        ClarivoPlan.objects.using(db_alias).update_or_create(
            slug=slug,
            defaults=defaults,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("businesses", "0002_clarivoplan_businesssubscription"),
    ]

    operations = [
        migrations.RunPython(
            seed_default_clarivo_plans,
            migrations.RunPython.noop,
        ),
    ]
