from django.db import migrations


def enable_pro_public_request_form(apps, schema_editor):
    ClarivoPlan = apps.get_model("businesses", "ClarivoPlan")
    ClarivoPlan.objects.using(schema_editor.connection.alias).filter(slug="pro").update(
        allow_public_request_form=True,
    )


def disable_pro_public_request_form(apps, schema_editor):
    ClarivoPlan = apps.get_model("businesses", "ClarivoPlan")
    ClarivoPlan.objects.using(schema_editor.connection.alias).filter(slug="pro").update(
        allow_public_request_form=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("businesses", "0006_businessinvitation"),
    ]

    operations = [
        migrations.RunPython(
            enable_pro_public_request_form,
            disable_pro_public_request_form,
        ),
    ]
