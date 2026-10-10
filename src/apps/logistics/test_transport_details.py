"""Optional mode references must preserve history, authorization and exact writes."""

import csv
from io import StringIO
from unittest import skipUnless
from uuid import uuid4

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import QuerySet
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from . import test_concurrency, test_operations, test_shipments
from .admin import ShipmentAdmin
from .models import LogisticsProfile, Shipment
from .public_tracking import lookup_public_tracking
from .shipment_forms import ShipmentForm
from .shipment_references import (
    ROAD_REFERENCE_FIELDS,
    SEA_REFERENCE_FIELDS,
    SHIPMENT_REFERENCE_FIELDS,
)
from .shipment_services import (
    assign_parcel,
    create_shipment,
    generate_manifest,
    update_shipment,
)

SEA_DETAILS = {
    "carrier_name": "Fictional Sea Carrier",
    "vessel_name": "MV Test Vessel",
    "voyage_reference": "TEST-VOY-001",
    "container_reference": "TEST-CONTAINER-001",
    "bill_of_lading_reference": "TEST-BOL-001",
}
ROAD_DETAILS = {
    "carrier_name": "Fictional Road Carrier",
    "vehicle_reference": "TEST-TRUCK-001",
    "driver_name": "Test Driver",
    "dispatch_reference": "TEST-DISPATCH-001",
}


class TransportDetailsTests(TestCase):
    setUp = test_shipments.ShipmentTests.setUp
    shipment = test_shipments.ShipmentTests.shipment
    parcel = test_shipments.ShipmentTests.parcel
    parcel_status = test_shipments.ShipmentTests.parcel_status
    status = test_shipments.ShipmentTests.status

    def edit(self, shipment, **fields):
        return update_shipment(business=self.business, shipment=shipment, actor=self.user, **fields)

    def form(self, shipment=None, **fields):
        data = {"origin": "Miami", "destination": "Curacao", "idempotency_key": str(uuid4())}
        if shipment:
            data["expected_revision"] = shipment.revision
            data["transport_mode"] = shipment.transport_mode or ""
        data.update(fields)
        return ShipmentForm(data, instance=shipment, business=self.business)

    def test_sea_and_road_references_save_and_display_only_populated_values(self):
        for mode, details, missing_label in (
            ("SEA", SEA_DETAILS, "Dispatch Reference"),
            ("ROAD", ROAD_DETAILS, "Bill of Lading"),
        ):
            with self.subTest(mode=mode):
                shipment = self.shipment(transport_mode=mode, **details)
                response = self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk]))
                self.assertContains(response, "Transportation details")
                for name, value in details.items():
                    self.assertEqual(getattr(shipment, name), value)
                    self.assertContains(response, value)
                self.assertNotContains(response, missing_label)
                self.assertTrue(
                    all(Shipment._meta.get_field(name).null for name in SHIPMENT_REFERENCE_FIELDS)
                )

    def test_air_rail_and_unknown_support_shared_carrier_without_specialized_fields(self):
        for mode in ("AIR", "RAIL", None):
            shipment = self.shipment(transport_mode=mode, carrier_name="Shared carrier")
            form = ShipmentForm(business=self.business, instance=shipment)
            self.assertFalse(form.sea_references_visible)
            self.assertFalse(form.road_references_visible)
            changed = self.edit(shipment, carrier_name="New carrier")
            self.assertEqual(changed.carrier_name, "New carrier")
            with self.subTest(mode=mode), self.assertRaises(ValidationError):
                self.shipment(transport_mode=mode, vessel_name="New unsupported vessel")

    def test_wrong_mode_new_and_changed_fields_rejected_in_forms_and_services(self):
        for mode, wrong in (
            ("SEA", "driver_name"),
            ("ROAD", "container_reference"),
            ("AIR", "dispatch_reference"),
            ("RAIL", "vessel_name"),
            (None, "vehicle_reference"),
        ):
            with self.subTest(mode=mode):
                with self.assertRaises(ValidationError):
                    self.shipment(transport_mode=mode, **{wrong: "Wrong field"})
                self.assertEqual(Shipment.objects.count(), 0)
                form = self.form(transport_mode=mode or "", **{wrong: "Keep entered value"})
                self.assertFalse(form.is_valid())
                self.assertIn(wrong, form.errors)
                self.assertEqual(form[wrong].value(), "Keep entered value")

    def test_optional_blank_normalization_and_length_limits(self):
        shipment = self.shipment(
            transport_mode="SEA", carrier_name="   Carrier   ", vessel_name="   "
        )
        self.assertEqual(shipment.carrier_name, "Carrier")
        self.assertIsNone(shipment.vessel_name)
        changed = self.edit(shipment, carrier_name="", voyage_reference="  V-1  ")
        self.assertIsNone(changed.carrier_name)
        self.assertEqual(changed.voyage_reference, "V-1")
        for field, mode in (
            ("carrier_name", "AIR"),
            ("vessel_name", "SEA"),
            ("voyage_reference", "SEA"),
            ("vehicle_reference", "ROAD"),
            ("driver_name", "ROAD"),
        ):
            limit = Shipment._meta.get_field(field).max_length
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.shipment(transport_mode=mode, **{field: "x" * (limit + 1)})
            form = self.form(transport_mode=mode, **{field: "x" * (limit + 1)})
            self.assertFalse(form.is_valid())
            self.assertIn(field, form.errors)

    def test_historical_hidden_fields_remain_readable_and_do_not_block_unrelated_edit(self):
        shipment = self.shipment(transport_mode="SEA", **SEA_DETAILS)
        QuerySet(model=Shipment).filter(pk=shipment.pk).update(driver_name="Historical driver")
        shipment.refresh_from_db()
        shipment.full_clean()
        changed = self.edit(shipment, notes="Unrelated correction")
        self.assertEqual(changed.driver_name, "Historical driver")
        form = self.form(
            changed, **{name: getattr(changed, name) for name in SHIPMENT_REFERENCE_FIELDS}
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.road_references_visible)
        response = self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk]))
        self.assertContains(response, "Historical driver")
        manifest = generate_manifest(business=self.business, shipment=shipment, actor=self.user)
        self.assertNotIn(
            "Historical driver", [item["value"] for item in manifest["transportation_details"]]
        )
        with self.assertRaises(ValidationError):
            self.edit(changed, driver_name="Different unsupported driver")
        self.assertIsNone(self.edit(changed, driver_name=None).driver_name)

    def test_mode_change_preserves_old_references_and_adds_current_ones(self):
        LogisticsProfile.objects.create(
            business=self.business, transportation_modes=["SEA", "ROAD"]
        )
        shipment = self.shipment(transport_mode="SEA", **SEA_DETAILS)
        changed = self.edit(shipment, transport_mode="ROAD", vehicle_reference="NEW-TRUCK")
        self.assertEqual(changed.vessel_name, SEA_DETAILS["vessel_name"])
        self.assertEqual(changed.vehicle_reference, "NEW-TRUCK")
        self.assertContains(
            self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk])),
            SEA_DETAILS["vessel_name"],
        )
        manifest = generate_manifest(business=self.business, shipment=changed, actor=self.user)
        self.assertEqual(
            [item["label"] for item in manifest["transportation_details"]], ["Carrier", "Vehicle"]
        )
        form = self.form(
            changed, vessel_name=SEA_DETAILS["vessel_name"], vehicle_reference="NEW-TRUCK"
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_partial_updates_use_saved_mode_and_preserve_omitted_references(self):
        shipment = self.shipment(transport_mode="SEA", **SEA_DETAILS)
        changed = self.edit(shipment, vessel_name="Updated vessel")
        self.assertEqual(changed.voyage_reference, SEA_DETAILS["voyage_reference"])
        with self.assertRaises(ValidationError):
            self.edit(changed, vehicle_reference="Wrong mode")
        form = self.form(changed, notes="Old form without new fields")
        response = self.client.post(
            reverse("logistics_shipment_edit", args=[shipment.pk]), form.data
        )
        self.assertEqual(response.status_code, 302)
        shipment.refresh_from_db()
        self.assertEqual(shipment.vessel_name, "Updated vessel")

    def test_create_edit_ui_and_error_values(self):
        form = self.form(transport_mode="SEA", **SEA_DETAILS)
        response = self.client.post(reverse("logistics_shipment_create"), form.data)
        self.assertEqual(response.status_code, 302)
        shipment = Shipment.objects.get()
        form = self.form(shipment, vessel_name="Edited vessel")
        response = self.client.post(
            reverse("logistics_shipment_edit", args=[shipment.pk]), form.data
        )
        self.assertEqual(response.status_code, 302)
        shipment.refresh_from_db()
        self.assertEqual(shipment.vessel_name, "Edited vessel")
        form = self.form(
            transport_mode="ROAD", vehicle_reference="Keep truck", voyage_reference="Wrong voyage"
        )
        response = self.client.post(reverse("logistics_shipment_create"), form.data)
        self.assertContains(response, 'value="Keep truck"')
        self.assertContains(response, 'value="Wrong voyage"')
        self.assertNotContains(response, 'data-shipment-reference-mode="SEA" hidden')
        self.assertEqual(Shipment.objects.count(), 1)

    def test_no_js_refresh_preserves_values_tokens_and_performs_no_writes(self):
        form = self.form(
            transport_mode="SEA",
            carrier_name="Draft carrier",
            vessel_name="Draft vessel",
            origin="",
        )
        response = self.client.post(
            reverse("logistics_shipment_create"), {**form.data, "refresh_transport_fields": "1"}
        )
        self.assertEqual(response.status_code, 200)
        refreshed = response.context["form"]
        self.assertFalse(refreshed.is_bound)
        self.assertFalse(refreshed.errors)
        self.assertEqual(refreshed["idempotency_key"].value(), form.data["idempotency_key"])
        self.assertEqual(refreshed["vessel_name"].value(), "Draft vessel")
        self.assertTrue(refreshed.sea_references_visible)
        self.assertFalse(refreshed.road_references_visible)
        self.assertFalse(Shipment.objects.exists())
        response = self.client.post(
            reverse("logistics_shipment_create"),
            {**form.data, "transport_mode": "ROAD", "refresh_transport_fields": "1"},
        )
        refreshed = response.context["form"]
        self.assertTrue(refreshed.road_references_visible)
        self.assertFalse(refreshed.sea_references_visible)
        self.assertEqual(refreshed["vessel_name"].value(), "Draft vessel")

    def test_edit_refresh_preserves_loaded_revision_and_cannot_bypass_stale_write(self):
        shipment = self.shipment(transport_mode="ROAD", **ROAD_DETAILS)
        form = self.form(shipment, dispatch_reference="Stale dispatch")
        self.edit(shipment, dispatch_reference="Other writer")
        url = reverse("logistics_shipment_edit", args=[shipment.pk])
        response = self.client.post(url, {**form.data, "refresh_transport_fields": "1"})
        self.assertEqual(
            response.context["form"]["expected_revision"].value(),
            str(form.data["expected_revision"]),
        )
        response = self.client.post(url, form.data)
        self.assertContains(response, "changed after this form was loaded")
        shipment.refresh_from_db()
        self.assertEqual(shipment.dispatch_reference, "Other writer")

    def test_reference_retries_are_exact_and_do_not_reapply_after_mode_change(self):
        key = uuid4()
        shipment = self.shipment(transport_mode="SEA", idempotency_key=key, **SEA_DETAILS)
        self.assertEqual(
            self.shipment(transport_mode="SEA", idempotency_key=key, **SEA_DETAILS).pk, shipment.pk
        )
        with self.assertRaises(ValidationError):
            self.shipment(
                transport_mode="SEA",
                idempotency_key=key,
                **{**SEA_DETAILS, "vessel_name": "Different"},
            )
        edit_key, revision = uuid4(), shipment.revision
        changed = self.edit(
            shipment,
            vessel_name="Earlier vessel",
            expected_revision=revision,
            idempotency_key=edit_key,
        )
        changed = self.edit(changed, transport_mode="ROAD")
        replay = self.edit(
            changed,
            vessel_name="Earlier vessel",
            expected_revision=revision,
            idempotency_key=edit_key,
        )
        self.assertEqual(replay.transport_mode, "ROAD")
        replay_form = self.form(
            changed,
            vessel_name="Earlier vessel",
            expected_revision=revision,
            idempotency_key=str(edit_key),
        )
        self.assertTrue(replay_form.is_valid(), replay_form.errors)
        with self.assertRaises(ValidationError):
            self.edit(
                changed,
                vessel_name="Different retry",
                expected_revision=revision,
                idempotency_key=edit_key,
            )

    def test_pre_details_receipts_survive_new_null_fields_and_later_detail_edits(self):
        create_key = uuid4()
        shipment = self.shipment(transport_mode="SEA", idempotency_key=create_key)
        key, revision = uuid4(), shipment.revision
        form = self.form(shipment, notes="Original edit", idempotency_key=str(key))
        url = reverse("logistics_shipment_edit", args=[shipment.pk])
        self.assertEqual(self.client.post(url, form.data).status_code, 302)
        shipment.refresh_from_db()
        changed = self.edit(shipment, vessel_name="Later vessel")
        self.assertEqual(self.client.post(url, form.data).status_code, 302)
        shipment.refresh_from_db()
        self.assertEqual(shipment.vessel_name, "Later vessel")
        self.assertEqual(
            self.shipment(transport_mode="SEA", idempotency_key=create_key).pk, shipment.pk
        )
        self.assertGreater(changed.revision, revision)

    def test_reference_stale_writes_and_lifecycle_rules_remain_in_force(self):
        shipment, parcel = self.shipment(transport_mode="ROAD", **ROAD_DETAILS), self.parcel()
        stale = Shipment.objects.get(pk=shipment.pk)
        shipment = self.edit(shipment, dispatch_reference="Latest dispatch")
        with self.assertRaises(ValidationError):
            self.edit(stale, dispatch_reference="Stale dispatch")
        assign_parcel(business=self.business, shipment=shipment, parcel=parcel, actor=self.user)
        self.parcel_status(parcel, "RECEIVED")
        for status in ("READY", "IN_TRANSIT", "ARRIVED"):
            self.status(shipment, status)
        with self.assertRaises(ValidationError):
            self.edit(shipment, driver_name="Late edit")
        self.parcel_status(parcel, "READY")
        self.parcel_status(parcel, "DELIVERED")
        self.status(shipment, "COMPLETED")
        shipment.refresh_from_db()
        parcel.refresh_from_db()
        self.assertEqual(shipment.dispatch_reference, "Latest dispatch")
        self.assertEqual(parcel.shipment_id, shipment.pk)

    def test_tenant_isolation_and_service_compatibility(self):
        foreign = create_shipment(
            business=self.other,
            actor=self.other_user,
            origin="Other",
            destination="Other",
            transport_mode="SEA",
            vessel_name="PRIVATE-FOREIGN",
        )
        with self.assertRaises(ValidationError):
            self.edit(foreign, vessel_name="Forbidden")
        self.assertEqual(
            self.client.post(
                reverse("logistics_shipment_edit", args=[foreign.pk]),
                {"refresh_transport_fields": "1"},
            ).status_code,
            404,
        )
        self.assertNotContains(
            self.client.get(reverse("logistics_shipment_list")), "PRIVATE-FOREIGN"
        )
        with self.assertRaises(PermissionDenied):
            create_shipment(
                business=self.service,
                actor=self.user,
                origin="A",
                destination="B",
                carrier_name="Carrier",
            )
        self.assertFalse(Shipment.objects.filter(business=self.service).exists())

    def test_manifest_references_escape_html_and_csv_and_keep_privacy_and_totals(self):
        shipment = self.shipment(
            transport_mode="SEA",
            **{
                **SEA_DETAILS,
                "carrier_name": "=SUM(1,2)",
                "vessel_name": "<script>fiction</script>",
            },
        )
        parcel = self.parcel(quantity=2, weight_kg="1.25")
        assign_parcel(business=self.business, shipment=shipment, parcel=parcel, actor=self.user)
        url = reverse("logistics_shipment_manifest", args=[shipment.pk])
        response = self.client.get(url)
        self.assertContains(response, "&lt;script&gt;fiction&lt;/script&gt;")
        self.assertNotContains(response, "<script>fiction</script>")
        csv_response = self.client.get(url + "?download=csv")
        rows = list(csv.reader(StringIO(csv_response.content.decode())))
        self.assertIn(["Carrier", "'=SUM(1,2)"], rows)
        self.assertIn(["Bill of Lading", SEA_DETAILS["bill_of_lading_reference"]], rows)
        self.assertIn(["Parcel count", "1"], rows)
        self.assertIn(["Total quantity", "2"], rows)
        self.assertNotIn("PRIVATE-PHONE", csv_response.content.decode())
        self.assertNotIn("vessel_name", lookup_public_tracking(parcel.tracking_code))

    def test_admin_uses_existing_search_and_readonly_inspection(self):
        model_admin = ShipmentAdmin(Shipment, AdminSite())
        self.assertIn("vessel_name", model_admin.search_fields)
        self.assertIn("dispatch_reference", model_admin.search_fields)
        self.assertNotIn("driver_name", model_admin.list_display)


class TransportDetailsSeedTests(TestCase):
    setUp = test_operations.LogisticsOperationsTests.setUp

    def test_seed_has_fictional_mode_specific_references_only(self):
        profile = LogisticsProfile.objects.create(
            business=self.business, transportation_modes=["SEA", "ROAD"]
        )
        call_command(
            "seed_logistics_demo_data",
            business_id=self.business.pk,
            execute=True,
            stdout=StringIO(),
        )
        shipments = Shipment.objects.filter(business=self.business)
        for shipment in shipments:
            active = (
                SEA_REFERENCE_FIELDS if shipment.transport_mode == "SEA" else ROAD_REFERENCE_FIELDS
            )
            other = (
                ROAD_REFERENCE_FIELDS if shipment.transport_mode == "SEA" else SEA_REFERENCE_FIELDS
            )
            for name in ("carrier_name", *active):
                self.assertIn("DEMO", getattr(shipment, name))
            for name in other:
                self.assertIsNone(getattr(shipment, name))
        self.assertEqual(shipments.filter(transport_mode="SEA").count(), 4)
        self.assertEqual(shipments.filter(transport_mode="ROAD").count(), 2)
        self.assertEqual(
            LogisticsProfile.objects.get(business=self.business).transportation_modes,
            ["SEA", "ROAD"],
        )
        self.assertEqual(LogisticsProfile.objects.get(pk=profile.pk).updated_at, profile.updated_at)


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency requires PostgreSQL")
class TransportDetailsConcurrencyTests(TransactionTestCase):
    setUp = test_concurrency.LogisticsOperationConcurrencyTests.setUp

    def test_reference_edit_race_rejects_stale_writer(self):
        shipment = create_shipment(
            business=self.business,
            actor=self.user,
            origin="A",
            destination="B",
            transport_mode="SEA",
        )
        results = test_concurrency.race(
            [
                lambda value=value: update_shipment(
                    business=self.business,
                    actor=self.user,
                    shipment=shipment,
                    vessel_name=value,
                    expected_revision=1,
                    idempotency_key=uuid4(),
                ).vessel_name
                for value in ("First vessel", "Second vessel")
            ]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        shipment.refresh_from_db()
        self.assertEqual(shipment.revision, 2)
        self.assertEqual(
            shipment.vessel_name, next(value for status, value in results if status == "ok")
        )

    def test_create_reference_retry_race_returns_one_shipment(self):
        key = uuid4()
        results = test_concurrency.race(
            [
                lambda: create_shipment(
                    business=self.business,
                    actor=self.user,
                    origin="A",
                    destination="B",
                    transport_mode="ROAD",
                    idempotency_key=key,
                    **ROAD_DETAILS,
                ).pk
            ]
            * 2
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], "ok")
        self.assertEqual(Shipment.objects.count(), 1)


class TransportDetailsMigrationTests(TransactionTestCase):
    def test_existing_shipments_get_null_fields_without_rewriting_history(self):
        old = [("logistics", "0011_shipment_transport_mode")]
        new = [("logistics", "0012_shipment_transport_references")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(old)
        try:
            state = executor.loader.project_state(old).apps
            Business = state.get_model("businesses", "Business")
            OldShipment = state.get_model("logistics", "Shipment")
            business = Business.objects.create(
                name="Legacy Details", slug="legacy-details", vertical="LOGISTICS"
            )
            saved = []
            for mode in ("SEA", "ROAD", "AIR", "RAIL", None):
                item = OldShipment.objects.create(
                    business=business,
                    origin="Old",
                    destination="Route",
                    transport_mode=mode,
                    revision=5,
                    status="IN_TRANSIT",
                    write_receipts={"old": "receipt"},
                )
                saved.append((item.pk, item.updated_at, mode))
            MigrationExecutor(connection).migrate(new)
            for pk, updated_at, mode in saved:
                item = (
                    MigrationExecutor(connection)
                    .loader.project_state(new)
                    .apps.get_model("logistics", "Shipment")
                    .objects.get(pk=pk)
                )
                for name in SHIPMENT_REFERENCE_FIELDS:
                    self.assertIsNone(getattr(item, name))
                self.assertEqual(item.transport_mode, mode)
                self.assertEqual(item.updated_at, updated_at)
                self.assertEqual(item.revision, 5)
                self.assertEqual(item.status, "IN_TRANSIT")
                self.assertEqual(item.write_receipts, {"old": "receipt"})
        finally:
            MigrationExecutor(connection).migrate(latest)
