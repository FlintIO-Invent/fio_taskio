"""The normal seed command exercises current Logistics forms and operational services."""

from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from apps.businesses.models import DemoSeedRecord, DemoSeedRun
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client

from . import test_operations as fixtures
from .demo import LOGISTICS_DEMO_COUNTS
from .models import LogisticsProfile, Parcel, ParcelEvent, Shipment
from .parcel_policy import ALLOWED_TRANSITIONS
from .parcel_services import PARCEL_INPUT_FIELDS


class LogisticsDemoDataTests(TestCase):
    setUp = fixtures.LogisticsOperationsTests.setUp

    def command(self, **options):
        output = StringIO()
        call_command(
            "seed_demo_data", stdout=output, **{"business_id": self.business.pk, **options}
        )
        return output.getvalue()

    def login(self, user=None, business=None):
        self.client.force_login(user or self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = (business or self.business).pk
        session.save()

    def test_normal_command_previews_logistics_without_writes(self):
        output = self.command()
        self.assertIn('"planned_counts"', output)
        self.assertIn('"parcels": 20', output)
        self.assertIn("DRY RUN ONLY", output)
        self.assertFalse(DemoSeedRun.objects.exists())
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(LogisticsProfile.objects.exists())
        self.assertEqual(Client.objects.count(), 1)

    def test_seed_defaults_to_realistic_modes_and_reset_keeps_profile(self):
        self.command(execute=True)
        profile = LogisticsProfile.objects.get(business=self.business)
        self.assertEqual(profile.operating_areas, ["TRANSPORTATION"])
        self.assertEqual(profile.transportation_modes, ["SEA", "AIR", "ROAD"])
        self.command(reset_demo=True, execute=True)
        profile.refresh_from_db()
        self.assertEqual(profile.transportation_modes, ["SEA", "AIR", "ROAD"])

    def test_seed_preserves_explicit_operating_profile(self):
        profile = LogisticsProfile.objects.create(
            business=self.business, operating_areas=["WAREHOUSING"]
        )
        self.command(execute=True)
        profile.refresh_from_db()
        self.assertEqual(profile.operating_areas, ["WAREHOUSING"])
        self.assertEqual(profile.transportation_modes, [])

    def test_dataset_covers_metadata_statuses_relations_and_valid_history(self):
        output = self.command(execute=True)
        self.assertIn("Logistics demo data created", output)
        parcels = list(
            Parcel.objects.select_related("client", "shipment").prefetch_related("events")
        )
        seed = DemoSeedRun.objects.get(business=self.business)
        self.assertEqual(seed.planned_counts, LOGISTICS_DEMO_COUNTS)
        self.assertEqual(seed.owned_records.count(), sum(LOGISTICS_DEMO_COUNTS.values()))
        self.assertEqual(len(parcels), 20)
        self.assertEqual(Client.objects.exclude(pk=self.genuine.pk).count(), 10)
        for client in Client.objects.exclude(pk=self.genuine.pk):
            client.full_clean()
        self.assertEqual(Shipment.objects.count(), 6)
        self.assertEqual(ParcelEvent.objects.count(), 83)
        self.assertEqual(len({parcel.tracking_code for parcel in parcels}), 20)
        self.assertEqual({parcel.current_status for parcel in parcels}, set(Parcel.Status.values))
        self.assertEqual(
            set(Shipment.objects.values_list("status", flat=True)), set(Shipment.Status.values)
        )
        self.assertEqual(sum(parcel.shipment_id is not None for parcel in parcels), 12)
        for name in PARCEL_INPUT_FIELDS:
            with self.subTest(populated_field=name):
                self.assertTrue(
                    any(getattr(parcel, name) not in (None, "", False) for parcel in parcels)
                )
        for parcel in parcels:
            with self.subTest(parcel=parcel.internal_reference):
                parcel.full_clean()
                self.assertEqual(parcel.business_id, self.business.pk)
                self.assertEqual(parcel.client.business_id, self.business.pk)
                self.assertEqual(parcel.created_by_id, self.user.pk)
                self.assertLessEqual(parcel.created_at, parcel.updated_at)
                self.assertRegex(parcel.tracking_code, r"\A[A-F0-9]{48}\Z")
                if parcel.shipment_id:
                    self.assertEqual(parcel.shipment.business_id, self.business.pk)
                    self.assertEqual(
                        (parcel.origin, parcel.destination),
                        (parcel.shipment.origin, parcel.shipment.destination),
                    )
                statuses = []
                previous_time = parcel.created_at
                for event in parcel.events.all():
                    self.assertEqual(event.business_id, self.business.pk)
                    self.assertEqual(event.actor_id, self.user.pk)
                    self.assertGreaterEqual(event.timestamp, previous_time)
                    previous_time = event.timestamp
                    if event.event_type == ParcelEvent.Type.STATUS:
                        if statuses:
                            self.assertIn(event.status, ALLOWED_TRANSITIONS[statuses[-1]])
                        statuses.append(event.status)
                self.assertEqual(statuses[0], Parcel.Status.REGISTERED)
                self.assertEqual(statuses[-1], parcel.current_status)
        for shipment in Shipment.objects.all():
            shipment.full_clean()
            self.assertLessEqual(shipment.departure_at, shipment.estimated_arrival_at)
        minimal = Parcel.objects.get(internal_reference="DEMO-020")
        self.assertIsNone(minimal.weight_kg)
        self.assertIsNone(minimal.length_cm)
        self.assertEqual(minimal.sender_name, "")
        self.assertFalse(minimal.shipment_id)
        self.assertTrue(Parcel.objects.filter(dimensions__gt="", length_cm__isnull=True).exists())
        self.assertEqual(
            ParcelEvent.objects.filter(internal_note__startswith="Parcel details updated:").count(),
            2,
        )
        self.assertFalse(Parcel.objects.filter(business=self.other).exists())
        self.genuine.refresh_from_db()
        self.assertEqual(self.genuine.email, "private@example.test")

    def test_all_seeded_parcels_render_and_can_be_edited_with_normal_forms(self):
        self.command(execute=True)
        self.login()
        listing = self.client.get(reverse("logistics_parcel_list"))
        self.assertEqual(listing.status_code, 200)
        for parcel in Parcel.objects.order_by("internal_reference"):
            with self.subTest(parcel=parcel.internal_reference, status=parcel.current_status):
                route = reverse("logistics_parcel_detail", args=[parcel.pk])
                detail = self.client.get(route)
                self.assertContains(detail, parcel.tracking_code)
                self.assertEqual(detail.context["parcel"].client_id, parcel.client_id)
                self.assertEqual(detail.context["parcel"].current_status, parcel.current_status)
                location = parcel.events.exclude(location="").order_by("-timestamp", "-pk").first()
                self.assertEqual(detail.context["latest_location"], location)
                edit_route = reverse("logistics_parcel_edit", args=[parcel.pk])
                editing = self.client.get(edit_route)
                self.assertEqual(editing.status_code, 200)
                data = {
                    name: "" if getattr(parcel, name) is None else getattr(parcel, name)
                    for name in PARCEL_INPUT_FIELDS
                }
                data.update(
                    package_description=parcel.package_description + " (demo edit)",
                    expected_updated_at=parcel.updated_at.isoformat(),
                )
                response = self.client.post(edit_route, data)
                self.assertRedirects(response, route)
                updated = Parcel.objects.get(pk=parcel.pk)
                self.assertEqual(updated.package_description, data["package_description"])
                self.assertEqual(updated.tracking_code, parcel.tracking_code)
                self.assertEqual(updated.client_id, parcel.client_id)
                self.assertEqual(updated.shipment_id, parcel.shipment_id)
                self.assertEqual(updated.current_status, parcel.current_status)
                self.assertEqual(updated.events.last().event_type, ParcelEvent.Type.NOTE)

    def test_seeded_dashboard_and_other_tenant_visibility(self):
        self.command(execute=True)
        self.login()
        dashboard = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        expected = {
            "REGISTERED": 3,
            "RECEIVED": 4,
            "IN_TRANSIT": 3,
            "ARRIVED": 2,
            "READY": 1,
            "DELIVERED": 3,
            "HOLD": 2,
            "CANCELLED": 2,
        }
        self.assertEqual(
            {row["status"]: row["count"] for row in dashboard.context["parcel_status_counts"]},
            expected,
        )
        for key, value in (
            ("parcel_count", 20),
            ("active_parcel_count", 15),
            ("shipment_count", 6),
            ("active_shipment_count", 4),
            ("recently_delivered_parcel_count", 3),
            ("delivered_this_month_count", 3),
        ):
            self.assertEqual(dashboard.context[key], value)
        parcel = Parcel.objects.first()
        self.login(user=self.other_user, business=self.other)
        self.assertEqual(
            self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk])).status_code, 404
        )
        self.assertNotContains(
            self.client.get(reverse("logistics_parcel_list")), parcel.tracking_code
        )

    def test_normal_command_replay_reset_and_alias_compatibility(self):
        output = StringIO()
        call_command(
            "seed_demo_data", business_slug=self.business.slug, execute=True, stdout=output
        )
        seed = DemoSeedRun.objects.get(business=self.business)
        run_id = seed.run_id
        with self.assertRaisesMessage(CommandError, "preview/reset"):
            self.command(execute=True)
        self.assertEqual(DemoSeedRun.objects.get(business=self.business).run_id, run_id)
        self.assertEqual(Parcel.objects.count(), 20)
        self.assertIn("RESET PREVIEW ONLY", self.command(reset_demo=True))
        self.assertEqual(Parcel.objects.count(), 20)
        self.command(reset_demo=True, execute=True)
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(Shipment.objects.exists())
        self.assertFalse(DemoSeedRecord.objects.exists())
        self.assertEqual(list(Client.objects.all()), [self.genuine])
        call_command(
            "seed_logistics_demo_data",
            business_id=self.business.pk,
            execute=True,
            stdout=StringIO(),
        )
        self.command(reset_demo=True, execute=True)
        self.command(execute=True)
        call_command(
            "seed_logistics_demo_data",
            business_id=self.business.pk,
            reset_demo=True,
            execute=True,
            stdout=StringIO(),
        )
        self.assertFalse(DemoSeedRun.objects.exists())

    def test_normal_reset_refuses_new_edit_history_on_demo_parcels(self):
        self.command(execute=True)
        self.login()
        parcel = Parcel.objects.first()
        data = {
            name: "" if getattr(parcel, name) is None else getattr(parcel, name)
            for name in PARCEL_INPUT_FIELDS
        }
        data.update(
            internal_notes="Manual edit after seeding",
            expected_updated_at=parcel.updated_at.isoformat(),
        )
        self.assertEqual(
            self.client.post(reverse("logistics_parcel_edit", args=[parcel.pk]), data).status_code,
            302,
        )
        for execute in (False, True):
            with (
                self.subTest(execute=execute),
                self.assertRaisesMessage(CommandError, "genuine or untracked"),
            ):
                self.command(reset_demo=True, execute=execute)
        self.assertTrue(Parcel.objects.filter(pk=parcel.pk).exists())

    def test_normal_command_rejects_service_options_and_checks_existing_access(self):
        for options in (
            {"clients": 10},
            {"services": 0},
            {"requests": 0},
            {"appointments": 0},
            {"invoices": 0},
            {"booking_setup": True},
            {"enable_public_booking": True},
        ):
            with (
                self.subTest(options=options),
                self.assertRaisesMessage(CommandError, "not supported"),
            ):
                self.command(execute=True, **options)
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        with self.assertRaises(CommandError):
            self.command(execute=True)
        self.assertFalse(DemoSeedRun.objects.exists())
        self.assertFalse(Parcel.objects.exists())

    def test_domain_failure_rolls_back_normal_command(self):
        with patch("apps.logistics.demo.edit_parcel", side_effect=ValidationError("failed edit")):
            with self.assertRaisesMessage(CommandError, "failed edit"):
                self.command(execute=True)
        self.assertEqual(Client.objects.count(), 1)
        for model in (Parcel, ParcelEvent, Shipment, DemoSeedRun, DemoSeedRecord):
            self.assertFalse(model.objects.exists())
