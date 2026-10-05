"""Block 9: vertical presentation, tenant isolation, permissions and regressions."""

from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice
from apps.businesses.models import (
    Business,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    UserOnboardingState,
)
from apps.businesses.onboarding import get_onboarding_status
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client

from .dashboard import get_logistics_dashboard_context
from .models import Parcel, Shipment
from .parcel_services import change_parcel_status, register_parcel
from .shipment_services import assign_parcel, change_shipment_status, create_shipment


class LogisticsWorkspaceTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Courier",
            slug="workspace-courier",
            vertical=Business.Vertical.LOGISTICS,
            email="courier@example.com",
            country="CW",
        )
        self.other = Business.objects.create(
            name="Other Courier",
            slug="workspace-other",
            vertical=Business.Vertical.LOGISTICS,
        )
        self.service = Business.objects.create(name="Services", slug="workspace-service")
        self.plan = ClarivoPlan.objects.get(slug="logistics")
        self.plan.is_active = True
        self.plan.save(update_fields=["is_active"])
        for business in (self.business, self.other, self.service):
            BusinessSubscription.objects.create(
                business=business,
                plan=self.plan if business != self.service else ClarivoPlan.objects.get(slug="pro"),
                status=BusinessSubscription.Status.ACTIVE,
                billing_interval=BusinessSubscription.BillingInterval.YEARLY,
            )
        self.user = TaskIOUser.objects.create_user(email="workspace@example.com")
        self.membership = BusinessUser.objects.create(
            business=self.business,
            user=self.user,
            role=BusinessUser.Role.OWNER,
        )
        for business in (self.other, self.service):
            BusinessUser.objects.create(
                business=business, user=self.user, role=BusinessUser.Role.OWNER
            )
        self.customer = Client.objects.create(
            business=self.business,
            first_name="Parcel",
            last_name="Customer",
            email="parcel-customer@example.com",
        )
        self.other_customer = Client.objects.create(
            business=self.other,
            first_name="Other",
            last_name="Customer",
            email="other-customer@example.com",
        )
        self.client.force_login(self.user)
        self.switch(self.business)

    def switch(self, business):
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = business.pk
        session.save()

    def parcel(self, *, business=None, customer=None, status=Parcel.Status.REGISTERED):
        business = business or self.business
        parcel = register_parcel(
            business=business,
            client=customer or self.customer,
            actor=self.user,
            origin="Miami",
            destination="Curacao",
            package_description="Books",
        )
        for next_status in (
            Parcel.Status.RECEIVED,
            Parcel.Status.IN_TRANSIT,
            Parcel.Status.ARRIVED,
            Parcel.Status.READY,
            Parcel.Status.DELIVERED,
        ):
            if parcel.current_status == status:
                break
            change_parcel_status(
                business=business, parcel=parcel, actor=self.user, status=next_status
            )
            parcel.refresh_from_db()
        return parcel

    def shipment(self, business=None):
        return create_shipment(
            business=business or self.business,
            actor=self.user,
            origin="Miami",
            destination="Curacao",
        )

    def dashboard(self):
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.status_code, 200)
        return response

    def test_logistics_navigation_and_shared_shell(self):
        response = self.dashboard()
        self.assertTemplateUsed(response, "inheritance/dashboard_parent.html")
        for label in (
            "Dashboard",
            "Clients",
            "Parcels",
            "Shipments",
            "Invoices",
            "Team Members",
            "Business Settings",
            "Public Tracking",
        ):
            self.assertContains(response, f'nav-link-text">{label}</span>')
        for route in (
            "business_service_list",
            "staff_lead_list",
            "appointment_list",
            "business_booking_settings",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        for label in (
            "Online Booking",
            "Service Requests",
            "Add your first service",
            "Set your availability",
        ):
            self.assertNotContains(response, label)

    def test_service_navigation_and_onboarding_remain_unchanged(self):
        self.switch(self.service)
        response = self.dashboard()
        self.assertFalse(response.context.get("logistics_dashboard", False))
        for route in (
            "business_service_list",
            "staff_lead_list",
            "appointment_list",
            "business_booking_settings",
        ):
            self.assertContains(response, f'href="{reverse(route)}"')
        for route in (
            "logistics_parcel_list",
            "logistics_shipment_list",
            "logistics_public_tracking",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertEqual(
            [j["key"] for j in response.context["onboarding_status"]["available_journeys"]],
            ["setup_business", "manage_clients", "booked_and_paid"],
        )
        self.assertEqual(
            {t["key"] for t in response.context["onboarding_status"]["tasks"]},
            {
                "complete_business_profile",
                "add_first_service",
                "set_availability",
                "add_first_client",
                "create_first_service_request",
                "schedule_first_appointment",
                "configure_online_booking",
                "create_first_invoice",
                "send_or_download_invoice",
            },
        )

    def test_service_availability_settings_still_work_without_public_booking(self):
        plan = self.service.subscription.plan
        plan.allow_public_booking = False
        plan.save(update_fields=["allow_public_booking"])
        self.switch(self.service)
        response = self.client.get(reverse("business_booking_settings"))
        self.assertEqual(response.status_code, 200)

    def test_logistics_settings_hide_service_shortcuts_and_queries(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("business_settings"))
        self.assertEqual(response.status_code, 200)
        for route in (
            "business_service_list",
            "business_service_import",
            "business_booking_settings",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertNotContains(response, "Services &amp; Categories")
        for table in (
            "crm_businessservice",
            "crm_servicecategory",
            "businesses_businessbookingsettings",
        ):
            self.assertFalse(any(f'"{table}"' in q["sql"] for q in queries), table)

    def test_service_only_routes_are_blocked_for_get_and_post(self):
        for route, kwargs in (
            ("business_service_list", {}),
            ("business_service_create", {}),
            ("staff_lead_list", {}),
            ("staff_lead_create", {}),
            ("appointment_list", {}),
            ("appointment_create", {}),
            ("appointment_detail", {"appointment_id": 1}),
            ("business_booking_settings", {}),
            ("business_weekly_availability_deactivate", {"availability_id": 1}),
        ):
            for method in (self.client.get, self.client.post):
                with self.subTest(route=route, method=method.__name__):
                    response = method(reverse(route, kwargs=kwargs), HTTP_ACCEPT="application/json")
                    self.assertEqual(response.status_code, 403)
                    self.assertIn("business vertical", response.json()["message"])

    def test_kpis_events_and_deliveries_use_only_active_tenant(self):
        self.parcel()
        self.parcel(status=Parcel.Status.RECEIVED)
        self.parcel(status=Parcel.Status.READY)
        delivered = self.parcel(status=Parcel.Status.DELIVERED)
        cancelled = self.parcel()
        change_parcel_status(
            business=self.business,
            parcel=cancelled,
            actor=self.user,
            status=Parcel.Status.CANCELLED,
        )
        held = self.parcel()
        change_parcel_status(
            business=self.business, parcel=held, actor=self.user, status=Parcel.Status.HOLD
        )
        assigned = self.parcel()
        shipment = self.shipment()
        assign_parcel(business=self.business, shipment=shipment, parcel=assigned, actor=self.user)
        cancelled_shipment = self.shipment()
        change_shipment_status(
            business=self.business,
            shipment=cancelled_shipment,
            actor=self.user,
            status=Shipment.Status.CANCELLED,
        )
        other_parcel = self.parcel(
            business=self.other, customer=self.other_customer, status=Parcel.Status.DELIVERED
        )
        other_shipment = self.shipment(self.other)
        response = self.dashboard()
        expected = {
            "parcel_count": 7,
            "active_parcel_count": 5,
            "ready_parcel_count": 1,
            "pending_movement_parcel_count": 2,
            "recently_delivered_parcel_count": 1,
            "shipment_count": 2,
            "active_shipment_count": 1,
        }
        for key, value in expected.items():
            self.assertEqual(response.context[key], value, key)
        counts = {row["status"]: row["count"] for row in response.context["parcel_status_counts"]}
        self.assertEqual(counts[Parcel.Status.REGISTERED], 2)
        self.assertEqual(counts[Parcel.Status.HOLD], 1)
        self.assertEqual(
            [e.parcel_id for e in response.context["recent_deliveries"]], [delivered.pk]
        )
        self.assertTrue(
            all(
                e.business_id == self.business.pk
                for e in response.context["recent_tracking_events"]
            )
        )
        self.assertNotContains(response, other_parcel.tracking_code)
        self.assertNotContains(response, other_shipment.reference)

    def test_delivery_window_uses_delivery_event_time(self):
        self.parcel(status=Parcel.Status.DELIVERED)
        later = timezone.now() + timedelta(days=8)
        with patch("apps.crm.views.timezone.now", return_value=later):
            response = self.dashboard()
        self.assertEqual(response.context["recently_delivered_parcel_count"], 0)
        self.assertEqual(len(response.context["recent_deliveries"]), 0)
        self.assertEqual(response.context["parcel_count"], 1)

    def test_dashboard_actions_respect_all_roles(self):
        for role in BusinessUser.Role.values:
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            response = self.dashboard()
            for route in ("logistics_parcel_register", "logistics_shipment_create"):
                with self.subTest(role=role, route=route):
                    if role in (
                        BusinessUser.Role.OWNER,
                        BusinessUser.Role.ADMIN,
                        BusinessUser.Role.STAFF,
                    ):
                        self.assertContains(response, f'href="{reverse(route)}"')
                    else:
                        self.assertNotContains(response, f'href="{reverse(route)}"')
            self.assertContains(response, f'href="{reverse("logistics_parcel_list")}"')
            self.assertContains(response, f'href="{reverse("logistics_public_tracking")}"')

    def test_read_only_dashboard_keeps_reads_and_hides_write_actions(self):
        subscription = self.business.subscription
        subscription.status = BusinessSubscription.Status.PAST_DUE
        subscription.payment_provider = BusinessSubscription.PaymentProvider.STRIPE
        subscription.billing_currency = BusinessSubscription.BillingCurrency.USD
        subscription.provider_customer_id = "cus_workspace_test"
        subscription.provider_subscription_id = "sub_workspace_test"
        subscription.provider_price_id = "price_workspace_test"
        subscription.past_due_since = timezone.now() - timedelta(days=10)
        subscription.grace_period_ends_at = timezone.now() - timedelta(days=3)
        subscription.save()
        response = self.dashboard()
        for route in ("logistics_parcel_register", "logistics_shipment_create"):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertContains(response, f'href="{reverse("logistics_parcel_list")}"')

    def test_missing_plan_entitlements_hide_actions_and_skip_domain_queries(self):
        allows_module = ClarivoPlan.allows_module
        with (
            patch.object(
                ClarivoPlan,
                "allows_module",
                autospec=True,
                side_effect=(
                    lambda plan, module: (
                        False
                        if module in ("parcels", "tracking", "shipments")
                        else allows_module(plan, module)
                    )
                ),
            ),
            CaptureQueriesContext(connection) as queries,
        ):
            response = self.dashboard()
        self.assertFalse(response.context["dashboard_parcels_enabled"])
        self.assertFalse(response.context["dashboard_shipments_enabled"])
        for route in (
            "logistics_parcel_register",
            "logistics_shipment_create",
            "logistics_parcel_list",
            "logistics_public_tracking",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        # Onboarding still checks prior completion, but no operational aggregates/lists run.
        logistics_queries = [q["sql"] for q in queries if '"logistics_' in q["sql"]]
        self.assertTrue(all("SELECT 1 AS" in sql for sql in logistics_queries))

    def test_dashboard_queries_do_not_cross_verticals(self):
        with CaptureQueriesContext(connection) as queries:
            self.dashboard()
        for table in (
            "crm_businessservice",
            "crm_lead",
            "appointments_appointment",
            "businesses_weeklyavailability",
            "businesses_businessbookingsettings",
        ):
            self.assertFalse(any(f'"{table}"' in q["sql"] for q in queries), table)
        self.switch(self.service)
        with CaptureQueriesContext(connection) as queries:
            self.dashboard()
        self.assertFalse(any('"logistics_' in q["sql"] for q in queries))

    def test_snapshot_reads_are_bounded_with_related_rows_loaded(self):
        for _ in range(6):
            self.parcel(status=Parcel.Status.DELIVERED)
        self.shipment()
        with CaptureQueriesContext(connection) as queries:
            snapshot = get_logistics_dashboard_context(
                business=self.business,
                actor=self.user,
                membership=self.membership,
                now=timezone.now(),
            )
            for event in snapshot["recent_deliveries"]:
                str(event.parcel.client)
            for parcel in snapshot["parcels_requiring_attention"]:
                str(parcel.client)
            list(snapshot["active_shipments"])
            for event in snapshot["recent_tracking_events"]:
                str(event.parcel)
        domain_queries = [q for q in queries if '"logistics_' in q["sql"]]
        self.assertEqual(len(domain_queries), 9)
        self.assertEqual(len(snapshot["recent_deliveries"]), 5)
        self.assertEqual(len(snapshot["recent_tracking_events"]), 5)

    def test_logistics_onboarding_uses_existing_state_and_tenant_completion(self):
        self.parcel(business=self.other, customer=self.other_customer)
        self.shipment(self.other)
        status = get_onboarding_status(user=self.user, business=self.business)
        tasks = {t["key"]: t for t in status["tasks"]}
        self.assertEqual(
            set(tasks),
            {
                "complete_business_profile",
                "add_first_client",
                "register_first_parcel",
                "create_first_shipment",
                "invite_team_member",
                "create_first_invoice",
                "send_or_download_invoice",
            },
        )
        self.assertTrue(tasks["add_first_client"]["completed"])
        self.assertFalse(tasks["register_first_parcel"]["completed"])
        self.assertFalse(tasks["create_first_shipment"]["completed"])
        self.assertFalse(tasks["invite_team_member"]["completed"])
        self.parcel()
        self.shipment()
        BusinessInvitation.objects.create(
            business=self.business, email="colleague@example.com", invited_by=self.user
        )
        response = self.client.post(
            reverse("agent_dashboard"),
            {
                "onboarding_action": "select_journey",
                "selected_journey": "logistics_setup",
            },
        )
        self.assertEqual(response.status_code, 302)
        state = UserOnboardingState.objects.get(user=self.user, business=self.business)
        self.assertEqual(state.selected_journey, "logistics_setup")
        tasks = {t["key"]: t for t in self.dashboard().context["onboarding_status"]["tasks"]}
        for key in ("register_first_parcel", "create_first_shipment", "invite_team_member"):
            self.assertTrue(tasks[key]["completed"])
            self.assertTrue(tasks[key]["cta_url"])

    def test_logistics_rejects_service_journey_and_task_posts(self):
        self.client.post(
            reverse("agent_dashboard"),
            {
                "onboarding_action": "select_journey",
                "selected_journey": "setup_business",
            },
        )
        self.assertFalse(UserOnboardingState.objects.filter(business=self.business).exists())
        UserOnboardingState.objects.create(
            user=self.user, business=self.business, selected_journey="logistics_setup"
        )
        response = self.client.post(
            reverse("agent_dashboard"),
            {
                "onboarding_action": "start_task",
                "current_step_key": "add_first_service",
            },
        )
        self.assertNotEqual(response.url, reverse("business_service_create"))

    def test_parcel_onboarding_prerequisite_points_to_add_client(self):
        self.switch(self.other)
        # A new workspace with no customer records uses the prerequisite CTA.
        fresh = Business.objects.create(
            name="New", slug="workspace-new", vertical=Business.Vertical.LOGISTICS
        )
        BusinessSubscription.objects.create(
            business=fresh, plan=self.plan, status="active", billing_interval="yearly"
        )
        BusinessUser.objects.create(business=fresh, user=self.user, role="owner")
        task = next(
            t
            for t in get_onboarding_status(user=self.user, business=fresh)["tasks"]
            if t["key"] == "register_first_parcel"
        )
        self.assertTrue(task["has_missing_prerequisites"])
        self.assertEqual(task["effective_cta_url"], reverse("staff_client_create"))

    def test_logistics_invoices_create_and_edit_manual_lines_without_service_prompts(self):
        for route, kwargs in (("invoice_create", {}),):
            response = self.client.get(reverse(route, kwargs=kwargs))
            self.assertContains(response, "Add Invoice Line")
            for prompt in (
                "No services found",
                "Save to services",
                "Saved service",
                "New service",
                "Service name",
            ):
                self.assertNotContains(response, prompt)
        response = self.client.post(
            reverse("invoice_create"),
            {
                "client_id": self.customer.pk,
                "description": ["Transport charge"],
                "quantity": ["2"],
                "unit_price": ["25"],
            },
        )
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(business=self.business)
        line = invoice.lines.get()
        self.assertIsNone(line.service_id)
        response = self.client.get(reverse("invoice_edit", kwargs={"invoice_id": invoice.pk}))
        self.assertContains(response, "Transport charge")
        self.assertContains(response, "Add Invoice Line")
        self.assertNotContains(response, "Save to services")
        self.assertNotContains(response, "No services found")
        response = self.client.post(
            reverse("invoice_edit", kwargs={"invoice_id": invoice.pk}),
            {
                "line_id": [line.pk],
                "description": ["Handling charge"],
                "quantity": ["1"],
                "unit_price": ["40"],
            },
        )
        self.assertEqual(response.status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.description, "Handling charge")
        self.assertIsNone(line.service_id)

    def test_logistics_empty_states_guide_next_action(self):
        for route, message in (
            ("logistics_parcel_list", "Add a client, then register their first parcel"),
            ("logistics_shipment_list", "Create a shipment to group parcels for movement"),
            ("staff_client_list", "Add your first client to register parcels"),
        ):
            response = self.client.get(reverse(route), {"q": "no-matches"})
            self.assertContains(response, message)
