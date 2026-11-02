from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("businesses", "0036_services_starter_description")]

    operations = [
        migrations.AddField(
            model_name="clarivoplan",
            name="logistics_free_test_enabled",
            field=models.BooleanField(
                default=False,
                verbose_name="Logistics free-test access",
                help_text=(
                    "Allow complete Core/Growth/Scale tiers for FREE_TEST / LOCAL access without Stripe. "
                    "Leave Is active unchecked to keep paid activation disabled. "
                    "Registration still requires the private token and registration setting."
                ),
            ),
        ),
    ]
