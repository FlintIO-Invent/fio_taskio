from decimal import Decimal

from django.db import migrations


PLAN_DATA = {
    "starter": {
        "name": "Starter",
        "description": (
            "For solo owners and small service businesses moving away from WhatsApp, "
            "paper, and spreadsheets."
        ),
        "price_monthly": Decimal("39.00"),
        "price_yearly": Decimal("390.00"),
        "regional_prices": {
            "usd": {
                "currency": "USD",
                "monthly": "39.00",
                "yearly": "390.00",
                "tax_note": "",
            },
            "eur": {
                "currency": "EUR",
                "monthly": "39.00",
                "yearly": "390.00",
                "tax_note": "",
            },
            "caribbean_international": {
                "currency": "USD",
                "monthly": "39.00",
                "yearly": "390.00",
                "tax_note": "",
            },
            "netherlands": {
                "currency": "EUR",
                "monthly": "39.00",
                "yearly": "390.00",
                "tax_note": "",
            },
        },
        "is_recommended": False,
        "is_active": True,
        "max_users": 2,
        "max_clients": 15,
        "max_invoices_per_month": 50,
        "max_appointments_per_month": 35,
        "max_public_bookings_per_month": 50,
        "allow_invoicing": True,
        "allow_appointments": True,
        "allow_memberships": True,
        "allow_public_booking": True,
        "allow_public_request_form": True,
    },
    "pro": {
        "name": "Pro",
        "description": (
            "For growing service businesses with recurring clients, more bookings, "
            "and a small team."
        ),
        "price_monthly": Decimal("79.00"),
        "price_yearly": Decimal("790.00"),
        "regional_prices": {
            "usd": {
                "currency": "USD",
                "monthly": "79.00",
                "yearly": "790.00",
                "tax_note": "",
            },
            "eur": {
                "currency": "EUR",
                "monthly": "79.00",
                "yearly": "790.00",
                "tax_note": "",
            },
            "caribbean_international": {
                "currency": "USD",
                "monthly": "79.00",
                "yearly": "790.00",
                "tax_note": "",
            },
            "netherlands": {
                "currency": "EUR",
                "monthly": "79.00",
                "yearly": "790.00",
                "tax_note": "",
            },
        },
        "is_recommended": True,
        "is_active": True,
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
    },
    "business": {
        "name": "Business",
        "description": (
            "For serious service teams with higher volume, multiple staff members, "
            "and a real operational workflow."
        ),
        "price_monthly": Decimal("159.00"),
        "price_yearly": Decimal("1590.00"),
        "regional_prices": {
            "usd": {
                "currency": "USD",
                "monthly": "159.00",
                "yearly": "1590.00",
                "tax_note": "",
            },
            "eur": {
                "currency": "EUR",
                "monthly": "149.00",
                "yearly": "1490.00",
                "tax_note": "",
            },
            "caribbean_international": {
                "currency": "USD",
                "monthly": "159.00",
                "yearly": "1590.00",
                "tax_note": "",
            },
            "netherlands": {
                "currency": "EUR",
                "monthly": "149.00",
                "yearly": "1490.00",
                "tax_note": "",
            },
        },
        "is_recommended": False,
        "is_active": True,
        "max_users": 10,
        "max_clients": 150,
        "max_invoices_per_month": 500,
        "max_appointments_per_month": 400,
        "max_public_bookings_per_month": 750,
        "allow_invoicing": True,
        "allow_appointments": True,
        "allow_memberships": True,
        "allow_public_booking": True,
        "allow_public_request_form": True,
    },
}


def update_motionmate_final_tiers(apps, schema_editor):
    ClarivoPlan = apps.get_model("businesses", "ClarivoPlan")
    db_alias = schema_editor.connection.alias

    ClarivoPlan.objects.using(db_alias).exclude(slug="pro").filter(
        is_recommended=True,
    ).update(is_recommended=False)

    for slug, plan_data in PLAN_DATA.items():
        ClarivoPlan.objects.using(db_alias).update_or_create(
            slug=slug,
            defaults=plan_data,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("businesses", "0012_motionmate_simple_tiers"),
    ]

    operations = [
        migrations.RunPython(
            update_motionmate_final_tiers,
            migrations.RunPython.noop,
        ),
    ]
