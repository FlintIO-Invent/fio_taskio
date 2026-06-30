from decimal import Decimal

from django.db import migrations, models

MOTIONMATE_PLAN_DATA = {
    "starter": {
        "name": "Starter",
        "description": (
            "Essential Motionmate workspace for solo operators and small teams getting "
            "started with clients, requests, appointments, and invoices."
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
        "allow_invoicing": True,
        "allow_appointments": True,
        "allow_memberships": True,
        "allow_public_booking": True,
        "allow_public_request_form": True,
    },
    "pro": {
        "name": "Pro",
        "description": (
            "Growing Motionmate workspace for teams that need client management, public "
            "requests, appointments, invoicing, and daily operations in one place."
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
        "allow_invoicing": True,
        "allow_appointments": True,
        "allow_memberships": True,
        "allow_public_booking": True,
        "allow_public_request_form": True,
    },
    "business": {
        "name": "Business",
        "description": (
            "Expanded Motionmate workspace for larger teams with higher client volume, "
            "invoicing needs, and advanced operational workflows."
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
        "allow_invoicing": True,
        "allow_appointments": True,
        "allow_memberships": True,
        "allow_public_booking": True,
        "allow_public_request_form": True,
    },
}


def update_motionmate_plan_pricing(apps, schema_editor):
    ClarivoPlan = apps.get_model("businesses", "ClarivoPlan")
    db_alias = schema_editor.connection.alias

    ClarivoPlan.objects.using(db_alias).exclude(slug="pro").filter(
        is_recommended=True,
    ).update(is_recommended=False)

    for slug, plan_data in MOTIONMATE_PLAN_DATA.items():
        ClarivoPlan.objects.using(db_alias).update_or_create(
            slug=slug,
            defaults=plan_data,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("businesses", "0010_weeklyavailability_staff_member_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="clarivoplan",
            name="is_recommended",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="clarivoplan",
            name="regional_prices",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(
            update_motionmate_plan_pricing,
            migrations.RunPython.noop,
        ),
    ]
