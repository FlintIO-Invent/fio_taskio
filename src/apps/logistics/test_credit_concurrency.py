"""Financial/credit changes versus scanner moves on real PostgreSQL transactions."""

import uuid
from unittest import skipUnless

from django.db import connection
from django.test import Client, TransactionTestCase
from django.urls import reverse

from apps.billings.payment_services import adjust_invoice_payment
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from . import test_credit_scanning as credit_fixtures
from . import test_workflow_summary_concurrency as fixtures
from .credit_services import revoke_credit
from .models import LogisticsCreditApproval, ParcelEvent
from .test_concurrency import race


@skipUnless(connection.vendor == "postgresql", "Credit/movement races require PostgreSQL")
class CreditMovementConcurrencyTests(TransactionTestCase):
    setUp = fixtures.ParcelWorkflowConcurrencyTests.setUp
    parcel = fixtures.ParcelWorkflowConcurrencyTests.parcel
    charge = fixtures.ParcelWorkflowConcurrencyTests.charge
    bill = fixtures.ParcelWorkflowConcurrencyTests.bill
    issue = fixtures.ParcelWorkflowConcurrencyTests.issue
    receipt = fixtures.ParcelWorkflowConcurrencyTests.receipt
    move = fixtures.ParcelWorkflowConcurrencyTests.move
    approve = credit_fixtures.CreditScannerTests.approve

    def scanner(self, parcel, status):
        client = Client()
        client.force_login(self.user)
        session = client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        return lambda: client.post(
            reverse("logistics_parcel_scan_action", args=[parcel.pk]),
            {
                "status": status,
                "expected_status": parcel.current_status,
                "idempotency_key": uuid.uuid4(),
            },
        ).status_code

    def test_full_payment_racing_departure_never_departs_before_its_authority(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        self.move(parcel, "RECEIVED")
        result = race([lambda: self.receipt(invoice).pk, self.scanner(parcel, "IN_TRANSIT")])
        self.assertEqual([item[0] for item in result], ["ok", "ok"])
        self.assertIn(result[1][1], (302, 400))
        departed = ParcelEvent.objects.filter(parcel=parcel, status="IN_TRANSIT").first()
        if departed:
            self.assertLessEqual(invoice.payments.get().recorded_at, departed.timestamp)

    def test_refund_racing_delivery_is_blocked_or_follows_authorized_delivery(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        receipt = self.receipt(invoice)
        for status in ("RECEIVED", "IN_TRANSIT", "ARRIVED", "READY"):
            self.move(parcel, status)
        result = race(
            [
                lambda: adjust_invoice_payment(
                    business=self.business,
                    actor=self.user,
                    invoice=invoice,
                    payment=receipt,
                    amount=10,
                    kind="REFUND",
                    reference="RACE-REFUND",
                    reason_reference="CASE",
                    idempotency_key=uuid.uuid4(),
                ).pk,
                self.scanner(parcel, "DELIVERED"),
            ]
        )
        self.assertEqual([item[0] for item in result], ["ok", "ok"])
        self.assertIn(result[1][1], (302, 400))
        delivered = ParcelEvent.objects.filter(parcel=parcel, status="DELIVERED").first()
        if delivered:
            self.assertLessEqual(
                delivered.timestamp, invoice.payments.get(kind="REFUND").recorded_at
            )

    def test_credit_revocation_racing_departure_and_exact_duplicate(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        self.move(parcel, "RECEIVED")
        approval = self.approve(parcel)
        result = race(
            [
                lambda: revoke_credit(
                    business=self.business,
                    actor=self.user,
                    approval=approval,
                    reason_reference="RACE",
                    idempotency_key=uuid.uuid4(),
                ).pk,
                self.scanner(parcel, "IN_TRANSIT"),
            ]
        )
        departed = ParcelEvent.objects.filter(parcel=parcel, status="IN_TRANSIT").first()
        if departed:
            self.assertLessEqual(departed.timestamp, approval.revocation.revoked_at)
            self.assertEqual(departed.credit_approval_id, approval.pk)
        else:
            self.assertEqual(result[1], ("ok", 400))

    def test_concurrent_credit_approval_retry_creates_one_authority(self):
        from datetime import timedelta

        from django.utils import timezone

        from .credit_services import approve_credit, credit_review, fingerprint

        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        snapshot = credit_review(business=self.business, actor=self.user, parcel=parcel)
        fields = dict(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            status="IN_TRANSIT",
            expires_at=timezone.now() + timedelta(days=1),
            reason_reference="RACE-CREDIT",
            obligation_fingerprint=fingerprint(snapshot),
            idempotency_key=uuid.uuid4(),
        )
        result = race([lambda: approve_credit(**fields).pk] * 2)
        self.assertEqual(result[0], result[1])
        self.assertEqual(LogisticsCreditApproval.objects.count(), 1)
