from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.billings.models import Invoice

from . import tests as crm_fixtures
from .models import Client


class ClientInvoiceTests(TestCase):
    setUp = crm_fixtures.CRMBusinessScopingTests.setUp
    _enable_invoicing_for_business = (
        crm_fixtures.CRMBusinessScopingTests._enable_invoicing_for_business
    )

    def customer(self, business=None):
        return Client.objects.create(
            business=business or self.business,
            first_name="Invoice",
            last_name="Customer",
            email="invoice-client@example.com",
        )

    def invoice(self, client, number):
        return Invoice.objects.create(
            business=client.business,
            client=client,
            invoice_number=number,
            subtotal=Decimal("125.00"),
            total=Decimal("125.00"),
        )

    def detail(self, client, **params):
        return self.client.get(reverse("staff_client_detail", args=[client.pk]), params)

    def test_only_selected_clients_current_workspace_invoices_are_displayed(self):
        self._enable_invoicing_for_business()
        customer = self.customer()
        own = self.invoice(customer, "CLIENT-OWN-001")
        self.invoice(self.customer(), "OTHER-CLIENT-001")
        foreign = self.invoice(self.customer(self.other_business), "FOREIGN-001")
        # Even an inconsistent legacy relationship must not bypass workspace scope.
        Invoice.objects.filter(pk=foreign.pk).update(client=customer)
        self.client.force_login(self.user)

        response = self.detail(customer)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "crm/main/client_invoice.html")
        self.assertEqual(list(response.context["client_invoices"]), [own])
        self.assertContains(response, reverse("invoice_detail", args=[own.pk]))
        self.assertContains(response, "125.00")
        self.assertNotContains(response, "OTHER-CLIENT-001")
        self.assertNotContains(response, "FOREIGN-001")

    def test_invoice_history_is_paginated_with_stable_ordering(self):
        self._enable_invoicing_for_business()
        customer = self.customer()
        invoices = [self.invoice(customer, f"PAGE-{index:03}") for index in range(8)]
        self.client.force_login(self.user)

        first = self.detail(customer)
        second = self.detail(customer, invoice_page=2)

        self.assertEqual(list(first.context["client_invoices"]), list(reversed(invoices[2:])))
        self.assertEqual(first.context["client_invoices"].paginator.count, 8)
        self.assertContains(first, "?invoice_page=2#client-invoices")
        self.assertEqual(list(second.context["client_invoices"]), list(reversed(invoices[:2])))
        self.assertContains(second, "?invoice_page=1#client-invoices")
        self.assertEqual(self.detail(customer, invoice_page="invalid").status_code, 200)

    def test_empty_invoice_history_has_a_clear_empty_state(self):
        self._enable_invoicing_for_business()
        self.client.force_login(self.user)

        response = self.detail(self.customer())

        self.assertContains(response, "No invoices to display")
        self.assertEqual(response.context["client_invoices"].paginator.count, 0)

    def test_disabled_invoicing_hides_history_and_financial_data(self):
        customer = self.customer()
        self.invoice(customer, "DISABLED-INVOICE-001")
        self.client.force_login(self.user)

        response = self.detail(customer)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("client_invoices", response.context)
        self.assertNotContains(response, 'id="client-invoices"')
        self.assertNotContains(response, "DISABLED-INVOICE-001")

    def test_viewer_can_read_invoices_without_invoice_creation_actions(self):
        self._enable_invoicing_for_business()
        customer = self.customer()
        invoice = self.invoice(customer, "VIEWER-INVOICE-001")
        self.client.force_login(self.viewer_user)

        response = self.detail(customer)

        self.assertContains(response, reverse("invoice_detail", args=[invoice.pk]))
        self.assertNotContains(response, reverse("invoice_create_from_client", args=[customer.pk]))

    def test_other_workspace_client_remains_unavailable(self):
        self._enable_invoicing_for_business()
        self.client.force_login(self.user)

        self.assertEqual(self.detail(self.customer(self.other_business)).status_code, 404)

    def test_all_clients_page_does_not_render_a_single_clients_invoice_history(self):
        self._enable_invoicing_for_business()
        self.invoice(self.customer(), "LIST-INVOICE-001")
        self.client.force_login(self.user)

        response = self.client.get(reverse("client_detail_view"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="client-invoices"')
        self.assertNotContains(response, "LIST-INVOICE-001")
