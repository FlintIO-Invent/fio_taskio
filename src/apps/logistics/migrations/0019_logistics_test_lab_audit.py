# Logistics Test Lab operation audit, independent of tenant deletion.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("logistics", "0018_parcel_shipping_snapshots"),
    ]

    operations = [
        migrations.CreateModel(
            name="LogisticsTestLabAudit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("fixture_version", models.CharField(max_length=80)),
                ("environment", models.CharField(max_length=20)),
                ("business_id_snapshot", models.PositiveBigIntegerField()),
                ("action", models.CharField(max_length=30)),
                ("reason_reference", models.CharField(max_length=120)),
                ("approval_reference", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
