"""Block 9: vertical presentation, tenant isolation, permissions and regressions."""

import re
from datetime import timedelta
from html.parser import HTMLParser
from unittest.mock import patch

from django.db import connection
from django.test import Client as WebClient
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


class FormControls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.controls = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in ("input", "select", "textarea"):
            self.controls.append(dict(attrs))


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

    def test_dashboard_empty_sections_and_zero_kpis_render(self):
        response = self.dashboard()
        self.assertTemplateUsed(response, "logistics/includes/kpi_card.html")
        for label in (
            "Active Parcels",
            "Received / Waiting",
            "In Transit",
            "Ready",
            "Active Shipments",
            "Delivered This Month",
            "Quick Actions",
            "No active shipments.",
            "No parcels require attention.",
            "No recent parcel activity.",
            "0 registered in total.",
        ):
            self.assertContains(response, label)
        for metric in (
            "active_parcel_count",
            "received_waiting_parcel_count",
            "in_transit_parcel_count",
            "ready_parcel_count",
            "active_shipment_count",
            "delivered_this_month_count",
        ):
            self.assertEqual(response.context[metric], 0)

    def test_dashboard_populated_sections_keep_links_statuses_and_timestamps(self):
        parcel = self.parcel(status=Parcel.Status.RECEIVED)
        shipment = self.shipment()
        response = self.dashboard()
        self.assertContains(
            response, f'href="{reverse("logistics_parcel_detail", args=[parcel.pk])}"'
        )
        self.assertContains(
            response, f'href="{reverse("logistics_shipment_detail", args=[shipment.pk])}"'
        )
        self.assertContains(response, parcel.tracking_code)
        self.assertContains(response, shipment.reference)
        self.assertContains(response, "1 registered in total.")
        self.assertContains(response, 'class="badge badge-phoenix')
        event = response.context["recent_tracking_events"][0]
        self.assertContains(response, event.timestamp.strftime("%Y-%m-%d"))
        for message in (
            "No active shipments.",
            "No parcels require attention.",
            "No recent parcel activity.",
        ):
            self.assertNotContains(response, message)

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
        ):
            self.assertContains(response, f'nav-link-text">{label}</span>')
        for route in (
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

    def sidebar(self, response):
        return (
            response.content.decode()
            .split('<nav class="navbar navbar-vertical', 1)[1]
            .split("</nav>", 1)[0]
        )

    def test_logistics_sidebar_order_and_dropdown_items(self):
        sidebar = self.sidebar(self.dashboard())
        labels = ["Invoices", "Clients", "Parcels", "Shipments"]
        positions = [sidebar.index(f'nav-link-text">{label}</span>') for label in labels]
        self.assertEqual(positions, sorted(positions))
        for module, items in (
            (
                "parcels",
                [
                    ("logistics_parcel_list", "All Parcels"),
                    ("logistics_parcel_register", "Register Parcel"),
                ],
            ),
            (
                "shipments",
                [
                    ("logistics_shipment_list", "All Shipments"),
                    ("logistics_shipment_create", "Create Shipment"),
                ],
            ),
        ):
            with self.subTest(module=module):
                self.assertIn(f'href="#nv-{module}"', sidebar)
                self.assertIn(
                    f'data-bs-toggle="collapse" aria-expanded="false" aria-controls="nv-{module}"',
                    sidebar,
                )
                dropdown = sidebar.split(f'id="nv-{module}">', 1)[1].split("</ul>", 1)[0]
                positions = []
                for route, label in items:
                    positions.append(dropdown.index(f'href="{reverse(route)}"'))
                    self.assertIn(f'nav-link-text">{label}</span>', dropdown)
                self.assertEqual(positions, sorted(positions))
        self.assertNotIn("Public Tracking", sidebar)
        self.assertNotIn(reverse("logistics_public_tracking"), sidebar)

    def test_public_tracking_remains_available_without_login(self):
        url = reverse("logistics_public_tracking")
        self.assertEqual(url, "/logistics/track/")
        response = WebClient().get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "logistics/public_tracking.html")

    def test_logistics_sidebar_write_links_respect_roles(self):
        for role in BusinessUser.Role.values:
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            sidebar = self.sidebar(self.dashboard())
            for route in ("logistics_parcel_register", "logistics_shipment_create"):
                with self.subTest(role=role, route=route):
                    link = f'href="{reverse(route)}"'
                    if role in (
                        BusinessUser.Role.OWNER,
                        BusinessUser.Role.ADMIN,
                        BusinessUser.Role.STAFF,
                    ):
                        self.assertIn(link, sidebar)
                    else:
                        self.assertNotIn(link, sidebar)
                        self.assertEqual(self.client.get(reverse(route)).status_code, 403)
            for route in ("logistics_parcel_list", "logistics_shipment_list"):
                self.assertIn(f'href="{reverse(route)}"', sidebar)

    def test_service_navigation_and_onboarding_remain_unchanged(self):
        self.switch(self.service)
        response = self.dashboard()
        self.assertFalse(response.context.get("logistics_dashboard", False))
        sidebar = self.sidebar(response)
        self.assertLess(sidebar.index('href="#nv-billing"'), sidebar.index('href="#nv-client"'))
        self.assertLess(
            sidebar.index('href="#nv-client"'), sidebar.index('href="#nv-appointments"')
        )
        for dropdown in ("nv-parcels", "nv-shipments"):
            self.assertNotIn(dropdown, sidebar)
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

    def test_logistics_settings_offer_services_without_booking_queries(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("business_settings"))
        self.assertEqual(response.status_code, 200)
        for route in ("business_service_list", "business_service_import"):
            self.assertContains(response, f'href="{reverse(route)}"')
        self.assertNotContains(response, f'href="{reverse("business_booking_settings")}"')
        self.assertFalse(any('"businesses_businessbookingsettings"' in q["sql"] for q in queries))

    def test_service_only_routes_are_blocked_for_get_and_post(self):
        for route, kwargs in (
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
        logistics_queries = [
            q["sql"] for q in queries if re.search(r'\b(?:FROM|JOIN) "logistics_', q["sql"])
        ]
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
        self.assertFalse(any(re.search(r'\b(?:FROM|JOIN) "logistics_', q["sql"]) for q in queries))

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
        domain_queries = [q for q in queries if re.search(r'\b(?:FROM|JOIN) "logistics_', q["sql"])]
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

    def test_logistics_invoices_preserve_manual_lines_and_offer_saved_services(self):
        for route, kwargs in (("invoice_create", {}),):
            response = self.client.get(reverse(route, kwargs=kwargs))
            self.assertContains(response, "Add Service Line")
            self.assertContains(response, "Save to services")
            self.assertContains(response, "Saved service")
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
        self.assertContains(response, "Add Service Line")
        self.assertContains(response, "Save to services")
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
            ("logistics_parcel_list", "No parcels match these filters."),
            ("logistics_shipment_list", "Create a shipment to group parcels for movement"),
            ("staff_client_list", "Add your first client to register parcels"),
        ):
            response = self.client.get(reverse(route), {"q": "no-matches"})
            self.assertContains(response, message)

    def test_logistics_empty_states_are_separate_from_tables(self):
        response = self.client.get(reverse("logistics_shipment_list"))
        self.assertContains(response, "No shipments created yet.")
        self.assertNotContains(response, "<table")
        shipment = self.shipment()
        for route, args, message in (
            ("logistics_parcel_list", [], "No parcels registered yet."),
            ("logistics_shipment_detail", [shipment.pk], "No parcels assigned yet."),
        ):
            response = self.client.get(reverse(route, args=args))
            content = response.content.decode().split('<div class="content">', 1)[1]
            self.assertContains(response, message)
            self.assertIn('class="card-body text-center py-5"', content)
            self.assertNotIn("<table", content)
            self.assertNotIn("<thead", content)

    def test_logistics_pages_use_dashboard_content_and_responsive_cards(self):
        parcel, shipment = self.parcel(), self.shipment()
        assignment_form = self.client.get(
            reverse("logistics_shipment_detail", args=[shipment.pk])
        ).context["assignment_form"]
        self.assertEqual(
            self.client.post(
                reverse("logistics_shipment_assign", args=[shipment.pk]),
                {
                    "parcel": parcel.pk,
                    **{field.name: field.value() for field in assignment_form.hidden_fields()},
                },
            ).status_code,
            302,
        )
        for route, args in (
            ("logistics_parcel_list", []),
            ("logistics_parcel_detail", [parcel.pk]),
            ("logistics_parcel_register", []),
            ("logistics_parcel_update", [parcel.pk]),
            ("logistics_shipment_list", []),
            ("logistics_shipment_detail", [shipment.pk]),
            ("logistics_shipment_create", []),
            ("logistics_shipment_edit", [shipment.pk]),
        ):
            with self.subTest(route=route):
                response = self.client.get(reverse(route, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "inheritance/dashboard_parent.html")
                self.assertContains(response, '<div class="content">', count=1)
                self.assertContains(response, 'aria-label="breadcrumb"')
                self.assertContains(response, 'class="card')
                if route.endswith("list") or route == "logistics_shipment_detail":
                    self.assertContains(response, 'class="table-responsive"')
                    self.assertContains(response, 'class="table table-hover align-middle mb-0"')

    def test_shipment_form_keeps_fields_and_shows_validation(self):
        url = reverse("logistics_shipment_create")
        response = self.client.get(url)
        for label in ("Create Shipment", "Route", "Schedule", "Notes", "Save Shipment"):
            self.assertContains(response, label)
        controls = FormControls(response.content.decode()).controls
        fields = {"origin", "destination", "departure_at", "estimated_arrival_at", "notes"}
        for name in fields:
            control = [c for c in controls if c.get("name") == name]
            self.assertEqual(len(control), 1, name)
            self.assertEqual(control[0]["class"], "form-control")
        for name in ("departure_at", "estimated_arrival_at"):
            self.assertEqual(
                next(c for c in controls if c.get("name") == name)["type"], "datetime-local"
            )
        response = self.client.post(
            url, {"origin": "Miami", "destination": "", "notes": "Keep this note"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(response, 'class="invalid-feedback d-block"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, "Keep this note")
        self.assertEqual(Shipment.objects.count(), 0)

    def test_parcel_forms_keep_hidden_tokens_and_themed_controls(self):
        parcel = self.parcel()
        for route, args, hidden_fields in (
            ("logistics_parcel_register", [], ["idempotency_key"]),
            ("logistics_parcel_update", [parcel.pk], ["idempotency_key", "expected_status"]),
        ):
            response = self.client.get(reverse(route, args=args))
            controls = FormControls(response.content.decode()).controls
            for name in hidden_fields:
                control = [c for c in controls if c.get("name") == name]
                self.assertEqual(len(control), 1, name)
                self.assertEqual(control[0]["type"], "hidden")
                self.assertTrue(control[0]["value"])
            for field in response.context["form"].visible_fields():
                control = next(c for c in controls if c.get("name") == field.name)
                if control.get("type") == "checkbox":
                    self.assertEqual(control["class"], "form-check-input")
                else:
                    self.assertIn(control["class"], ("form-control", "form-select"))
