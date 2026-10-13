"""Invoice clearance uses complete persisted Parcel/site authorization."""

import uuid
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.billings.models import Invoice, InvoiceLine
from apps.billings.pdf import render_invoice_pdf, render_invoice_pdf_html
from apps.billings.services import (
    change_invoice_status,
    create_invoice_for_client,
    recalculate_invoice_totals,
)
from apps.businesses.models import BusinessUser
from apps.crm.models import Client
from apps.notifications.emails import send_invoice_email

from . import test_location_access, test_parcels
from .billing_forms import ChargeInvoiceForm
from .billing_services import add_charge, invoice_charges
from .financial_access import scope_invoices
from .location_access_services import select_work_location, set_location_assignment
from .models import LogisticsCharge, LogisticsLocationAssignment, LogisticsProfile


class LogisticsFinancialAccessTests(TestCase):
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    parcel = test_location_access.LocationAccessTests.parcel
    shipment = test_location_access.LocationAccessTests.shipment
    grant = test_location_access.LocationAccessTests.grant
    login_worker = test_location_access.LocationAccessTests.login_worker

    def setUp(self):
        test_location_access.LocationAccessTests.setUp(self)
        self.ia = self.bill(self.charge(self.pa))
        self.ic = self.bill(self.charge(self.pc))
        self.mixed = self.bill(self.charge(self.pa), self.charge(self.pc))
        self.manual = create_invoice_for_client(actor=self.user, client=self.customer)
        InvoiceLine.objects.create(
            invoice=self.manual, description="Unrelated accounting", quantity=1, unit_price=1000
        )
        recalculate_invoice_totals(self.manual, actor=self.user)
        self.login_worker()

    def charge(self, parcel, actor=None, **fields):
        return add_charge(
            business=self.business,
            actor=actor or self.user,
            parcel=parcel,
            description="Handling",
            unit_price=25,
            idempotency_key=uuid.uuid4(),
            occurrence_reference=uuid.uuid4().hex,
            **fields,
        )

    def bill(self, *charges, actor=None, invoice=None):
        return invoice_charges(
            business=self.business,
            actor=actor or self.user,
            charge_ids=[charge.pk for charge in charges],
            invoice=invoice,
        )

    def status(self, invoice, status="SENT"):
        return self.client.post(
            reverse("invoice_change_status", args=[invoice.pk]), {"status": status}
        )

    def test_staff_invoice_list_detail_pdf_and_dashboard_only_include_complete_accessible_invoices(
        self,
    ):
        response = self.client.get(reverse("invoice_list"))
        self.assertEqual(list(response.context["invoices"]), [self.ia])
        self.assertFalse(response.context["role_access"]["can_manage_invoices"])
        self.assertContains(
            self.client.get(reverse("invoice_detail", args=[self.ia.pk])), "Mark as Sent"
        )
        self.assertEqual(
            self.client.get(reverse("invoice_pdf_download", args=[self.ia.pk])).status_code, 200
        )
        for invoice in (self.ic, self.mixed, self.manual):
            for name in ("invoice_detail", "invoice_pdf_download"):
                with self.subTest(invoice=invoice.pk, route=name):
                    self.assertEqual(
                        self.client.get(reverse(name, args=[invoice.pk])).status_code, 404
                    )
        dashboard = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(dashboard.context["draft_invoice_total"], self.ia.total)
        parcel = self.client.get(reverse("logistics_parcel_detail", args=[self.pa.pk]))
        self.assertNotContains(parcel, self.mixed.invoice_number)
        self.assertContains(parcel, "Financial details restricted")

    def test_normal_ui_issues_protected_draft_without_modifying_lines(self):
        before = list(self.ia.lines.values())
        detail = self.client.get(reverse("invoice_detail", args=[self.ia.pk]))
        self.assertContains(detail, "Mark as Sent")
        self.assertNotContains(detail, "Edit Invoice")
        self.assertNotContains(detail, "Cancel Invoice")
        self.assertNotContains(
            detail, 'action="' + reverse("invoice_email_send", args=[self.ia.pk]) + '"'
        )
        self.assertEqual(self.status(self.ia).status_code, 302)
        self.ia.refresh_from_db()
        self.assertEqual(self.ia.status, Invoice.Status.SENT)
        self.assertContains(
            self.client.get(reverse("invoice_detail", args=[self.ia.pk])), "Mark as Paid"
        )
        self.assertEqual(self.status(self.ia, "PAID").status_code, 302)
        self.ia.refresh_from_db()
        self.assertEqual(self.ia.status, Invoice.Status.PAID)
        self.assertEqual(list(self.ia.lines.values()), before)

    def test_cross_location_status_and_direct_calls_fail_without_changes(self):
        for invoice in (self.ic, self.mixed, self.manual):
            self.assertEqual(self.status(invoice).status_code, 403)
            with self.assertRaises(PermissionDenied):
                change_invoice_status(
                    business=self.business, actor=self.staff, invoice=invoice, status="SENT"
                )
            with self.assertRaises(PermissionDenied):
                recalculate_invoice_totals(invoice, actor=self.staff)
            invoice.refresh_from_db()
            self.assertEqual(invoice.status, Invoice.Status.DRAFT)
        with self.assertRaises(PermissionDenied):
            self.charge(self.pc, actor=self.staff)
        self.assertEqual(
            self.client.get(reverse("logistics_parcel_charge", args=[self.pc.pk])).status_code, 404
        )

    def test_staff_can_generate_and_append_only_at_writable_active_site(self):
        first = self.charge(self.pa, actor=self.staff)
        invoice = self.bill(first, actor=self.staff)
        second = self.charge(self.pa, actor=self.staff)
        self.bill(second, actor=self.staff, invoice=invoice)
        self.assertEqual(invoice.lines.count(), 2)
        self.grant(self.c)
        self.assertTrue(
            scope_invoices(
                Invoice.objects.filter(pk=self.ic.pk), business=self.business, actor=self.staff
            ).exists()
        )
        with self.assertRaises(PermissionDenied):
            self.charge(self.pc, actor=self.staff)
        self.assertEqual(self.status(self.ic).status_code, 403)
        select_work_location(business=self.business, actor=self.staff, location=self.c)
        self.charge(self.pc, actor=self.staff)
        self.assertEqual(self.status(self.ic).status_code, 302)
        self.assertEqual(self.status(self.ia).status_code, 403)

    def test_append_and_exact_replay_check_whole_invoice_not_only_selected_charge(self):
        pending = self.charge(self.pa)
        before = (self.mixed.lines.count(), self.mixed.total)
        with self.assertRaises(PermissionDenied):
            self.bill(pending, actor=self.staff, invoice=self.mixed)
        pending.refresh_from_db()
        self.assertIsNone(pending.invoice_line_id)
        self.mixed.refresh_from_db()
        self.assertEqual((self.mixed.lines.count(), self.mixed.total), before)
        linked = LogisticsCharge.objects.get(invoice_line__invoice=self.mixed, parcel=self.pa)
        with self.assertRaises(PermissionDenied):
            self.bill(linked, actor=self.staff)
        form = ChargeInvoiceForm(
            business=self.business, actor=self.staff, target=self.pa, client=self.customer
        )
        self.assertEqual(list(form.fields["invoice"].queryset), [self.ia])
        response = self.client.post(
            reverse("logistics_parcel_invoice", args=[self.pa.pk]),
            {"charges": [pending.pk], "invoice": self.mixed.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        pending.refresh_from_db()
        self.assertIsNone(pending.invoice_line_id)

    def test_read_only_grant_cannot_create_invoice_append_issue_or_replay(self):
        pending = self.charge(self.pa)
        existing = LogisticsCharge.objects.get(invoice_line__invoice=self.ia)
        self.grant(self.a, operate=False)
        self.assertEqual(
            self.client.get(reverse("invoice_detail", args=[self.ia.pk])).status_code, 200
        )
        self.assertNotContains(
            self.client.get(reverse("invoice_detail", args=[self.ia.pk])), "Mark as Sent"
        )
        with self.assertRaises(PermissionDenied):
            self.charge(self.pa, actor=self.staff)
        for charge, invoice in ((pending, None), (pending, self.ia), (existing, None)):
            with self.assertRaises(PermissionDenied):
                self.bill(charge, actor=self.staff, invoice=invoice)
        self.assertEqual(self.status(self.ia).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("logistics_parcel_charge", args=[self.pa.pk]),
                {
                    "charge_type": "custom",
                    "description": "Denied",
                    "quantity": 1,
                    "unit_price": "25",
                    "idempotency_key": uuid.uuid4(),
                },
            ).status_code,
            403,
        )

    def test_no_selected_site_prevents_financial_writes(self):
        LogisticsLocationAssignment.objects.filter(membership=self.member).update(is_current=False)
        self.assertEqual(
            self.client.get(reverse("invoice_detail", args=[self.ia.pk])).status_code, 200
        )
        with self.assertRaises(PermissionDenied):
            self.charge(self.pa, actor=self.staff)
        self.assertEqual(self.status(self.ia).status_code, 403)

    def test_unassigned_staff_and_pending_review_have_no_financial_access(self):
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=self.member,
            location=self.a,
            revoke=True,
        )
        self.assertFalse(self.client.get(reverse("invoice_list")).context["invoices"].exists())
        self.assertEqual(
            self.client.get(reverse("invoice_detail", args=[self.ia.pk])).status_code, 404
        )
        with self.assertRaises(PermissionDenied):
            self.charge(self.pa, actor=self.staff)
        self.grant(self.a)
        LogisticsProfile.objects.filter(business=self.business).update(
            location_access_reviewed_at=None
        )
        self.assertFalse(self.client.get(reverse("invoice_list")).context["invoices"].exists())
        with self.assertRaises(PermissionDenied):
            self.bill(self.charge(self.pa), actor=self.staff)

    def test_staff_cannot_use_generic_invoice_management_or_shipment_billing(self):
        for name, args in (
            ("invoice_create", []),
            ("invoice_create_from_client", [self.customer.pk]),
            ("invoice_edit", [self.ia.pk]),
        ):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
        for name, args in (
            ("invoice_quick_create_client", []),
            ("invoice_email_send", [self.ia.pk]),
            ("invoice_edit", [self.ia.pk]),
        ):
            self.assertEqual(self.client.post(reverse(name, args=args)).status_code, 403)
        self.assertEqual(self.status(self.ia, "CANCELLED").status_code, 403)
        with self.assertRaises(PermissionDenied):
            create_invoice_for_client(actor=self.staff, client=self.customer)
        with self.assertRaises(PermissionDenied):
            add_charge(
                business=self.business,
                actor=self.staff,
                shipment=self.sa,
                description="Denied",
                unit_price=25,
                idempotency_key=uuid.uuid4(),
            )
        # Operational Shipment detail stays available, with its billing panel hidden.
        self.assertEqual(
            self.client.get(reverse("logistics_shipment_detail", args=[self.sa.pk])).status_code,
            200,
        )

    def test_owner_admin_accountant_business_wide_accounting_without_location_grants(self):
        LogisticsLocationAssignment.objects.filter(membership=self.member).delete()
        for index, role in enumerate(
            (BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN, BusinessUser.Role.ACCOUNTANT)
        ):
            self.member.role = role
            self.member.save(update_fields=["role"])
            self.assertEqual(
                self.client.get(reverse("invoice_list")).context["invoices"].count(), 4 + index
            )
            self.assertEqual(
                self.client.get(reverse("invoice_detail", args=[self.ic.pk])).status_code, 200
            )
            self.assertEqual(
                self.client.get(reverse("invoice_pdf_download", args=[self.ic.pk])).status_code, 200
            )
            self.assertEqual(self.client.get(reverse("invoice_create")).status_code, 200)
            self.assertEqual(
                self.client.get(reverse("logistics_parcel_charge", args=[self.pc.pk])).status_code,
                200,
            )
            generated = self.bill(self.charge(self.pc, actor=self.staff), actor=self.staff)
            self.assertEqual(self.status(generated).status_code, 302)
            self.assertEqual(
                self.client.post(
                    reverse("invoice_edit", args=[generated.pk]), {"notes": "Tampered"}
                ).status_code,
                302,
            )
            with self.assertRaises(ProtectedError):
                generated.lines.all().delete()

    def test_protected_lines_and_invoice_survive_owner_edit_and_delete_attempts(self):
        self.client.force_login(self.user)
        line = self.ia.lines.get()
        before = list(self.ia.lines.values())
        self.assertEqual(
            self.client.post(
                reverse("invoice_edit", args=[self.ia.pk]),
                {
                    "line_id": [line.pk],
                    "description": ["Tampered"],
                    "quantity": [99],
                    "unit_price": [0],
                    "notes": "Tampered",
                },
            ).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(reverse("invoice_delete", args=[self.ia.pk])).status_code, 302
        )
        self.assertTrue(Invoice.objects.filter(pk=self.ia.pk).exists())
        self.assertEqual(list(self.ia.lines.values()), before)
        line.description = "Tampered"
        with self.assertRaises(ValidationError):
            line.save()
        with self.assertRaises(ProtectedError):
            self.ia.lines.all().delete()
        self.assertEqual(self.status(self.ia).status_code, 302)

    def test_direct_pdf_email_and_missing_actor_cannot_bypass_policy(self):
        for renderer in (render_invoice_pdf, render_invoice_pdf_html):
            with self.assertRaises(PermissionDenied):
                renderer(self.ic, actor=self.staff)
            with self.assertRaises(PermissionDenied):
                renderer(self.ia)
        with patch("apps.notifications.emails.send_templated_email") as send:
            with self.assertRaises(PermissionDenied):
                send_invoice_email(
                    self.ia, pdf_bytes=b"test", filename="test.pdf", actor=self.staff
                )
            send.assert_not_called()

    def test_service_staff_keep_generic_invoice_management_without_location_assignments(self):
        BusinessUser.objects.create(business=self.service, user=self.staff, role="staff")
        customer = Client.objects.create(
            business=self.service, first_name="Service", last_name="Customer"
        )
        invoice = create_invoice_for_client(actor=self.user, client=customer)
        InvoiceLine.objects.create(
            invoice=invoice, description="Service work", quantity=1, unit_price=50
        )
        recalculate_invoice_totals(invoice)
        self.switch(self.service)
        detail = self.client.get(reverse("invoice_detail", args=[invoice.pk]))
        self.assertContains(detail, "Edit Invoice")
        self.assertContains(detail, "Mark as Sent")
        self.assertContains(detail, "Cancel Invoice")
        self.assertTrue(detail.context["role_access"]["can_manage_invoices"])
        self.assertEqual(self.client.get(reverse("invoice_create")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("invoice_pdf_download", args=[invoice.pk])).status_code, 200
        )
        self.assertEqual(self.status(invoice).status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "SENT")

    def test_inactive_membership_location_and_user_invalidate_access(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        self.assertFalse(
            scope_invoices(Invoice.objects.all(), business=self.business, actor=self.staff).exists()
        )
        self.member.is_active = True
        self.member.save(update_fields=["is_active"])
        self.a.is_active = False
        self.a.save(update_fields=["is_active"])
        self.assertFalse(
            scope_invoices(Invoice.objects.all(), business=self.business, actor=self.staff).exists()
        )
        self.a.is_active = True
        self.a.save(update_fields=["is_active"])
        self.staff.is_active = False
        self.staff.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            self.charge(self.pa, actor=self.staff)
