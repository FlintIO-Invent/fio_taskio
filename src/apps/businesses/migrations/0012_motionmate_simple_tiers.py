from decimal import Decimal

from django.db import migrations, models


PLAN_DATA = {
    "starter": {
        "name": "Starter",
        "description": (
            "Essential Motionmate workspace for small businesses managing clients and invoices."
        ),
        "price_monthly": Decimal("19.00"),
        "price_yearly": Decimal("190.00"),
        "regional_prices": {
            "caribbean_international": {
                "currency": "EUR",
                "monthly": "19.00",
                "yearly": "190.00",
                "tax_note": "",
            },
            "netherlands": {
                "currency": "EUR",
                "monthly": "29.00",
                "yearly": "290.00",
                "tax_note": "ex. VAT",
            },
        },
        "is_recommended": False,
        "is_active": True,
        "max_users": 2,
        "max_clients": 100,
        "max_invoices_per_month": 50,
        "max_appointments_per_month": 0,
        "max_public_bookings_per_month": 0,
        "allow_invoicing": True,
        "allow_appointments": False,
        "allow_memberships": False,
        "allow_public_booking": False,
        "allow_public_request_form": False,
    },
    "pro": {
        "name": "Pro",
        "description": (
            "Growing Motionmate workspace for teams that need client management, "
            "invoicing, and appointments."
        ),
        "price_monthly": Decimal("69.00"),
        "price_yearly": Decimal("690.00"),
        "regional_prices": {
            "caribbean_international": {
                "currency": "EUR",
                "monthly": "69.00",
                "yearly": "690.00",
                "tax_note": "",
            },
            "netherlands": {
                "currency": "EUR",
                "monthly": "99.00",
                "yearly": "990.00",
                "tax_note": "ex. VAT",
            },
        },
        "is_recommended": True,
        "is_active": True,
        "max_users": 5,
        "max_clients": 500,
        "max_invoices_per_month": 250,
        "max_appointments_per_month": 250,
        "max_public_bookings_per_month": 0,
        "allow_invoicing": True,
        "allow_appointments": True,
        "allow_memberships": False,
        "allow_public_booking": False,
        "allow_public_request_form": False,
    },
    "business": {
        "name": "Business",
        "description": (
            "Complete Motionmate workspace for businesses that need clients, invoices, "
            "appointments, and public bookings."
        ),
        "price_monthly": Decimal("119.00"),
        "price_yearly": Decimal("1190.00"),
        "regional_prices": {
            "caribbean_international": {
                "currency": "EUR",
                "monthly": "119.00",
                "yearly": "1190.00",
                "tax_note": "",
            },
            "netherlands": {
                "currency": "EUR",
                "monthly": "169.00",
                "yearly": "1690.00",
                "tax_note": "ex. VAT",
            },
        },
        "is_recommended": False,
        "is_active": True,
        "max_users": 15,
        "max_clients": 2000,
        "max_invoices_per_month": 1000,
        "max_appointments_per_month": 1000,
        "max_public_bookings_per_month": 1000,
        "allow_invoicing": True,
        "allow_appointments": True,
        "allow_memberships": False,
        "allow_public_booking": True,
        "allow_public_request_form": True,
    },
}


def update_motionmate_simple_tiers(apps, schema_editor):
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
        ("businesses", "0011_motionmate_plan_pricing"),
    ]

    operations = [
        migrations.AddField(
            model_name="clarivoplan",
            name="max_appointments_per_month",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="clarivoplan",
            name="max_public_bookings_per_month",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(
            update_motionmate_simple_tiers,
            migrations.RunPython.noop,
        ),
    ]
