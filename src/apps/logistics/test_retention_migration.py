from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business

from .models import LogisticsApplication, Parcel, ParcelEvent
from .tests import application_data


class ApplicationRetentionMigrationTests(TransactionTestCase):
    def test_migration_backfills_existing_conversion_and_prevents_loss_of_retained_history(self):
        old_target = [("logistics", "0004_shipment_parcel_shipment_and_more")]
        new_target = [("logistics", "0005_application_purge_retention")]
        executor = MigrationExecutor(connection)
        latest_targets = executor.loader.graph.leaf_nodes()
        executor.migrate(old_target)
        try:
            historical = executor.loader.project_state(old_target).apps
            user = TaskIOUser.objects.create_user(email="migration-applicant@example.test")
            business = Business.objects.create(
                name="Historical courier", slug="retention-migration", vertical="LOGISTICS"
            )
            application = historical.get_model("logistics", "LogisticsApplication").objects.create(
                **application_data(),
                business_id=business.pk,
                enrolled_user_id=user.pk,
                converted_at=timezone.now(),
                converted_revision=1,
            )
            MigrationExecutor(connection).migrate(new_target)
            converted = LogisticsApplication.objects.get(pk=application.pk)
            self.assertEqual(converted.business_id_snapshot, business.pk)
            self.assertEqual(converted.business_id, business.pk)
            LogisticsApplication.objects.filter(pk=application.pk).update(business=None)
            with self.assertRaisesMessage(RuntimeError, "retained history must survive"):
                MigrationExecutor(connection).migrate(old_target)
            self.assertEqual(
                LogisticsApplication.objects.get(pk=application.pk).business_id_snapshot,
                business.pk,
            )
        finally:
            MigrationExecutor(connection).migrate(latest_targets)


class ParcelMetadataMigrationTests(TransactionTestCase):
    def test_existing_parcels_keep_data_relations_and_history_with_empty_metadata(self):
        old_target = [("logistics", "0005_application_purge_retention")]
        new_target = [("logistics", "0007_reconcile_parcel_handling_column")]
        executor = MigrationExecutor(connection)
        latest_targets = executor.loader.graph.leaf_nodes()
        executor.migrate(old_target)
        try:
            historical = executor.loader.project_state(old_target).apps
            business = historical.get_model("businesses", "Business").objects.create(
                name="Existing courier",
                slug="parcel-metadata-migration",
                vertical="LOGISTICS",
            )
            customer = historical.get_model("crm", "Client").objects.create(
                business_id=business.pk,
                first_name="Existing",
                last_name="Client",
            )
            parcel = historical.get_model("logistics", "Parcel").objects.create(
                business_id=business.pk,
                client_id=customer.pk,
                tracking_code="F" * 48,
                origin="Miami",
                destination="Curacao",
                package_description="Existing books",
                weight_kg="2.250",
                dimensions="20 x 10 x 5 inches",
                quantity=3,
            )
            historical.get_model("logistics", "ParcelEvent").objects.create(
                business_id=business.pk,
                parcel_id=parcel.pk,
                event_type="STATUS",
                status="REGISTERED",
                public_message="Parcel registered.",
            )
            MigrationExecutor(connection).migrate(new_target)
            migrated = Parcel.objects.get(pk=parcel.pk)
            self.assertEqual(
                (migrated.business_id, migrated.client_id, migrated.tracking_code),
                (business.pk, customer.pk, "F" * 48),
            )
            self.assertEqual(
                (migrated.package_description, migrated.quantity, migrated.dimensions),
                ("Existing books", 3, "20 x 10 x 5 inches"),
            )
            self.assertEqual(migrated.created_at, parcel.created_at)
            self.assertEqual(migrated.updated_at, parcel.updated_at)
            self.assertEqual(migrated.current_status, "REGISTERED")
            self.assertEqual(migrated.sender_name, "")
            self.assertEqual(migrated.internal_notes, "")
            self.assertIsNone(migrated.length_cm)
            self.assertIsNone(migrated.expiry_date)
            self.assertFalse(migrated.fragile_goods)
            self.assertFalse(migrated.biodegradable_goods)
            self.assertEqual(ParcelEvent.objects.filter(parcel_id=parcel.pk).count(), 1)
        finally:
            MigrationExecutor(connection).migrate(latest_targets)

    def test_repair_preserves_values_from_the_earlier_metadata_column(self):
        old_target = [("logistics", "0006_parcel_metadata")]
        new_target = [("logistics", "0007_reconcile_parcel_handling_column")]
        executor = MigrationExecutor(connection)
        latest_targets = executor.loader.graph.leaf_nodes()
        executor.migrate(old_target)
        try:
            historical = executor.loader.project_state(old_target).apps
            business = historical.get_model("businesses", "Business").objects.create(
                name="Earlier metadata", slug="earlier-parcel-metadata", vertical="LOGISTICS"
            )
            customer = historical.get_model("crm", "Client").objects.create(
                business_id=business.pk, first_name="Existing", last_name="Client"
            )
            parcel_model = historical.get_model("logistics", "Parcel")
            parcels = [
                parcel_model.objects.create(
                    business_id=business.pk,
                    client_id=customer.pk,
                    tracking_code=code * 48,
                    origin="Miami",
                    destination="Curacao",
                    package_description="Existing metadata",
                    biodegradable_goods=value,
                    sender_name="Existing sender",
                )
                for code, value in (("A", True), ("B", False))
            ]
            field = parcel_model._meta.get_field("biodegradable_goods")
            earlier = field.clone()
            earlier.set_attributes_from_name("perishable_goods")
            earlier.model = parcel_model
            with connection.schema_editor() as schema_editor:
                schema_editor.alter_field(parcel_model, field, earlier)
            MigrationExecutor(connection).migrate(new_target)
            for original, expected in zip(parcels, (True, False), strict=True):
                repaired = Parcel.objects.get(pk=original.pk)
                self.assertEqual(repaired.biodegradable_goods, expected)
                self.assertEqual(repaired.sender_name, "Existing sender")
                self.assertEqual(repaired.updated_at, original.updated_at)
            with connection.cursor() as cursor:
                columns = {
                    column.name
                    for column in connection.introspection.get_table_description(
                        cursor, parcel_model._meta.db_table
                    )
                }
            self.assertIn("biodegradable_goods", columns)
            self.assertNotIn("perishable_goods", columns)
        finally:
            MigrationExecutor(connection).migrate(latest_targets)
