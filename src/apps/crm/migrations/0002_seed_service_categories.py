from django.db import migrations


def seed_service_categories(apps, schema_editor):
    ServiceCategory = apps.get_model("crm", "ServiceCategory")

    defaults = [
        ("SEPTIC_PUMPING", "Septic Pumping"),
        ("SEPTIC_INSTALLATION", "Septic Installation"),
        ("SEPTIC_REPAIR", "Septic Repair"),
        ("GREASE_TRAP_SERVICES", "Grease Trap Services"),
        ("UNCLOGGING_SERVICES", "Unclogging Services"),
        ("OTHER", "Other"),
    ]

    for code, name in defaults:
        ServiceCategory.objects.update_or_create(
            code=code,
            defaults={"name": name, "is_active": True},
        )


def unseed_service_categories(apps, schema_editor):
    ServiceCategory = apps.get_model("crm", "ServiceCategory")
    codes = [
        "SEPTIC_PUMPING",
        "SEPTIC_INSTALLATION",
        "SEPTIC_REPAIR",
        "GREASE_TRAP_SERVICES",
        "UNCLOGGING_SERVICES",
        "OTHER",
    ]
    ServiceCategory.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        # IMPORTANT: replace with your latest crm migration
        ("crm", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_service_categories, reverse_code=unseed_service_categories),
    ]