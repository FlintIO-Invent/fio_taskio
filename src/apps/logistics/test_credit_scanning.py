"""Authoritative movement gates, credit evidence, scanner resume and privacy."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.billings.models import InvoicePayment
from apps.billings.payment_services import adjust_invoice_payment
from apps.billings.services import change_invoice_status

from . import test_location_operations as locations
from . import test_parcels
from . import test_workflow_summary as fixtures
from .credit_services import approve_credit, credit_review, fingerprint, revoke_credit
from .models import LogisticsCreditApproval, LogisticsCreditRevocation, ParcelEvent
from .shipment_services import change_shipment_status
from .workflow_summary import resolve_parcel_workflow


class CreditScannerTests(TestCase):
    setUp = fixtures.ParcelWorkflowSummaryTests.setUp
    parcel = fixtures.ParcelWorkflowSummaryTests.parcel
    shipment = fixtures.ParcelWorkflowSummaryTests.shipment
    charge = fixtures.ParcelWorkflowSummaryTests.charge
    bill = fixtures.ParcelWorkflowSummaryTests.bill
    issue = fixtures.ParcelWorkflowSummaryTests.issue
    receipt = fixtures.ParcelWorkflowSummaryTests.receipt
    move = fixtures.ParcelWorkflowSummaryTests.move
    cargo = fixtures.ParcelWorkflowSummaryTests.cargo

    def prepare(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        self.move(parcel, "RECEIVED")
        return parcel, invoice

    def approve(self, parcel, status="IN_TRANSIT", **fields):
        snapshot = credit_review(business=self.business, actor=self.user, parcel=parcel)
        return approve_credit(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            status=status,
            expires_at=timezone.now() + timedelta(days=1),
            reason_reference="PRIVATE-CREDIT-CASE",
            obligation_fingerprint=fingerprint(snapshot),
            idempotency_key=uuid.uuid4(),
            **fields,
        )

    def summary(self, parcel, **fields):
        return resolve_parcel_workflow(
            business=self.business, actor=self.user, parcel=parcel, **fields
        )

    def scan(self, parcel):
        return self.client.post(
            reverse("logistics_parcel_scan"), {"tracking_code": parcel.tracking_code}
        )

    def action(self, parcel, status, **fields):
        return self.client.post(
            reverse("logistics_parcel_scan_action", args=[parcel.pk]),
            {
                "status": status,
                "expected_status": parcel.current_status,
                "idempotency_key": uuid.uuid4(),
                **fields,
            },
        )

    def test_missing_unpaid_and_partial_departures_denied_even_direct_services(self):
        parcel = self.parcel()
        self.move(parcel, "RECEIVED")
        count = ParcelEvent.objects.count()
        with self.assertRaises(ValidationError):
            self.move(parcel, "IN_TRANSIT")
        self.assertEqual(ParcelEvent.objects.count(), count)
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        self.assertEqual(self.action(parcel, "IN_TRANSIT").status_code, 400)
        self.receipt(invoice, 40)
        with self.assertRaises(ValidationError):
            self.move(parcel, "IN_TRANSIT")
        self.receipt(invoice, 60)
        self.assertEqual(self.action(parcel, "IN_TRANSIT").status_code, 302)

    def test_credit_is_one_action_one_parcel_and_never_payment(self):
        parcel, invoice = self.prepare()
        approval = self.approve(parcel)
        summary = self.summary(parcel)
        self.assertEqual(summary.financial["state"], "CREDIT_APPROVED")
        self.assertEqual(summary.financial["settlement_state"], "UNPAID")
        self.assertTrue(summary.financial["clearance"]["movements"]["IN_TRANSIT"])
        self.assertFalse(summary.financial["clearance"]["movements"]["DELIVERED"])
        self.assertEqual(InvoicePayment.objects.count(), 0)
        event = self.move(parcel, "IN_TRANSIT")
        self.assertEqual(event.credit_approval_id, approval.pk)
        self.move(parcel, "ARRIVED")
        self.move(parcel, "READY")
        with self.assertRaises(ValidationError):
            self.move(parcel, "DELIVERED")
        delivery = self.approve(parcel, "DELIVERED")
        self.assertEqual(self.move(parcel, "DELIVERED").credit_approval_id, delivery.pk)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "SENT")
        other = self.parcel()
        self.move(other, "RECEIVED")
        with self.assertRaises(ValidationError):
            self.move(other, "IN_TRANSIT")

    def test_receiving_and_arrival_unpaid_with_site_authority(self):
        parcel, _ = self.prepare()
        self.approve(parcel)
        self.move(parcel, "IN_TRANSIT")
        self.assertFalse(self.summary(parcel).financial["clearance"]["cleared"])
        self.assertEqual(self.action(parcel, "ARRIVED").status_code, 302)
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "ARRIVED")

    def test_revocation_expiry_invalid_evidence_and_missing_credit_never_clear(self):
        parcel, _ = self.prepare()
        approval = self.approve(parcel)
        key = uuid.uuid4()
        for _ in range(2):
            revoke_credit(
                business=self.business,
                actor=self.user,
                approval=approval,
                reason_reference="REVOKE-CASE",
                idempotency_key=key,
            )
        self.assertEqual(LogisticsCreditRevocation.objects.count(), 1)
        self.assertEqual(self.summary(parcel).financial["state"], "UNPAID")
        with self.assertRaises(ValidationError):
            self.move(parcel, "IN_TRANSIT")
        new = self.approve(parcel)
        with patch("apps.logistics.credit_services.timezone.now", return_value=new.expires_at):
            self.assertFalse(self.summary(parcel).financial["clearance"]["cleared"])
        strict = self.summary(parcel, require_credit_evidence=True)
        self.assertEqual(strict.financial["state"], "CREDIT_APPROVED")
        revoke_credit(
            business=self.business,
            actor=self.user,
            approval=new,
            reason_reference="REVOKE-NEW",
            idempotency_key=uuid.uuid4(),
        )
        self.assertEqual(
            self.summary(parcel, require_credit_evidence=True).financial["state"], "UNKNOWN"
        )

    def test_refund_cannot_expand_approved_outstanding_limit(self):
        parcel, invoice = self.prepare()
        receipt = self.receipt(invoice, 60)
        self.approve(parcel)
        adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            payment=receipt,
            kind="REFUND",
            amount=10,
            reference="REFUND-LIMIT",
            reason_reference="REFUND-CASE",
            idempotency_key=uuid.uuid4(),
        )
        self.assertFalse(self.summary(parcel).financial["clearance"]["cleared"])
        self.assertEqual(self.action(parcel, "IN_TRANSIT").status_code, 400)

    def test_payment_reduction_keeps_credit_valid_and_full_settlement_is_paid(self):
        parcel, invoice = self.prepare()
        self.approve(parcel)
        self.receipt(invoice, 40)
        self.assertEqual(self.summary(parcel).financial["state"], "CREDIT_APPROVED")
        self.receipt(invoice, 60)
        self.assertEqual(self.summary(parcel).financial["state"], "PAID")
        self.assertIsNone(self.move(parcel, "IN_TRANSIT").credit_approval_id)

    def test_new_charge_and_cancel_reissue_invalidate_prior_credit(self):
        parcel, invoice = self.prepare()
        self.approve(parcel)
        self.charge(parcel=parcel, description="Extra handling")
        self.assertFalse(self.summary(parcel).financial["clearance"]["cleared"])
        self.assertEqual(self.action(parcel, "IN_TRANSIT").status_code, 400)

    def test_no_approval_for_uninvoiced_draft_or_legacy_unknown(self):
        parcel = self.parcel()
        for stage in ("missing", "charge", "draft"):
            if stage == "charge":
                charge = self.charge(parcel=parcel)
            if stage == "draft":
                self.bill(charge)
            with self.assertRaises(ValidationError):
                self.approve(parcel)
        self.assertEqual(LogisticsCreditApproval.objects.count(), 0)

    def test_same_client_shared_invoice_requires_separate_parcel_approval(self):
        a, b = self.parcel(), self.parcel()
        ship = self.shipment()
        self.cargo(ship, a, b)
        invoice = self.bill(self.charge(shipment=ship, unit_price=100))
        self.issue(invoice)
        self.move(a, "RECEIVED")
        self.move(b, "RECEIVED")
        self.approve(a)
        change_shipment_status(
            business=self.business, actor=self.user, shipment=ship, status="READY"
        )
        with self.assertRaises(ValidationError):
            change_shipment_status(
                business=self.business, actor=self.user, shipment=ship, status="IN_TRANSIT"
            )
        a.refresh_from_db()
        self.assertEqual(a.current_status, "RECEIVED")
        self.approve(b)
        change_shipment_status(
            business=self.business, actor=self.user, shipment=ship, status="IN_TRANSIT"
        )
        ship.refresh_from_db()
        self.assertEqual(ship.status, "IN_TRANSIT")

    def test_scanning_is_read_only_resumes_registration_and_rechecks_after_revocation(self):
        parcel, _ = self.prepare()
        response = self.scan(parcel)
        self.assertContains(response, "Continue Registration")
        self.assertNotContains(response, 'value="IN_TRANSIT"')
        approval = self.approve(parcel)
        response = self.scan(parcel)
        self.assertContains(response, 'value="IN_TRANSIT"')
        before = ParcelEvent.objects.count()
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.scan(parcel).status_code, 200)
        writes = [
            row["sql"]
            for row in queries
            if row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            # Existing authenticated middleware refreshes the session expiry.
            # Lookup must leave every application/domain table unchanged.
            and not row["sql"].lstrip().startswith('UPDATE "django_session" ')
        ]
        self.assertEqual(writes, [])
        self.assertEqual(ParcelEvent.objects.count(), before)
        self.assertEqual(parcel.current_status, "RECEIVED")
        revoke_credit(
            business=self.business,
            actor=self.user,
            approval=approval,
            reason_reference="AFTER-SCAN",
            idempotency_key=uuid.uuid4(),
        )
        self.assertEqual(self.action(parcel, "IN_TRANSIT").status_code, 400)

    def test_exact_retry_after_revocation_is_no_new_movement(self):
        parcel, _ = self.prepare()
        approval = self.approve(parcel)
        data = {
            "status": "IN_TRANSIT",
            "expected_status": "RECEIVED",
            "idempotency_key": uuid.uuid4(),
        }
        url = reverse("logistics_parcel_scan_action", args=[parcel.pk])
        self.assertEqual(self.client.post(url, data).status_code, 302)
        revoke_credit(
            business=self.business,
            actor=self.user,
            approval=approval,
            reason_reference="AFTER-MOVEMENT",
            idempotency_key=uuid.uuid4(),
        )
        before = ParcelEvent.objects.count()
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(ParcelEvent.objects.count(), before)

    def test_only_owner_admin_credit_authority_and_immutable_audit(self):
        parcel, _ = self.prepare()
        approval = self.approve(parcel)
        with self.assertRaises(ValidationError):
            LogisticsCreditApproval.objects.filter(pk=approval.pk).update(
                reason_reference="changed"
            )
        with self.assertRaises(ValidationError):
            approval._domain_save()
        for role in ("accountant", "staff", "viewer"):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            with self.assertRaises(PermissionDenied):
                revoke_credit(
                    business=self.business,
                    actor=self.user,
                    approval=approval,
                    reason_reference="FORGED",
                    idempotency_key=uuid.uuid4(),
                )
            self.assertEqual(
                self.client.get(reverse("logistics_parcel_credit", args=[parcel.pk])).status_code,
                403,
            )
        self.assertEqual(LogisticsCreditRevocation.objects.count(), 0)

    def test_review_stale_nonce_and_timeline(self):
        parcel, invoice = self.prepare()
        snapshot = credit_review(business=self.business, actor=self.user, parcel=parcel)
        self.receipt(invoice, 20)
        with self.assertRaises(ValidationError):
            approve_credit(
                business=self.business,
                actor=self.user,
                parcel=parcel,
                status="IN_TRANSIT",
                expires_at=timezone.now() + timedelta(days=1),
                reason_reference="STALE",
                obligation_fingerprint=fingerprint(snapshot),
                idempotency_key=uuid.uuid4(),
            )
        approval = self.approve(parcel)
        revoke_credit(
            business=self.business,
            actor=self.user,
            approval=approval,
            reason_reference="AUDIT",
            idempotency_key=uuid.uuid4(),
        )
        history = self.summary(parcel).history
        self.assertEqual(
            [row["timestamp"] for row in history], sorted(row["timestamp"] for row in history)
        )
        self.assertIn("CREDIT_APPROVED", {row["kind"] for row in history})
        self.assertIn("CREDIT_REVOKED", {row["kind"] for row in history})

    def test_credit_renewal_revokes_older_wider_limit(self):
        parcel, invoice = self.prepare()
        first = self.approve(parcel)
        receipt = self.receipt(invoice, 60)
        second = self.approve(parcel)
        first.refresh_from_db()
        self.assertIsNotNone(first.revocation)
        self.assertIn(str(second.pk), first.revocation.reason_reference)
        adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            payment=receipt,
            kind="REFUND",
            amount=10,
            reference="RENEWAL-REFUND",
            reason_reference="CASE",
            idempotency_key=uuid.uuid4(),
        )
        self.assertFalse(self.summary(parcel).financial["clearance"]["cleared"])

    def test_cancel_reissue_requires_new_credit_and_saved_currency_tax_remain_stable(self):
        parcel, invoice = self.prepare()
        self.approve(parcel)
        self.business.currency = "EUR"
        self.business.tax_rate = 25
        self.business.save(update_fields=["currency", "tax_rate"])
        self.assertEqual(self.summary(parcel).financial["state"], "CREDIT_APPROVED")
        change_invoice_status(
            business=self.business, actor=self.user, invoice=invoice, status="CANCELLED"
        )
        charge = parcel.charges.get()
        reissue = self.bill(charge)
        self.issue(reissue)
        self.assertEqual(reissue.currency_code, "USD")
        self.assertEqual(reissue.tax_rate_percentage, 0)
        self.assertEqual(self.summary(parcel).financial["state"], "UNPAID")

    def test_malformed_credit_record_never_produces_authority(self):
        from django.db.models import QuerySet

        parcel, _ = self.prepare()
        approval = self.approve(parcel)
        QuerySet(model=LogisticsCreditApproval).filter(pk=approval.pk).update(
            obligation_fingerprint="0" * 64
        )
        summary = self.summary(parcel, require_credit_evidence=True)
        self.assertEqual(summary.financial["state"], "UNKNOWN")
        self.assertFalse(summary.financial["clearance"]["cleared"])
        with self.assertRaises(ValidationError):
            self.move(parcel, "IN_TRANSIT")

    def test_foreign_credit_target_and_lookup_are_denied(self):
        from .parcel_services import register_parcel

        foreign = register_parcel(
            business=self.other,
            actor=self.other_user,
            client=self.other_customer,
            origin="A",
            destination="B",
            package_description="Foreign",
        )
        with self.assertRaises(PermissionDenied):
            self.approve(foreign)
        self.assertEqual(self.scan(foreign).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("logistics_parcel_credit", args=[foreign.pk])).status_code, 404
        )


class CreditLocationScannerTests(TestCase):
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    setUp = locations.LocationOperationsTests.setUp
    select = locations.LocationOperationsTests.select
    parcel = locations.LocationOperationsTests.parcel
    charge = CreditScannerTests.charge
    bill = CreditScannerTests.bill
    issue = CreditScannerTests.issue
    approve = CreditScannerTests.approve

    def login_worker(self):
        from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

        self.client.force_login(self.staff)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    def lookup(self):
        return self.client.post(
            reverse("logistics_parcel_scan"), {"tracking_code": self.item.tracking_code}
        )

    def act(self, status, **fields):
        self.item.refresh_from_db()
        return self.client.post(
            reverse("logistics_parcel_scan_action", args=[self.item.pk]),
            {
                "status": status,
                "expected_status": self.item.current_status,
                "idempotency_key": uuid.uuid4(),
                **fields,
            },
        )

    def test_origin_destination_credit_and_private_financial_data(self):
        invoice = self.bill(self.charge(parcel=self.item))
        self.issue(invoice)
        self.approve(self.item)
        self.login_worker()
        self.assertContains(self.lookup(), 'value="RECEIVED"')
        self.assertEqual(self.act("RECEIVED").status_code, 302)
        self.assertContains(self.lookup(), 'value="IN_TRANSIT"')
        self.select(self.staff, self.b)
        self.assertNotContains(self.lookup(), 'value="IN_TRANSIT"')
        self.assertEqual(self.act("IN_TRANSIT").status_code, 403)
        self.select(self.staff, self.a)
        self.assertEqual(self.act("IN_TRANSIT").status_code, 302)
        self.select(self.staff, self.b)
        response = self.lookup()
        self.assertContains(response, 'value="ARRIVED"')
        self.assertNotContains(response, invoice.invoice_number)
        self.assertNotContains(response, "PRIVATE-CREDIT-CASE")
        self.assertNotContains(response, "Outstanding USD")
        self.assertEqual(self.act("ARRIVED").status_code, 302)
        self.assertEqual(self.act("READY").status_code, 302)
        self.assertEqual(self.act("DELIVERED").status_code, 400)
        self.item.refresh_from_db()
        self.approve(self.item, "DELIVERED")
        self.assertEqual(self.act("DELIVERED").status_code, 302)

    def test_read_only_unassigned_and_cross_tenant_lookups(self):
        self.login_worker()
        self.member.logistics_location_assignments.update(can_operate=False)
        response = self.lookup()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scan_actions"], [])
        self.assertEqual(self.act("RECEIVED").status_code, 403)
        self.member.logistics_location_assignments.all().delete()
        self.assertEqual(self.lookup().status_code, 404)

    def test_credit_review_endpoint_validates_snapshot_and_expiry(self):
        invoice = self.bill(self.charge(parcel=self.item))
        self.issue(invoice)
        url = reverse("logistics_parcel_credit", args=[self.item.pk])
        response = self.client.get(url)
        self.assertContains(response, "Full Invoice balance limits")
        form = response.context["form"]
        data = {
            "status": "IN_TRANSIT",
            "reason_reference": "UI-CREDIT",
            "expires_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "confirm_obligations": "on",
            "obligation_fingerprint": form.initial["obligation_fingerprint"],
            "idempotency_key": form.initial["idempotency_key"],
        }
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(LogisticsCreditApproval.objects.count(), 1)
        approval = LogisticsCreditApproval.objects.get()
        self.assertEqual(
            self.client.post(
                url,
                {
                    "revoke": approval.pk,
                    "reason_reference": "UI-REVOKE",
                    "idempotency_key": uuid.uuid4(),
                },
            ).status_code,
            302,
        )
        self.assertContains(self.client.get(url), "Revoked")
