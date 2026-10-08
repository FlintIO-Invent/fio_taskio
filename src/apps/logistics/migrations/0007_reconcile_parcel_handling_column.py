"""Reconcile databases that applied the earlier draft of parcel metadata."""

from django.db import migrations


def reconcile_handling_column(apps, schema_editor):
    parcel = apps.get_model("logistics", "Parcel")
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, parcel._meta.db_table
            )
        }
    if "biodegradable_goods" in columns:
        return
    if "perishable_goods" not in columns:
        raise RuntimeError("Parcel handling column is missing; check the parcel metadata schema.")
    field = parcel._meta.get_field("biodegradable_goods")
    previous = field.clone()
    previous.set_attributes_from_name("perishable_goods")
    previous.model = parcel
    schema_editor.alter_field(parcel, previous, field)


class Migration(migrations.Migration):
    dependencies = [("logistics", "0006_parcel_metadata")]

    # State already uses the canonical name. Reversing this repair leaves that
    # name intact so the database remains compatible with migration 0006's state.
    operations = [
        migrations.RunPython(reconcile_handling_column, reverse_code=migrations.RunPython.noop)
    ]
