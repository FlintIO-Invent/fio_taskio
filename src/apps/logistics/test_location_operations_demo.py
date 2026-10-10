"""Verified demo creation uses explicit facilities and the normal movement services."""

import json
from collections import Counter
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.billings.models import Invoice, InvoiceLine
from apps.businesses.models import Business, DemoSeedRun

from . import test_location_operations, test_parcels
from .demo import LOGISTICS_DEMO_COUNTS, PARCEL_STATUS_COUNTS, SHIPMENT_STATUS_COUNTS
from .location_access_services import select_work_location, set_location_assignment
from .models import (
    LogisticsLocation,
    LogisticsLocationAssignment,
    LogisticsProfile,
    Parcel,
    ParcelEvent,
    Shipment,
)


class VerifiedDemoOperationsTests(TestCase):
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    select = test_location_operations.LocationOperationsTests.select
    parcel = test_location_operations.LocationOperationsTests.parcel
    setUp = test_location_operations.LocationOperationsTests.setUp

    def command(self, **options):
        output = StringIO()
        call_command(
            "seed_logistics_demo_data",
            business_id=self.business.pk,
            actor_id=self.user.pk,
            origin_location_id=self.a.pk,
            destination_location_id=self.b.pk,
            stdout=output,
            **options,
        )
        return output.getvalue()

    def test_verified_preview_is_read_only_and_describes_registered_sites(self):
        before = {
            model: list(model.objects.order_by("pk").values())
            for model in (
                Parcel,
                ParcelEvent,
                Shipment,
                LogisticsProfile,
                LogisticsLocationAssignment,
                LogisticsLocation,
            )
        }
        plan = json.loads(self.command().splitlines()[0])
        self.assertEqual(plan["operational_locations"]["origin"]["id"], self.a.pk)
        self.assertEqual(plan["operational_locations"]["destination"]["id"], self.b.pk)
        for model, values in before.items():
            self.assertEqual(list(model.objects.order_by("pk").values()), values)
        self.assertFalse(DemoSeedRun.objects.exists())

    def test_verified_seed_preserves_counts_invoices_profile_and_reset_ownership(self):
        profile = LogisticsProfile.objects.get(business=self.business)
        classifications = (
            profile.operating_areas,
            profile.transportation_modes,
            profile.location_operations_enabled_at,
            profile.location_access_reviewed_at,
        )
        self.command(execute=True)
        demo_parcels = Parcel.objects.exclude(pk=self.item.pk)
        self.assertEqual(
            Counter(demo_parcels.values_list("current_status", flat=True)), PARCEL_STATUS_COUNTS
        )
        self.assertEqual(
            Counter(Shipment.objects.values_list("status", flat=True)), SHIPMENT_STATUS_COUNTS
        )
        self.assertEqual(
            ParcelEvent.objects.exclude(parcel=self.item).count(),
            LOGISTICS_DEMO_COUNTS["parcel_events"],
        )
        self.assertEqual(Invoice.objects.count(), 4)
        self.assertEqual(InvoiceLine.objects.count(), 13)
        self.assertFalse(
            ParcelEvent.objects.exclude(parcel=self.item)
            .filter(operational_location__isnull=True)
            .exists()
        )
        self.assertFalse(
            ParcelEvent.objects.exclude(parcel=self.item)
            .exclude(location_override_reason="")
            .exists()
        )
        self.assertTrue(all(item.tracking_code.startswith("MM-PCL-") for item in demo_parcels))
        profile.refresh_from_db()
        self.assertEqual(
            (
                profile.operating_areas,
                profile.transportation_modes,
                profile.location_operations_enabled_at,
                profile.location_access_reviewed_at,
            ),
            classifications,
        )
        self.assertEqual(
            LogisticsLocationAssignment.objects.get(
                membership=self.membership, is_current=True
            ).location_id,
            self.a.pk,
        )
        before = list(demo_parcels.values_list("pk", "tracking_code"))
        with self.assertRaises(CommandError):
            self.command(execute=True)
        self.assertEqual(list(demo_parcels.values_list("pk", "tracking_code")), before)
        call_command(
            "seed_logistics_demo_data",
            business_id=self.business.pk,
            reset_demo=True,
            execute=True,
            stdout=StringIO(),
        )
        self.assertEqual(list(Parcel.objects.all()), [self.item])
        self.assertEqual(LogisticsLocation.objects.filter(business=self.business).count(), 4)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(DemoSeedRun.objects.exists())

    def test_unmapped_foreign_and_wrong_current_site_reject_without_writes(self):
        for fields in (
            {},
            {"origin_location_id": self.a.pk, "destination_location_id": self.foreign.pk},
            {"origin_location_id": self.b.pk, "destination_location_id": self.a.pk},
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "seed_logistics_demo_data",
                    business_id=self.business.pk,
                    actor_id=self.user.pk,
                    execute=True,
                    stdout=StringIO(),
                    **fields,
                )
        self.assertEqual(Parcel.objects.count(), 1)
        self.assertFalse(DemoSeedRun.objects.exists())

    def test_worker_needs_operational_permission_at_both_demo_sites(self):
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=self.member,
            location=self.b,
            can_operate=False,
        )
        select_work_location(business=self.business, actor=self.staff, location=self.a)
        with self.assertRaises(CommandError):
            call_command(
                "seed_logistics_demo_data",
                business_id=self.business.pk,
                actor_id=self.staff.pk,
                origin_location_id=self.a.pk,
                destination_location_id=self.b.pk,
                execute=True,
                stdout=StringIO(),
            )
        self.assertFalse(DemoSeedRun.objects.exists())

    def test_verified_seed_preserves_all_configured_transport_modes(self):
        profile = LogisticsProfile.objects.get(business=self.business)
        for mode in ("SEA", "ROAD", "AIR", "RAIL"):
            with self.subTest(mode=mode):
                profile.transportation_modes = [mode]
                profile.save(update_fields=["transportation_modes"])
                self.command(execute=True)
                self.assertEqual(
                    set(Shipment.objects.values_list("transport_mode", flat=True)), {mode}
                )
                profile.refresh_from_db()
                self.assertEqual(profile.transportation_modes, [mode])
                call_command(
                    "seed_logistics_demo_data",
                    business_id=self.business.pk,
                    reset_demo=True,
                    execute=True,
                    stdout=StringIO(),
                )

    def test_single_site_worker_can_seed_local_or_return_scenarios(self):
        for site in (self.b, self.stop):
            set_location_assignment(
                business=self.business,
                actor=self.user,
                membership=self.member,
                location=site,
                revoke=True,
            )
        call_command(
            "seed_logistics_demo_data",
            business_id=self.business.pk,
            actor_id=self.staff.pk,
            origin_location_id=self.a.pk,
            destination_location_id=self.a.pk,
            execute=True,
            stdout=StringIO(),
        )
        self.assertEqual(Parcel.objects.exclude(pk=self.item.pk).count(), 20)
        self.assertEqual(ParcelEvent.objects.exclude(parcel=self.item).count(), 83)
        self.assertFalse(
            ParcelEvent.objects.exclude(parcel=self.item)
            .exclude(operational_location=self.a)
            .exists()
        )

    def test_general_command_forwards_verified_sites_and_preserves_reset(self):
        output = StringIO()
        fields = {
            "business_id": self.business.pk,
            "origin_location_id": self.a.pk,
            "destination_location_id": self.b.pk,
            "stdout": output,
        }
        call_command("seed_demo_data", **fields)
        self.assertFalse(DemoSeedRun.objects.exists())
        plan = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(plan["operational_locations"]["origin"]["id"], self.a.pk)
        call_command("seed_demo_data", execute=True, **fields)
        self.assertEqual(Parcel.objects.exclude(pk=self.item.pk).count(), 20)
        call_command(
            "seed_demo_data",
            business_id=self.business.pk,
            reset_demo=True,
            execute=True,
            stdout=StringIO(),
        )
        self.assertEqual(list(Parcel.objects.all()), [self.item])

    def test_service_command_rejects_logistics_only_options_without_writes(self):
        self.business.vertical = Business.Vertical.SERVICE
        self.business.save(update_fields=["vertical"])
        with self.assertRaisesMessage(CommandError, "only supported for LOGISTICS"):
            call_command(
                "seed_demo_data",
                business_id=self.business.pk,
                origin_location_id=self.a.pk,
                execute=True,
                stdout=StringIO(),
            )
        self.assertFalse(DemoSeedRun.objects.exists())
