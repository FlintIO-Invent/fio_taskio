"""Shipment transportation defaults must preserve tenant, history and write safety."""

import csv
import json
from io import StringIO
from unittest import skipUnless
from uuid import uuid4

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import QuerySet
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from . import test_concurrency, test_operations, test_shipments
from .admin import ShipmentAdmin
from .classification import TransportationMode
from .models import LogisticsProfile, Shipment
from .shipment_forms import ShipmentForm
from .shipment_services import (
    SHIPMENT_INPUT_FIELDS,
    assign_parcel,
    create_shipment,
    generate_manifest,
    update_shipment,
)


class ShipmentTransportationTests(TestCase):
    setUp = test_shipments.ShipmentTests.setUp
    shipment = test_shipments.ShipmentTests.shipment
    parcel = test_shipments.ShipmentTests.parcel
    parcel_status = test_shipments.ShipmentTests.parcel_status
    status = test_shipments.ShipmentTests.status

    def profile(self, modes, areas=None):
        profile, _ = LogisticsProfile.objects.get_or_create(business=self.business)
        profile.transportation_modes = modes
        profile.operating_areas = areas or ["TRANSPORTATION"]
        profile.save()
        return profile

    def form(self, *, shipment=None, **changes):
        data = {
            "origin": "Unrestricted inland origin",
            "destination": "Unrestricted distant destination",
            "idempotency_key": str(uuid4()),
        }
        if shipment:
            data["expected_revision"] = shipment.revision
        data.update(changes)
        return ShipmentForm(data, business=self.business, instance=shipment)

    def test_all_shared_choices_and_unrestricted_routes(self):
        self.assertEqual(
            Shipment._meta.get_field("transport_mode").choices, TransportationMode.choices
        )
        for mode in TransportationMode.values:
            with self.subTest(mode=mode):
                self.profile([mode])
                shipment = self.shipment(
                    transport_mode=mode, origin="Inland", destination="Any territory"
                )
                shipment.full_clean()
                self.assertEqual(shipment.transport_mode, mode)
                self.assertEqual(shipment.origin, "Inland")

    def test_configured_modes_required_and_foreign_modes_rejected(self):
        self.profile(["SEA", "ROAD"])
        for mode in (None, "", "AIR", "RAIL", "BOAT", False, 0):
            with self.subTest(mode=mode), self.assertRaises(ValidationError):
                self.shipment(transport_mode=mode)
        self.assertEqual(self.shipment(transport_mode="ROAD").transport_mode, "ROAD")
        for mode in ("", "AIR", "BOAT"):
            form = self.form(transport_mode=mode)
            self.assertFalse(form.is_valid())
            self.assertIn("transport_mode", form.errors)

    def test_multi_mode_choices_and_single_mode_initial(self):
        self.profile(["SEA", "ROAD"])
        form = ShipmentForm(business=self.business)
        self.assertEqual(
            list(form.fields["transport_mode"].choices),
            [("", "Select transportation mode"), ("SEA", "Sea"), ("ROAD", "Road / Truck")],
        )
        self.assertTrue(form.fields["transport_mode"].required)
        self.profile(["SEA"])
        form = ShipmentForm(business=self.business)
        self.assertEqual(form.initial["transport_mode"], "SEA")
        self.assertEqual(len(form.fields["transport_mode"].choices), 2)
        # An unbound default never masks a missing field on a fresh submission.
        self.assertFalse(self.form().is_valid())

    def test_no_known_modes_and_missing_profile_keep_creation_compatible(self):
        for has_profile in (False, True):
            if has_profile:
                self.profile([])
            with self.subTest(has_profile=has_profile):
                shipment = self.shipment()
                self.assertIsNone(shipment.transport_mode)
                form = self.form()
                self.assertTrue(form.is_valid(), form.errors)
                self.assertFalse(form.fields["transport_mode"].required)
                self.assertEqual(len(form.fields["transport_mode"].choices), 5)
                self.assertEqual(self.shipment(transport_mode="AIR").transport_mode, "AIR")

    def test_non_transportation_profile_does_not_gate_shipments_or_parcels(self):
        self.profile([], areas=["WAREHOUSING"])
        shipment, parcel = self.shipment(transport_mode="RAIL"), self.parcel()
        assign_parcel(business=self.business, shipment=shipment, parcel=parcel, actor=self.user)
        parcel.refresh_from_db()
        self.assertEqual(parcel.shipment_id, shipment.pk)
        self.assertEqual(self.client.get(reverse("logistics_shipment_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("logistics_parcel_list")).status_code, 200)

    def test_removed_mode_remains_editable_and_readable(self):
        self.profile(["SEA", "ROAD"])
        shipment = self.shipment(transport_mode="SEA")
        self.profile(["ROAD"])
        shipment.full_clean()
        form = self.form(shipment=shipment, transport_mode="SEA")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn(("SEA", "Sea"), form.fields["transport_mode"].choices)
        changed = update_shipment(
            business=self.business,
            shipment=shipment,
            actor=self.user,
            transport_mode="SEA",
            notes="Keep history",
        )
        self.assertEqual(changed.transport_mode, "SEA")
        self.assertContains(
            self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk])), "Sea"
        )
        with self.assertRaises(ValidationError):
            self.shipment(transport_mode="SEA")
        with self.assertRaises(ValidationError):
            update_shipment(
                business=self.business, shipment=changed, actor=self.user, transport_mode="AIR"
            )
        with self.assertRaises(ValidationError):
            update_shipment(
                business=self.business, shipment=changed, actor=self.user, transport_mode=None
            )
        changed = update_shipment(
            business=self.business, shipment=changed, actor=self.user, transport_mode="ROAD"
        )
        self.assertEqual(changed.transport_mode, "ROAD")

    def test_unknown_historical_mode_is_not_required_or_silently_changed(self):
        shipment = self.shipment()
        self.profile(["SEA"])
        form = ShipmentForm(business=self.business, instance=shipment)
        self.assertIsNone(form.initial["transport_mode"])
        self.assertFalse(form.fields["transport_mode"].required)
        submitted = self.form(shipment=shipment, transport_mode="")
        self.assertTrue(submitted.is_valid(), submitted.errors)
        changed = update_shipment(
            business=self.business,
            shipment=shipment,
            actor=self.user,
            transport_mode=None,
            notes="Old unknown",
        )
        self.assertIsNone(changed.transport_mode)
        self.assertContains(
            self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk])), "Unknown"
        )

    def test_current_profile_requeried_and_service_rechecks_form(self):
        self.profile(["SEA"])
        _ = self.business.logistics_profile
        form = self.form(transport_mode="SEA")
        self.assertTrue(form.is_valid(), form.errors)
        self.profile(["ROAD"])
        with self.assertRaises(ValidationError):
            create_shipment(
                business=self.business,
                actor=self.user,
                **{key: form.cleaned_data[key] for key in SHIPMENT_INPUT_FIELDS},
            )
        self.assertIn(
            ("ROAD", "Road / Truck"),
            ShipmentForm(business=self.business).fields["transport_mode"].choices,
        )

    def test_create_replay_survives_profile_removal_and_changed_payload_rejected(self):
        self.profile(["SEA"])
        key = uuid4()
        shipment = self.shipment(transport_mode="SEA", idempotency_key=key)
        self.profile(["ROAD"])
        replay = self.shipment(transport_mode="SEA", idempotency_key=key)
        self.assertEqual(replay.pk, shipment.pk)
        form = self.form(
            transport_mode="SEA", origin="Miami", destination="Curacao", idempotency_key=str(key)
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            self.shipment(transport_mode="ROAD", idempotency_key=key)

    def test_pre_mode_create_receipt_and_backfill_do_not_break_replay(self):
        key = uuid4()
        shipment = self.shipment(idempotency_key=key)
        # A data migration backfills the field without changing old receipts.
        QuerySet(model=Shipment).filter(pk=shipment.pk).update(transport_mode="SEA")
        self.profile(["SEA"])
        replay = self.shipment(idempotency_key=key)
        self.assertEqual(replay.pk, shipment.pk)
        form = self.form(origin="Miami", destination="Curacao", idempotency_key=str(key))
        self.assertTrue(form.is_valid(), form.errors)
        response = self.client.post(reverse("logistics_shipment_create"), form.data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Shipment.objects.count(), 1)

    def test_edit_replay_survives_later_mode_change_and_profile_removal(self):
        self.profile(["SEA", "ROAD"])
        shipment = self.shipment(transport_mode="ROAD")
        key, revision = uuid4(), shipment.revision
        changed = update_shipment(
            business=self.business,
            shipment=shipment,
            actor=self.user,
            transport_mode="SEA",
            idempotency_key=key,
            expected_revision=revision,
        )
        changed = update_shipment(
            business=self.business, shipment=changed, actor=self.user, transport_mode="ROAD"
        )
        self.profile(["ROAD"])
        replay = update_shipment(
            business=self.business,
            shipment=changed,
            actor=self.user,
            transport_mode="SEA",
            idempotency_key=key,
            expected_revision=revision,
        )
        self.assertEqual(replay.transport_mode, "ROAD")
        form = self.form(
            shipment=changed,
            transport_mode="SEA",
            idempotency_key=str(key),
            expected_revision=revision,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_mode_changes_preserve_stale_write_protection(self):
        self.profile(["SEA", "ROAD"])
        shipment = self.shipment(transport_mode="SEA")
        stale = Shipment.objects.get(pk=shipment.pk)
        update_shipment(
            business=self.business, shipment=shipment, actor=self.user, transport_mode="ROAD"
        )
        with self.assertRaisesMessage(ValidationError, "changed after"):
            update_shipment(
                business=self.business, shipment=stale, actor=self.user, transport_mode="SEA"
            )

    def test_mode_preserved_through_assignment_and_full_lifecycle(self):
        self.profile(["ROAD"])
        shipment, parcel = self.shipment(transport_mode="ROAD"), self.parcel()
        assign_parcel(business=self.business, shipment=shipment, parcel=parcel, actor=self.user)
        self.parcel_status(parcel, "RECEIVED")
        for status in ("READY", "IN_TRANSIT", "ARRIVED"):
            self.status(shipment, status)
        with self.assertRaises(ValidationError):
            update_shipment(
                business=self.business, shipment=shipment, actor=self.user, transport_mode="ROAD"
            )
        self.parcel_status(parcel, "READY")
        self.parcel_status(parcel, "DELIVERED")
        self.status(shipment, "COMPLETED")
        shipment.refresh_from_db()
        parcel.refresh_from_db()
        self.assertEqual(shipment.transport_mode, "ROAD")
        self.assertEqual(parcel.shipment_id, shipment.pk)
        self.assertEqual(parcel.current_status, "DELIVERED")

    def test_tenant_profile_and_foreign_shipment_isolation(self):
        self.profile(["SEA"])
        LogisticsProfile.objects.create(business=self.other, transportation_modes=["AIR"])
        foreign = create_shipment(
            business=self.other,
            actor=self.other_user,
            origin="Anywhere",
            destination="Elsewhere",
            transport_mode="AIR",
        )
        with self.assertRaises(ValidationError):
            update_shipment(
                business=self.business, shipment=foreign, actor=self.user, transport_mode="SEA"
            )
        for route in (
            "logistics_shipment_detail",
            "logistics_shipment_edit",
            "logistics_shipment_manifest",
        ):
            self.assertEqual(self.client.get(reverse(route, args=[foreign.pk])).status_code, 404)
        response = self.client.get(reverse("logistics_shipment_list") + "?transport_mode=AIR")
        self.assertNotContains(response, foreign.reference)
        self.assertFalse(self.form(transport_mode="AIR").is_valid())

    def test_manifest_list_detail_dashboard_and_csv_render_mode(self):
        shipment = self.shipment(transport_mode="ROAD")
        parcel = self.parcel()
        assign_parcel(business=self.business, shipment=shipment, parcel=parcel, actor=self.user)
        manifest = generate_manifest(business=self.business, shipment=shipment, actor=self.user)
        self.assertEqual(manifest["transport_mode"], "ROAD")
        self.assertEqual(manifest["transport_mode_label"], "Road / Truck")
        self.assertEqual(manifest["parcel_count"], 1)
        for route, args in (
            ("logistics_shipment_list", []),
            ("logistics_shipment_detail", [shipment.pk]),
            ("logistics_shipment_manifest", [shipment.pk]),
            ("agent_dashboard", []),
        ):
            response = self.client.get(reverse(route, args=args))
            self.assertContains(response, "Road / Truck")
            self.assertContains(response, "fa-truck")
        response = self.client.get(
            reverse("logistics_shipment_manifest", args=[shipment.pk]) + "?download=csv"
        )
        rows = list(csv.reader(StringIO(response.content.decode())))
        self.assertIn(["Transportation mode", "Road / Truck"], rows)
        self.assertNotIn("private@example.com", response.content.decode())

    def test_create_and_edit_ui_post(self):
        self.profile(["SEA", "ROAD"])
        response = self.client.get(reverse("logistics_shipment_create"))
        self.assertContains(response, "Transportation mode")
        self.assertContains(response, 'value="ROAD"')
        self.assertNotContains(response, 'value="AIR"')
        form = self.form(transport_mode="SEA")
        response = self.client.post(reverse("logistics_shipment_create"), form.data)
        self.assertEqual(response.status_code, 302)
        shipment = Shipment.objects.get()
        form = self.form(shipment=shipment, transport_mode="ROAD")
        response = self.client.post(
            reverse("logistics_shipment_edit", args=[shipment.pk]), form.data
        )
        self.assertEqual(response.status_code, 302)
        shipment.refresh_from_db()
        self.assertEqual(shipment.transport_mode, "ROAD")

    def test_old_edit_form_omitting_mode_retains_historical_value(self):
        shipment = self.shipment(transport_mode="SEA")
        self.profile(["ROAD"])
        form = self.form(shipment=shipment)
        self.assertTrue(form.is_valid(), form.errors)
        response = self.client.post(
            reverse("logistics_shipment_edit", args=[shipment.pk]), form.data
        )
        self.assertEqual(response.status_code, 302)
        shipment.refresh_from_db()
        self.assertEqual(shipment.transport_mode, "SEA")

    def test_filter_includes_historical_and_unknown_modes_and_keeps_pagination(self):
        sea, road, unknown = (
            self.shipment(transport_mode="SEA"),
            self.shipment(transport_mode="ROAD"),
            self.shipment(),
        )
        self.profile(["ROAD"])
        for mode, included, excluded in (
            ("SEA", sea, road),
            ("ROAD", road, sea),
            ("UNKNOWN", unknown, sea),
        ):
            response = self.client.get(reverse("logistics_shipment_list"), {"transport_mode": mode})
            self.assertContains(response, included.reference)
            self.assertNotContains(response, excluded.reference)
            self.assertEqual(response.context["pagination_query"], f"transport_mode={mode}")
        response = self.client.get(reverse("logistics_shipment_list"), {"transport_mode": "BAD"})
        self.assertTrue(response.context["filter_form"].errors)
        self.assertNotContains(response, sea.reference)

    def test_inspection_reports_tenant_mode_counts_and_admin_exposes_field(self):
        self.shipment(transport_mode="SEA")
        self.shipment()
        create_shipment(
            business=self.other,
            actor=self.other_user,
            origin="Other",
            destination="Route",
            transport_mode="AIR",
        )
        output = StringIO()
        call_command(
            "inspect_business_data",
            business_id=self.business.pk,
            output_format="json",
            stdout=output,
        )
        summary = json.loads(output.getvalue())["logistics"]["usage"][
            "shipment_transport_mode_summary"
        ]
        self.assertEqual(summary, {"SEA": 1, "AIR": 0, "ROAD": 0, "RAIL": 0, "unknown": 1})
        model_admin = ShipmentAdmin(Shipment, AdminSite())
        self.assertIn("transport_mode", model_admin.list_display)
        self.assertIn("transport_mode", model_admin.list_filter)

    def test_service_workspace_unchanged(self):
        with self.assertRaises(PermissionDenied):
            create_shipment(
                business=self.service,
                actor=self.user,
                origin="A",
                destination="B",
                transport_mode="SEA",
            )
        self.assertFalse(LogisticsProfile.objects.filter(business=self.service).exists())

    def test_database_rejects_invalid_modes_and_accepts_unknown(self):
        shipment = self.shipment()
        for mode in ("BAD", ""):
            with self.subTest(mode=mode), self.assertRaises(IntegrityError), transaction.atomic():
                QuerySet(model=Shipment).filter(pk=shipment.pk).update(transport_mode=mode)
        shipment.refresh_from_db()
        self.assertIsNone(shipment.transport_mode)


class TransportationSeedTests(TestCase):
    setUp = test_operations.LogisticsOperationsTests.setUp

    def test_seed_distributes_sea_and_road_without_air_or_rail(self):
        call_command(
            "seed_logistics_demo_data",
            business_id=self.business.pk,
            execute=True,
            stdout=StringIO(),
        )
        shipments = Shipment.objects.filter(business=self.business)
        self.assertEqual(shipments.filter(transport_mode="SEA").count(), 4)
        self.assertEqual(shipments.filter(transport_mode="ROAD").count(), 2)
        self.assertFalse(shipments.exclude(transport_mode__in=["SEA", "ROAD"]).exists())
        self.assertEqual(
            LogisticsProfile.objects.get(business=self.business).transportation_modes,
            ["SEA", "ROAD"],
        )
        self.assertTrue(shipments.filter(origin__startswith="Miami", transport_mode="SEA").exists())
        self.assertTrue(
            shipments.filter(destination="Cole Bay delivery hub", transport_mode="ROAD").exists()
        )


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency requires PostgreSQL")
class TransportationConcurrencyTests(TransactionTestCase):
    setUp = test_concurrency.LogisticsOperationConcurrencyTests.setUp

    def test_concurrent_mode_edits_reject_stale_writer(self):
        LogisticsProfile.objects.create(
            business=self.business, transportation_modes=["SEA", "ROAD"]
        )
        shipment = create_shipment(
            business=self.business,
            actor=self.user,
            origin="A",
            destination="B",
            transport_mode="SEA",
        )
        results = test_concurrency.race(
            [
                lambda mode=mode: update_shipment(
                    business=self.business,
                    actor=self.user,
                    shipment=shipment,
                    transport_mode=mode,
                    expected_revision=1,
                    idempotency_key=uuid4(),
                ).transport_mode
                for mode in ("SEA", "ROAD")
            ]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        shipment.refresh_from_db()
        self.assertEqual(shipment.revision, 2)
        self.assertEqual(
            shipment.transport_mode, next(mode for status, mode in results if status == "ok")
        )

    def test_same_create_key_with_different_modes_cannot_replay(self):
        LogisticsProfile.objects.create(
            business=self.business, transportation_modes=["SEA", "ROAD"]
        )
        key = uuid4()
        results = test_concurrency.race(
            [
                lambda mode=mode: create_shipment(
                    business=self.business,
                    actor=self.user,
                    origin="A",
                    destination="B",
                    transport_mode=mode,
                    idempotency_key=key,
                ).transport_mode
                for mode in ("SEA", "ROAD")
            ]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        self.assertEqual(Shipment.objects.count(), 1)
        self.assertEqual(
            Shipment.objects.get().transport_mode,
            next(mode for status, mode in results if status == "ok"),
        )


class TransportationMigrationTests(TransactionTestCase):
    def test_backfills_exactly_one_known_mode_only_and_preserves_writes(self):
        old = [("logistics", "0010_operating_classification")]
        new = [("logistics", "0011_shipment_transport_mode")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(old)
        try:
            historical = executor.loader.project_state(old).apps
            Business = historical.get_model("businesses", "Business")
            Profile = historical.get_model("logistics", "LogisticsProfile")
            OldShipment = historical.get_model("logistics", "Shipment")
            cases = [([mode], "LOGISTICS", mode) for mode in TransportationMode.values]
            cases += [
                (["SEA", "ROAD"], "LOGISTICS", None),
                ([], "LOGISTICS", None),
                (None, "LOGISTICS", None),
                (["SEA"], "SERVICE", None),
                (["BAD"], "LOGISTICS", None),
            ]
            for index, (modes, vertical, expected) in enumerate(cases):
                business = Business.objects.create(
                    name=f"Legacy {index}", slug=f"transport-legacy-{index}", vertical=vertical
                )
                if modes is not None:
                    Profile.objects.create(business=business, transportation_modes=modes)
                shipment = OldShipment.objects.create(
                    business=business,
                    origin="Unchanged",
                    destination="Anywhere",
                    revision=3,
                    write_receipts={"old-key": "unchanged"},
                )
                cases[index] = (shipment.pk, shipment.updated_at, expected)
            MigrationExecutor(connection).migrate(new)
            NewShipment = (
                MigrationExecutor(connection)
                .loader.project_state(new)
                .apps.get_model("logistics", "Shipment")
            )
            for pk, updated_at, expected in cases:
                shipment = NewShipment.objects.get(pk=pk)
                self.assertEqual(shipment.transport_mode, expected)
                self.assertEqual(shipment.updated_at, updated_at)
                self.assertEqual(shipment.revision, 3)
                self.assertEqual(shipment.write_receipts, {"old-key": "unchanged"})
                self.assertEqual(shipment.origin, "Unchanged")
            # Reapplying the backfill does not rewrite a saved historical mode.
            from importlib import import_module

            migration = import_module("apps.logistics.migrations.0011_shipment_transport_mode")
            NewShipment.objects.filter(pk=cases[0][0]).update(transport_mode="RAIL")
            with connection.schema_editor() as editor:
                migration.backfill_transport_mode(
                    MigrationExecutor(connection).loader.project_state(new).apps, editor
                )
            self.assertEqual(NewShipment.objects.get(pk=cases[0][0]).transport_mode, "RAIL")
        finally:
            MigrationExecutor(connection).migrate(latest)
