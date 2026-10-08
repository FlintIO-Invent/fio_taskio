"""The normal seed command exercises current Logistics forms and operational services."""

import json
from collections import Counter
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from apps.appointments.models import Appointment
from apps.billings.models import Invoice, InvoiceLine
from apps.billings.services import generate_invoice_number
from apps.businesses.models import DemoSeedRecord, DemoSeedRun
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import ActivityLog, BusinessService, Client, Lead

from . import test_operations as fixtures
from .billing_services import invoice_charges
from .demo import LOGISTICS_DEMO_COUNTS, PARCEL_STATUS_COUNTS, SHIPMENT_STATUS_COUNTS
from .models import LogisticsCharge, LogisticsProfile, Parcel, ParcelEvent, Shipment
from .parcel_policy import ALLOWED_TRANSITIONS
from .parcel_services import PARCEL_INPUT_FIELDS
from .public_tracking import lookup_public_tracking
from .shipment_services import generate_manifest


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
        plan = json.loads(output.splitlines()[0])
        self.assertEqual(plan["planned_counts"], {"logistics_profiles": 1, **LOGISTICS_DEMO_COUNTS})
        self.assertEqual(plan["parcel_status_counts"], PARCEL_STATUS_COUNTS)
        self.assertEqual(plan["shipment_status_counts"], SHIPMENT_STATUS_COUNTS)
        self.assertEqual(plan["invoice_status_counts"], {"DRAFT": 1, "SENT": 2, "PAID": 1})
        self.assertFalse(DemoSeedRun.objects.exists())
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(LogisticsProfile.objects.exists())
        self.assertEqual(Client.objects.count(), 1)

    def test_seed_defaults_to_realistic_modes_and_reset_keeps_profile(self):
        self.command(execute=True)
        profile = LogisticsProfile.objects.get(business=self.business)
        self.assertEqual(profile.operating_areas, ["TRANSPORTATION"])
        self.assertEqual(profile.transportation_modes, ["SEA", "ROAD"])
        self.command(reset_demo=True, execute=True)
        profile.refresh_from_db()
        self.assertEqual(profile.transportation_modes, ["SEA", "ROAD"])
        plan = json.loads(self.command().splitlines()[0])
        self.assertEqual(plan["planned_counts"]["logistics_profiles"], 0)
        self.assertEqual(plan["logistics_profile"]["action"], "keep")

    def test_seed_preserves_explicit_operating_profile(self):
        profile = LogisticsProfile.objects.create(
            business=self.business, operating_areas=["WAREHOUSING"]
        )
        for execute in (False, True):
            with self.assertRaisesMessage(CommandError, "existing explicit LogisticsProfile"):
                self.command(execute=execute)
        profile.refresh_from_db()
        self.assertEqual(profile.operating_areas, ["WAREHOUSING"])
        self.assertEqual(profile.transportation_modes, [])
        self.assertFalse(DemoSeedRun.objects.exists())
        self.assertFalse(Parcel.objects.exists())

    def test_seed_fills_only_unknown_modes_and_rejects_explicit_other_modes(self):
        profile = LogisticsProfile.objects.create(business=self.business)
        preview = json.loads(self.command().splitlines()[0])
        self.assertEqual(preview["logistics_profile"]["action"], "fill_modes")
        profile.refresh_from_db()
        self.assertEqual(profile.transportation_modes, [])
        self.command(execute=True)
        profile.refresh_from_db()
        self.assertEqual(profile.transportation_modes, ["SEA", "ROAD"])
        self.command(reset_demo=True, execute=True)
        profile.transportation_modes = ["AIR"]
        profile.save()
        with self.assertRaisesMessage(CommandError, "Sea + Road"):
            self.command(execute=True)
        profile.refresh_from_db()
        self.assertEqual(profile.transportation_modes, ["AIR"])

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
        self.assertEqual(Client.objects.exclude(pk=self.genuine.pk).count(), 6)
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
            for field in ("mode_of_transport", "vessel_name", "voyage_no", "master_bl_no"):
                self.assertLessEqual(len(set(shipment.parcels.values_list(field, flat=True))), 1)
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

    def test_connected_client_stories_and_invoice_snapshots(self):
        self.command(execute=True)
        parcels = {
            p.internal_reference: p for p in Parcel.objects.select_related("client", "shipment")
        }
        a, b, c, d, e, f = [
            parcels[reference].client
            for reference in (
                "DEMO-004",
                "DEMO-016",
                "DEMO-001",
                "DEMO-015",
                "DEMO-007",
                "DEMO-009",
            )
        ]
        self.assertEqual(len({client.pk for client in (a, b, c, d, e, f)}), 6)
        self.assertEqual(
            Counter(Parcel.objects.values_list("client_id", flat=True)),
            {
                a.pk: 4,
                b.pk: 2,
                c.pk: 3,
                d.pk: 2,
                e.pk: 4,
                f.pk: 5,
            },
        )
        for reference, client, status, shipment_status in (
            ("DEMO-004", a, "IN_TRANSIT", "IN_TRANSIT"),
            ("DEMO-001", c, "DELIVERED", "COMPLETED"),
            ("DEMO-007", e, "ARRIVED", "ARRIVED"),
            ("DEMO-009", f, "RECEIVED", "READY"),
            ("DEMO-011", e, "RECEIVED", "DRAFT"),
        ):
            parcel = parcels[reference]
            self.assertEqual(parcel.client, client)
            self.assertEqual(parcel.current_status, status)
            self.assertEqual(parcel.shipment.status, shipment_status)
            self.assertEqual(
                set(parcel.shipment.parcels.values_list("client_id", flat=True)), {client.pk}
            )
        self.assertEqual(parcels["DEMO-017"].current_status, "HOLD")
        self.assertIn("packaging inspection", parcels["DEMO-017"].internal_notes)
        ready = parcels["DEMO-015"]
        self.assertEqual(ready.current_status, "READY")
        self.assertIsNone(ready.shipment_id)
        self.assertFalse(Shipment.objects.get(status="CANCELLED").parcels.exists())
        self.assertEqual(
            Counter(Invoice.objects.values_list("status", flat=True)),
            {
                "SENT": 2,
                "PAID": 1,
                "DRAFT": 1,
            },
        )
        self.assertEqual(InvoiceLine.objects.count(), 13)
        self.assertFalse(BusinessService.objects.filter(business=self.business).exists())
        self.assertFalse(Appointment.objects.filter(business=self.business).exists())
        self.assertFalse(Lead.objects.filter(business=self.business).exists())
        self.assertFalse(
            Invoice.objects.filter(business=self.business, appointment__isnull=False).exists()
        )
        self.assertFalse(
            InvoiceLine.objects.filter(
                invoice__business=self.business, service__isnull=False
            ).exists()
        )
        self.assertEqual(LogisticsCharge.objects.filter(invoice_line__isnull=True).count(), 3)
        for client, state, count, subtotal in (
            (a, "SENT", 3, "195.00"),
            (c, "PAID", 4, "227.50"),
            (d, "SENT", 3, "43.00"),
            (e, "DRAFT", 3, "190.00"),
        ):
            invoice = Invoice.objects.get(client=client)
            invoice.full_clean()
            self.assertEqual(invoice.status, state)
            self.assertEqual(invoice.lines.count(), count)
            self.assertEqual(invoice.subtotal, Decimal(subtotal))
            self.assertEqual(invoice.total, invoice.subtotal + invoice.tax)
            self.assertIn("[DEMO]", invoice.notes)
            self.assertIsNone(invoice.emailed_at)
            self.assertEqual(invoice.email_send_count, 0)
            for line in invoice.lines.select_related("parcel", "shipment", "logistics_charge"):
                line.full_clean()
                self.assertEqual(line.logistics_charge.client_id, client.pk)
                self.assertEqual(line.logistics_charge.business_id, self.business.pk)
                self.assertEqual(line.line_total, line.quantity * line.unit_price)
        descriptions = " ".join(InvoiceLine.objects.values_list("description", flat=True))
        for label in ("Freight", "Handling", "Delivery", "Customs", "Storage"):
            self.assertIn(label, descriptions)

    def test_execute_outputs_owned_active_and_delivered_public_tracking(self):
        output = self.command(execute=True)
        codes = json.loads(output.splitlines()[-1])["demo_tracking"]
        self.assertEqual({item["current_status"] for item in codes}, {"IN_TRANSIT", "DELIVERED"})
        for item in codes:
            parcel = Parcel.objects.get(tracking_code=item["tracking_code"])
            result = lookup_public_tracking(parcel.tracking_code)
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], parcel.current_status)
            expected = list(
                parcel.events.exclude(public_message="").values_list("public_message", flat=True)
            )
            self.assertEqual([event["message"] for event in result["events"]], expected)
            self.assertGreaterEqual(len(expected), 4)
            public = json.dumps(result)
            for private in (parcel.client.email, parcel.internal_reference, parcel.internal_notes):
                if private:
                    self.assertNotIn(private, public)
            for event in parcel.events.exclude(internal_note=""):
                self.assertNotIn(event.internal_note, public)
        hold = Parcel.objects.get(internal_reference="DEMO-017")
        public = json.dumps(lookup_public_tracking(hold.tracking_code))
        self.assertNotIn("packaging inspection", public)
        self.assertNotIn("Packaging and routing checkpoint", public)

    def test_manifest_and_shared_client_shipment_invoice_pages(self):
        self.command(execute=True)
        self.login()
        shipment = Shipment.objects.get(status="IN_TRANSIT")
        manifest = generate_manifest(business=self.business, shipment=shipment, actor=self.user)
        self.assertEqual(manifest["parcel_count"], 3)
        self.assertEqual(manifest["total_quantity"], 7)
        self.assertEqual(manifest["total_known_weight_kg"], Decimal("9.750"))
        self.assertEqual(manifest["unknown_weight_count"], 0)
        route = reverse("logistics_shipment_manifest", args=[shipment.pk])
        html = self.client.get(route)
        csv = self.client.get(route, {"download": "csv"})
        self.assertEqual(html.status_code, 200)
        self.assertEqual(csv.status_code, 200)
        self.assertIn("text/csv", csv["Content-Type"])
        for parcel in shipment.parcels.select_related("client"):
            self.assertContains(html, parcel.tracking_code)
            self.assertContains(csv, parcel.tracking_code)
            self.assertContains(html, parcel.client.first_name)
            self.assertNotContains(csv, parcel.client.email)
        for route_name in ("staff_client_list", "logistics_shipment_list", "invoice_list"):
            self.assertEqual(self.client.get(reverse(route_name)).status_code, 200)
        listing = self.client.get(reverse("invoice_list"))
        self.assertEqual(
            set(listing.context["invoices"].values_list("pk", flat=True)),
            set(Invoice.objects.values_list("pk", flat=True)),
        )
        for invoice in Invoice.objects.all():
            response = self.client.get(reverse("invoice_detail", args=[invoice.pk]))
            self.assertContains(response, invoice.invoice_number)

    def test_reset_alias_preserves_real_paid_financial_and_application_history(self):
        # An old genuine log can share a number later reused by a demo invoice.
        activity = ActivityLog.objects.create(
            business=self.business,
            client=self.genuine,
            actor=self.user,
            action_type=ActivityLog.ActionType.INVOICE_CREATED,
            summary="Genuine history",
            payload={"invoice_number": generate_invoice_number(business=self.business)},
        )
        self.command(execute=True)
        self.assertFalse(
            DemoSeedRecord.objects.filter(
                model_label=ActivityLog._meta.label, object_pk=str(activity.pk)
            ).exists()
        )
        application = fixtures.LogisticsOperationsTests.link_application(self)
        invoice = Invoice.objects.create(
            business=self.business, client=self.genuine, invoice_number="REAL-PAID", status="PAID"
        )
        line = InvoiceLine.objects.create(
            invoice=invoice, description="Real freight", unit_price=Decimal("42.00")
        )
        before = {
            model: model.objects.count() for model in (Parcel, Invoice, InvoiceLine, DemoSeedRecord)
        }
        for execute in (False, True):
            output = StringIO()
            arguments = ["--business-id", str(self.business.pk), "--reset"]
            if execute:
                arguments.append("--execute")
            call_command("seed_logistics_demo_data", *arguments, stdout=output)
            if not execute:
                self.assertIn("RESET PREVIEW ONLY", output.getvalue())
                self.assertEqual(before, {model: model.objects.count() for model in before})
        self.assertEqual(list(Invoice.objects.all()), [invoice])
        self.assertEqual(list(InvoiceLine.objects.all()), [line])
        self.assertEqual(list(ActivityLog.objects.all()), [activity])
        application.refresh_from_db()
        self.assertEqual(application.business_id, self.business.pk)
        self.assertTrue(application.decisions.exists())
        self.assertFalse(DemoSeedRun.objects.exists())

    def test_reset_refuses_genuine_line_on_seed_owned_paid_invoice(self):
        self.command(execute=True)
        invoice = Invoice.objects.get(status="PAID")
        line = InvoiceLine.objects.create(
            invoice=invoice, description="Genuine financial history", unit_price=Decimal("42.00")
        )
        before = {
            model: model.objects.count() for model in (Parcel, Invoice, InvoiceLine, DemoSeedRecord)
        }
        for execute in (False, True):
            with self.assertRaisesMessage(CommandError, "genuine or untracked"):
                self.command(reset_demo=True, execute=execute)
            self.assertEqual(before, {model: model.objects.count() for model in before})
        self.assertTrue(InvoiceLine.objects.filter(pk=line.pk).exists())

    def test_invoice_failure_rolls_back_the_entire_connected_seed(self):
        def fail_after_paid_scenario(**kwargs):
            if Invoice.objects.filter(status="PAID").exists():
                raise ValidationError("Demo invoice failure")
            return invoice_charges(**kwargs)

        with patch("apps.logistics.demo.invoice_charges", side_effect=fail_after_paid_scenario):
            with self.assertRaisesMessage(CommandError, "Demo invoice failure"):
                self.command(execute=True)
        self.assertEqual(list(Client.objects.all()), [self.genuine])
        for model in (
            Invoice,
            InvoiceLine,
            LogisticsCharge,
            ActivityLog,
            Parcel,
            ParcelEvent,
            Shipment,
            LogisticsProfile,
            DemoSeedRun,
            DemoSeedRecord,
        ):
            self.assertFalse(model.objects.exists())

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
            ("received_waiting_parcel_count", 7),
            ("ready_parcel_count", 1),
            ("in_transit_parcel_count", 3),
            ("pending_movement_parcel_count", 3),
        ):
            self.assertEqual(dashboard.context[key], value)
        for key in ("recent_tracking_events", "parcels_requiring_attention", "active_shipments"):
            self.assertTrue(dashboard.context[key])
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
        self.assertFalse(LogisticsProfile.objects.exists())
