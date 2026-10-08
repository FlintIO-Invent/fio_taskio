"""Shared invoices, legacy seed refresh and the supported vertical boundaries."""

import json
from decimal import Decimal
from io import StringIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from apps.appointments.models import Appointment
from apps.billings.models import Invoice, InvoiceLine
from apps.businesses.models import BusinessUser, DemoSeedRecord, DemoSeedRun
from apps.crm.models import BusinessService, Client, Lead

from . import test_workspace as fixtures
from .models import LogisticsProfile, Parcel, ParcelEvent, Shipment
from .parcel_services import register_parcel


class VerticalInvoiceAuditTests(TestCase):
    setUp = fixtures.LogisticsWorkspaceTests.setUp
    switch = fixtures.LogisticsWorkspaceTests.switch

    def command(self, name="seed_logistics_demo_data", business=None, **options):
        output = StringIO()
        call_command(name, business_id=(business or self.business).pk, stdout=output, **options)
        return output.getvalue()

    def invoice(self, business):
        customer = (
            self.customer
            if business == self.business
            else Client.objects.create(business=business, first_name="Shared", last_name="Client")
        )
        invoice = Invoice.objects.create(
            business=business, client=customer, invoice_number="SHARED-001"
        )
        InvoiceLine.objects.create(
            invoice=invoice, description="One-off charge", quantity=2, unit_price=Decimal("15.00")
        )
        return invoice

    def test_seed_database_ownership_and_ui_counts_match_exactly(self):
        output = self.command(execute=True)
        planned = json.loads(output.splitlines()[0])["planned_counts"]
        self.assertEqual((planned["invoices"], planned["invoice_lines"]), (4, 13))
        invoices = Invoice.objects.filter(business=self.business)
        lines = InvoiceLine.objects.filter(invoice__business=self.business)
        self.assertEqual((invoices.count(), lines.count()), (4, 13))
        self.assertFalse(invoices.exclude(client__business=self.business).exists())
        self.assertFalse(invoices.filter(appointment__isnull=False).exists())
        self.assertFalse(lines.filter(service__isnull=False).exists())
        seed = DemoSeedRun.objects.get(business=self.business)
        for model, queryset in ((Invoice, invoices), (InvoiceLine, lines)):
            self.assertEqual(
                set(
                    seed.owned_records.filter(model_label=model._meta.label).values_list(
                        "object_pk", flat=True
                    )
                ),
                {str(pk) for pk in queryset.values_list("pk", flat=True)},
            )
        listing = self.client.get(reverse("invoice_list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(set(listing.context["invoices"]), set(invoices))
        for invoice in invoices:
            self.assertContains(listing, invoice.invoice_number)
            self.assertContains(
                self.client.get(reverse("invoice_detail", args=[invoice.pk])),
                invoice.invoice_number,
            )
        for status, count in (("DRAFT", 1), ("SENT", 2), ("PAID", 1), ("CANCELLED", 0)):
            filtered = self.client.get(reverse("invoice_list"), {"status": status})
            self.assertEqual(filtered.context["invoices"].count(), count)

    def test_legacy_pre_invoice_seed_requires_safe_reset_before_refresh(self):
        old_client = Client.objects.create(
            business=self.business, first_name="Old", last_name="Demo"
        )
        old_parcel = register_parcel(
            business=self.business,
            actor=self.user,
            client=old_client,
            origin="Miami",
            destination="Sint Maarten",
            package_description="Old demo cargo",
        )
        old_seed = DemoSeedRun.objects.create(
            business=self.business,
            planned_counts={"clients": 1, "parcels": 1, "parcel_events": 1, "shipments": 0},
        )
        for obj in (old_client, old_parcel, old_parcel.events.get()):
            DemoSeedRecord.objects.create(
                seed_run=old_seed, model_label=obj._meta.label, object_pk=str(obj.pk)
            )
        genuine = self.invoice(self.business)
        for execute in (False, True):
            with self.assertRaisesMessage(CommandError, "preview/reset"):
                self.command(execute=execute)
        self.assertIn("RESET PREVIEW ONLY", self.command(reset_demo=True))
        self.assertTrue(Parcel.objects.filter(pk=old_parcel.pk).exists())
        self.command(reset_demo=True, execute=True)
        self.assertTrue(Invoice.objects.filter(pk=genuine.pk).exists())
        self.command(execute=True)
        demo = Invoice.objects.filter(business=self.business).exclude(pk=genuine.pk)
        self.assertEqual(demo.count(), 4)
        self.assertEqual(InvoiceLine.objects.filter(invoice__in=demo).count(), 13)
        self.assertEqual(self.client.get(reverse("invoice_list")).context["invoices"].count(), 5)

    def test_shared_manual_invoice_creation_works_without_service_or_appointment(self):
        for business in (self.business, self.service):
            with self.subTest(vertical=business.vertical):
                self.switch(business)
                customer = Client.objects.create(
                    business=business, first_name="Manual", last_name="Client"
                )
                response = self.client.post(
                    reverse("invoice_create"),
                    {
                        "client_id": customer.pk,
                        "description": "Freight or agreed work",
                        "quantity": "2",
                        "unit_price": "45.00",
                    },
                )
                self.assertEqual(response.status_code, 302)
                invoice = Invoice.objects.get(business=business)
                self.assertEqual(invoice.client, customer)
                self.assertIsNone(invoice.appointment_id)
                self.assertEqual(invoice.subtotal, Decimal("90.00"))
                self.assertIsNone(invoice.lines.get().service_id)
                self.assertFalse(BusinessService.objects.filter(business=business).exists())
                self.assertFalse(Appointment.objects.filter(business=business).exists())
                self.assertFalse(Lead.objects.filter(business=business).exists())

    def test_shared_invoice_roles_and_tenant_scoping_for_both_verticals(self):
        invoices = {
            business.pk: self.invoice(business) for business in (self.business, self.service)
        }
        for business in (self.business, self.service):
            own = invoices[business.pk]
            other = next(invoice for pk, invoice in invoices.items() if pk != business.pk)
            self.switch(business)
            membership = BusinessUser.objects.get(business=business, user=self.user)
            membership.role = BusinessUser.Role.VIEWER
            membership.save(update_fields=["role"])
            listing = self.client.get(reverse("invoice_list"))
            self.assertEqual(list(listing.context["invoices"]), [own])
            self.assertFalse(listing.context["role_access"]["can_manage_invoices"])
            self.assertEqual(
                self.client.get(reverse("invoice_detail", args=[own.pk])).status_code, 200
            )
            self.assertEqual(
                self.client.get(reverse("invoice_detail", args=[other.pk])).status_code, 404
            )
            self.assertRedirects(
                self.client.get(reverse("invoice_create")),
                reverse("agent_dashboard"),
                fetch_redirect_response=False,
            )
            self.assertEqual(Invoice.objects.count(), 2)
            membership.role = BusinessUser.Role.ACCOUNTANT
            membership.save(update_fields=["role"])
            self.assertEqual(self.client.get(reverse("invoice_create")).status_code, 200)

    def test_service_cannot_access_logistics_operational_routes_or_profile(self):
        self.switch(self.service)
        for name in (
            "logistics_parcel_list",
            "logistics_parcel_register",
            "logistics_shipment_list",
            "logistics_shipment_create",
        ):
            for method in (self.client.get, self.client.post):
                with self.subTest(route=name, method=method.__name__):
                    self.assertEqual(
                        method(reverse(name), HTTP_ACCEPT="application/json").status_code, 403
                    )
        with self.assertRaises(ValidationError):
            LogisticsProfile.objects.create(business=self.service)
        with self.assertRaises(PermissionDenied):
            register_parcel(
                business=self.service,
                actor=self.user,
                client=self.customer,
                origin="Origin",
                destination="Destination",
                package_description="Denied",
            )
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(Shipment.objects.exists())

    def test_logistics_cannot_use_service_requests_appointments_or_booking(self):
        for name in (
            "staff_lead_list",
            "staff_lead_create",
            "appointment_list",
            "appointment_create",
            "business_booking_settings",
        ):
            for method in (self.client.get, self.client.post):
                with self.subTest(route=name, method=method.__name__):
                    self.assertEqual(
                        method(reverse(name), HTTP_ACCEPT="application/json").status_code, 403
                    )
        for method in (self.client.get, self.client.post):
            response = method(reverse("public_booking", args=[self.business.slug]))
            self.assertTemplateUsed(response, "crm/success_fail/public_booking_unavailable.html")
        self.assertFalse(Appointment.objects.exists())
        self.assertFalse(Lead.objects.exists())

    def test_client_detail_keeps_vertical_sections_and_tenants_separate(self):
        logistics_invoice = self.invoice(self.business)
        service_invoice = self.invoice(self.service)
        for business, own, other in (
            (self.business, logistics_invoice, service_invoice),
            (self.service, service_invoice, logistics_invoice),
        ):
            self.switch(business)
            response = self.client.get(reverse("staff_client_detail", args=[own.client_id]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                bool(response.context.get("logistics_client_parcels")), business == self.business
            )
            self.assertEqual(
                response.context["module_access"]["appointments"], business == self.service
            )
            self.assertEqual(
                self.client.get(reverse("staff_client_detail", args=[other.client_id])).status_code,
                404,
            )

    def test_seed_and_reset_commands_keep_service_and_logistics_runs_separate(self):
        self.command("seed_demo_data", business=self.service, execute=True)
        self.command(execute=True)
        service_seed = DemoSeedRun.objects.get(business=self.service)
        logistics_seed = DemoSeedRun.objects.get(business=self.business)
        self.assertEqual(Invoice.objects.filter(business=self.service).count(), 5)
        self.assertEqual(InvoiceLine.objects.filter(invoice__business=self.service).count(), 10)
        self.assertEqual(Invoice.objects.filter(business=self.business).count(), 4)
        self.assertFalse(Parcel.objects.filter(business=self.service).exists())
        self.assertFalse(BusinessService.objects.filter(business=self.business).exists())
        for options in ({"execute": True}, {"reset_demo": True, "execute": True}):
            with self.assertRaisesMessage(CommandError, "LOGISTICS Business"):
                self.command(business=self.service, **options)
        self.command("seed_demo_data", business=self.business, reset_demo=True, execute=True)
        self.assertTrue(DemoSeedRun.objects.filter(pk=service_seed.pk).exists())
        self.assertFalse(DemoSeedRun.objects.filter(pk=logistics_seed.pk).exists())
        self.assertEqual(Invoice.objects.filter(business=self.service).count(), 5)
        self.command(execute=True)
        self.command("seed_demo_data", business=self.service, reset_demo=True, execute=True)
        self.assertEqual(Invoice.objects.filter(business=self.business).count(), 4)
        self.assertEqual(InvoiceLine.objects.filter(invoice__business=self.business).count(), 13)
        self.assertTrue(Client.objects.filter(pk=self.customer.pk).exists())

    def test_forged_cross_vertical_invoice_ownership_aborts_reset(self):
        self.command("seed_demo_data", business=self.service, execute=True)
        self.command(execute=True)
        service_invoice = Invoice.objects.filter(business=self.service).first()
        seed = DemoSeedRun.objects.get(business=self.business)
        DemoSeedRecord.objects.create(
            seed_run=seed, model_label=Invoice._meta.label, object_pk=str(service_invoice.pk)
        )
        before = {
            model: model.objects.count()
            for model in (Invoice, InvoiceLine, Parcel, ParcelEvent, DemoSeedRecord)
        }
        for execute in (False, True):
            with self.assertRaisesMessage(CommandError, "does not belong"):
                self.command(reset_demo=True, execute=execute)
            self.assertEqual(before, {model: model.objects.count() for model in before})
