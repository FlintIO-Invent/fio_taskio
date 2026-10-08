"""Local-only effective access, promotion safety and the shared operational dashboard."""

from datetime import UTC, datetime, timedelta
from unittest import mock

from django.core.checks import run_checks
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.db.models import QuerySet
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice
from apps.businesses.models import (
    BillingProviderWebhookEvent,
    Business,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    SubscriptionAccessMode,
)
from apps.businesses.utils import (
    business_can_access_module,
    business_can_modify_workspace,
    business_can_view_workspace,
)
from apps.crm.models import Client

from .checks import check_logistics_local_billing_bypass
from .models import ParcelEvent
from .parcel_services import change_parcel_status, register_parcel
from .shipment_services import assign_parcel, create_shipment, generate_manifest
from .test_enrollment import PASSWORD
from .tests import application_data


class LocalBypassConfigurationTests(SimpleTestCase):
    def test_setting_defaults_false_and_parses_environment_boolean(self):
        from config import Settings

        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(Settings(_env_file=None).logistics_local_billing_bypass)
            with mock.patch.dict("os.environ", {"LOGISTICS_LOCAL_BILLING_BYPASS": "True"}):
                self.assertTrue(Settings(_env_file=None).logistics_local_billing_bypass)
            with mock.patch.dict("os.environ", {"LOGISTICS_LOCAL_BILLING_BYPASS": "False"}):
                self.assertFalse(Settings(_env_file=None).logistics_local_billing_bypass)

    @override_settings(
        LOGISTICS_LOCAL_BILLING_BYPASS=True, DEBUG=False, MOTIONMATE_ENVIRONMENT="local"
    )
    def test_debug_false_fails_normal_startup_check_even_without_deployment_checks(self):
        self.assertEqual(
            [issue.id for issue in check_logistics_local_billing_bypass(None)], ["logistics.E014"]
        )
        self.assertIn("logistics.E014", {issue.id for issue in run_checks()})
        with self.assertRaises(SystemCheckError):
            call_command("check")

    @override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=True, DEBUG=True)
    def test_nonlocal_environment_fails_even_when_debug_is_accidentally_on(self):
        for environment in ("development", "staging", "production", "prod", "", "unknown"):
            with (
                self.subTest(environment=environment),
                override_settings(MOTIONMATE_ENVIRONMENT=environment),
            ):
                self.assertEqual(
                    [issue.id for issue in check_logistics_local_billing_bypass(None)],
                    ["logistics.E014"],
                )

    def test_disabled_bypass_and_valid_local_config_pass(self):
        with override_settings(
            LOGISTICS_LOCAL_BILLING_BYPASS=False, DEBUG=False, MOTIONMATE_ENVIRONMENT="production"
        ):
            self.assertEqual(check_logistics_local_billing_bypass(None), [])
        with override_settings(
            LOGISTICS_LOCAL_BILLING_BYPASS=True, DEBUG=True, MOTIONMATE_ENVIRONMENT="local"
        ):
            self.assertEqual(check_logistics_local_billing_bypass(None), [])


@override_settings(DEBUG=True, MOTIONMATE_ENVIRONMENT="local", LOGISTICS_LOCAL_BILLING_BYPASS=True)
class LocalLogisticsAccessTests(TestCase):
    def setUp(self):
        self.plan = ClarivoPlan.objects.get(slug="logistics")
        self.business = Business.objects.create(
            name="Local Courier",
            slug="local-courier",
            vertical="LOGISTICS",
            timezone="America/Curacao",
        )
        self.user = TaskIOUser.objects.create_user(email="local-courier@example.com")
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
        self.customer = Client.objects.create(
            business=self.business, first_name="Pilot", last_name="Customer"
        )
        self.client.force_login(self.user)

    def parcel(self, **changes):
        return register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            origin="Miami",
            destination="Curacao",
            package_description="Books",
            **changes,
        )

    def move(self, parcel, status):
        for next_status in ("RECEIVED", "IN_TRANSIT", "ARRIVED", "READY", "DELIVERED"):
            if parcel.current_status == status:
                break
            change_parcel_status(
                business=self.business, actor=self.user, parcel=parcel, status=next_status
            )
            parcel.refresh_from_db()
        return parcel

    def paid(self):
        self.plan.is_active = True
        self.plan.save(update_fields=["is_active"])
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.subscription.current_period_end = timezone.now() + timedelta(days=365)
        self.subscription.save()

    def test_local_pending_access_is_full_even_for_the_staged_offering(self):
        state = self.subscription.effective_access_state
        self.assertEqual(state.mode, SubscriptionAccessMode.FULL)
        self.assertTrue(state.local_billing_bypass_active)
        self.assertTrue(business_can_view_workspace(self.business))
        self.assertTrue(business_can_modify_workspace(self.business))
        for module in ("clients", "parcels", "tracking", "shipments", "manifests", "team"):
            for access in ("read", "write"):
                self.assertTrue(
                    business_can_access_module(self.business, module, access=access),
                    (module, access),
                )

    def test_normal_owner_login_can_create_and_view_client_and_open_operations(self):
        self.user.set_password(PASSWORD)
        self.user.save(update_fields=["password"])
        self.client.logout()
        before = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        with mock.patch("apps.businesses.stripe_checkout.configure_stripe_sdk") as stripe:
            login = self.client.post(
                reverse("business_login"), {"email": self.user.email, "password": PASSWORD}
            )
            self.assertRedirects(login, reverse("agent_dashboard"))
            self.assertEqual(self.client.session["current_business_id"], self.business.pk)
            dashboard = self.client.get(reverse("agent_dashboard"))
            self.assertTemplateUsed(dashboard, "crm/agent_dashboard/agent_dashboard.html")
            self.assertContains(dashboard, "billing bypass active")
            response = self.client.post(
                reverse("staff_client_create"),
                {
                    "client_type": "INDIVIDUAL",
                    "first_name": "Local",
                    "last_name": "Customer",
                    "company_name": "Local Customer",
                    "email": "local-client@example.com",
                    "phone": "+59991234567",
                    "preferred_contact_method": "EMAIL",
                    "client_status": "ACTIVE",
                    "priority": "MEDIUM",
                    "street_address": "Local test street 1",
                },
            )
            self.assertRedirects(response, reverse("staff_client_list"))
            customer = Client.objects.get(business=self.business, email="local-client@example.com")
            for name, args in (
                ("staff_client_detail", [customer.pk]),
                ("logistics_parcel_list", []),
                ("logistics_parcel_register", []),
                ("logistics_shipment_list", []),
                ("logistics_shipment_create", []),
            ):
                with self.subTest(route=name):
                    self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        stripe.assert_not_called()
        self.assertEqual(BusinessSubscription.objects.values().get(pk=self.subscription.pk), before)

    def test_operational_services_work_without_mutating_billing_or_calling_stripe(self):
        before = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        plan_before = ClarivoPlan.objects.values().get(pk=self.plan.pk)
        with mock.patch("apps.businesses.stripe_checkout.configure_stripe_sdk") as stripe:
            parcel = self.move(self.parcel(), "RECEIVED")
            shipment = create_shipment(
                business=self.business, actor=self.user, origin="Miami", destination="Curacao"
            )
            assign_parcel(business=self.business, actor=self.user, parcel=parcel, shipment=shipment)
            manifest = generate_manifest(business=self.business, actor=self.user, shipment=shipment)
            self.assertEqual(manifest["parcel_count"], 1)
            self.assertEqual(
                self.client.get(
                    reverse("logistics_shipment_manifest", args=[shipment.pk])
                ).status_code,
                200,
            )
            self.assertEqual(self.client.get(reverse("agent_dashboard")).status_code, 200)
        stripe.assert_not_called()
        self.assertEqual(BusinessSubscription.objects.values().get(pk=self.subscription.pk), before)
        self.assertEqual(ClarivoPlan.objects.values().get(pk=self.plan.pk), plan_before)
        self.assertEqual(ParcelEvent.objects.count(), 2)
        self.assertEqual(BillingProviderWebhookEvent.objects.count(), 0)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_disabling_bypass_immediately_restores_gates_on_the_same_objects_and_views(self):
        self.parcel()
        with override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False):
            self.assertFalse(self.subscription.can_view_workspace)
            self.assertFalse(business_can_modify_workspace(self.business))
            self.assertFalse(business_can_access_module(self.business, "parcels"))
            with self.assertRaises(PermissionDenied):
                self.parcel()
            self.assertNotEqual(self.client.get(reverse("logistics_parcel_list")).status_code, 200)
            response = self.client.get(reverse("agent_dashboard"))
            self.assertTemplateUsed(response, "logistics/pending_checkout_dashboard.html")
            self.assertNotContains(response, "billing bypass active")
        self.assertTrue(self.subscription.can_view_workspace)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)

    def test_nonlocal_and_debug_false_fail_closed_at_runtime_even_if_checks_are_skipped(self):
        for debug, environment in (
            (False, "local"),
            (False, "production"),
            (True, "development"),
            (True, "staging"),
            (True, "production"),
        ):
            with (
                self.subTest(debug=debug, environment=environment),
                override_settings(DEBUG=debug, MOTIONMATE_ENVIRONMENT=environment),
            ):
                self.assertFalse(self.subscription.can_view_workspace)
                self.assertFalse(
                    self.subscription.effective_access_state.local_billing_bypass_active
                )

    def test_service_never_receives_bypass(self):
        service = Business.objects.create(name="Service", slug="service")
        subscription = BusinessSubscription.objects.create(
            business=service,
            plan=ClarivoPlan.objects.get(slug="pro"),
            status=BusinessSubscription.Status.PENDING_CHECKOUT,
        )
        self.assertFalse(subscription.has_access)
        self.assertFalse(subscription.effective_access_state.local_billing_bypass_active)

    def test_cancelled_suspended_expired_and_past_due_are_not_bypassed(self):
        for status in ("cancelled", "suspended", "expired", "past_due"):
            with self.subTest(status=status):
                self.subscription.status = status
                self.assertFalse(self.subscription.has_access)
                self.assertFalse(
                    self.subscription.effective_access_state.local_billing_bypass_active
                )

    def test_inactive_business_invalid_offering_or_pre_payment_shape_is_not_bypassed(self):
        self.business.is_active = False
        self.assertFalse(self.subscription.has_access)
        self.business.is_active = True
        for field, value in (
            ("billing_interval", "monthly"),
            ("billing_currency", "unknown"),
            ("payment_provider", "local"),
            ("trial_start", timezone.now()),
            ("trial_end", timezone.now()),
            ("status", "trialing"),
        ):
            with self.subTest(field=field):
                original = getattr(self.subscription, field)
                setattr(self.subscription, field, value)
                self.assertFalse(
                    self.subscription.effective_access_state.local_billing_bypass_active
                )
                setattr(self.subscription, field, original)
        self.subscription.plan = ClarivoPlan.objects.get(slug="pro")
        self.assertFalse(self.subscription.has_access)
        missing = Business.objects.create(
            name="No subscription", slug="no-subscription", vertical="LOGISTICS"
        )
        self.assertFalse(business_can_modify_workspace(missing))

    def test_bypass_preserves_module_entitlements_roles_and_service_only_boundaries(self):
        self.plan.allow_invoicing = False
        self.plan.save(update_fields=["allow_invoicing"])
        self.assertFalse(business_can_access_module(self.business, "invoicing"))
        for module in (
            "service_requests",
            "appointments",
            "public_booking",
            "booking_availability",
        ):
            self.assertFalse(business_can_access_module(self.business, module))
        self.membership.role = BusinessUser.Role.VIEWER
        self.membership.save(update_fields=["role"])
        with self.assertRaises(PermissionDenied):
            self.parcel()
        response = self.client.get(reverse("agent_dashboard"))
        self.assertNotContains(response, f'href="{reverse("logistics_parcel_register")}"')
        self.assertNotContains(response, f'href="{reverse("logistics_shipment_create")}"')

    def test_same_dashboard_and_navigation_for_local_full_and_normal_paid_access(self):
        local = self.client.get(reverse("agent_dashboard"))
        self.assertTemplateUsed(local, "crm/agent_dashboard/agent_dashboard.html")
        self.assertContains(local, "LOCAL DEVELOPMENT — billing bypass active")
        self.assertNotContains(local, "assets/js/dashboards/crm-dashboard.js")
        for label in (
            "Active Parcels",
            "Received / Waiting",
            "In Transit",
            "Ready",
            "Active Shipments",
            "Delivered This Month",
            "Recent Parcel Activity",
            "Parcels Requiring Attention",
        ):
            self.assertContains(local, label)
        for name in (
            "staff_client_create",
            "logistics_parcel_list",
            "logistics_shipment_list",
            "business_settings",
        ):
            self.assertContains(local, f'href="{reverse(name)}"')
        for name in ("appointment_list", "staff_lead_list"):
            self.assertNotContains(local, f'href="{reverse(name)}"')
        self.paid()
        for environment in ("development", "staging", "production"):
            with (
                self.subTest(environment=environment),
                override_settings(
                    DEBUG=False,
                    MOTIONMATE_ENVIRONMENT=environment,
                    LOGISTICS_LOCAL_BILLING_BYPASS=False,
                ),
            ):
                paid = self.client.get(reverse("agent_dashboard"))
                self.assertTemplateUsed(paid, "crm/agent_dashboard/agent_dashboard.html")
                self.assertNotContains(paid, "billing bypass active")
                self.assertNotContains(paid, "assets/js/dashboards/crm-dashboard.js")
                self.assertContains(paid, "Recent Parcel Activity")
                self.assertContains(paid, f'href="{reverse("logistics_shipment_list")}"')

    def test_requests_and_database_attributes_cannot_enable_bypass(self):
        with override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False):
            for method in (self.client.get, self.client.post):
                response = method(
                    reverse("agent_dashboard"),
                    {
                        "DEBUG": "True",
                        "LOGISTICS_LOCAL_BILLING_BYPASS": "True",
                        "local_billing_bypass_active": "True",
                    },
                )
                self.assertTemplateUsed(response, "logistics/pending_checkout_dashboard.html")
                self.assertNotContains(response, "billing bypass active")
                self.assertNotContains(response, "assets/js/dashboards/crm-dashboard.js")
            self.subscription.logistics_local_billing_bypass = True
            self.assertFalse(self.subscription.has_access)
        self.assertNotIn(
            "logistics_local_billing_bypass",
            {field.name for field in BusinessSubscription._meta.fields},
        )

    def test_dashboard_kpis_and_sections_are_tenant_scoped_and_limited(self):
        self.parcel()
        self.move(self.parcel(), "RECEIVED")
        self.move(self.parcel(), "IN_TRANSIT")
        self.move(self.parcel(), "READY")
        self.move(self.parcel(), "DELIVERED")
        held = self.parcel()
        change_parcel_status(business=self.business, actor=self.user, parcel=held, status="HOLD")
        for _ in range(6):
            self.parcel()
            create_shipment(
                business=self.business, actor=self.user, origin="Miami", destination="Curacao"
            )
        other = Business.objects.create(name="Other", slug="other-local", vertical="LOGISTICS")
        BusinessUser.objects.create(business=other, user=self.user, role=BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=other,
            plan=self.plan,
            status="pending_checkout",
            payment_provider="stripe",
            billing_interval="yearly",
            billing_currency="eur",
        )
        other_customer = Client.objects.create(business=other, first_name="PRIVATE_OTHER_TENANT")
        foreign = register_parcel(
            business=other,
            actor=self.user,
            client=other_customer,
            origin="Miami",
            destination="Curacao",
            package_description="PRIVATE_OTHER_TENANT",
        )
        create_shipment(
            business=other, actor=self.user, origin="PRIVATE_OTHER_TENANT", destination="Elsewhere"
        )
        response = self.client.get(reverse("agent_dashboard"))
        for key, expected in {
            "active_parcel_count": 11,
            "received_waiting_parcel_count": 8,
            "in_transit_parcel_count": 1,
            "ready_parcel_count": 1,
            "active_shipment_count": 6,
            "delivered_this_month_count": 1,
        }.items():
            self.assertEqual(response.context[key], expected, key)
        self.assertNotContains(response, foreign.tracking_code)
        self.assertNotContains(response, "PRIVATE_OTHER_TENANT")
        for key in ("recent_tracking_events", "active_shipments", "parcels_requiring_attention"):
            self.assertEqual(len(response.context[key]), 5)
            self.assertTrue(
                all(row.business_id == self.business.pk for row in response.context[key])
            )

    def test_delivered_month_uses_business_timezone_half_open_boundaries_and_distinct_parcels(self):
        first = self.move(self.parcel(), "DELIVERED")
        second = self.move(self.parcel(), "DELIVERED")
        third = self.move(self.parcel(), "DELIVERED")
        # Curacao is UTC-4: October begins at 04:00 UTC and ends at November 04:00 UTC.
        start = datetime(2026, 10, 1, 4, tzinfo=UTC)
        end = datetime(2026, 11, 1, 4, tzinfo=UTC)
        # Historical clock fixtures use the base queryset; production writes stay guarded.
        for parcel, stamp in ((first, start), (second, start - timedelta(seconds=1)), (third, end)):
            QuerySet(model=ParcelEvent, using="default").filter(
                parcel=parcel, status="DELIVERED"
            ).update(timestamp=stamp)
        QuerySet(model=ParcelEvent, using="default").bulk_create(
            [
                ParcelEvent(
                    business=self.business,
                    parcel=first,
                    event_type=ParcelEvent.Type.STATUS,
                    status="DELIVERED",
                    timestamp=start + timedelta(days=1),
                ),
            ]
        )
        with mock.patch("apps.crm.views.timezone.now", return_value=start + timedelta(days=4)):
            response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.context["delivered_this_month_count"], 1)

    def test_direct_signup_uses_the_normal_operational_dashboard_with_truthful_pending_state(self):
        response = self.client.post(
            reverse("logistics_application_create"),
            {**application_data(), "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertEqual(response.url, reverse("agent_dashboard"))
        dashboard = self.client.get(response.url)
        self.assertTemplateUsed(dashboard, "crm/agent_dashboard/agent_dashboard.html")
        self.assertContains(dashboard, "billing bypass active")
        self.assertEqual(
            dashboard.context["current_subscription"].status,
            BusinessSubscription.Status.PENDING_CHECKOUT,
        )
        self.assertEqual(dashboard.context["current_subscription"].provider_customer_id, "")

    def test_restricted_subscription_uses_payment_state_and_is_never_bypassed(self):
        self.plan.is_active = True
        self.plan.save(update_fields=["is_active"])
        self.subscription.status = BusinessSubscription.Status.PAST_DUE
        self.subscription.provider_customer_id = "cus_test"
        self.subscription.provider_subscription_id = "sub_test"
        self.subscription.provider_price_id = "price_test"
        self.subscription.past_due_since = timezone.now() - timedelta(days=10)
        self.subscription.grace_period_ends_at = timezone.now() - timedelta(days=3)
        self.subscription.save()
        self.assertEqual(self.subscription.access_mode, SubscriptionAccessMode.RESTRICTED)
        response = self.client.get(reverse("agent_dashboard"))
        self.assertTemplateUsed(response, "logistics/pending_checkout_dashboard.html")
        self.assertContains(response, "Review subscription")
        self.assertNotContains(response, "billing bypass active")
