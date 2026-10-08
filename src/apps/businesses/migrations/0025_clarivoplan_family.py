from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("businesses", "0024_business_vertical")]

    operations = [
        migrations.AddField(
            model_name="clarivoplan",
            name="family",
            field=models.CharField(
                choices=[("SERVICE", "Service"), ("LOGISTICS", "Logistics")],
                default="SERVICE",
                max_length=20,
            ),
        ),
    ]
