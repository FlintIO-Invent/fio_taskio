"""Refresh the canonical Starter copy without replacing custom descriptions."""

from django.db import migrations


BASELINE_DESCRIPTION = (
    "For solo owners and small service businesses moving away from WhatsApp, "
    "paper, and spreadsheets."
)
APPROVED_DESCRIPTION = (
    "For small service businesses moving away from WhatsApp, paper, and spreadsheets."
)


def update_starter_description(apps, schema_editor):
    Plan = apps.get_model("businesses", "ClarivoPlan")
    Plan.objects.using(schema_editor.connection.alias).filter(
        slug="starter", family="SERVICE", description=BASELINE_DESCRIPTION
    ).update(description=APPROVED_DESCRIPTION)


class Migration(migrations.Migration):
    dependencies = [("businesses", "0035_services_allowances")]
    operations = [
        migrations.RunPython(update_starter_description, migrations.RunPython.noop),
    ]
