from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("businesses", "0023_businesssubscription_provisioning_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="vertical",
            field=models.CharField(
                choices=[("SERVICE", "Service"), ("LOGISTICS", "Logistics")],
                default="SERVICE",
                max_length=20,
            ),
        ),
    ]
