"""Guided handoffs reuse authoritative records and existing service permissions."""

import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.billings.models import Invoice, InvoiceLine, InvoicePayment
from apps.businesses.models import BusinessUser
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client

from . import test_workflow_summary as fixtures
from .location_access_services import set_location_assignment
from .location_test_support import approve_test_site
from .models import LogisticsCharge, Parcel, Shipment
from .parcel_services import register_parcel


class ParcelRegistrationTests(TestCase):
    def setUp(self):
        fixtures.ParcelWorkflowSummaryTests.setUp(self)
        from .models import LogisticsLocation

        for code in ("US", "CW"):
            LogisticsLocation.objects.create(
                business=self.business,
                code=code,
                name=code,
                country_code=code,
                location_type="WAREHOUSE",
            )

    parcel = fixtures.ParcelWorkflowSummaryTests.parcel
    shipment = fixtures.ParcelWorkflowSummaryTests.shipment
    charge = fixtures.ParcelWorkflowSummaryTests.charge
    bill = fixtures.ParcelWorkflowSummaryTests.bill
    issue = fixtures.ParcelWorkflowSummaryTests.issue

    def url(self, parcel):
        return reverse("logistics_parcel_registration", args=[parcel.pk])

    def register(self, **fields):
        return self.client.post(
            reverse("logistics_parcel_register"),
            {
                "client": self.customer.pk,
                "origin": "A",
                "origin_country_code": "US",
                "destination_country_code": "CW",
                "destination": "B",
                "quantity": 1,
                "package_description": "Books",
                "sender_name": "Sender",
                "recipient_name": "Recipient",
                "weight_kg": "2.50",
                "length_cm": "10",
                "width_cm": "20",
                "height_cm": "30",
                "idempotency_key": uuid.uuid4(),
                "continue_registration": "1",
                **fields,
            },
        )

    def add(self, parcel, **fields):
        return self.client.post(
            reverse("logistics_parcel_charge", args=[parcel.pk]) + "?registration=1",
            {
                "charge_type": "custom",
                "description": "Freight",
                "quantity": "1",
                "unit_price": "100",
                "idempotency_key": uuid.uuid4(),
                **fields,
            },
        )

    def invoice(self, parcel, charges, **fields):
        return self.client.post(
            reverse("logistics_parcel_invoice", args=[parcel.pk]) + "?registration=1",
            {
                "charges": [charge.pk for charge in charges],
                "invoice": "",
                **fields,
            },
        )

    def pay(self, parcel, invoice, **fields):
        return self.client.post(
            self.url(parcel),
            {
                "action": "payment",
                "decision": "paid",
                "invoice": invoice.pk,
                "amount": "100",
                "method": "CASH",
                "reference": "CASH-001",
                "idempotency_key": uuid.uuid4(),
                **fields,
            },
        )

    def test_existing_client_complete_workflow_and_retries(self):
        key = uuid.uuid4()
        response = self.register(idempotency_key=key)
        parcel = Parcel.objects.get()
        self.assertRedirects(response, self.url(parcel))
        self.assertRedirects(self.register(idempotency_key=key), self.url(parcel))
        self.assertEqual(Parcel.objects.count(), 1)
        self.assertEqual(parcel.sender_name, "Sender")
        charge_key = uuid.uuid4()
        self.assertRedirects(self.add(parcel, idempotency_key=charge_key), self.url(parcel))
        self.assertRedirects(self.add(parcel, idempotency_key=charge_key), self.url(parcel))
        # Fresh tokens cannot duplicate the same logical charge.
        self.assertContains(self.add(parcel), "This logical charge already exists")
        self.assertEqual(LogisticsCharge.objects.count(), 1)
        charge = LogisticsCharge.objects.get()
        self.assertRedirects(self.invoice(parcel, [charge]), self.url(parcel))
        self.assertRedirects(self.invoice(parcel, [charge]), self.url(parcel))
        invoice = Invoice.objects.get()
        self.assertEqual(InvoiceLine.objects.count(), 1)
        for _ in range(2):
            self.assertRedirects(
                self.client.post(self.url(parcel), {"action": "issue", "invoice": invoice.pk}),
                self.url(parcel),
            )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "SENT")
        receipt_key = uuid.uuid4()
        for _ in range(2):
            self.assertRedirects(
                self.pay(parcel, invoice, idempotency_key=receipt_key),
                self.url(parcel) + "#registration-shipment",
            )
        self.assertEqual(InvoicePayment.objects.count(), 1)
        shipment = self.shipment(origin="A", destination="B")
        assignment = {
            "action": "assign",
            "shipment": shipment.pk,
            "expected_revision": shipment.revision,
            "idempotency_key": uuid.uuid4(),
        }
        for _ in range(2):
            self.assertRedirects(self.client.post(self.url(parcel), assignment), self.url(parcel))
        parcel.refresh_from_db()
        self.assertEqual(parcel.shipment_id, shipment.pk)
        response = self.client.get(self.url(parcel))
        self.assertContains(response, "Registration summary")
        self.assertContains(response, "Paid")
        self.assertContains(response, invoice.invoice_number)
        self.assertContains(response, shipment.reference)
        self.assertContains(response, "Preview tracking label")

    def test_inline_new_client_is_preserved_and_selected(self):
        response = self.client.post(
            reverse("staff_client_create"),
            {
                "workflow": "parcel",
                "new_client-first_name": "Inline",
                "new_client-last_name": "New",
                "new_client-email": "guided-inline@example.test",
                "new_client-phone": "1234567",
                "new_client-company_name": "Inline Company",
                "new_client-street_address": "10 Main Street",
            },
        )
        self.assertEqual(response.status_code, 201)
        customer = Client.objects.get(email="guided-inline@example.test")
        self.assertRedirects(self.register(client=customer.pk), self.url(Parcel.objects.get()))
        self.assertEqual(Parcel.objects.get().client_id, customer.pk)

    def test_resume_persisted_state_defer_and_detail_entrypoint(self):
        parcel = self.parcel()
        response = self.client.get(self.url(parcel))
        self.assertContains(response, "Needs charges")
        self.assertContains(
            self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk])),
            "Continue Registration",
        )
        charge = self.charge(parcel=parcel)
        self.assertContains(self.client.get(self.url(parcel)), "Needs Invoice")
        invoice = self.bill(charge)
        self.assertContains(self.client.get(self.url(parcel)), "Needs Invoice issuance")
        self.issue(invoice)
        self.assertContains(self.client.get(self.url(parcel)), "Needs payment")
        self.assertRedirects(
            self.client.post(self.url(parcel), {"action": "later"}), self.url(parcel) + "?summary=1"
        )
        parcel.refresh_from_db()
        self.assertIsNone(parcel.shipment_id)
        self.assertContains(self.client.get(self.url(parcel)), "Needs Shipment")
        self.assertEqual(
            (Parcel.objects.count(), LogisticsCharge.objects.count(), Invoice.objects.count()),
            (1, 1, 1),
        )

    def test_combined_invoice_and_same_client_draft_append(self):
        a, b, c = self.parcel(), self.parcel(), self.parcel()
        first, second, third = self.charge(parcel=a), self.charge(parcel=b), self.charge(parcel=c)
        self.assertRedirects(self.invoice(a, [first, second]), self.url(a))
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.lines.count(), 2)
        self.assertRedirects(self.invoice(c, [third], invoice=invoice.pk), self.url(c))
        self.assertEqual(invoice.lines.count(), 3)
        self.assertEqual(Invoice.objects.count(), 1)
        for parcel in (a, b, c):
            self.assertContains(self.client.get(self.url(parcel)), invoice.invoice_number)

    def test_guided_invoice_requires_current_parcel_and_same_client(self):
        parcel, other = self.parcel(), self.parcel()
        charge = self.charge(parcel=other)
        response = self.invoice(parcel, [charge])
        self.assertContains(response, "Include at least one charge", status_code=200)
        different = Client.objects.create(business=self.business, first_name="Different")
        different_parcel = register_parcel(
            business=self.business,
            actor=self.user,
            client=different,
            origin="A",
            destination="B",
            package_description="Books",
        )
        foreign_client_charge = self.charge(parcel=different_parcel)
        response = self.invoice(parcel, [self.charge(parcel=parcel), foreign_client_charge])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_create_shipment_preselected_atomic_and_retry(self):
        parcel = self.parcel(origin="A", destination="B")
        url = (
            reverse("logistics_shipment_create")
            + f"?parcel={parcel.pk}&registration_parcel={parcel.pk}"
        )
        response = self.client.get(url)
        self.assertEqual(response.context["form"].initial["parcel"], parcel)
        key = uuid.uuid4()
        data = {
            "origin": "A",
            "destination": "B",
            "origin_country_code": "US",
            "destination_country_code": "CW",
            "parcel": parcel.pk,
            "idempotency_key": key,
        }
        for _ in range(2):
            self.assertRedirects(self.client.post(url, data), self.url(parcel))
        parcel.refresh_from_db()
        self.assertIsNotNone(parcel.shipment_id)
        self.assertEqual(Shipment.objects.count(), 1)
        self.assertRedirects(self.client.get(url), self.url(parcel))

    def test_create_shipment_cannot_replace_preselected_parcel(self):
        parcel, other = self.parcel(), self.parcel()
        url = reverse("logistics_shipment_create") + f"?registration_parcel={parcel.pk}"
        response = self.client.post(
            url,
            {
                "origin": "A",
                "origin_country_code": "US",
                "destination_country_code": "CW",
                "destination": "B",
                "parcel": other.pk,
                "idempotency_key": uuid.uuid4(),
            },
        )
        self.assertContains(response, "Keep the registered Parcel", status_code=200)
        self.assertEqual(Shipment.objects.count(), 0)

    def test_payment_errors_retain_values_and_no_overpayment(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        response = self.pay(parcel, invoice, amount="101")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.context["payment_form"]["amount"].value()), "101")
        self.assertEqual(InvoicePayment.objects.count(), 0)
        self.assertRedirects(
            self.pay(parcel, invoice, amount="40"), self.url(parcel) + "#registration-shipment"
        )
        self.assertContains(self.client.get(self.url(parcel)), "Partial")
        self.assertRedirects(
            self.pay(parcel, invoice, amount="60", reference="CASH-002"),
            self.url(parcel) + "#registration-shipment",
        )
        self.assertContains(self.client.get(self.url(parcel)), "Paid")

    def test_unrelated_invoice_and_foreign_parcel_denied(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=self.parcel()))
        self.assertEqual(
            self.client.post(
                self.url(parcel), {"action": "issue", "invoice": invoice.pk}
            ).status_code,
            404,
        )
        foreign = register_parcel(
            business=self.other,
            actor=self.other_user,
            client=self.other_customer,
            origin="A",
            destination="B",
            package_description="Books",
        )
        self.assertEqual(self.client.get(self.url(foreign)).status_code, 404)
        self.assertEqual(self.client.post(self.url(foreign), {"action": "later"}).status_code, 404)
        for value in ("bad", "-1", "999999"):
            self.assertEqual(
                self.client.post(
                    self.url(parcel), {"action": "issue", "invoice": value}
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.get(
                    reverse("logistics_shipment_create"), {"registration_parcel": value}
                ).status_code,
                404,
            )

    def test_staff_read_only_grant_has_no_financial_writes_or_details(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        self.membership.role = BusinessUser.Role.STAFF
        self.membership.save(update_fields=["role"])
        site = approve_test_site(business=self.business, membership=self.membership, parcel=parcel)
        self.membership.logistics_location_assignments.update(can_operate=False)
        response = self.client.get(self.url(parcel))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, invoice.invoice_number)
        self.assertEqual(response.context["financial_actions"], [])
        self.assertFalse(response.context["can_assign"])
        self.assertEqual(self.add(parcel).status_code, 403)
        self.assertEqual(
            self.client.post(
                self.url(parcel),
                {"action": "payment", "decision": "paid", "invoice": invoice.pk, "amount": 25},
            ).status_code,
            404,
        )
        self.assertIsNotNone(site)

    def test_accounting_role_without_operational_scope_cannot_bypass_parcel_scope(self):
        parcel = self.parcel()
        self.membership.role = "accountant"
        self.membership.save(update_fields=["role"])
        self.assertEqual(self.client.get(self.url(parcel)).status_code, 404)

    def test_operating_staff_can_issue_and_record_payment_without_references(self):
        from apps.billings.payment_services import invoice_settlement, record_invoice_payment

        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        before = list(invoice.lines.values())
        self.membership.role = "staff"
        self.membership.save(update_fields=["role"])
        approve_test_site(business=self.business, membership=self.membership, parcel=parcel)
        response = self.client.get(self.url(parcel))
        self.assertContains(response, "Issue Invoice Parcel Invoice")
        self.assertNotContains(response, invoice.invoice_number)
        self.assertNotContains(response, "Outstanding USD")
        self.assertRedirects(
            self.client.post(self.url(parcel), {"action": "issue", "invoice": invoice.pk}),
            self.url(parcel),
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "SENT")
        self.assertEqual(list(invoice.lines.values()), before)
        response = self.client.get(self.url(parcel), {"payment": invoice.pk})
        form = response.context["payment_form"]
        self.assertFalse(form.fields["reference"].required)
        self.assertNotIn("verification_reference", form.fields)
        self.assertContains(response, 'value="ONLINE"')
        key = uuid.uuid4()
        payload = dict(amount="25", method="ONLINE", reference="", idempotency_key=key)
        self.assertRedirects(
            self.pay(parcel, invoice, **payload), self.url(parcel) + "#registration-shipment"
        )
        receipt = InvoicePayment.objects.get()
        self.assertEqual(receipt.method, "ONLINE")
        self.assertEqual(receipt.verification_reference, "")
        self.assertEqual(receipt.reference, f"RECEIPT-{str(key).upper()}")
        self.assertEqual(receipt.recorded_by, self.user)
        self.assertRedirects(
            self.pay(parcel, invoice, **payload), self.url(parcel) + "#registration-shipment"
        )
        self.assertEqual(InvoicePayment.objects.count(), 1)
        self.assertEqual(self.pay(parcel, invoice, **{**payload, "amount": "26"}).status_code, 200)
        # Older open forms still work without evidence, and save the ordinary method.
        self.assertRedirects(
            self.pay(parcel, invoice, amount="75", method="VERIFIED_ONLINE", reference=""),
            self.url(parcel) + "#registration-shipment",
        )
        balance = invoice_settlement(business=self.business, actor=self.user, invoice=invoice)
        self.assertTrue(balance.settled)
        self.assertEqual(balance.outstanding, 0)
        self.assertEqual(set(invoice.payments.values_list("method", flat=True)), {"ONLINE"})
        with self.assertRaises(ValidationError):
            record_invoice_payment(
                business=self.business,
                actor=self.user,
                invoice=invoice,
                amount="1",
                currency="USD",
                method="CASH",
                idempotency_key=uuid.uuid4(),
            )
        self.assertEqual(InvoicePayment.objects.count(), 2)

    def test_invoice_payment_page_accepts_blank_reference_for_logistics(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        response = self.client.post(
            reverse("invoice_payment_record", args=[invoice.pk]),
            {"amount": "100", "method": "ONLINE", "idempotency_key": uuid.uuid4()},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(InvoicePayment.objects.get().verification_reference, "")

    def test_cross_location_combining_and_forged_issued_invoice_are_denied(self):
        from apps.accounts.models import TaskIOUser

        from .models import LogisticsHandlingSite, LogisticsLocation

        admin = TaskIOUser.objects.create_user(email="guide-admin@example.test")
        BusinessUser.objects.create(business=self.business, user=admin, role="admin")
        a, b = self.parcel(), self.parcel()
        invoice = self.bill(self.charge(parcel=b))
        charge_a, charge_b = self.charge(parcel=a), self.charge(
            parcel=b, description="Extra service"
        )
        site = approve_test_site(business=self.business, membership=self.membership, parcel=a)
        other_site = LogisticsLocation.objects.create(
            business=self.business,
            code="OTHER-SITE",
            name="Other",
            country_code="US",
            location_type="HUB",
        )
        LogisticsHandlingSite.objects.create(
            business=self.business, parcel=b, location=other_site, kind="STOP"
        )
        self.membership.role = "staff"
        self.membership.save(update_fields=["role"])
        self.assertEqual(self.client.get(self.url(b)).status_code, 404)
        self.assertEqual(
            self.client.post(self.url(a), {"action": "issue", "invoice": invoice.pk}).status_code,
            404,
        )
        # Reading at a second assigned site still does not make it the active work site.
        set_location_assignment(
            business=self.business,
            actor=admin,
            membership=self.membership,
            location=other_site,
            can_operate=True,
        )
        response = self.invoice(a, [charge_a, charge_b])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertEqual(self.add(b).status_code, 403)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "DRAFT")
        self.assertIsNone(LogisticsCharge.objects.get(pk=charge_a.pk).invoice_line_id)
        self.assertEqual(
            self.membership.logistics_location_assignments.get(location=site).is_current, True
        )

    def test_service_workspace_and_direct_registration_unchanged(self):
        response = self.register(continue_registration="")
        parcel = Parcel.objects.get()
        self.assertRedirects(response, reverse("logistics_parcel_detail", args=[parcel.pk]))
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.service.pk
        session.save()
        self.assertEqual(self.client.get(self.url(parcel)).status_code, 302)
        self.assertEqual(self.client.post(self.url(parcel), {"action": "later"}).status_code, 302)

    def test_failed_shipment_creation_rolls_back_and_keeps_resume_state(self):
        parcel = self.parcel()
        url = reverse("logistics_shipment_create") + f"?registration_parcel={parcel.pk}"
        with patch(
            "apps.logistics.shipment_services.assign_parcel",
            side_effect=ValidationError("Test assignment failure"),
        ):
            response = self.client.post(
                url,
                {
                    "origin": "A",
                    "origin_country_code": "US",
                    "destination_country_code": "CW",
                    "destination": "B",
                    "parcel": parcel.pk,
                    "idempotency_key": uuid.uuid4(),
                },
            )
        self.assertContains(response, "Test assignment failure")
        self.assertEqual(Shipment.objects.count(), 0)
        self.assertContains(self.client.get(self.url(parcel)), "Needs Shipment")
