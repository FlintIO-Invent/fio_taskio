"""Real Services forms retain routes, posted names, tenant context and action guards."""

from django.test import TestCase
from django.urls import reverse

from . import tests as fixtures
from .models import Invoice


class ServicesInvoiceUITests(TestCase):
    def setUp(self):
        fixtures.BillingBusinessScopingTests.setUp(self)
        fixtures.BillingBusinessScopingTests._add_invoice_line(self)
        self.client.force_login(self.user)

    def test_services_editor_posts_original_names_and_retains_inline_client(self):
        response = self.client.get(reverse("invoice_create"))
        self.assertContains(response, 'data-invoice-workspace="editor"')
        for name in ("client_id", "description", "quantity", "unit_price", "notes"):
            self.assertContains(response, f'name="{name}"')
        self.assertContains(response, 'id="quick-client-form"')
        self.assertContains(response, reverse("invoice_quick_create_client"))
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertNotContains(response, self.other_business.name)

    def test_payment_action_precedes_download_and_viewer_is_read_only(self):
        self.invoice.status = Invoice.Status.SENT
        self.invoice.save(update_fields=["status"])
        response = self.client.get(reverse("invoice_detail", args=[self.invoice.pk]))
        html = response.content.decode()
        self.assertLess(html.index("Record customer payment"), html.index("Download PDF"))
        self.assertContains(response, 'onclick="window.print()">Print</button>')
        self.client.force_login(self.viewer_user)
        response = self.client.get(reverse("invoice_detail", args=[self.invoice.pk]))
        self.assertNotContains(response, "Record customer payment")
        self.assertNotContains(response, "Issue invoice")

    def test_edit_existing_and_new_line_prefixes_remain_distinct(self):
        response = self.client.get(reverse("invoice_edit", args=[self.invoice.pk]))
        for name in ("line_id", "quantity", "new_quantity", "new_unit_price"):
            self.assertContains(response, f'name="{name}"')
        self.assertContains(response, 'id="line-item-template" hidden')

    def test_logistics_does_not_load_services_assets(self):
        # Access the shared templates with an existing request/context; rendering proves
        # vertical dispatch without manufacturing Logistics subscription/access grants.
        from django.template.loader import render_to_string

        response = self.client.get(reverse("invoice_list"))
        context = (
            response.context.flatten()
            if hasattr(response.context, "flatten")
            else response.context[-1].flatten()
        )
        self.business.vertical = "LOGISTICS"
        context["current_business"] = self.business
        html = render_to_string(
            "billings/invoice_list.html", context, request=response.wsgi_request
        )
        self.assertNotIn("assets/css/services-invoices.css", html)
        self.assertNotIn("mm-services-invoices", html)
