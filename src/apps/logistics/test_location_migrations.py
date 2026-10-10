from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from .tests import application_data


class LocationMigrationTests(TransactionTestCase):
    def test_historical_text_and_relations_preserved_with_exact_only_backfill(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old_target = [("logistics", "0013_tracking_code_v2")]
        try:
            executor.migrate(old_target)
            old = executor.loader.project_state(old_target).apps
            Business = old.get_model("businesses", "Business")
            Client = old.get_model("crm", "Client")
            Parcel = old.get_model("logistics", "Parcel")
            Shipment = old.get_model("logistics", "Shipment")
            Event = old.get_model("logistics", "ParcelEvent")
            Application = old.get_model("logistics", "LogisticsApplication")
            Profile = old.get_model("logistics", "LogisticsProfile")
            business = Business.objects.create(
                name="Historical", slug="historical", vertical="LOGISTICS"
            )
            client = Client.objects.create(business=business, first_name="Historical")
            profile = Profile.objects.create(
                business=business,
                operating_areas=["TRANSPORTATION"],
                transportation_modes=["SEA", "ROAD", "AIR", "RAIL"],
            )
            shipment = Shipment.objects.create(
                business=business,
                origin="Dominica",
                destination="St Martin",
                status="ARRIVED",
                transport_mode="SEA",
            )
            parcel = Parcel.objects.create(
                business=business,
                client=client,
                shipment=shipment,
                origin="Curaçao",
                destination="Miami",
                package_description="Historical books",
                tracking_code="A" * 48,
            )
            event = Event.objects.create(
                business=business,
                parcel=parcel,
                status="REGISTERED",
                event_type="STATUS",
                public_message="Historical registered",
                location="Legacy location",
            )
            exact = Application.objects.create(**application_data(country="Anguilla"))
            ambiguous = Application.objects.create(
                **application_data(country="St Martin", email="ambiguous@example.com")
            )
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            new = executor.loader.project_state(latest).apps
            parcel_new = new.get_model("logistics", "Parcel").objects.get(pk=parcel.pk)
            shipment_new = new.get_model("logistics", "Shipment").objects.get(pk=shipment.pk)
            self.assertEqual(
                (
                    parcel_new.origin,
                    parcel_new.destination,
                    parcel_new.tracking_code,
                    parcel_new.shipment_id,
                ),
                ("Curaçao", "Miami", "A" * 48, shipment.pk),
            )
            self.assertEqual(parcel_new.origin_country_code, "CW")
            self.assertIsNone(parcel_new.destination_country_code)
            self.assertTrue(parcel_new.location_review_required)
            self.assertIsNone(parcel_new.origin_location_id)
            self.assertEqual(shipment_new.origin_country_code, "DM")
            self.assertIsNone(shipment_new.destination_country_code)
            self.assertTrue(shipment_new.location_review_required)
            self.assertEqual(shipment_new.status, "ARRIVED")
            self.assertEqual(
                new.get_model("logistics", "ParcelEvent").objects.get(pk=event.pk).location,
                "Legacy location",
            )
            self.assertEqual(
                new.get_model("logistics", "LogisticsProfile")
                .objects.get(pk=profile.pk)
                .transportation_modes,
                ["SEA", "ROAD", "AIR", "RAIL"],
            )
            self.assertEqual(
                new.get_model("logistics", "LogisticsApplication")
                .objects.get(pk=exact.pk)
                .country_code,
                "AI",
            )
            reviewed = new.get_model("logistics", "LogisticsApplication").objects.get(
                pk=ambiguous.pk
            )
            self.assertEqual(reviewed.country, "St Martin")
            self.assertTrue(reviewed.location_review_required)
            self.assertIsNone(reviewed.country_code)
            self.assertEqual(new.get_model("logistics", "LogisticsLocation").objects.count(), 0)
            self.assertIsNone(
                new.get_model("logistics", "LogisticsProfile")
                .objects.get(pk=profile.pk)
                .location_access_reviewed_at
            )
            self.assertEqual(
                new.get_model("logistics", "LogisticsLocationAssignment").objects.count(), 0
            )
            self.assertEqual(new.get_model("logistics", "LogisticsHandlingSite").objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate(latest)
