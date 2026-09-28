from django.db import migrations, models


def mark_existing_beta_subscriptions(apps, schema_editor):
    BusinessSubscription = apps.get_model("businesses", "BusinessSubscription")
    BusinessSubscription.objects.using(schema_editor.connection.alias).filter(
        plan__slug="beta",
    ).update(provisioning_source="beta")


def restore_existing_beta_subscriptions_to_standard(apps, schema_editor):
    BusinessSubscription = apps.get_model("businesses", "BusinessSubscription")
    BusinessSubscription.objects.using(schema_editor.connection.alias).filter(
        provisioning_source="beta",
    ).update(provisioning_source="standard")


class Migration(migrations.Migration):
    dependencies = [
        ("businesses", "0022_demoseedrun_demoseedrecord"),
    ]

    operations = [
        migrations.AddField(
            model_name="businesssubscription",
            name="provisioning_source",
            field=models.CharField(
                choices=[
                    ("standard", "Standard"),
                    ("beta", "Beta"),
                    ("free_test", "Free Test"),
                ],
                db_index=True,
                default="standard",
                max_length=20,
            ),
        ),
        migrations.RunPython(
            mark_existing_beta_subscriptions,
            restore_existing_beta_subscriptions_to_standard,
        ),
    ]
