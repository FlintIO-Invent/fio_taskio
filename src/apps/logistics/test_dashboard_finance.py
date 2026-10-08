"""Tenant isolation, invoice semantics and access gates for Logistics finance cards."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice
from apps.businesses.localization import format_money_for_business
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import BILLING_VIEW_ROLES, CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client

from .dashboard import get_logistics_dashboard_context


@override_settings(DEBUG=True, MOTIONMATE_ENVIRONMENT="local", LOGISTICS_LOCAL_BILLING_BYPASS=True)
class LogisticsDashboardFinanceTests(TestCase):
    def setUp(self):
        self.plan = ClarivoPlan.objects.get(slug="logistics")
        self.business = Business.objects.create(
            name="Finance Courier",
            slug="finance-courier",
            vertical="LOGISTICS",
            timezone="America/Curacao",
            currency="EUR",
        )
        self.user = TaskIOUser.objects.create_user(email="finance-courier@example.com")
        self.membership = BusinessUser.objects.create(
            business=self.business, user=self.user, role=BusinessUser.Role.OWNER
        )
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.PENDING_CHECKOUT,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.YEARLY,
            billing_currency="eur",
        )
        self.customer = Client.objects.create(business=self.business, first_name="Finance Customer")
        self.client.force_login(self.user)

    def invoice(self, status, total, *, created_at=None, business=None, client=None):
        invoice = Invoice.objects.create(
            business=business or self.business,
            client=client or self.customer,
            invoice_number=f"FIN-{Invoice.objects.count() + 1}",
            status=status,
            total=Decimal(total),
        )
        if created_at:
            Invoice.objects.filter(pk=invoice.pk).update(created_at=created_at)
        return invoice

    def test_totals_use_invoice_status_and_business_month_boundaries(self):
        # October in Curacao starts at 04:00 UTC; the end is exclusive.
        start = datetime(2026, 10, 1, 4, tzinfo=UTC)
        end = datetime(2026, 11, 1, 4, tzinfo=UTC)
        self.invoice("SENT", "100.25", created_at=start)
        self.invoice("PAID", "80.50", created_at=end - timedelta(seconds=1))
        self.invoice("PAID", "20.10", created_at=start - timedelta(seconds=1))
        self.invoice("SENT", "9.75", created_at=end)
        self.invoice("DRAFT", "30.00", created_at=start)
        self.invoice("CANCELLED", "900.00", created_at=start)
        with mock.patch("apps.crm.views.timezone.now", return_value=start + timedelta(days=7)):
            response = self.client.get(reverse("agent_dashboard"))
        for key, expected in {
            "invoiced_this_month_total": "180.75",
            "outstanding_invoice_total": "110.00",
            "paid_invoice_total": "100.60",
            "draft_invoice_total": "30.00",
        }.items():
            self.assertEqual(response.context[key], Decimal(expected), key)
            self.assertContains(
                response, format_money_for_business(Decimal(expected), self.business)
            )
        self.assertContains(response, "Finance overview")
        self.assertContains(response, "Monthly totals use America/Curacao.")
        self.assertContains(response, f'href="{reverse("invoice_list")}"')

    def test_active_business_switch_changes_totals_and_excludes_mismatched_clients(self):
        other = Business.objects.create(
            name="Other Courier", slug="other-finance", vertical="LOGISTICS"
        )
        BusinessUser.objects.create(business=other, user=self.user, role=BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=other,
            plan=self.plan,
            status="pending_checkout",
            payment_provider="stripe",
            billing_interval="yearly",
            billing_currency="usd",
        )
        customer = Client.objects.create(business=other, first_name="Private Other Customer")
        self.invoice("SENT", "25.00")
        self.invoice("SENT", "999.00", business=other, client=customer)
        corrupt = self.invoice("SENT", "888.00")
        # Simulate historical corruption that bypassed model validation.
        Invoice.objects.filter(pk=corrupt.pk).update(client=customer)
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.context["outstanding_invoice_total"], Decimal("25.00"))
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = other.pk
        session.save()
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.context["outstanding_invoice_total"], Decimal("999.00"))

    def test_empty_business_displays_currency_formatted_zero_totals(self):
        response = self.client.get(reverse("agent_dashboard"))
        for key in (
            "invoiced_this_month_total",
            "outstanding_invoice_total",
            "paid_invoice_total",
            "draft_invoice_total",
        ):
            self.assertEqual(response.context[key], Decimal("0.00"))
        self.assertContains(
            response, format_money_for_business(Decimal("0.00"), self.business), count=4
        )

    def test_all_existing_invoice_view_roles_can_view_finance_cards(self):
        for role in BILLING_VIEW_ROLES:
            with self.subTest(role=role):
                self.membership.role = role
                self.membership.save(update_fields=["role"])
                response = self.client.get(reverse("agent_dashboard"))
                self.assertTrue(response.context["dashboard_invoices_enabled"])
                self.assertContains(response, "Finance overview")

    def test_disabled_invoicing_hides_cards_without_querying_invoices(self):
        self.plan.allow_invoicing = False
        self.plan.save(update_fields=["allow_invoicing"])
        with mock.patch("apps.logistics.dashboard.Invoice") as invoices:
            response = self.client.get(reverse("agent_dashboard"))
        invoices.objects.filter.assert_not_called()
        self.assertFalse(response.context["dashboard_invoices_enabled"])
        self.assertNotContains(response, "Finance overview")
        self.assertNotIn("paid_invoice_total", response.context)

    def test_missing_invoice_role_does_not_query_financial_data(self):
        with mock.patch("apps.logistics.dashboard.Invoice") as invoices:
            context = get_logistics_dashboard_context(
                business=self.business, actor=self.user, membership=None, now=datetime.now(UTC)
            )
        invoices.objects.filter.assert_not_called()
        self.assertFalse(context["dashboard_invoices_enabled"])
        self.assertNotIn("paid_invoice_total", context)

    @override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False)
    def test_pending_checkout_does_not_query_financial_data(self):
        with mock.patch("apps.logistics.dashboard.Invoice") as invoices:
            response = self.client.get(reverse("agent_dashboard"))
        invoices.objects.filter.assert_not_called()
        self.assertTemplateUsed(response, "logistics/pending_checkout_dashboard.html")
        self.assertNotContains(response, "Finance overview")
