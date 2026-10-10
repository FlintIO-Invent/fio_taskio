"""Presentation changes retain tenant, lifecycle, CSRF and subscription boundaries."""

from datetime import timedelta

from django.test import Client as WebClient
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.businesses.models import BusinessSubscription, BusinessUser

from . import test_shipments as fixtures
from .forms import ParcelEventForm
from .models import Shipment
from .shipment_forms import ShipmentStatusForm
from .shipment_services import create_shipment


@override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False)
class LogisticsMobileTests(TestCase):
    setUp = fixtures.ShipmentTests.setUp
    shipment = fixtures.ShipmentTests.shipment
    parcel = fixtures.ShipmentTests.parcel
    assign = fixtures.ShipmentTests.assign

    def test_cards_are_scoped_and_counts_preserve_order(self):
        first, second = self.shipment(), self.shipment(transport_mode="SEA")
        parcel = self.parcel()
        self.assign(second, parcel)
        foreign = create_shipment(
            business=self.other, actor=self.other_user, origin="Other", destination="Other"
        )
        response = self.client.get(reverse("logistics_shipment_list"))
        self.assertContains(response, "data-mobile-shipments")
        self.assertNotContains(response, foreign.reference)
        self.assertEqual(
            [(s.pk, s.parcel_count) for s in response.context["page_obj"]],
            [(second.pk, 1), (first.pk, 0)],
        )
        response = self.client.get(reverse("logistics_parcel_list"), {"q": parcel.tracking_code})
        self.assertContains(response, "data-mobile-parcels")
        self.assertContains(response, second.reference)
        self.assertEqual(list(response.context["page_obj"]), [parcel])

    def test_bound_status_widgets_display_only_current_transitions(self):
        parcel = self.parcel()
        form = ParcelEventForm({"status": "DELIVERED"}, parcel=parcel)
        self.assertNotIn("DELIVERED", dict(form.fields["status"].widget.choices))
        # Keep receipt validation choices: the service still decides replays and writes.
        self.assertIn("DELIVERED", dict(form.fields["status"].choices))
        shipment = self.shipment()
        form = ShipmentStatusForm({"status": "COMPLETED"}, shipment=shipment)
        self.assertNotIn("COMPLETED", dict(form.fields["status"].widget.choices))
        self.assertIn("COMPLETED", dict(form.fields["status"].choices))
        response = self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk]))
        self.assertEqual(
            dict(response.context["status_actions"]), {"READY": "Ready", "CANCELLED": "Cancelled"}
        )
        self.assertContains(response, 'name="status" value="READY"')
        self.assertNotContains(response, 'name="status" value="COMPLETED"')

    def test_mobile_actions_respect_role_and_csrf(self):
        shipment = self.shipment()
        from .location_test_support import approve_test_site
        from .models import LogisticsHandlingSite

        site = approve_test_site(business=self.business, membership=self.membership)
        LogisticsHandlingSite.objects.create(
            business=self.business, shipment=shipment, location=site, kind="STOP"
        )
        self.membership.role = BusinessUser.Role.VIEWER
        self.membership.save(update_fields=["role"])
        response = self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk]))
        self.assertNotContains(response, "data-mobile-status-actions")
        csrf_client = WebClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(
            csrf_client.post(
                reverse("logistics_shipment_status", args=[shipment.pk]), {"status": "READY"}
            ).status_code,
            403,
        )
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, Shipment.Status.DRAFT)

    def test_billing_readonly_blocks_mobile_writes(self):
        shipment = self.shipment()
        BusinessSubscription.objects.filter(business=self.business).update(
            status="past_due",
            payment_provider="stripe",
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_mobile_test",
            provider_subscription_id="sub_mobile_test",
            provider_price_id="price_mobile_test",
            past_due_since=timezone.now() - timedelta(days=10),
            grace_period_ends_at=timezone.now() - timedelta(days=3),
        )
        response = self.client.get(reverse("logistics_shipment_detail", args=[shipment.pk]))
        self.assertNotContains(response, "data-mobile-status-actions")
        self.assertEqual(
            self.client.post(
                reverse("logistics_shipment_status", args=[shipment.pk]), {"status": "READY"}
            ).status_code,
            302,
        )
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, Shipment.Status.DRAFT)

    def test_service_shell_does_not_load_logistics_presentation(self):
        from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.service.pk
        session.save()
        for route in ("agent_dashboard", "staff_client_list", "invoice_list"):
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'class="logistics-workspace"')
            self.assertNotContains(response, "assets/css/logistics-mobile")
            self.assertNotContains(response, "assets/js/logistics-mobile")

    def test_dashboard_has_no_public_tracking_navigation_and_private_responses_remain_uncached(
        self,
    ):
        response = self.client.get(reverse("agent_dashboard"))
        self.assertNotContains(response, f'href="{reverse("logistics_public_tracking")}"')
        for route in ("agent_dashboard", "logistics_parcel_list", "logistics_shipment_list"):
            response = self.client.get(reverse(route))
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertIn("private", response.headers["Cache-Control"])
