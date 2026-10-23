from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ShippingSnapshotMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_historical_parties_codes_and_relationships(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old_target = [("logistics", "0017_verified_operations")]
        try:
            executor.migrate(old_target)
            old = executor.loader.project_state(old_target).apps
            Business = old.get_model("businesses", "Business")
            Client = old.get_model("crm", "Client")
            Parcel = old.get_model("logistics", "Parcel")
            Shipment = old.get_model("logistics", "Shipment")
            Event = old.get_model("logistics", "ParcelEvent")
            business = Business.objects.create(
                name="Historic", slug="historic-label", vertical="LOGISTICS"
            )
            customer = Client.objects.create(business=business, first_name="Bill to")
            shipment = Shipment.objects.create(
                business=business,
                origin="Old origin",
                destination="Old destination",
                status="ARRIVED",
            )
            parcel = Parcel.objects.create(
                business=business,
                client=customer,
                shipment=shipment,
                tracking_code="F" * 48,
                origin="Old origin",
                destination="Old destination",
                package_description="Historic cargo",
                current_status="ARRIVED",
                sender_name="Historical sender",
                sender_address="Historical free-text street",
                sender_country_code="USA",
                recipient_address="Historical recipient address",
            )
            event = Event.objects.create(
                business=business, parcel=parcel, status="ARRIVED", event_type="STATUS"
            )
            before = Parcel.objects.values().get(pk=parcel.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            new = executor.loader.project_state(latest).apps
            after = new.get_model("logistics", "Parcel").objects.values().get(pk=parcel.pk)
            for name, value in before.items():
                self.assertEqual(after[name], value)
            added = set(after) - set(before)
            self.assertEqual(len(added), 11)
            self.assertTrue(all(after[name] is None for name in added))
            self.assertEqual(
                new.get_model("logistics", "ParcelEvent").objects.get(pk=event.pk).actor_id, None
            )
            self.assertEqual(
                new.get_model("logistics", "Shipment").objects.get(pk=shipment.pk).status, "ARRIVED"
            )
        finally:
            MigrationExecutor(connection).migrate(latest)
