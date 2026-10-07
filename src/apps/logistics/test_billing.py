import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.billings.models import Invoice, InvoiceLine
from apps.billings.pdf import render_invoice_pdf_html
from apps.businesses.business_data_inventory import build_business_data_inventory
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.forms import BusinessServiceForm
from apps.crm.models import BusinessService, Client, ImportJob

from . import test_shipments as fixtures
from .billing_forms import ChargeInvoiceForm, LogisticsChargeForm
from .billing_services import add_charge, invoice_charges
from .models import LogisticsCharge
from .parcel_services import edit_parcel, register_parcel
from .shipment_services import assign_parcel


class LogisticsBillingTests(TestCase):
    setUp = fixtures.ShipmentTests.setUp
    parcel = fixtures.ShipmentTests.parcel
    shipment = fixtures.ShipmentTests.shipment

    def saved_service(self, business=None, **fields):
        return BusinessService.objects.create(
            business=business or self.business,
            name="Medium Parcel Delivery",
            unit_price=Decimal("25.00"),
            **fields,
        )

    def charge(self, **fields):
        parcel = fields.pop("parcel", None)
        if parcel is None:
            parcel = self.parcel()
        return add_charge(
            business=self.business,
            actor=self.user,
            **{
                "parcel": parcel,
                "description": "Special handling",
                "unit_price": Decimal("37.50"),
                "idempotency_key": uuid.uuid4(),
                **fields,
            },
        )

    def bill(self, *charges, **fields):
        return invoice_charges(
            business=self.business,
            actor=self.user,
            charge_ids=[charge.pk for charge in charges],
            **fields,
        )

    def test_logistics_services_use_existing_management_and_hide_booking_fields(self):
        response = self.client.post(
            reverse("business_service_create"),
            {
                "name": "Freight",
                "unit_price": "150.00",
                "is_active": "on",
                "is_bookable_online": "on",
                "default_duration_minutes": "20",
            },
        )
        self.assertEqual(response.status_code, 302)
        service = BusinessService.objects.get(business=self.business, name="Freight")
        self.assertFalse(service.is_bookable_online)
        self.assertIsNone(service.default_duration_minutes)
        response = self.client.get(reverse("business_service_list"))
        self.assertContains(response, "Freight")
        self.assertNotContains(response, "Online Booking")
        self.assertNotIn("is_bookable_online", BusinessServiceForm(business=self.business).fields)
        self.assertIn("is_bookable_online", BusinessServiceForm(business=self.service).fields)

    def test_existing_service_csv_import_supports_logistics(self):
        upload = SimpleUploadedFile(
            "services.csv", b"name,unit_price\nFreight,150.00\n", content_type="text/csv"
        )
        response = self.client.post(reverse("business_service_import"), {"csv_file": upload})
        self.assertEqual(response.status_code, 302)
        job = ImportJob.objects.get(business=self.business)
        response = self.client.post(reverse("business_service_import_execute", args=[job.pk]))
        self.assertEqual(response.status_code, 302)
        service = BusinessService.objects.get(business=self.business, name="Freight")
        self.assertEqual(service.unit_price, Decimal("150"))
        self.assertFalse(service.is_bookable_online)
        self.assertIsNone(service.default_duration_minutes)

    def test_fractional_quantity_rounds_charge_and_invoice_consistently(self):
        charge = self.charge(quantity=Decimal("0.01"), unit_price=Decimal("0.50"))
        invoice = self.bill(charge)
        self.assertEqual(charge.total, Decimal("0.01"))
        self.assertEqual(invoice.subtotal, charge.total)

    def test_amount_overflow_is_a_validation_error_before_invoice_creation(self):
        with self.assertRaises(ValidationError):
            self.charge(quantity=Decimal("99999999"), unit_price=Decimal("9999999999"))
        self.assertFalse(LogisticsCharge.objects.exists())

    def test_invoice_owner_cannot_change_after_charge_attachment(self):
        invoice = self.bill(self.charge())
        invoice.client = Client.objects.create(
            business=self.business, first_name="Other", last_name="Client"
        )
        with self.assertRaises(ValidationError):
            invoice.save()

    def test_service_price_snapshot_and_historical_reference(self):
        parcel = self.parcel(internal_reference="MM-P-00124")
        service = self.saved_service()
        charge = self.charge(parcel=parcel, service=service, description="", unit_price=None)
        service.unit_price = Decimal("30")
        service.is_active = False
        service.save()
        edit_parcel(
            business=self.business, actor=self.user, parcel=parcel, internal_reference="new-ref"
        )
        invoice = self.bill(charge)
        line = invoice.lines.get()
        self.assertEqual(line.unit_price, Decimal("25"))
        self.assertEqual(line.parcel_id, parcel.pk)
        self.assertEqual(line.service_id, service.pk)
        self.assertIn("MM-P-00124", line.description)
        self.assertIn("MM-P-00124", render_invoice_pdf_html(invoice))
        with self.assertRaises(ProtectedError):
            service.delete()

    def test_price_override_and_custom_charge(self):
        service = self.saved_service()
        parcel = self.parcel()
        standard = self.charge(parcel=parcel, service=service, description="", unit_price=None)
        override = self.charge(parcel=parcel, service=service, unit_price=Decimal("20"))
        custom = self.charge(parcel=parcel)
        invoice = self.bill(standard, override, custom)
        self.assertEqual(invoice.lines.count(), 3)
        self.assertEqual(invoice.subtotal, Decimal("82.50"))
        self.assertEqual(override.service_id, service.pk)
        self.assertIsNone(custom.service_id)
        service.refresh_from_db()
        self.assertEqual(service.unit_price, Decimal("25"))

    def test_multiple_parcels_can_share_client_draft_invoice(self):
        first, second = self.charge(), self.charge()
        invoice = self.bill(first)
        self.assertEqual(self.bill(second, invoice=invoice).pk, invoice.pk)
        invoice.refresh_from_db()
        self.assertEqual(invoice.lines.count(), 2)
        self.assertEqual(invoice.subtotal, Decimal("75"))

    def test_charge_creation_and_invoicing_are_retry_safe(self):
        parcel, key = self.parcel(), uuid.uuid4()
        charge = self.charge(parcel=parcel, idempotency_key=key)
        self.assertEqual(self.charge(parcel=parcel, idempotency_key=key).pk, charge.pk)
        with self.assertRaises(ValidationError):
            self.charge(parcel=parcel, idempotency_key=key, unit_price=Decimal("40"))
        invoice = self.bill(charge)
        self.assertEqual(self.bill(charge).pk, invoice.pk)
        self.assertEqual(Invoice.objects.count(), 1)
        another = Invoice.objects.create(
            business=self.business, client=self.customer, invoice_number="OTHER"
        )
        with self.assertRaises(ValidationError):
            self.bill(charge, invoice=another)
        self.assertEqual(InvoiceLine.objects.count(), 1)

    def test_invalid_service_and_inactive_service_fail_closed(self):
        for service in (
            self.saved_service(business=self.other),
            self.saved_service(is_active=False),
        ):
            with self.subTest(service=service.pk), self.assertRaises(ValidationError):
                self.charge(service=service)
        self.assertFalse(LogisticsCharge.objects.exists())

    def test_invoice_client_and_tenant_must_match(self):
        charge = self.charge()
        different = Client.objects.create(
            business=self.business, first_name="Different", last_name="Client"
        )
        for business, client in ((self.business, different), (self.other, self.other_customer)):
            invoice = Invoice.objects.create(
                business=business, client=client, invoice_number="WRONG"
            )
            with self.subTest(invoice=invoice.pk), self.assertRaises(ValidationError):
                self.bill(charge, invoice=invoice)
        with self.assertRaises(ValidationError):
            InvoiceLine.objects.create(
                invoice=Invoice.objects.first(),
                parcel=charge.parcel,
                description="Bad",
                unit_price=1,
            )
        self.assertFalse(InvoiceLine.objects.exists())

    def test_non_draft_invoice_rejected(self):
        charge = self.charge()
        invoice = Invoice.objects.create(
            business=self.business, client=self.customer, invoice_number="SENT", status="SENT"
        )
        with self.assertRaises(ValidationError):
            self.bill(charge, invoice=invoice)

    def test_tampered_charge_ids_or_targets_rejected_atomically(self):
        charge = self.charge()
        with self.assertRaises(ValidationError):
            invoice_charges(business=self.other, actor=self.other_user, charge_ids=[charge.pk])
        with self.assertRaises(ValidationError):
            invoice_charges(business=self.business, actor=self.user, charge_ids=[charge.pk, 99999])
        with self.assertRaises(ValidationError):
            add_charge(
                business=self.other,
                actor=self.other_user,
                parcel=charge.parcel,
                description="Bad",
                unit_price=1,
                idempotency_key=uuid.uuid4(),
            )
        self.assertFalse(Invoice.objects.exists())

    def test_shipment_service_and_custom_charges_are_separate_from_parcels(self):
        shipment, parcel = self.shipment(), self.parcel()
        assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=parcel)
        parcel_charge = self.charge(parcel=parcel)
        service = add_charge(
            business=self.business,
            actor=self.user,
            shipment=shipment,
            service=self.saved_service(),
            idempotency_key=uuid.uuid4(),
        )
        custom = add_charge(
            business=self.business,
            actor=self.user,
            shipment=shipment,
            description="Port handling",
            unit_price=Decimal("12"),
            idempotency_key=uuid.uuid4(),
        )
        invoice = self.bill(service, custom)
        self.assertEqual(invoice.subtotal, Decimal("37"))
        self.assertTrue(
            all(
                line.shipment_id == shipment.pk and not line.parcel_id
                for line in invoice.lines.all()
            )
        )
        parcel_charge.refresh_from_db()
        self.assertIsNone(parcel_charge.invoice_line_id)

    def test_empty_and_mixed_client_shipments_reject_billing(self):
        shipment = self.shipment()
        with self.assertRaises(ValidationError):
            add_charge(
                business=self.business,
                actor=self.user,
                shipment=shipment,
                description="Freight",
                unit_price=150,
                idempotency_key=uuid.uuid4(),
            )
        for customer in (
            self.customer,
            Client.objects.create(business=self.business, first_name="Other", last_name="Client"),
        ):
            parcel = register_parcel(
                business=self.business,
                client=customer,
                actor=self.user,
                origin="A",
                destination="B",
                package_description="Box",
            )
            assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=parcel)
        with self.assertRaises(ValidationError):
            add_charge(
                business=self.business,
                actor=self.user,
                shipment=shipment,
                description="Freight",
                unit_price=150,
                idempotency_key=uuid.uuid4(),
            )

    def test_saved_shipment_charge_protects_client_relationship(self):
        shipment, parcel = self.shipment(), self.parcel()
        assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=parcel)
        add_charge(
            business=self.business,
            actor=self.user,
            shipment=shipment,
            description="Freight",
            unit_price=150,
            idempotency_key=uuid.uuid4(),
        )
        other = Client.objects.create(
            business=self.business, first_name="Other", last_name="Client"
        )
        parcel = register_parcel(
            business=self.business,
            client=other,
            actor=self.user,
            origin="A",
            destination="B",
            package_description="Box",
        )
        with self.assertRaises(ValidationError):
            assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=parcel)

    def test_permissions_reuse_billing_roles_and_subscription(self):
        parcel = self.parcel()
        for role in ("staff", "accountant"):
            self.membership.role = role
            self.membership.save()
            self.charge(parcel=parcel)
        self.membership.role = "viewer"
        self.membership.save()
        with self.assertRaises(PermissionDenied):
            self.charge(parcel=parcel)
        self.membership.role = "owner"
        self.membership.save()
        subscription = self.business.subscription
        subscription.status = "cancelled"
        subscription.save()
        with self.assertRaises(PermissionDenied):
            self.charge(parcel=parcel)

    def test_financial_history_cannot_be_detached_or_edited(self):
        charge = self.charge()
        invoice = self.bill(charge)
        detail = self.client.get(reverse("invoice_detail", args=[invoice.pk]))
        self.assertNotContains(detail, f'href="{reverse("invoice_edit", args=[invoice.pk])}"')
        self.assertNotContains(detail, f'action="{reverse("invoice_delete", args=[invoice.pk])}"')
        self.assertContains(
            detail, f'href="{reverse("logistics_parcel_detail", args=[charge.parcel_id])}"'
        )
        line = invoice.lines.get()
        line.unit_price = Decimal("1")
        with self.assertRaises(ValidationError):
            line.save()
        with self.assertRaises(ProtectedError):
            invoice.delete()
        self.assertRedirects(
            self.client.post(reverse("invoice_delete", args=[invoice.pk])),
            reverse("invoice_detail", args=[invoice.pk]),
        )
        self.assertRedirects(
            self.client.post(reverse("invoice_edit", args=[invoice.pk]), {}),
            reverse("invoice_detail", args=[invoice.pk]),
        )
        with self.assertRaises(ValidationError):
            LogisticsCharge.objects.filter(pk=charge.pk).update(invoice_line=None)

    def test_forms_filter_drafts_services_and_validate_custom_money(self):
        parcel, service = self.parcel(), self.saved_service()
        self.saved_service(business=self.other)
        self.assertEqual(
            list(LogisticsChargeForm(business=self.business).fields["service"].queryset), [service]
        )
        for value in ("-1", "NaN", "Infinity", "1.234"):
            form = LogisticsChargeForm(
                {
                    "charge_type": "custom",
                    "description": "One off",
                    "quantity": 1,
                    "unit_price": value,
                    "idempotency_key": str(uuid.uuid4()),
                },
                business=self.business,
            )
            self.assertFalse(form.is_valid(), value)
        invoice = self.bill(self.charge(parcel=parcel))
        Invoice.objects.create(
            business=self.other, client=self.other_customer, invoice_number="OTHER"
        )
        Invoice.objects.create(
            business=self.business, client=self.customer, invoice_number="SENT", status="SENT"
        )
        self.assertEqual(
            list(
                ChargeInvoiceForm(business=self.business, target=parcel, client=self.customer)
                .fields["invoice"]
                .queryset
            ),
            [invoice],
        )

    def test_detail_and_charge_workflow_use_existing_invoice_pages(self):
        parcel = self.parcel()
        route = reverse("logistics_parcel_charge", args=[parcel.pk])
        self.assertContains(self.client.get(route), "Existing service")
        response = self.client.post(
            route,
            {
                "charge_type": "custom",
                "description": "Handling",
                "quantity": 2,
                "unit_price": "12.50",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, 302)
        charge = LogisticsCharge.objects.get(parcel=parcel)
        self.assertContains(
            self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk])), "Not invoiced"
        )
        response = self.client.post(
            reverse("logistics_parcel_invoice", args=[parcel.pk]), {"charges": [charge.pk]}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Invoice.objects.get().subtotal, Decimal("25"))
        self.assertContains(
            self.client.get(reverse("invoice_detail", args=[Invoice.objects.get().pk])), "Handling"
        )

    def test_other_workspace_routes_and_form_charge_ids_are_blocked(self):
        parcel = self.parcel()
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.other.pk
        session.save()
        self.client.force_login(self.other_user)
        self.assertEqual(
            self.client.get(reverse("logistics_parcel_charge", args=[parcel.pk])).status_code, 404
        )

    def test_inventory_registers_charges_without_integrity_blockers(self):
        charge = self.charge()
        self.bill(charge)
        inventory = build_business_data_inventory(business=self.business)
        self.assertEqual(inventory.summary.cross_tenant_integrity_blocker_count, 0)
        self.assertEqual(
            next(
                record.total_count
                for record in inventory.records
                if record.key == "logistics_charges"
            ),
            1,
        )
