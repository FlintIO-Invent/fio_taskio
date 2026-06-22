from django.db import migrations


UPDATED_PLAN_DESCRIPTIONS = {
    "starter": "Essential Motionmate workspace for small teams getting started.",
    "pro": "Growing Motionmate workspace with invoicing and scheduling access.",
    "business": "Expanded Motionmate workspace for larger teams and advanced modules.",
}


PREVIOUS_PLAN_DESCRIPTIONS = {
    "starter": "Essential Clarivo workspace for small teams getting started.",
    "pro": "Growing Clarivo workspace with invoicing and scheduling access.",
    "business": "Expanded Clarivo workspace for larger teams and advanced modules.",
}


def update_motionmate_plan_descriptions(apps, schema_editor):
    ClarivoPlan = apps.get_model("businesses", "ClarivoPlan")
    db_alias = schema_editor.connection.alias

    for slug, description in UPDATED_PLAN_DESCRIPTIONS.items():
        ClarivoPlan.objects.using(db_alias).filter(
            slug=slug,
            description__icontains="clarivo",
        ).update(description=description)


def revert_motionmate_plan_descriptions(apps, schema_editor):
    ClarivoPlan = apps.get_model("businesses", "ClarivoPlan")
    db_alias = schema_editor.connection.alias

    for slug, description in PREVIOUS_PLAN_DESCRIPTIONS.items():
        ClarivoPlan.objects.using(db_alias).filter(
            slug=slug,
            description=UPDATED_PLAN_DESCRIPTIONS[slug],
        ).update(description=description)


class Migration(migrations.Migration):

    dependencies = [
        ("businesses", "0007_enable_pro_public_request_form"),
    ]

    operations = [
        migrations.RunPython(
            update_motionmate_plan_descriptions,
            revert_motionmate_plan_descriptions,
        ),
    ]
