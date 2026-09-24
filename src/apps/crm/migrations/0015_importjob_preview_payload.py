from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0014_importjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="importjob",
            name="preview_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
