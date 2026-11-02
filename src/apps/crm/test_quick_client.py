from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .client_capacity import lock_client_capacity_scope
from .models import Client, Lead


class QuickClientTests(TestCase):
    def setUp(self):
        self.plan = ClarivoPlan.objects.create(
            name="Quick client test",
            slug="quick-client-test",
            max_clients=10,
            allow_appointments=True,
        )
        self.business = Business.objects.create(name="Current", slug="quick-current")
        self.other = Business.objects.create(name="Other", slug="quick-other")
        self.subscription = BusinessSubscription.objects.create(
            business=self.business, plan=self.plan, status="active", payment_provider="local"
        )
        self.owner = TaskIOUser.objects.create_user(email="quick@example.test", password="test")
        self.membership = BusinessUser.objects.create(
            business=self.business, user=self.owner, role="owner"
        )
        self.client.force_login(self.owner)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.url = reverse("staff_client_quick_create")
        self.payload = {
            "new_client-first_name": "New",
            "new_client-last_name": "Customer",
            "new_client-company_name": "Customer Co",
            "new_client-email": "customer@example.test",
            "new_client-phone": "+17215550100",
            "new_client-street_address": "14 Example Street",
        }

    def test_client_is_created_in_current_business_under_capacity_lock(self):
        def lock(business):
            self.assertTrue(connection.in_atomic_block)
            return lock_client_capacity_scope(business)

        with patch("apps.crm.views.lock_client_capacity_scope", side_effect=lock) as locked:
            response = self.client.post(
                self.url,
                {
                    **self.payload,
                    "business": self.other.pk,
                    "assigned_to": self.owner.pk,
                },
            )
        self.assertEqual(response.status_code, 201)
        client = Client.objects.get(pk=response.json()["client"]["id"])
        self.assertEqual(client.business, self.business)
        self.assertIsNone(client.assigned_to_id)
        self.assertEqual(response.json()["client"]["email"], client.email)
        self.assertEqual(response.json()["client"]["label"], str(client))
        locked.assert_called_once()
        self.assertFalse(Lead.objects.exists())

    def test_validation_errors_do_not_create_client(self):
        response = self.client.post(self.url, {**self.payload, "new_client-email": "invalid"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json()["errors"])
        self.assertFalse(Client.objects.exists())

    def test_client_capacity_is_enforced(self):
        self.plan.max_clients = 0
        self.plan.save(update_fields=["max_clients"])
        response = self.client.post(self.url, self.payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("__all__", response.json()["errors"])
        self.assertFalse(Client.objects.exists())

    def test_viewer_cannot_create_client(self):
        self.membership.role = "viewer"
        self.membership.save(update_fields=["role"])
        response = self.client.post(self.url, self.payload)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Client.objects.exists())

    def test_restricted_subscription_cannot_create_client(self):
        self.subscription.status = BusinessSubscription.Status.CANCELLED
        self.subscription.save(update_fields=["status", "updated_at"])
        response = self.client.post(self.url, self.payload, HTTP_ACCEPT="application/json")
        self.assertIn(response.status_code, (302, 403))
        self.assertFalse(Client.objects.exists())

    def test_get_cannot_create_client(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertFalse(Client.objects.exists())

    def test_csrf_is_enforced(self):
        self.client.handler.enforce_csrf_checks = True
        self.assertEqual(self.client.post(self.url, self.payload).status_code, 403)
        self.assertFalse(Client.objects.exists())

    def test_both_creation_pages_offer_client_dialog_outside_draft_form(self):
        for route in ("appointment_create", "staff_lead_create"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertContains(response, 'data-bs-target="#draftClientModal"')
                self.assertContains(response, self.url)
                self.assertContains(response, "draft-client.js")

    def test_service_request_edit_does_not_offer_creation_dialog(self):
        lead = Lead.objects.create(business=self.business, first_name="Existing")
        response = self.client.get(reverse("staff_lead_update", args=[lead.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="draftClientModal"')
