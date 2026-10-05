from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business

from .models import LogisticsApplication
from .tests import application_data


class ApplicationRetentionMigrationTests(TransactionTestCase):
    def test_migration_backfills_existing_conversion_and_prevents_loss_of_retained_history(self):
        old_target = [("logistics", "0004_shipment_parcel_shipment_and_more")]
        new_target = [("logistics", "0005_application_purge_retention")]
        executor = MigrationExecutor(connection)
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
            MigrationExecutor(connection).migrate(new_target)
