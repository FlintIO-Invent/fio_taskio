from datetime import time
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.crm.models import BusinessService
from config import Settings
from helpers import build_public_url

from .localization import format_money_for_business, parse_localized_decimal
from .models import (
    Business,
    BusinessBookingSettings,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    WeeklyAvailability,
)
from .utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    MULTI_WORKSPACE_EMAIL_MESSAGE,
    SAME_WORKSPACE_EMAIL_MESSAGE,
    business_has_active_subscription,
    business_is_trialing,
    business_limit_reached,
    business_required,
    business_role_required,
    can_use_module,
    get_current_business,
    get_current_business_membership,
)


class BusinessModelTests(TestCase):
    def test_business_slug_is_unique(self):
        Business.objects.create(name="Motionmate HQ", slug="motionmate-hq")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Business.objects.create(name="Motionmate HQ 2", slug="motionmate-hq")

    def test_formatted_address_lines_prefers_structured_fields_and_falls_back_to_legacy_address(
        self,
    ):
        legacy_business = Business.objects.create(
            name="Legacy Address Workspace",
            slug="legacy-address-workspace",
            address="Front Street, Philipsburg",
        )
        structured_business = Business.objects.create(
            name="Structured Address Workspace",
            slug="structured-address-workspace",
            address_line_1="Herengracht 101",
            city="Amsterdam",
            region="North Holland",
            postal_code="1015 BJ",
            country="Netherlands",
        )

        self.assertEqual(
            legacy_business.formatted_address_lines,
            ["Front Street, Philipsburg"],
        )
        self.assertEqual(
            structured_business.formatted_address_lines,
            ["Herengracht 101", "1015 BJ Amsterdam", "Netherlands"],
        )

    def test_formatted_address_lines_use_caribbean_order_and_skip_unused_postal_code(self):
        business = Business.objects.create(
            name="Caribbean Address Workspace",
            slug="caribbean-address-workspace",
            address_line_1="Front Street 12",
            address_line_2="Suite 4",
            city="Philipsburg",
            region="Sint Maarten",
            postal_code="N/A",
            country="Sint Maarten",
        )

        self.assertEqual(
            business.formatted_address_lines,
            ["Front Street 12", "Suite 4", "Philipsburg", "Sint Maarten"],
        )

    def test_money_formatting_uses_business_currency_locale_and_country(self):
        dutch_business = Business.objects.create(
            name="Amsterdam Workspace",
            slug="amsterdam-workspace",
            country="Netherlands",
            currency=Business.Currency.EUR,
            default_locale="nl-NL",
        )
        caribbean_business = Business.objects.create(
            name="Caribbean Workspace",
            slug="caribbean-workspace",
            country="Sint Maarten",
            currency=Business.Currency.USD,
            default_locale="en-SX",
        )

        self.assertEqual(format_money_for_business(Decimal("1234.56"), dutch_business), "€1.234,56")
        self.assertEqual(
            format_money_for_business(Decimal("1234.56"), caribbean_business), "$1,234.56"
        )
        self.assertEqual(parse_localized_decimal("1.234,56", dutch_business), Decimal("1234.56"))
        self.assertEqual(
            parse_localized_decimal("1,234.56", caribbean_business), Decimal("1234.56")
        )


class EmailConfigurationTests(TestCase):
    def test_email_settings_support_env_driven_smtp_without_hardcoded_credentials(self):
        app_settings = Settings(
            _env_file=None,
            default_from_email="no-reply@motionmate.test",
            server_email="server@motionmate.test",
            email_backend="django.core.mail.backends.smtp.EmailBackend",
            email_host="smtp.motionmate.test",
            email_port=2525,
            email_host_user="motionmate-smtp-user",
            email_host_password="",
            email_use_tls=True,
            email_use_ssl=False,
            email_timeout=15,
            motionmate_public_base_url="https://www.motionmate.net/",
            motionmate_support_email="support@motionmate.net",
        )

        self.assertEqual(app_settings.default_from_email, "no-reply@motionmate.test")
        self.assertEqual(app_settings.server_email, "server@motionmate.test")
        self.assertEqual(app_settings.email_backend, "django.core.mail.backends.smtp.EmailBackend")
        self.assertEqual(app_settings.email_host, "smtp.motionmate.test")
        self.assertEqual(app_settings.email_port, 2525)
        self.assertEqual(app_settings.email_host_user, "motionmate-smtp-user")
        self.assertEqual(app_settings.email_host_password, "")
        self.assertTrue(app_settings.email_use_tls)
        self.assertFalse(app_settings.email_use_ssl)
        self.assertEqual(app_settings.email_timeout, 15)
        self.assertEqual(app_settings.motionmate_public_base_url, "https://www.motionmate.net")
        self.assertEqual(app_settings.motionmate_support_email, "support@motionmate.net")

    def test_email_timeout_defaults_to_10_seconds(self):
        app_settings = Settings(_env_file=None)

        self.assertEqual(app_settings.email_timeout, 10)

    @override_settings(MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net/")
    def test_build_public_url_uses_configured_public_base_url(self):
        self.assertEqual(
            build_public_url("/accounts/password-reset/confirm/example/"),
            "https://www.motionmate.net/accounts/password-reset/confirm/example/",
        )

    @override_settings(MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net/")
    def test_build_public_url_strips_configured_base_trailing_slash(self):
        self.assertEqual(build_public_url(""), "https://www.motionmate.net")

    @override_settings(MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net/")
    def test_build_public_url_does_not_create_double_slashes(self):
        self.assertEqual(
            build_public_url("crm/public_request/motionmate/"),
            "https://www.motionmate.net/crm/public_request/motionmate/",
        )

    @override_settings(MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net/")
    def test_build_public_url_prefers_configured_public_base_url_over_request_host(self):
        request = RequestFactory().get(
            "/businesses/team/",
            secure=True,
            HTTP_HOST="staging.motionmate.test",
        )

        self.assertEqual(
            build_public_url("/accounts/invitations/accept/token/", request=request),
            "https://www.motionmate.net/accounts/invitations/accept/token/",
        )

    @override_settings(
        ALLOWED_HOSTS=["pilot.motionmate.test"],
        MOTIONMATE_PUBLIC_BASE_URL="",
    )
    def test_build_public_url_falls_back_to_request_when_no_public_base_url(self):
        request = RequestFactory().get(
            "/businesses/team/",
            secure=True,
            HTTP_HOST="pilot.motionmate.test",
        )

        self.assertEqual(
            build_public_url("/accounts/invitations/accept/token/", request=request),
            "https://pilot.motionmate.test/accounts/invitations/accept/token/",
        )

    @override_settings(MOTIONMATE_PUBLIC_BASE_URL="")
    def test_build_public_url_returns_path_without_public_base_url_or_request(self):
        self.assertEqual(build_public_url("/relative/path/"), "/relative/path/")


class BusinessUserModelTests(TestCase):
    def test_membership_is_unique_per_user_and_business(self):
        user = TaskIOUser.objects.create_user(
            email="owner@example.com",
            password="testpass123",
        )
        business = Business.objects.create(name="Motionmate HQ", slug="motionmate-hq")
        BusinessUser.objects.create(user=user, business=business, role=BusinessUser.Role.OWNER)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BusinessUser.objects.create(
                    user=user, business=business, role=BusinessUser.Role.ADMIN
                )


class SubscriptionAccessTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Motionmate HQ", slug="motionmate-hq")
        self.plan = ClarivoPlan.objects.create(
            name="Growth",
            slug="growth",
            price_monthly=Decimal("49.00"),
            price_yearly=Decimal("490.00"),
            allow_invoicing=True,
            allow_public_booking=True,
        )

    def test_active_subscription_exposes_access_helpers(self):
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        self.assertTrue(self.business.has_active_subscription)
        self.assertFalse(self.business.is_trialing)
        self.assertTrue(business_has_active_subscription(self.business))
        self.assertTrue(can_use_module(self.business, "invoicing"))
        self.assertTrue(can_use_module(self.business, "clients"))
        self.assertFalse(can_use_module(self.business, "appointments"))

    def test_trialing_subscription_keeps_enabled_modules_available(self):
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.TRIALING,
        )

        self.assertTrue(self.business.is_trialing)
        self.assertTrue(business_is_trialing(self.business))
        self.assertTrue(can_use_module(self.business, "public_booking"))
        self.assertTrue(can_use_module(self.business, "public_request_form"))

    def test_cancelled_subscription_has_no_module_access(self):
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.CANCELLED,
        )

        self.assertFalse(self.business.has_active_subscription)
        self.assertFalse(business_has_active_subscription(self.business))
        self.assertFalse(can_use_module(self.business, "invoicing"))


class MotionmatePlanCatalogTests(TestCase):
    def test_default_motionmate_plans_have_agreed_prices_limits_and_modules(self):
        expected = {
            "starter": {
                "monthly": Decimal("19.00"),
                "yearly": Decimal("190.00"),
                "users": 2,
                "clients": 100,
                "invoices": 50,
                "appointments": 0,
                "public_bookings": 0,
                "allow_appointments": False,
                "allow_public_booking": False,
            },
            "pro": {
                "monthly": Decimal("69.00"),
                "yearly": Decimal("690.00"),
                "users": 5,
                "clients": 500,
                "invoices": 250,
                "appointments": 250,
                "public_bookings": 0,
                "allow_appointments": True,
                "allow_public_booking": False,
            },
            "business": {
                "monthly": Decimal("119.00"),
                "yearly": Decimal("1190.00"),
                "users": 15,
                "clients": 2000,
                "invoices": 1000,
                "appointments": 1000,
                "public_bookings": 1000,
                "allow_appointments": True,
                "allow_public_booking": True,
            },
        }

        plans = list(ClarivoPlan.motionmate_plans())

        self.assertEqual([plan.slug for plan in plans], ["starter", "pro", "business"])
        for plan in plans:
            with self.subTest(plan=plan.slug):
                expected_plan = expected[plan.slug]
                self.assertEqual(plan.price_monthly, expected_plan["monthly"])
                self.assertEqual(plan.price_yearly, expected_plan["yearly"])
                self.assertEqual(plan.max_users, expected_plan["users"])
                self.assertEqual(plan.max_clients, expected_plan["clients"])
                self.assertEqual(plan.max_invoices_per_month, expected_plan["invoices"])
                self.assertEqual(
                    plan.max_appointments_per_month,
                    expected_plan["appointments"],
                )
                self.assertEqual(
                    plan.max_public_bookings_per_month,
                    expected_plan["public_bookings"],
                )
                self.assertTrue(plan.allows_module("client_management"))
                self.assertTrue(plan.allows_module("invoicing"))
                self.assertEqual(
                    plan.allows_module("appointments"),
                    expected_plan["allow_appointments"],
                )
                self.assertEqual(
                    plan.allows_module("public_booking"),
                    expected_plan["allow_public_booking"],
                )
                self.assertEqual(
                    plan.allows_module("public_booking_requests"),
                    expected_plan["allow_public_booking"],
                )
                self.assertEqual(
                    plan.allows_module("public_request_form"),
                    expected_plan["allow_public_booking"],
                )
                self.assertEqual(
                    plan.regional_prices["netherlands"]["tax_note"],
                    "ex. VAT",
                )

        self.assertTrue(ClarivoPlan.objects.get(slug="pro").is_recommended)
        self.assertFalse(ClarivoPlan.objects.get(slug="starter").is_recommended)
        self.assertFalse(ClarivoPlan.objects.get(slug="business").is_recommended)

    def test_display_pricing_defaults_publicly_and_uses_netherlands_business_context(self):
        plan = ClarivoPlan.objects.get(slug="business")
        dutch_business = Business.objects.create(
            name="Amsterdam Ops",
            slug="amsterdam-ops",
            country="Netherlands",
        )

        public_pricing = plan.get_display_pricing()
        dutch_pricing = plan.get_display_pricing(business=dutch_business)

        self.assertEqual(public_pricing["monthly_display"], "€119")
        self.assertEqual(public_pricing["yearly_display"], "€1,190")
        self.assertEqual(public_pricing["tax_note"], "")
        self.assertEqual(dutch_pricing["monthly_display"], "€169")
        self.assertEqual(dutch_pricing["yearly_display"], "€1,690")
        self.assertEqual(dutch_pricing["tax_note"], "ex. VAT")

    def test_business_limit_helper_uses_subscription_plan_limits(self):
        business = Business.objects.create(name="Starter Limit HQ", slug="starter-limit-hq")
        plan = ClarivoPlan.objects.get(slug="starter")
        owner = TaskIOUser.objects.create_user(
            email="starter-owner@example.com",
            password="StrongPass123!",
        )
        staff = TaskIOUser.objects.create_user(
            email="starter-staff@example.com",
            password="StrongPass123!",
        )
        BusinessSubscription.objects.create(
            business=business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        BusinessUser.objects.create(user=owner, business=business, role=BusinessUser.Role.OWNER)
        BusinessUser.objects.create(user=staff, business=business, role=BusinessUser.Role.STAFF)

        self.assertTrue(business_limit_reached(business, "users"))
        self.assertFalse(business_limit_reached(business, "clients"))
        self.assertTrue(business_limit_reached(business, "appointments_per_month"))
        self.assertTrue(business_limit_reached(business, "public_bookings_per_month"))

    def test_public_pricing_page_uses_euro_prices_and_no_growth_plan(self):
        ClarivoPlan.objects.create(
            name="Growth",
            slug="growth",
            price_monthly=Decimal("49.00"),
            price_yearly=Decimal("490.00"),
            is_active=True,
        )

        response = self.client.get(reverse("home"), HTTP_HOST="localhost", secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "€19")
        self.assertContains(response, "€69")
        self.assertContains(response, "€119")
        self.assertContains(response, "€1,190 billed yearly")
        self.assertContains(response, "Recommended")
        self.assertContains(response, "Client Management")
        self.assertContains(response, "Public Bookings")
        self.assertNotContains(response, "$0.00")
        self.assertNotContains(response, "Free")
        self.assertNotContains(response, "Growth")
        self.assertNotContains(response, "Public Request Form")
        self.assertNotContains(response, "Public booking requests")

    def test_starter_direct_urls_block_locked_services_cleanly(self):
        business = Business.objects.create(
            name="Starter Direct URL",
            slug="starter-direct-url",
        )
        user = TaskIOUser.objects.create_user(
            email="starter-direct-owner@example.com",
            password="StrongPass123!",
        )
        BusinessSubscription.objects.create(
            business=business,
            plan=ClarivoPlan.objects.get(slug="starter"),
            status=BusinessSubscription.Status.ACTIVE,
        )
        BusinessUser.objects.create(
            user=user,
            business=business,
            role=BusinessUser.Role.OWNER,
        )
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = business.id
        session.save()
        self.client.force_login(user)

        client_response = self.client.get(reverse("staff_client_list"))
        invoice_response = self.client.get(reverse("invoice_list"))
        appointment_response = self.client.get(reverse("appointment_list"), follow=True)
        public_booking_response = self.client.get(reverse("public_booking", args=[business.slug]))

        self.assertEqual(client_response.status_code, 200)
        self.assertEqual(invoice_response.status_code, 200)
        self.assertRedirects(appointment_response, reverse("business_subscription"))
        self.assertContains(
            appointment_response,
            "Appointments is not included in the current workspace plan.",
        )
        self.assertEqual(public_booking_response.status_code, 403)
        self.assertContains(
            public_booking_response,
            "Public Bookings Unavailable",
            status_code=403,
        )


class CurrentBusinessTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = TaskIOUser.objects.create_user(
            email="workspace-user@example.com",
            password="testpass123",
        )

    def _build_request(self, session: dict | None = None):
        request = self.factory.get("/")
        request.user = self.user
        request.session = session if session is not None else {}
        return request

    def test_get_current_business_prefers_valid_session_business(self):
        first_business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        second_business = Business.objects.create(name="Beta Workspace", slug="beta-workspace")
        BusinessUser.objects.create(
            user=self.user, business=first_business, role=BusinessUser.Role.STAFF
        )
        BusinessUser.objects.create(
            user=self.user, business=second_business, role=BusinessUser.Role.OWNER
        )

        request = self._build_request({CURRENT_BUSINESS_SESSION_KEY: second_business.id})

        current_business = get_current_business(request)

        self.assertEqual(current_business, second_business)
        self.assertEqual(request.current_business, second_business)

    def test_get_current_business_falls_back_to_first_active_membership(self):
        first_business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        second_business = Business.objects.create(name="Beta Workspace", slug="beta-workspace")
        BusinessUser.objects.create(
            user=self.user, business=first_business, role=BusinessUser.Role.STAFF
        )
        BusinessUser.objects.create(
            user=self.user, business=second_business, role=BusinessUser.Role.OWNER
        )

        request = self._build_request({CURRENT_BUSINESS_SESSION_KEY: 999999})

        current_business = get_current_business(request)

        self.assertEqual(current_business, first_business)
        self.assertEqual(request.session[CURRENT_BUSINESS_SESSION_KEY], first_business.id)

    def test_get_current_business_returns_none_without_membership(self):
        request = self._build_request({CURRENT_BUSINESS_SESSION_KEY: 999999})

        current_business = get_current_business(request)

        self.assertIsNone(current_business)
        self.assertNotIn(CURRENT_BUSINESS_SESSION_KEY, request.session)

    def test_business_required_redirects_to_setup_when_user_has_no_membership(self):
        @business_required()
        def sample_view(request):
            return HttpResponse("ok")

        request = self._build_request()

        response = sample_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("business_setup"))

    def test_business_required_allows_access_and_sets_request_current_business(self):
        business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        BusinessUser.objects.create(user=self.user, business=business, role=BusinessUser.Role.OWNER)

        @business_required()
        def sample_view(request):
            self.assertEqual(request.current_business, business)
            return HttpResponse("ok")

        request = self._build_request()

        response = sample_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_get_current_business_membership_returns_current_workspace_membership(self):
        business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        membership = BusinessUser.objects.create(
            user=self.user,
            business=business,
            role=BusinessUser.Role.ADMIN,
        )

        request = self._build_request()

        resolved_membership = get_current_business_membership(request)

        self.assertEqual(resolved_membership, membership)
        self.assertEqual(request.current_business_membership, membership)

    def test_business_role_required_blocks_non_allowed_roles(self):
        business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        BusinessUser.objects.create(
            user=self.user,
            business=business,
            role=BusinessUser.Role.STAFF,
        )

        @business_role_required(BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)
        def sample_view(request):
            return HttpResponse("ok")

        request = self._build_request()

        with self.assertRaises(PermissionDenied):
            sample_view(request)


class BusinessSettingsViewTests(TestCase):
    def setUp(self):
        self.user = TaskIOUser.objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Jane",
            last_name="Doe",
        )
        self.business = Business.objects.create(
            name="Motionmate HQ",
            slug="motionmate-hq",
            email="hello@motionmate.test",
            country="Sint Maarten",
        )

    def _login_with_role(self, role: str):
        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=role,
        )
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()
        self.client.force_login(self.user)

    def test_owner_can_view_business_settings(self):
        self._login_with_role(BusinessUser.Role.OWNER)

        response = self.client.get(reverse("business_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Business Details")
        self.assertContains(response, "Business type / industry")
        self.assertContains(response, "Default locale")
        self.assertContains(response, "Tax label")
        self.assertContains(response, "Street address")
        self.assertContains(response, "Motionmate HQ")
        self.assertContains(response, 'name="tax_rate"')
        self.assertContains(response, 'step="1.00"')

    def test_business_settings_showcases_ready_public_booking_link(self):
        public_booking_plan = ClarivoPlan.objects.create(
            name="Public Booking",
            slug="business-settings-public-booking",
            allow_public_booking=True,
        )
        BusinessSubscription.objects.create(
            business=self.business,
            plan=public_booking_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        BusinessBookingSettings.objects.create(
            business=self.business,
            booking_enabled=True,
        )
        BusinessService.objects.create(
            business=self.business,
            name="Bookable Inspection",
            is_bookable_online=True,
        )
        WeeklyAvailability.objects.create(
            business=self.business,
            day_of_week=WeeklyAvailability.DayOfWeek.MONDAY,
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        self._login_with_role(BusinessUser.Role.OWNER)

        response = self.client.get(reverse("business_settings"))

        self.assertContains(response, "Public Booking Link")
        self.assertContains(response, "Ready to share")
        self.assertContains(response, reverse("public_booking", args=[self.business.slug]))

    def test_business_settings_form_uses_dutch_address_labels_and_normalizes_postcode(self):
        self.business.country = "Netherlands"
        self.business.save(update_fields=["country", "updated_at"])
        self._login_with_role(BusinessUser.Role.OWNER)

        get_response = self.client.get(reverse("business_settings"))

        self.assertContains(get_response, "Street and house number")
        self.assertContains(get_response, "Postcode")
        self.assertContains(get_response, "Dutch format: 1234 AB.")

        post_response = self.client.post(
            reverse("business_settings"),
            {
                "name": self.business.name,
                "business_type": "",
                "email": self.business.email,
                "phone": "",
                "country": "Netherlands",
                "currency": "EUR",
                "timezone": "Europe/Amsterdam",
                "default_locale": "nl-NL",
                "tax_label": "BTW",
                "tax_rate": "21.00",
                "invoice_prefix": "INV",
                "invoice_start_number": "1",
                "address_line_1": "Herengracht 101",
                "address_line_2": "",
                "city": "Amsterdam",
                "region": "North Holland",
                "postal_code": "1015bj",
                "address": "",
            },
            follow=True,
        )

        self.business.refresh_from_db()

        self.assertRedirects(post_response, reverse("business_settings"))
        self.assertEqual(self.business.postal_code, "1015 BJ")
        self.assertEqual(
            self.business.formatted_address_lines,
            ["Herengracht 101", "1015 BJ Amsterdam", "Netherlands"],
        )

    def test_admin_can_update_business_settings(self):
        self._login_with_role(BusinessUser.Role.ADMIN)

        response = self.client.post(
            reverse("business_settings"),
            {
                "name": "Motionmate Caribbean",
                "business_type": "Cleaning Service",
                "email": "billing@motionmate.test",
                "phone": "+1 721 555 0100",
                "country": "Sint Maarten",
                "currency": "XCD",
                "timezone": "America/Lower_Princes",
                "default_locale": "en-SX",
                "tax_label": "TOT",
                "tax_rate": "6.50",
                "invoice_prefix": "CLR",
                "invoice_start_number": "250",
                "address_line_1": "Front Street 12",
                "address_line_2": "Suite 4",
                "city": "Philipsburg",
                "region": "",
                "postal_code": "",
                "address": "Blue building next to the harbor.",
            },
            follow=True,
        )

        self.business.refresh_from_db()

        self.assertRedirects(response, reverse("business_settings"))
        self.assertEqual(self.business.name, "Motionmate Caribbean")
        self.assertEqual(self.business.business_type, "Cleaning Service")
        self.assertEqual(self.business.currency, "XCD")
        self.assertEqual(self.business.timezone, "America/Lower_Princes")
        self.assertEqual(self.business.default_locale, "en-SX")
        self.assertEqual(self.business.tax_label, "TOT")
        self.assertEqual(self.business.tax_rate, Decimal("6.50"))
        self.assertEqual(self.business.invoice_prefix, "CLR")
        self.assertEqual(self.business.invoice_start_number, 250)
        self.assertEqual(self.business.address_line_1, "Front Street 12")
        self.assertEqual(self.business.address_line_2, "Suite 4")
        self.assertEqual(self.business.city, "Philipsburg")
        self.assertEqual(self.business.postal_code, "")
        self.assertEqual(self.business.address, "Blue building next to the harbor.")
        self.assertContains(response, "Business settings updated.")

    def test_staff_viewer_and_accountant_cannot_edit_business_settings(self):
        restricted_roles = [
            BusinessUser.Role.STAFF,
            BusinessUser.Role.VIEWER,
            BusinessUser.Role.ACCOUNTANT,
        ]

        for role in restricted_roles:
            with self.subTest(role=role):
                BusinessUser.objects.all().delete()
                self.client.logout()
                self._login_with_role(role)

                response = self.client.get(reverse("business_settings"))

                self.assertEqual(response.status_code, 403)


class BusinessBookingSettingsTests(TestCase):
    def setUp(self):
        self.user = TaskIOUser.objects.create_user(
            email="booking-owner@example.com",
            password="StrongPass123!",
            first_name="Booking",
            last_name="Owner",
        )
        self.business = Business.objects.create(
            name="Motionmate Booking HQ",
            slug="motionmate-booking-hq",
            email="booking@motionmate.test",
            country="Sint Maarten",
        )
        self.other_business = Business.objects.create(
            name="Other Booking Workspace",
            slug="other-booking-workspace",
        )
        self.public_booking_plan = ClarivoPlan.objects.create(
            name="Public Booking Plan",
            slug="public-booking-plan-tests",
            allow_public_booking=True,
        )
        self.locked_plan = ClarivoPlan.objects.create(
            name="Locked Booking Plan",
            slug="locked-booking-plan-tests",
            allow_public_booking=False,
        )

    def _login_with_role(self, role: str):
        BusinessUser.objects.all().delete()
        self.client.logout()
        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=role,
        )
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()
        self.client.force_login(self.user)

    def _settings_payload(self, **overrides):
        payload = {
            "form_kind": "settings",
            "booking_enabled": "on",
            "default_duration_minutes": "45",
            "minimum_notice_hours": "12",
            "maximum_days_ahead": "21",
            "buffer_minutes": "10",
            "confirmation_mode": BusinessBookingSettings.ConfirmationMode.REQUEST_ONLY,
            "public_booking_instructions": "Tell us what you need and request a time.",
            "cancellation_policy_text": "Please contact us to cancel.",
            "reschedule_policy_text": "Please contact us to reschedule.",
        }
        payload.update(overrides)
        return payload

    def _availability_payload(self, **overrides):
        payload = {
            "form_kind": "availability",
            "day_of_week": WeeklyAvailability.DayOfWeek.MONDAY,
            "start_time": "09:00",
            "end_time": "17:00",
            "is_active": "on",
        }
        payload.update(overrides)
        return payload

    def test_booking_settings_validation_rejects_invalid_values(self):
        settings = BusinessBookingSettings(
            business=self.business,
            default_duration_minutes=0,
            maximum_days_ahead=0,
        )

        with self.assertRaises(ValidationError):
            settings.full_clean()

    def test_weekly_availability_validation_rejects_end_before_start(self):
        availability = WeeklyAvailability(
            business=self.business,
            day_of_week=WeeklyAvailability.DayOfWeek.MONDAY,
            start_time=time(17, 0),
            end_time=time(9, 0),
        )

        with self.assertRaises(ValidationError):
            availability.full_clean()

    def test_owner_admin_and_staff_can_access_booking_settings(self):
        for role in [BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN, BusinessUser.Role.STAFF]:
            with self.subTest(role=role):
                self._login_with_role(role)

                response = self.client.get(reverse("business_booking_settings"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Booking Settings")
                self.assertContains(response, "Add Weekly Availability")

    def test_accountant_and_viewer_cannot_edit_booking_settings(self):
        for role in [
            BusinessUser.Role.ACCOUNTANT,
            BusinessUser.Role.VIEWER,
        ]:
            with self.subTest(role=role):
                self._login_with_role(role)

                response = self.client.get(reverse("business_booking_settings"))

                self.assertEqual(response.status_code, 403)

    def test_booking_settings_are_created_for_current_business_only(self):
        self._login_with_role(BusinessUser.Role.OWNER)

        response = self.client.get(reverse("business_booking_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(BusinessBookingSettings.objects.filter(business=self.business).exists())
        self.assertFalse(
            BusinessBookingSettings.objects.filter(business=self.other_business).exists()
        )

    def test_settings_post_updates_current_business_only(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        other_settings = BusinessBookingSettings.objects.create(
            business=self.other_business,
            booking_enabled=False,
            default_duration_minutes=90,
        )

        response = self.client.post(
            reverse("business_booking_settings"),
            self._settings_payload(default_duration_minutes="30"),
            follow=True,
        )

        current_settings = BusinessBookingSettings.objects.get(business=self.business)
        other_settings.refresh_from_db()

        self.assertRedirects(response, reverse("business_booking_settings"))
        self.assertTrue(current_settings.booking_enabled)
        self.assertEqual(current_settings.default_duration_minutes, 30)
        self.assertFalse(other_settings.booking_enabled)
        self.assertEqual(other_settings.default_duration_minutes, 90)

    def test_valid_weekly_availability_can_be_created_for_current_business(self):
        self._login_with_role(BusinessUser.Role.ADMIN)

        response = self.client.post(
            reverse("business_booking_settings"),
            self._availability_payload(),
            follow=True,
        )

        availability = WeeklyAvailability.objects.get(business=self.business)

        self.assertRedirects(response, reverse("business_booking_settings"))
        self.assertEqual(availability.day_of_week, WeeklyAvailability.DayOfWeek.MONDAY)
        self.assertEqual(availability.start_time, time(9, 0))
        self.assertEqual(availability.end_time, time(17, 0))
        self.assertTrue(availability.is_active)
        self.assertFalse(WeeklyAvailability.objects.filter(business=self.other_business).exists())

    def test_admin_can_create_staff_specific_availability(self):
        self._login_with_role(BusinessUser.Role.ADMIN)

        response = self.client.post(
            reverse("business_booking_settings"),
            self._availability_payload(staff_member=self.user.pk),
            follow=True,
        )

        availability = WeeklyAvailability.objects.get(business=self.business)

        self.assertRedirects(response, reverse("business_booking_settings"))
        self.assertEqual(availability.staff_member, self.user)
        self.assertContains(response, "Booking Owner")

    def test_staff_can_create_own_availability(self):
        self._login_with_role(BusinessUser.Role.STAFF)

        response = self.client.post(
            reverse("business_booking_settings"),
            self._availability_payload(staff_member=""),
            follow=True,
        )

        availability = WeeklyAvailability.objects.get(business=self.business)

        self.assertRedirects(response, reverse("business_booking_settings"))
        self.assertEqual(availability.staff_member, self.user)
        self.assertContains(response, "Booking Owner")

    def test_staff_cannot_update_booking_rules(self):
        self._login_with_role(BusinessUser.Role.STAFF)
        settings = BusinessBookingSettings.objects.create(
            business=self.business,
            booking_enabled=False,
            default_duration_minutes=60,
        )

        response = self.client.post(
            reverse("business_booking_settings"),
            self._settings_payload(default_duration_minutes="30"),
        )

        settings.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertFalse(settings.booking_enabled)
        self.assertEqual(settings.default_duration_minutes, 60)

    def test_invalid_weekly_availability_is_rejected(self):
        self._login_with_role(BusinessUser.Role.OWNER)

        response = self.client.post(
            reverse("business_booking_settings"),
            self._availability_payload(start_time="17:00", end_time="09:00"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "End time must be after the start time.")
        self.assertFalse(WeeklyAvailability.objects.filter(business=self.business).exists())

    def test_other_business_availability_cannot_be_deactivated(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        other_availability = WeeklyAvailability.objects.create(
            business=self.other_business,
            day_of_week=WeeklyAvailability.DayOfWeek.TUESDAY,
            start_time=time(9, 0),
            end_time=time(12, 0),
        )

        response = self.client.post(
            reverse(
                "business_weekly_availability_deactivate",
                args=[other_availability.id],
            )
        )

        other_availability.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertTrue(other_availability.is_active)

    def test_staff_cannot_deactivate_business_wide_availability(self):
        self._login_with_role(BusinessUser.Role.STAFF)
        availability = WeeklyAvailability.objects.create(
            business=self.business,
            day_of_week=WeeklyAvailability.DayOfWeek.FRIDAY,
            start_time=time(10, 0),
            end_time=time(14, 0),
        )

        response = self.client.post(
            reverse(
                "business_weekly_availability_deactivate",
                args=[availability.id],
            ),
        )
        availability.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertTrue(availability.is_active)

    def test_staff_can_deactivate_own_availability(self):
        self._login_with_role(BusinessUser.Role.STAFF)
        availability = WeeklyAvailability.objects.create(
            business=self.business,
            staff_member=self.user,
            day_of_week=WeeklyAvailability.DayOfWeek.FRIDAY,
            start_time=time(10, 0),
            end_time=time(14, 0),
        )

        response = self.client.post(
            reverse(
                "business_weekly_availability_deactivate",
                args=[availability.id],
            ),
            follow=True,
        )
        availability.refresh_from_db()

        self.assertRedirects(response, reverse("business_booking_settings"))
        self.assertFalse(availability.is_active)

    def test_deactivated_availability_no_longer_appears_as_active(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        availability = WeeklyAvailability.objects.create(
            business=self.business,
            day_of_week=WeeklyAvailability.DayOfWeek.FRIDAY,
            start_time=time(10, 0),
            end_time=time(14, 0),
        )

        response = self.client.post(
            reverse(
                "business_weekly_availability_deactivate",
                args=[availability.id],
            ),
            follow=True,
        )
        availability.refresh_from_db()

        self.assertRedirects(response, reverse("business_booking_settings"))
        self.assertFalse(availability.is_active)
        self.assertNotIn(availability, list(response.context["availability_blocks"]))

    def test_plan_message_allows_settings_preparation_when_public_booking_locked(self):
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.locked_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        self._login_with_role(BusinessUser.Role.OWNER)

        response = self.client.get(reverse("business_booking_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Public Bookings is not included in the current workspace plan.",
        )
        self.assertContains(response, "You can still prepare these settings now")

    def test_plan_message_shows_setup_status_when_public_booking_allowed(self):
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.public_booking_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        self._login_with_role(BusinessUser.Role.ADMIN)

        response = self.client.get(reverse("business_booking_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Public bookings require setup")

    def test_staff_can_see_ready_public_booking_link_in_booking_settings(self):
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.public_booking_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        BusinessBookingSettings.objects.create(
            business=self.business,
            booking_enabled=True,
        )
        BusinessService.objects.create(
            business=self.business,
            name="Online Consultation",
            is_bookable_online=True,
        )
        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=BusinessUser.Role.STAFF,
        )
        WeeklyAvailability.objects.create(
            business=self.business,
            staff_member=self.user,
            day_of_week=WeeklyAvailability.DayOfWeek.MONDAY,
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()
        self.client.force_login(self.user)

        response = self.client.get(reverse("business_booking_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Public Booking Link")
        self.assertContains(response, "Ready to share")
        self.assertContains(response, reverse("public_booking", args=[self.business.slug]))


class BusinessSubscriptionViewTests(TestCase):
    def setUp(self):
        self.user = TaskIOUser.objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Jane",
            last_name="Doe",
        )
        self.business = Business.objects.create(
            name="Motionmate HQ",
            slug="motionmate-hq",
            email="hello@motionmate.test",
            country="Sint Maarten",
        )
        self.starter_plan = ClarivoPlan.objects.get(slug="starter")
        self.pro_plan = ClarivoPlan.objects.get(slug="pro")
        self.business_plan = ClarivoPlan.objects.get(slug="business")

    def _login_with_role(self, role: str):
        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=role,
        )
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()
        self.client.force_login(self.user)

    def _add_business_member(self, email: str, role: str = BusinessUser.Role.STAFF):
        user = TaskIOUser.objects.create_user(
            email=email,
            password="StrongPass123!",
        )
        return BusinessUser.objects.create(
            user=user,
            business=self.business,
            role=role,
        )

    def test_owner_can_view_subscription_page(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.pro_plan,
            status=BusinessSubscription.Status.TRIALING,
        )

        response = self.client.get(reverse("business_subscription"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Subscription")
        self.assertContains(response, "Motionmate HQ")
        self.assertContains(response, "Current Plan")
        self.assertContains(response, "Pro")
        self.assertNotContains(response, "Recommended")

    def test_subscription_page_shows_netherlands_prices_as_ex_vat(self):
        self.business.country = "Netherlands"
        self.business.save(update_fields=["country", "updated_at"])
        self._login_with_role(BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.starter_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        response = self.client.get(reverse("business_subscription"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "€29")
        self.assertContains(response, "€99")
        self.assertContains(response, "€169")
        self.assertContains(response, "ex. VAT")
        self.assertContains(response, "Current Plan")
        self.assertContains(response, "Recommended")

    def test_owner_can_change_subscription_plan_and_keep_trialing_status(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.starter_plan,
            status=BusinessSubscription.Status.TRIALING,
        )

        response = self.client.post(
            reverse("business_subscription"),
            {"plan": self.pro_plan.id},
            follow=True,
        )

        subscription.refresh_from_db()

        self.assertRedirects(response, reverse("business_subscription"))
        self.assertEqual(subscription.plan, self.pro_plan)
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertTrue(subscription.can_use_module("appointments"))
        self.assertContains(response, "Workspace plan updated to Pro")

    def test_over_quota_downgrade_requires_confirmation_before_plan_changes(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        self._add_business_member("staff-one@example.com")
        self._add_business_member("staff-two@example.com")
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.business_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        response = self.client.post(
            reverse("business_subscription"),
            {"plan": self.starter_plan.id},
        )

        subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(subscription.plan, self.business_plan)
        self.assertContains(response, "Review the limits before changing to Starter.")
        self.assertContains(response, "Confirm change to Starter")
        self.assertContains(response, "Over Starter quota")
        self.assertContains(response, "Team users: using 3, Starter allows 2.")
        self.assertContains(response, "Appointments")
        self.assertContains(response, "Public Bookings")
        self.assertNotContains(response, "Workspace plan updated to Starter")

    def test_confirmed_over_quota_downgrade_keeps_records_and_updates_plan(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        self._add_business_member("staff-one@example.com")
        self._add_business_member("staff-two@example.com")
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.business_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        response = self.client.post(
            reverse("business_subscription"),
            {
                "plan": self.starter_plan.id,
                "confirm_plan_change": "1",
            },
            follow=True,
        )

        subscription.refresh_from_db()
        self.assertRedirects(response, reverse("business_subscription"))
        self.assertEqual(subscription.plan, self.starter_plan)
        self.assertEqual(self.business.memberships.filter(is_active=True).count(), 3)
        self.assertTrue(business_limit_reached(self.business, "users"))
        self.assertContains(response, "Workspace plan updated to Starter")
        self.assertContains(response, "Existing records were kept")

    def test_module_loss_downgrade_requires_confirmation_even_within_quota(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.business_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        response = self.client.post(
            reverse("business_subscription"),
            {"plan": self.pro_plan.id},
        )

        subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(subscription.plan, self.business_plan)
        self.assertContains(response, "Confirm change to Pro")
        self.assertContains(response, "Current usage is within the Pro quotas.")
        self.assertContains(response, "Modules no longer included")
        self.assertContains(response, "Public Bookings")

    def test_owner_can_start_trial_from_subscription_page_if_missing(self):
        self._login_with_role(BusinessUser.Role.OWNER)

        response = self.client.post(
            reverse("business_subscription"),
            {"plan": self.pro_plan.id},
            follow=True,
        )

        subscription = BusinessSubscription.objects.get(business=self.business)

        self.assertRedirects(response, reverse("business_subscription"))
        self.assertEqual(subscription.plan, self.pro_plan)
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertIsNotNone(subscription.trial_start)
        self.assertIsNotNone(subscription.trial_end)

    def test_admin_cannot_access_subscription_page(self):
        self._login_with_role(BusinessUser.Role.ADMIN)

        response = self.client.get(reverse("business_subscription"))

        self.assertEqual(response.status_code, 403)


class BusinessInvitationViewTests(TestCase):
    def setUp(self):
        self.owner = TaskIOUser.objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Owner",
            last_name="User",
        )
        self.admin = TaskIOUser.objects.create_user(
            email="admin@example.com",
            password="StrongPass123!",
            first_name="Admin",
            last_name="User",
        )
        self.business = Business.objects.create(
            name="Motionmate HQ",
            slug="motionmate-hq-team",
            email="hello@motionmate.test",
            country="Sint Maarten",
        )

    def _login(self, user: TaskIOUser, role: str):
        BusinessUser.objects.create(
            user=user,
            business=self.business,
            role=role,
        )
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()
        self.client.force_login(user)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net/",
    )
    def test_owner_can_create_workspace_invitation(self):
        mail.outbox.clear()
        self._login(self.owner, BusinessUser.Role.OWNER)

        response = self.client.post(
            reverse("business_team_members"),
            {
                "email": "employee@example.com",
                "role": BusinessUser.Role.STAFF,
            },
            follow=True,
        )

        invitation = BusinessInvitation.objects.get(email="employee@example.com")
        accept_url = f"https://www.motionmate.net{reverse('accept_business_invitation', args=[invitation.token])}"

        self.assertRedirects(response, reverse("business_team_members"))
        self.assertEqual(invitation.business, self.business)
        self.assertEqual(invitation.role, BusinessUser.Role.STAFF)
        self.assertEqual(invitation.status, BusinessInvitation.Status.PENDING)
        self.assertEqual(invitation.invited_by, self.owner)
        self.assertContains(response, "Invitation created and emailed successfully.")
        self.assertContains(response, accept_url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["employee@example.com"])
        self.assertIn("Motionmate", mail.outbox[0].body)
        self.assertIn(self.business.name, mail.outbox[0].body)
        self.assertIn("Staff", mail.outbox[0].body)
        self.assertIn(accept_url, mail.outbox[0].body)
        self.assertNotIn("testserver", mail.outbox[0].body)
        self.assertNotIn("https://www.motionmate.net//", mail.outbox[0].body)

    def test_invite_still_exists_if_email_send_fails(self):
        self._login(self.owner, BusinessUser.Role.OWNER)

        with mock.patch(
            "apps.businesses.views.send_business_invitation_email",
            return_value=False,
        ):
            response = self.client.post(
                reverse("business_team_members"),
                {
                    "email": "failed-email@example.com",
                    "role": BusinessUser.Role.STAFF,
                },
                follow=True,
            )

        invitation = BusinessInvitation.objects.get(email="failed-email@example.com")

        self.assertRedirects(response, reverse("business_team_members"))
        self.assertEqual(invitation.business, self.business)
        self.assertEqual(invitation.status, BusinessInvitation.Status.PENDING)
        self.assertContains(response, "email could not be sent")
        self.assertContains(
            response, reverse("accept_business_invitation", args=[invitation.token])
        )

    def test_admin_cannot_invite_owner_role(self):
        self._login(self.admin, BusinessUser.Role.ADMIN)

        response = self.client.post(
            reverse("business_team_members"),
            {
                "email": "owner-2@example.com",
                "role": BusinessUser.Role.OWNER,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(BusinessInvitation.objects.filter(email="owner-2@example.com").exists())
        self.assertContains(response, "Select a valid choice")

    def test_invite_is_blocked_when_email_already_belongs_to_current_workspace(self):
        existing_user = TaskIOUser.objects.create_user(
            email="employee@example.com",
            password="StrongPass123!",
            first_name="Existing",
            last_name="Member",
        )
        BusinessUser.objects.create(
            user=existing_user,
            business=self.business,
            role=BusinessUser.Role.STAFF,
        )
        self._login(self.owner, BusinessUser.Role.OWNER)

        response = self.client.post(
            reverse("business_team_members"),
            {
                "email": existing_user.email,
                "role": BusinessUser.Role.VIEWER,
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("business_team_members"))
        self.assertEqual(
            BusinessInvitation.objects.filter(
                business=self.business,
                email=existing_user.email,
            ).count(),
            0,
        )
        self.assertContains(response, SAME_WORKSPACE_EMAIL_MESSAGE)

    def test_invite_is_blocked_when_email_has_active_membership_in_other_workspace(self):
        other_workspace_user = TaskIOUser.objects.create_user(
            email="shared.employee@example.com",
            password="StrongPass123!",
            first_name="Shared",
            last_name="Employee",
        )
        other_business = Business.objects.create(
            name="Legacy Workspace",
            slug="legacy-workspace-team",
            email="hello@legacy.test",
            country="Curacao",
        )
        BusinessUser.objects.create(
            user=other_workspace_user,
            business=other_business,
            role=BusinessUser.Role.STAFF,
        )
        self._login(self.owner, BusinessUser.Role.OWNER)

        response = self.client.post(
            reverse("business_team_members"),
            {
                "email": other_workspace_user.email,
                "role": BusinessUser.Role.STAFF,
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("business_team_members"))
        self.assertEqual(
            BusinessInvitation.objects.filter(
                business=self.business,
                email=other_workspace_user.email,
            ).count(),
            0,
        )
        self.assertContains(response, MULTI_WORKSPACE_EMAIL_MESSAGE)
