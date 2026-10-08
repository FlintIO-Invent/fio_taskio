from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("businesses", "0026_logistics_offering")]

    operations = [
        migrations.AddField(
            model_name="businesssubscription",
            name="logistics_approval_review_required",
            field=models.BooleanField(
                default=False,
                help_text="Logistics access is blocked until approval/payment reconciliation is reviewed. "
                "After reviewing the application and Stripe payment, an admin must clear this hold.",
            ),
        ),
    ]
