"""Snapshot consistency and fresh scanner clearance on real PostgreSQL transactions."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.db.models import QuerySet
from django.test import Client, TransactionTestCase
from django.urls import reverse

from apps.billings.models import InvoicePayment
from apps.billings.payment_services import adjust_invoice_payment
from apps.businesses.models import Business
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from . import test_billing_concurrency, test_financial_coverage_concurrency, test_workflow_summary
from .workflow_summary import resolve_parcel_workflow


@skipUnless(connection.vendor == "postgresql", "Workflow snapshots require PostgreSQL")
class ParcelWorkflowConcurrencyTests(TransactionTestCase):
    parcel = test_billing_concurrency.LogisticsBillingConcurrencyTests.parcel
    charge = test_financial_coverage_concurrency.FinancialCoverageConcurrencyTests.charge
    bill = test_financial_coverage_concurrency.FinancialCoverageConcurrencyTests.bill
    issue = test_workflow_summary.ParcelWorkflowSummaryTests.issue
    receipt = test_workflow_summary.ParcelWorkflowSummaryTests.receipt
    move = test_workflow_summary.ParcelWorkflowSummaryTests.move

    def setUp(self):
        test_billing_concurrency.LogisticsBillingConcurrencyTests.setUp(self)
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    def prepare(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        receipt = self.receipt(invoice)
        return parcel, invoice, receipt

    def refund(self, invoice, receipt):
        return adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            payment=receipt,
            amount=10,
            kind="REFUND",
            reference="SNAPSHOT-REFUND",
            reason_reference="CASE-SNAPSHOT",
            idempotency_key=uuid.uuid4(),
        )

    def test_read_only_snapshot_remains_consistent_when_refund_commits_before_receipt_query(self):
        parcel, invoice, receipt = self.prepare()
        waiting, continue_read = Event(), Event()
        original_fetch = QuerySet._fetch_all
        reader_identity, settings_seen = [], []

        def intercepted_fetch(queryset):
            if (
                reader_identity
                and get_ident() == reader_identity[0]
                and queryset.model is InvoicePayment
                and queryset._result_cache is None
                and not waiting.is_set()
            ):
                with connection.cursor() as cursor:
                    cursor.execute("SHOW transaction_isolation")
                    settings_seen.append(cursor.fetchone()[0])
                    cursor.execute("SHOW transaction_read_only")
                    settings_seen.append(cursor.fetchone()[0])
                waiting.set()
                if not continue_read.wait(timeout=15):
                    raise AssertionError("Refund did not finish before receipt snapshot query")
            return original_fetch(queryset)

        def read():
            close_old_connections()
            reader_identity.append(get_ident())
            try:
                return resolve_parcel_workflow(
                    business=self.business, actor=self.user, parcel=parcel
                )
            finally:
                connections.close_all()

        with (
            patch.object(QuerySet, "_fetch_all", intercepted_fetch),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future = pool.submit(read)
            try:
                self.assertTrue(waiting.wait(timeout=15))
                self.refund(invoice, receipt)
            finally:
                continue_read.set()
            before = future.result(timeout=20)
        self.assertEqual(settings_seen, ["repeatable read", "on"])
        self.assertEqual(before.financial["state"], "PAID")
        self.assertEqual(before.financial["invoices"][0]["outstanding"], 0)
        after = resolve_parcel_workflow(business=self.business, actor=self.user, parcel=parcel)
        self.assertEqual(after.financial["state"], "PARTIAL")
        self.assertEqual(after.financial["invoices"][0]["outstanding"], 10)

    def test_scan_waiting_for_business_lock_rechecks_clearance_after_refund(self):
        parcel, invoice, receipt = self.prepare()
        for status in ("RECEIVED", "IN_TRANSIT", "ARRIVED", "READY"):
            self.move(parcel, status)
        started = Event()
        cookie = self.client.cookies["sessionid"].value

        def deliver():
            close_old_connections()
            try:
                client = Client()
                client.cookies["sessionid"] = cookie
                started.set()
                return client.post(
                    reverse("logistics_parcel_scan_action", args=[parcel.pk]),
                    {
                        "status": "DELIVERED",
                        "expected_status": "READY",
                        "idempotency_key": str(uuid.uuid4()),
                    },
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Business.objects.select_for_update().get(pk=self.business.pk)
                future = pool.submit(deliver)
                self.assertTrue(started.wait(timeout=10))
                self.refund(invoice, receipt)
            self.assertEqual(future.result(timeout=20), 400)
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "READY")
        self.assertFalse(parcel.events.filter(status="DELIVERED").exists())
