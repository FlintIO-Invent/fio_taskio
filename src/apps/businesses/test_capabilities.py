from datetime import timedelta
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice
from apps.crm.importing.permissions import user_can_import
from apps.crm.importing.types import ImportType
from apps.crm.models import BusinessService, Client, ServiceCategory

from .capabilities import business_has_capability
from .models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from .utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    business_module_required,
    business_role_required,
    can_use_module,
    can_view_module,
)


class VerticalPolicyTests(SimpleTestCase):
    def test_default_creation_preserves_industry_and_service_vertical(self):
        business = Business(name="Existing workspace", slug="existing", business_type="Cleaning")
        self.assertEqual(business.vertical, Business.Vertical.SERVICE)
        self.assertEqual(business.business_type, "Cleaning")

    def test_explicit_vertical_capability_matrix(self):
        shared = {"workspace", "team", "clients", "invoicing"}
        service = {"services", "service_requests", "appointments", "public_booking"}
        logistics = {"parcels", "tracking", "shipments", "manifests"}
        for vertical, expected in (
            (Business.Vertical.SERVICE, shared | service),
            (Business.Vertical.LOGISTICS, shared | logistics),
        ):
            business = Business(vertical=vertical)
            for capability in shared | service | logistics:
                with self.subTest(vertical=vertical, capability=capability):
                    self.assertEqual(business.has_capability(capability), capability in expected)

    def test_legacy_aliases_preserve_domain_boundaries(self):
        for vertical in Business.Vertical.values:
            business = Business(vertical=vertical)
            for alias in ("crm", "client_management", " CLIENT-MANAGEMENT "):
                self.assertTrue(business.has_capability(alias))
            for alias in (
                "public_booking_requests",
                "public_request_form",
                "public_request",
                "PUBLIC-BOOKING",
            ):
                self.assertEqual(
                    business.has_capability(alias), vertical == Business.Vertical.SERVICE
                )

    def test_unknown_vertical_or_capability_and_missing_business_fail_closed(self):
        self.assertFalse(business_has_capability(None, "clients"))
        self.assertFalse(Business(vertical="UNKNOWN").has_capability("clients"))
        self.assertFalse(Business().has_capability("unknown_module"))


class VerticalAccessTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Workspace", slug="vertical-workspace")
        self.plan = ClarivoPlan.objects.get(slug="pro")
        self.subscription = BusinessSubscription.objects.create(
            business=self.business, plan=self.plan, status=BusinessSubscription.Status.ACTIVE
        )
        self.user = TaskIOUser.objects.create_user(
            email="vertical@example.com", password="testpass123"
        )
        self.membership = BusinessUser.objects.create(
            business=self.business, user=self.user, role=BusinessUser.Role.OWNER
        )
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    def logistics(self):
        self.business.vertical = Business.Vertical.LOGISTICS
        self.business.save(update_fields=["vertical", "updated_at"])

    def test_persisted_creation_defaults_and_industry_remain_compatible(self):
        self.business.refresh_from_db()
        self.assertEqual(self.business.vertical, Business.Vertical.SERVICE)
        self.business.business_type = "Freight forwarding"
        self.logistics()
        self.business.save(update_fields=["business_type"])
        self.business.refresh_from_db()
        self.assertEqual(self.business.vertical, Business.Vertical.LOGISTICS)
        self.assertEqual(self.business.business_type, "Freight forwarding")
        self.business.full_clean()
        self.business.vertical = "UNKNOWN"
        with self.assertRaises(ValidationError):
            self.business.full_clean()

    def test_service_module_access_and_legacy_aliases_remain_available(self):
        for module in (
            "workspace",
            "team",
            "clients",
            "crm",
            "client_management",
            "services",
            "service_requests",
            "invoicing",
            "appointments",
            "public_booking",
            "public_booking_requests",
            "public_request_form",
            "public_request",
        ):
            with self.subTest(module=module):
                self.assertTrue(self.business.can_use_module(module))
                self.assertTrue(can_view_module(self.business, module))
                self.assertTrue(self.subscription.can_modify_module_at(module, timezone.now()))

    def test_logistics_shared_access_does_not_grant_service_modules(self):
        self.logistics()
        for module in ("workspace", "team", "clients", "crm", "client_management", "invoicing"):
            with self.subTest(module=module):
                self.assertTrue(can_use_module(self.business, module))
        for module in (
            "services",
            "service_requests",
            "appointments",
            "public_booking",
            "public_booking_requests",
            "public_request_form",
            "public_request",
        ):
            with self.subTest(module=module):
                self.assertFalse(self.business.can_use_module(module))
                self.assertFalse(self.subscription.can_view_module(module))
                self.assertFalse(self.subscription.can_view_module_at(module, timezone.now()))
                self.assertFalse(self.subscription.can_modify_module_at(module, timezone.now()))

    def test_logistics_domain_capabilities_do_not_bypass_plan_entitlements(self):
        self.logistics()
        for module in ("parcels", "tracking", "shipments", "manifests"):
            with self.subTest(module=module):
                self.assertTrue(self.business.has_capability(module))
                self.assertFalse(self.plan.allows_module(module))
                self.assertFalse(can_use_module(self.business, module))
                self.assertFalse(can_view_module(self.business, module))

    def test_plan_flag_is_required_for_shared_invoicing(self):
        self.logistics()
        self.plan.allow_invoicing = False
        self.plan.save(update_fields=["allow_invoicing"])
        self.assertTrue(self.business.has_capability("invoicing"))
        self.assertFalse(self.business.can_use_module("invoicing"))
        response = self.client.get(reverse("invoice_list"), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 403)

    def test_unavailable_subscription_business_and_plan_still_deny_access(self):
        self.logistics()
        for status in (
            BusinessSubscription.Status.PENDING_CHECKOUT,
            BusinessSubscription.Status.CANCELLED,
            BusinessSubscription.Status.EXPIRED,
            BusinessSubscription.Status.SUSPENDED,
        ):
            with self.subTest(status=status):
                self.subscription.status = status
                self.assertFalse(self.subscription.can_view_module("clients"))
                self.assertFalse(self.subscription.can_use_module("clients"))
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.business.is_active = False
        self.assertFalse(self.subscription.can_use_module("clients"))
        self.business.is_active = True
        self.plan.is_active = False
        self.assertFalse(self.subscription.can_use_module("clients"))
        self.subscription.delete()
        fresh_business = Business.objects.get(pk=self.business.pk)
        self.assertTrue(fresh_business.has_capability("clients"))
        self.assertFalse(fresh_business.can_use_module("clients"))

    def test_restricted_logistics_preserves_shared_reads_but_blocks_writes(self):
        self.logistics()
        now = timezone.now()
        self.subscription.status = BusinessSubscription.Status.PAST_DUE
        self.subscription.payment_provider = BusinessSubscription.PaymentProvider.STRIPE
        self.subscription.billing_interval = BusinessSubscription.BillingInterval.MONTHLY
        self.subscription.billing_currency = BusinessSubscription.BillingCurrency.USD
        self.subscription.provider_customer_id = "cus_vertical_test"
        self.subscription.provider_subscription_id = "sub_vertical_test"
        self.subscription.provider_price_id = "price_vertical_test"
        self.subscription.past_due_since = now - timedelta(days=10)
        self.subscription.grace_period_ends_at = now - timedelta(days=3)
        self.subscription.save()
        self.assertTrue(self.subscription.can_view_module_at("clients", now))
        self.assertFalse(self.subscription.can_modify_module_at("clients", now))
        response = self.client.get(reverse("staff_client_list"))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("staff_client_create"), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "subscription_restricted")
        response = self.client.get(reverse("business_service_list"), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "subscription_unavailable")

    def test_role_guard_remains_independent_of_vertical_and_module_access(self):
        self.logistics()
        self.membership.role = BusinessUser.Role.STAFF
        self.membership.save(update_fields=["role"])

        @business_role_required(BusinessUser.Role.OWNER)
        @business_module_required("clients")
        def owner_view(request):
            return HttpResponse("ok")

        request = RequestFactory().get("/")
        request.user = self.user
        request.session = {CURRENT_BUSINESS_SESSION_KEY: self.business.pk}
        self.assertTrue(self.business.can_use_module("clients"))
        with self.assertRaises(PermissionDenied):
            owner_view(request)

    def test_logistics_client_routes_and_existing_template_context_remain_available(self):
        self.logistics()
        for route in ("staff_client_list", "staff_client_create", "client_import_upload"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["current_business"].vertical, Business.Vertical.LOGISTICS
                )

    def test_logistics_service_routes_cannot_be_reached_via_crm(self):
        self.logistics()
        routes = (
            ("business_service_list", {}),
            ("business_service_create", {}),
            ("business_service_update", {"service_id": 1}),
            ("business_service_archive", {"service_id": 1}),
            ("business_service_category_list", {}),
            ("business_service_category_create", {}),
            ("business_service_category_update", {"category_id": 1}),
            ("business_service_category_archive", {"category_id": 1}),
            ("business_service_import", {}),
            ("business_service_sample_csv", {}),
            ("staff_lead_list", {}),
            ("staff_lead_create", {}),
            ("staff_lead_detail", {"lead_id": 1}),
            ("staff_lead_update", {"lead_id": 1}),
            ("staff_lead_convert_to_client", {"lead_id": 1}),
            ("staff_lead_create_invoice", {"lead_id": 1}),
            ("lead_import_upload", {}),
            ("lead_import_template", {}),
            *(
                (f"{prefix}_{action}", {"job_id": uuid4()})
                for prefix in ("business_service_import", "lead_import")
                for action in ("preview", "execute", "result")
            ),
        )
        for route, kwargs in routes:
            with self.subTest(route=route):
                response = self.client.get(
                    reverse(route, kwargs=kwargs), HTTP_ACCEPT="application/json"
                )
                self.assertEqual(response.status_code, 403)
                self.assertIn("business vertical", response.json()["message"])

    def test_logistics_import_permissions_keep_clients_and_block_service_data(self):
        self.logistics()
        self.assertTrue(user_can_import(self.business, self.user, ImportType.CLIENTS))
        self.assertFalse(user_can_import(self.business, self.user, ImportType.LEADS))
        self.assertFalse(user_can_import(self.business, self.user, ImportType.SERVICES))

    def test_logistics_invoices_allow_manual_lines_without_creating_services(self):
        self.logistics()
        client = Client.objects.create(
            business=self.business,
            first_name="Parcel",
            last_name="Customer",
            company_name="Customer",
            email="customer@example.com",
            phone="123456",
            street_address="12 Example Street",
        )
        line_data = {
            "client_id": str(client.pk),
            "description": ["Transport charge"],
            "quantity": ["1"],
            "unit_price": ["25"],
        }
        response = self.client.post(
            reverse("invoice_create"),
            {**line_data, "save_as_service": ["1"], "new_service_category_name": ["Transport"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "services are not available for this business vertical")
        self.assertFalse(BusinessService.objects.exists())
        self.assertFalse(ServiceCategory.objects.filter(business=self.business).exists())
        self.assertFalse(Invoice.objects.exists())

        response = self.client.post(reverse("invoice_create"), line_data)
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(business=self.business)
        self.assertEqual(invoice.lines.get().description, "Transport charge")
        self.assertIsNone(invoice.lines.get().service_id)


class BusinessVerticalMigrationTests(TransactionTestCase):
    def test_existing_rows_receive_service_without_changing_industry(self):
        executor = MigrationExecutor(connection)
        latest_targets = executor.loader.graph.leaf_nodes()
        old_target = [("businesses", "0023_businesssubscription_provisioning_source")]
        new_target = [("businesses", "0024_business_vertical")]
        try:
            executor.migrate(old_target)
            old_apps = executor.loader.project_state(old_target).apps
            old_business = old_apps.get_model("businesses", "Business").objects.create(
                name="Existing business", slug="migration-existing", business_type="Cleaning"
            )
            executor = MigrationExecutor(connection)
            executor.migrate(new_target)
            new_apps = executor.loader.project_state(new_target).apps
            migrated_business = new_apps.get_model("businesses", "Business").objects.get(
                pk=old_business.pk
            )
            self.assertEqual(migrated_business.vertical, "SERVICE")
            self.assertEqual(migrated_business.business_type, "Cleaning")
        finally:
            MigrationExecutor(connection).migrate(latest_targets)
