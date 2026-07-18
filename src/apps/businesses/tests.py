from datetime import time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core import mail
from django.core.checks import run_checks
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from apps.accounts.beta_registration import BETA_PLAN_DISPLAY_NAME, BETA_PLAN_SLUG
from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.crm.models import BusinessService, Client, Lead
from config import Settings
from helpers import build_public_url

from . import stripe_checkout, stripe_config
from .checks import check_stripe_configuration
from .localization import format_money_for_business, parse_localized_decimal
from .models import (
    Business,
    BusinessBookingSettings,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    UserOnboardingState,
    WeeklyAvailability,
)
from .onboarding import (
    get_journey_definitions,
    get_onboarding_status,
    get_or_create_user_onboarding_state,
    get_task_definitions,
    user_can_view_onboarding,
)
from .plan_catalog import (
    DEFAULT_PUBLIC_BILLING_INTERVAL,
    DEFAULT_PUBLIC_PAID_PLAN_SLUG,
    PUBLIC_BILLING_INTERVALS,
    PUBLIC_PAID_PLAN_ORDERING,
    PUBLIC_PAID_PLAN_SLUGS,
    PUBLIC_PRICING_CURRENCIES,
    STANDARD_TRIAL_DAYS,
    is_public_billing_interval,
    is_public_paid_plan_slug,
    normalize_plan_slug,
    normalize_public_billing_interval,
    normalize_public_paid_plan_slug,
    public_billing_interval_or_default,
    public_paid_plan_slug_or_default,
)
from .stripe_checkout import (
    StripeCheckoutAlreadyCompleted,
    StripeCheckoutError,
    create_trial_checkout_session,
    ensure_pending_checkout_subscription,
    resume_trial_checkout_session,
)
from .stripe_config import (
    STRIPE_CHECK_BETA_PLAN,
    STRIPE_CHECK_INVALID_PRICE_ID,
    STRIPE_CHECK_INVALID_PUBLISHABLE_KEY,
    STRIPE_CHECK_INVALID_SECRET_KEY,
    STRIPE_CHECK_MISSING_PRICE_ID,
    STRIPE_CHECK_MISSING_PUBLISHABLE_KEY,
    STRIPE_CHECK_MISSING_SECRET_KEY,
    STRIPE_CHECK_MISSING_WEBHOOK_SECRET,
    STRIPE_CHECK_MIXED_KEY_MODES,
    STRIPE_CHECK_UNKNOWN_PLAN,
    STRIPE_CHECK_UNSUPPORTED_CURRENCY,
    STRIPE_CHECK_UNSUPPORTED_INTERVAL,
    StripeConfigurationError,
    configure_stripe_sdk,
    get_stripe_mode,
    get_stripe_price_id,
    is_stripe_enabled,
    validate_stripe_configuration,
)
from .utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    MULTI_WORKSPACE_EMAIL_MESSAGE,
    SAME_WORKSPACE_EMAIL_MESSAGE,
    assign_business_subscription_plan,
    business_has_active_subscription,
    business_is_trialing,
    business_limit_reached,
    business_required,
    business_role_required,
    can_use_module,
    create_default_trial_subscription,
    get_business_usage_count,
    get_current_business,
    get_current_business_membership,
)


class PlanCatalogPolicyTests(SimpleTestCase):
    def test_public_paid_plan_policy_is_canonical_and_ordered(self):
        self.assertEqual(PUBLIC_PAID_PLAN_SLUGS, ("starter", "pro", "business"))
        self.assertEqual(PUBLIC_PAID_PLAN_ORDERING, PUBLIC_PAID_PLAN_SLUGS)
        self.assertEqual(ClarivoPlan.MOTIONMATE_PLAN_SLUGS, PUBLIC_PAID_PLAN_SLUGS)
        self.assertEqual(DEFAULT_PUBLIC_PAID_PLAN_SLUG, "pro")
        self.assertEqual(DEFAULT_PUBLIC_BILLING_INTERVAL, "monthly")
        self.assertEqual(STANDARD_TRIAL_DAYS, 14)
        self.assertEqual(PUBLIC_BILLING_INTERVALS, ("monthly", "yearly"))
        self.assertEqual(PUBLIC_PRICING_CURRENCIES, ("usd", "eur"))

    def test_public_paid_plan_validation_excludes_internal_and_unknown_slugs(self):
        for slug in PUBLIC_PAID_PLAN_SLUGS:
            with self.subTest(slug=slug):
                self.assertTrue(is_public_paid_plan_slug(slug))

        for slug in (BETA_PLAN_SLUG, "enterprise", "", None):
            with self.subTest(slug=slug):
                self.assertFalse(is_public_paid_plan_slug(slug))

    def test_submitted_plan_slugs_are_normalized_safely(self):
        self.assertEqual(normalize_plan_slug(" Pro "), "pro")
        self.assertEqual(normalize_public_paid_plan_slug(" BUSINESS "), "business")
        self.assertEqual(normalize_public_paid_plan_slug("starter"), "starter")
        self.assertIsNone(normalize_public_paid_plan_slug(BETA_PLAN_SLUG))
        self.assertIsNone(normalize_public_paid_plan_slug("enterprise"))
        self.assertIsNone(normalize_public_paid_plan_slug(None))
        self.assertEqual(normalize_public_billing_interval(" YEARLY "), "yearly")
        self.assertEqual(normalize_public_billing_interval("monthly"), "monthly")
        self.assertIsNone(normalize_public_billing_interval("weekly"))
        self.assertTrue(is_public_billing_interval("yearly"))
        self.assertFalse(is_public_billing_interval("weekly"))

    def test_missing_or_invalid_submitted_slug_resolves_to_default_paid_plan(self):
        self.assertEqual(public_paid_plan_slug_or_default(None), DEFAULT_PUBLIC_PAID_PLAN_SLUG)
        self.assertEqual(public_paid_plan_slug_or_default(""), DEFAULT_PUBLIC_PAID_PLAN_SLUG)
        self.assertEqual(
            public_paid_plan_slug_or_default("enterprise"), DEFAULT_PUBLIC_PAID_PLAN_SLUG
        )
        self.assertEqual(
            public_paid_plan_slug_or_default(BETA_PLAN_SLUG), DEFAULT_PUBLIC_PAID_PLAN_SLUG
        )
        self.assertEqual(public_paid_plan_slug_or_default("starter"), "starter")
        self.assertEqual(public_billing_interval_or_default("yearly"), "yearly")
        self.assertEqual(
            public_billing_interval_or_default("weekly"),
            DEFAULT_PUBLIC_BILLING_INTERVAL,
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


class StripeConfigurationTests(SimpleTestCase):
    @staticmethod
    def _price_map(
        *,
        missing: set[tuple[str, str, str]] | None = None,
        overrides: dict[tuple[str, str, str], str] | None = None,
    ) -> dict[tuple[str, str, str], str]:
        missing = missing or set()
        prices = {
            (plan_slug, interval, currency): f"price_{plan_slug}_{interval}_{currency}"
            for plan_slug in PUBLIC_PAID_PLAN_SLUGS
            for interval in PUBLIC_BILLING_INTERVALS
            for currency in PUBLIC_PRICING_CURRENCIES
            if (plan_slug, interval, currency) not in missing
        }
        if overrides:
            prices.update(overrides)
        return prices

    def _valid_stripe_settings(self, **overrides):
        settings_overrides = {
            "STRIPE_ENABLED": True,
            "STRIPE_PUBLISHABLE_KEY": "pk_test_motionmate",
            "STRIPE_SECRET_KEY": "sk_test_motionmate",
            "STRIPE_WEBHOOK_SECRET": "whsec_motionmate",
            "STRIPE_PRICE_ID_MAP": self._price_map(),
        }
        settings_overrides.update(overrides)
        return settings_overrides

    def _stripe_check_ids(self) -> set[str]:
        return {issue.id for issue in validate_stripe_configuration()}

    def test_settings_trim_stripe_values_without_logging_or_defaults(self):
        app_settings = Settings(
            _env_file=None,
            stripe_publishable_key=" pk_test_replace_me ",
            stripe_secret_key=" ",
            stripe_webhook_secret=" whsec_replace_me ",
            stripe_price_pro_monthly_usd=" price_pro_monthly_usd ",
        )

        self.assertEqual(app_settings.stripe_publishable_key, "pk_test_replace_me")
        self.assertEqual(app_settings.stripe_secret_key, "")
        self.assertEqual(app_settings.stripe_webhook_secret, "whsec_replace_me")
        self.assertEqual(app_settings.stripe_price_pro_monthly_usd, "price_pro_monthly_usd")

    @override_settings(
        STRIPE_ENABLED=False,
        STRIPE_PUBLISHABLE_KEY="",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
        STRIPE_PRICE_ID_MAP={},
    )
    def test_stripe_defaults_disabled_without_requiring_credentials(self):
        self.assertFalse(is_stripe_enabled())
        self.assertEqual(get_stripe_mode(), "disabled")
        self.assertEqual(validate_stripe_configuration(), [])
        self.assertEqual(check_stripe_configuration(None), [])

        registered_stripe_errors = [
            check for check in run_checks() if check.id.startswith("motionmate_stripe.")
        ]
        self.assertEqual(registered_stripe_errors, [])

    def test_stripe_enabled_requires_credentials_and_treats_blank_values_as_missing(self):
        with override_settings(
            STRIPE_ENABLED=True,
            STRIPE_PUBLISHABLE_KEY=" ",
            STRIPE_SECRET_KEY="",
            STRIPE_WEBHOOK_SECRET=" ",
            STRIPE_PRICE_ID_MAP=self._price_map(),
        ):
            self.assertEqual(
                {
                    STRIPE_CHECK_MISSING_PUBLISHABLE_KEY,
                    STRIPE_CHECK_MISSING_SECRET_KEY,
                    STRIPE_CHECK_MISSING_WEBHOOK_SECRET,
                },
                self._stripe_check_ids()
                & {
                    STRIPE_CHECK_MISSING_PUBLISHABLE_KEY,
                    STRIPE_CHECK_MISSING_SECRET_KEY,
                    STRIPE_CHECK_MISSING_WEBHOOK_SECRET,
                },
            )

    def test_stripe_mode_resolves_test_and_live_keys(self):
        with override_settings(**self._valid_stripe_settings()):
            self.assertEqual(get_stripe_mode(), "test")

        with override_settings(
            **self._valid_stripe_settings(
                STRIPE_PUBLISHABLE_KEY="pk_live_motionmate",
                STRIPE_SECRET_KEY="sk_live_motionmate",
            )
        ):
            self.assertEqual(get_stripe_mode(), "live")

    def test_mixed_and_malformed_key_modes_are_rejected_without_exposing_secrets(self):
        sensitive_secret = "sk_live_super_secret_value"
        with override_settings(
            **self._valid_stripe_settings(
                STRIPE_PUBLISHABLE_KEY="pk_test_motionmate",
                STRIPE_SECRET_KEY=sensitive_secret,
            )
        ):
            issues = validate_stripe_configuration()

        self.assertIn(STRIPE_CHECK_MIXED_KEY_MODES, {issue.id for issue in issues})
        self.assertNotIn(sensitive_secret, " ".join(issue.message for issue in issues))

        with override_settings(
            **self._valid_stripe_settings(
                STRIPE_PUBLISHABLE_KEY="pub_test_motionmate",
                STRIPE_SECRET_KEY="secret_test_motionmate",
            )
        ):
            self.assertEqual(
                {
                    STRIPE_CHECK_INVALID_PUBLISHABLE_KEY,
                    STRIPE_CHECK_INVALID_SECRET_KEY,
                },
                self._stripe_check_ids()
                & {
                    STRIPE_CHECK_INVALID_PUBLISHABLE_KEY,
                    STRIPE_CHECK_INVALID_SECRET_KEY,
                },
            )

    def test_price_mapping_resolves_supported_public_plan_interval_and_currency(self):
        with override_settings(STRIPE_PRICE_ID_MAP=self._price_map()):
            self.assertEqual(
                get_stripe_price_id(
                    plan_slug=" Starter ",
                    billing_interval=" monthly ",
                    currency=" USD ",
                ),
                "price_starter_monthly_usd",
            )
            self.assertEqual(
                get_stripe_price_id(
                    plan_slug="pro",
                    billing_interval="yearly",
                    currency="eur",
                ),
                "price_pro_yearly_eur",
            )
            self.assertEqual(
                get_stripe_price_id(
                    plan_slug="BUSINESS",
                    billing_interval="YEARLY",
                    currency="EUR",
                ),
                "price_business_yearly_eur",
            )

    def test_price_mapping_rejects_beta_unknown_interval_and_currency(self):
        with override_settings(STRIPE_PRICE_ID_MAP=self._price_map()):
            invalid_requests = (
                (
                    {"plan_slug": "beta", "billing_interval": "monthly", "currency": "usd"},
                    "Beta is not a public Stripe subscription plan.",
                ),
                (
                    {"plan_slug": "enterprise", "billing_interval": "monthly", "currency": "usd"},
                    "Unsupported Motionmate public plan",
                ),
                (
                    {"plan_slug": "pro", "billing_interval": "weekly", "currency": "usd"},
                    "Unsupported Stripe billing interval.",
                ),
                (
                    {"plan_slug": "pro", "billing_interval": "monthly", "currency": "cad"},
                    "Unsupported Stripe Price currency.",
                ),
            )
            for kwargs, message in invalid_requests:
                with self.subTest(kwargs=kwargs):
                    with self.assertRaisesMessage(StripeConfigurationError, message):
                        get_stripe_price_id(**kwargs)

    def test_price_mapping_missing_or_malformed_price_ids_raise_clear_errors_without_fallback(self):
        missing_starter = {("starter", "monthly", "usd")}
        with override_settings(STRIPE_PRICE_ID_MAP=self._price_map(missing=missing_starter)):
            with self.assertRaisesMessage(
                StripeConfigurationError,
                "Stripe Price ID is not configured for starter monthly usd.",
            ):
                get_stripe_price_id(
                    plan_slug="starter",
                    billing_interval="monthly",
                    currency="usd",
                )

        with override_settings(
            STRIPE_PRICE_ID_MAP=self._price_map(
                overrides={("starter", "monthly", "usd"): "pro_monthly_usd"}
            )
        ):
            with self.assertRaisesMessage(
                StripeConfigurationError,
                "Configured Stripe Price ID must start with price_.",
            ):
                get_stripe_price_id(
                    plan_slug="starter",
                    billing_interval="monthly",
                    currency="usd",
                )

        with override_settings(
            STRIPE_PRICE_ID_MAP={
                ("pro", "monthly", "usd"): "price_pro_monthly_usd",
            }
        ):
            with self.assertRaisesMessage(
                StripeConfigurationError,
                "Stripe Price ID is not configured for starter monthly usd.",
            ):
                get_stripe_price_id(
                    plan_slug="starter",
                    billing_interval="monthly",
                    currency="usd",
                )

    def test_system_checks_report_enabled_configuration_errors(self):
        with override_settings(STRIPE_ENABLED=False, STRIPE_PRICE_ID_MAP={}):
            self.assertEqual(check_stripe_configuration(None), [])

        with override_settings(
            STRIPE_ENABLED=True,
            STRIPE_PUBLISHABLE_KEY="",
            STRIPE_SECRET_KEY="",
            STRIPE_WEBHOOK_SECRET="",
            STRIPE_PRICE_ID_MAP={},
        ):
            error_ids = {error.id for error in check_stripe_configuration(None)}

        self.assertIn(STRIPE_CHECK_MISSING_PUBLISHABLE_KEY, error_ids)
        self.assertIn(STRIPE_CHECK_MISSING_SECRET_KEY, error_ids)
        self.assertIn(STRIPE_CHECK_MISSING_WEBHOOK_SECRET, error_ids)
        self.assertIn(STRIPE_CHECK_MISSING_PRICE_ID, error_ids)

    def test_system_checks_report_invalid_price_ids_and_dimensions(self):
        invalid_price_map = self._price_map(
            overrides={
                ("starter", "monthly", "usd"): "not_a_price",
                ("beta", "monthly", "usd"): "price_beta_monthly_usd",
                ("enterprise", "monthly", "usd"): "price_enterprise_monthly_usd",
                ("pro", "weekly", "usd"): "price_pro_weekly_usd",
                ("pro", "monthly", "cad"): "price_pro_monthly_cad",
            }
        )

        with override_settings(
            **self._valid_stripe_settings(STRIPE_PRICE_ID_MAP=invalid_price_map)
        ):
            error_ids = {error.id for error in check_stripe_configuration(None)}

        self.assertTrue(
            {
                STRIPE_CHECK_INVALID_PRICE_ID,
                STRIPE_CHECK_BETA_PLAN,
                STRIPE_CHECK_UNKNOWN_PLAN,
                STRIPE_CHECK_UNSUPPORTED_INTERVAL,
                STRIPE_CHECK_UNSUPPORTED_CURRENCY,
            }.issubset(error_ids)
        )

    def test_system_checks_do_not_make_stripe_api_calls(self):
        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_config.stripe.Customer, "create") as create_customer:
                self.assertEqual(check_stripe_configuration(None), [])

        create_customer.assert_not_called()

    def test_configure_stripe_sdk_is_lazy_and_requires_enabled_valid_configuration(self):
        with override_settings(STRIPE_ENABLED=False):
            with self.assertRaisesMessage(
                StripeConfigurationError,
                "Stripe subscription billing is disabled.",
            ):
                configure_stripe_sdk()

        original_api_key = stripe_config.stripe.api_key
        try:
            with override_settings(**self._valid_stripe_settings()):
                configured_stripe = configure_stripe_sdk()

            self.assertIs(configured_stripe, stripe_config.stripe)
            self.assertEqual(stripe_config.stripe.api_key, "sk_test_motionmate")
        finally:
            stripe_config.stripe.api_key = original_api_key

    def test_checkout_routes_exist_without_webhook_or_customer_portal_routes(self):
        def flatten_url_patterns(patterns):
            for pattern in patterns:
                if isinstance(pattern, URLPattern):
                    yield pattern
                elif isinstance(pattern, URLResolver):
                    yield from flatten_url_patterns(pattern.url_patterns)

        route_text = " ".join(
            f"{pattern.pattern} {pattern.name or ''}".lower()
            for pattern in flatten_url_patterns(get_resolver().url_patterns)
        )

        self.assertIn("billing/checkout/success/", route_text)
        self.assertIn("billing/checkout/cancelled/", route_text)
        self.assertIn("billing/checkout/resume/", route_text)

        for forbidden_term in (
            "webhook",
            "customer_portal",
            "customer-portal",
        ):
            with self.subTest(forbidden_term=forbidden_term):
                self.assertNotIn(forbidden_term, route_text)


class StripeCheckoutServiceTests(TestCase):
    @staticmethod
    def _price_map() -> dict[tuple[str, str, str], str]:
        return {
            (plan_slug, interval, currency): f"price_{plan_slug}_{interval}_{currency}"
            for plan_slug in PUBLIC_PAID_PLAN_SLUGS
            for interval in PUBLIC_BILLING_INTERVALS
            for currency in PUBLIC_PRICING_CURRENCIES
        }

    def _valid_stripe_settings(self, **overrides):
        settings_overrides = {
            "STRIPE_ENABLED": True,
            "STRIPE_PUBLISHABLE_KEY": "pk_test_motionmate",
            "STRIPE_SECRET_KEY": "sk_test_motionmate",
            "STRIPE_WEBHOOK_SECRET": "whsec_motionmate",
            "STRIPE_PRICE_ID_MAP": self._price_map(),
        }
        settings_overrides.update(overrides)
        return settings_overrides

    def setUp(self):
        self.factory = RequestFactory()
        self.user = TaskIOUser.objects.create_user(
            email="checkout-owner@example.com",
            password="StrongPass123!",
        )
        self.business = Business.objects.create(
            name="Checkout Workspace",
            slug="checkout-workspace",
            country="Netherlands",
        )
        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        self.plan = ClarivoPlan.objects.get(slug="pro")

    def _request(self):
        return self.factory.post(
            reverse("billing_checkout_resume"),
            secure=True,
            HTTP_HOST="localhost",
        )

    def _stripe_client(
        self,
        *,
        create_session: dict | None = None,
        retrieve_session: dict | None = None,
    ):
        session_api = SimpleNamespace(
            create=mock.Mock(return_value=create_session or self._session_payload()),
            retrieve=mock.Mock(return_value=retrieve_session or self._session_payload()),
            expire=mock.Mock(),
        )
        return SimpleNamespace(checkout=SimpleNamespace(Session=session_api)), session_api

    def _session_payload(
        self,
        *,
        session_id: str = "cs_test_checkout",
        status: str = "open",
        url: str = "https://checkout.stripe.test/session",
        expires_at=None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        if expires_at is None:
            expires_at = int((timezone.now() + timedelta(hours=1)).timestamp())
        return {
            "id": session_id,
            "status": status,
            "url": url,
            "expires_at": expires_at,
            "client_reference_id": "",
            "metadata": metadata or {},
        }

    def _pending_subscription(
        self,
        *,
        billing_interval: str = "yearly",
        billing_currency: str = "eur",
    ) -> BusinessSubscription:
        return BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.PENDING_CHECKOUT,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=billing_interval,
            billing_currency=billing_currency,
        )

    def _metadata(self, subscription: BusinessSubscription) -> dict[str, str]:
        return {
            "motionmate_business_id": str(subscription.business_id),
            "motionmate_subscription_id": str(subscription.pk),
            "motionmate_user_id": str(self.user.pk),
            "plan_slug": subscription.plan.slug,
            "billing_interval": subscription.billing_interval,
            "billing_currency": subscription.billing_currency,
        }

    @override_settings(STRIPE_ENABLED=False)
    def test_pending_subscription_requires_stripe_enabled(self):
        with self.assertRaisesMessage(
            StripeConfigurationError,
            "Stripe subscription billing is disabled.",
        ):
            ensure_pending_checkout_subscription(
                business=self.business,
                plan=self.plan,
                billing_interval="monthly",
                currency="eur",
            )

    def test_create_checkout_session_payload_records_session_without_granting_access(self):
        expires_at = int((timezone.now() + timedelta(hours=1)).timestamp())
        create_session = self._session_payload(
            session_id="cs_test_created",
            url="https://checkout.stripe.test/created",
            expires_at=expires_at,
        )

        with override_settings(**self._valid_stripe_settings()):
            subscription = ensure_pending_checkout_subscription(
                business=self.business,
                plan=self.plan,
                billing_interval="yearly",
                currency="eur",
            )
            stripe_client, session_api = self._stripe_client(create_session=create_session)
            with mock.patch.object(
                stripe_checkout,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                checkout_url = create_trial_checkout_session(
                    request=self._request(),
                    subscription=subscription,
                    user=self.user,
                )

        subscription.refresh_from_db()
        create_kwargs = session_api.create.call_args.kwargs
        metadata = create_kwargs["metadata"]

        self.assertEqual(checkout_url, "https://checkout.stripe.test/created")
        self.assertEqual(create_kwargs["mode"], "subscription")
        self.assertEqual(
            create_kwargs["line_items"],
            [{"price": "price_pro_yearly_eur", "quantity": 1}],
        )
        self.assertEqual(create_kwargs["subscription_data"]["trial_period_days"], 14)
        self.assertEqual(create_kwargs["subscription_data"]["metadata"], metadata)
        self.assertEqual(create_kwargs["payment_method_collection"], "always")
        self.assertEqual(create_kwargs["payment_method_types"], ["card"])
        self.assertEqual(create_kwargs["customer_email"], self.user.email)
        self.assertIn("{CHECKOUT_SESSION_ID}", create_kwargs["success_url"])
        self.assertIn("/billing/checkout/success/", create_kwargs["success_url"])
        self.assertTrue(create_kwargs["cancel_url"].endswith("/billing/checkout/cancelled/"))
        self.assertEqual(metadata["motionmate_business_id"], str(self.business.pk))
        self.assertEqual(metadata["motionmate_subscription_id"], str(subscription.pk))
        self.assertEqual(metadata["motionmate_user_id"], str(self.user.pk))
        self.assertEqual(metadata["plan_slug"], "pro")
        self.assertEqual(metadata["billing_interval"], "yearly")
        self.assertEqual(metadata["billing_currency"], "eur")
        self.assertEqual(
            create_kwargs["client_reference_id"],
            f"business:{self.business.pk}:subscription:{subscription.pk}",
        )
        self.assertTrue(create_kwargs["idempotency_key"].startswith("motionmate-checkout-"))
        self.assertEqual(subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertFalse(subscription.has_access)
        self.assertFalse(subscription.can_use_module("invoicing"))
        self.assertEqual(subscription.provider_price_id, "price_pro_yearly_eur")
        self.assertEqual(subscription.provider_checkout_session_id, "cs_test_created")
        self.assertIsNotNone(subscription.checkout_session_expires_at)
        self.assertIsNone(subscription.trial_start)
        self.assertIsNone(subscription.trial_end)

    def test_resume_reuses_existing_open_session_for_same_subscription(self):
        with override_settings(**self._valid_stripe_settings()):
            subscription = self._pending_subscription()
            subscription.provider_checkout_session_id = "cs_test_existing"
            subscription.provider_price_id = "price_pro_yearly_eur"
            subscription.save(
                update_fields=[
                    "provider_checkout_session_id",
                    "provider_price_id",
                    "updated_at",
                ]
            )
            retrieve_session = self._session_payload(
                session_id="cs_test_existing",
                status="open",
                url="https://checkout.stripe.test/existing",
                metadata=self._metadata(subscription),
            )
            retrieve_session["client_reference_id"] = (
                f"business:{self.business.pk}:subscription:{subscription.pk}"
            )
            stripe_client, session_api = self._stripe_client(retrieve_session=retrieve_session)

            with mock.patch.object(
                stripe_checkout,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                checkout_url = resume_trial_checkout_session(
                    request=self._request(),
                    subscription=subscription,
                    user=self.user,
                )

        self.assertEqual(checkout_url, "https://checkout.stripe.test/existing")
        session_api.retrieve.assert_called_once_with("cs_test_existing")
        session_api.create.assert_not_called()
        session_api.expire.assert_not_called()

    def test_resume_replaces_expired_session_and_keeps_subscription_pending(self):
        with override_settings(**self._valid_stripe_settings()):
            subscription = self._pending_subscription()
            subscription.provider_checkout_session_id = "cs_test_expired"
            subscription.provider_price_id = "price_pro_yearly_eur"
            subscription.save(
                update_fields=[
                    "provider_checkout_session_id",
                    "provider_price_id",
                    "updated_at",
                ]
            )
            retrieve_session = self._session_payload(
                session_id="cs_test_expired",
                status="expired",
                metadata=self._metadata(subscription),
            )
            create_session = self._session_payload(
                session_id="cs_test_replacement",
                status="open",
                url="https://checkout.stripe.test/replacement",
            )
            stripe_client, session_api = self._stripe_client(
                retrieve_session=retrieve_session,
                create_session=create_session,
            )

            with mock.patch.object(
                stripe_checkout,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                checkout_url = resume_trial_checkout_session(
                    request=self._request(),
                    subscription=subscription,
                    user=self.user,
                )

        subscription.refresh_from_db()
        self.assertEqual(checkout_url, "https://checkout.stripe.test/replacement")
        session_api.retrieve.assert_called_once_with("cs_test_expired")
        session_api.create.assert_called_once()
        self.assertEqual(subscription.provider_checkout_session_id, "cs_test_replacement")
        self.assertEqual(subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertFalse(subscription.has_access)

    def test_resume_completed_session_waits_for_webhook_confirmation(self):
        with override_settings(**self._valid_stripe_settings()):
            subscription = self._pending_subscription()
            subscription.provider_checkout_session_id = "cs_test_complete"
            subscription.save(update_fields=["provider_checkout_session_id", "updated_at"])
            retrieve_session = self._session_payload(
                session_id="cs_test_complete",
                status="complete",
                metadata=self._metadata(subscription),
            )
            stripe_client, _session_api = self._stripe_client(retrieve_session=retrieve_session)

            with mock.patch.object(
                stripe_checkout,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                with self.assertRaises(StripeCheckoutAlreadyCompleted):
                    resume_trial_checkout_session(
                        request=self._request(),
                        subscription=subscription,
                        user=self.user,
                    )

        subscription.refresh_from_db()
        self.assertEqual(subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertIsNone(subscription.trial_start)

    def test_resume_rejects_session_metadata_for_another_workspace(self):
        with override_settings(**self._valid_stripe_settings()):
            subscription = self._pending_subscription()
            subscription.provider_checkout_session_id = "cs_test_other"
            subscription.save(update_fields=["provider_checkout_session_id", "updated_at"])
            retrieve_session = self._session_payload(
                session_id="cs_test_other",
                status="open",
                metadata={
                    **self._metadata(subscription),
                    "motionmate_business_id": "999999",
                },
            )
            stripe_client, session_api = self._stripe_client(retrieve_session=retrieve_session)

            with mock.patch.object(
                stripe_checkout,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                with self.assertRaisesMessage(
                    StripeCheckoutError,
                    "Stored Checkout Session does not match this workspace.",
                ):
                    resume_trial_checkout_session(
                        request=self._request(),
                        subscription=subscription,
                        user=self.user,
                    )

        session_api.create.assert_not_called()


class CheckoutReturnViewTests(TestCase):
    def setUp(self):
        self.owner = TaskIOUser.objects.create_user(
            email="checkout-view-owner@example.com",
            password="StrongPass123!",
        )
        self.business = Business.objects.create(
            name="Checkout View Workspace",
            slug="checkout-view-workspace",
        )
        BusinessUser.objects.create(
            user=self.owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        self.plan = ClarivoPlan.objects.get(slug="pro")
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.PENDING_CHECKOUT,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_checkout_session_id="cs_test_pending",
        )
        self.client.force_login(self.owner)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    def test_success_page_does_not_activate_pending_subscription(self):
        response = self.client.get(
            f"{reverse('billing_checkout_success')}?session_id=cs_test_pending",
        )

        self.subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your payment method was received.")
        self.assertContains(response, "Your 14-day trial will become available")
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertFalse(self.subscription.has_access)
        self.assertIsNone(self.subscription.trial_start)

    def test_cancelled_page_keeps_pending_subscription_and_allows_resume(self):
        response = self.client.get(reverse("billing_checkout_cancelled"))

        self.subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No payment was taken.")
        self.assertContains(response, "without creating another business")
        self.assertContains(response, reverse("billing_checkout_resume"))
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertFalse(self.subscription.has_access)

    def test_resume_requires_post_and_redirects_to_checkout_url(self):
        get_response = self.client.get(reverse("billing_checkout_resume"))

        self.assertEqual(get_response.status_code, 405)

        with mock.patch(
            "apps.businesses.views.resume_trial_checkout_session",
            return_value="https://checkout.stripe.test/resume",
        ) as resume_checkout:
            post_response = self.client.post(reverse("billing_checkout_resume"))

        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(post_response.url, "https://checkout.stripe.test/resume")
        resume_checkout.assert_called_once()

    def test_completed_resume_redirects_to_confirmation_without_activating(self):
        with mock.patch(
            "apps.businesses.views.resume_trial_checkout_session",
            side_effect=StripeCheckoutAlreadyCompleted,
        ):
            response = self.client.post(reverse("billing_checkout_resume"))

        self.subscription.refresh_from_db()
        self.assertRedirects(response, reverse("billing_checkout_success"))
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertFalse(self.subscription.has_access)

    def test_pending_owner_dashboard_redirects_to_checkout_setup(self):
        response = self.client.get(reverse("agent_dashboard"), follow=True)

        self.assertRedirects(response, reverse("billing_checkout_cancelled"))
        self.assertContains(response, "Finish secure payment setup")
        self.assertContains(response, "Payment setup paused")


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


class UserOnboardingStateTests(TestCase):
    def setUp(self):
        self.user = TaskIOUser.objects.create_user(
            email="owner-onboarding@example.com",
            password="testpass123",
        )
        self.business = Business.objects.create(
            name="Onboarding HQ",
            slug="onboarding-hq",
        )

    def test_user_onboarding_state_can_be_created(self):
        state = UserOnboardingState.objects.create(
            user=self.user,
            business=self.business,
            selected_journey="setup_business",
            completed_welcome=True,
            skipped_steps=["add_first_service"],
            last_step_key="complete_business_profile",
        )

        self.assertEqual(state.user, self.user)
        self.assertEqual(state.business, self.business)
        self.assertEqual(state.selected_journey, "setup_business")
        self.assertTrue(state.completed_welcome)
        self.assertEqual(state.skipped_steps, ["add_first_service"])
        self.assertIn("owner-onboarding@example.com", str(state))

    def test_user_onboarding_state_is_unique_per_user_and_business(self):
        UserOnboardingState.objects.create(user=self.user, business=self.business)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserOnboardingState.objects.create(user=self.user, business=self.business)

    def test_get_or_create_user_onboarding_state_reuses_existing_record(self):
        created_state, created = get_or_create_user_onboarding_state(
            user=self.user,
            business=self.business,
        )
        existing_state, existing_created = get_or_create_user_onboarding_state(
            user=self.user,
            business=self.business,
        )

        self.assertTrue(created)
        self.assertFalse(existing_created)
        self.assertEqual(created_state, existing_state)


class OnboardingJourneyDefinitionTests(TestCase):
    def test_journey_definitions_include_three_initial_journeys(self):
        journeys = get_journey_definitions()

        self.assertEqual(
            [journey["key"] for journey in journeys],
            ["setup_business", "manage_clients", "booked_and_paid"],
        )

    def test_each_initial_journey_has_three_tasks(self):
        journeys = get_journey_definitions()

        self.assertTrue(all(len(journey["tasks"]) == 3 for journey in journeys))


class OnboardingStatusHelperTests(TestCase):
    def setUp(self):
        self.owner = TaskIOUser.objects.create_user(
            email="guide-owner@example.com",
            password="testpass123",
        )
        self.business = Business.objects.create(
            name="Guide HQ",
            slug="guide-hq",
        )
        self.plan = ClarivoPlan.objects.create(
            name="Onboarding Full Access",
            slug="onboarding-full-access",
            allow_public_booking=True,
            allow_appointments=True,
            allow_invoicing=True,
        )
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        BusinessUser.objects.create(
            user=self.owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )

    @staticmethod
    def _task_map(status):
        return {task["key"]: task for task in status["tasks"]}

    def test_status_helper_returns_empty_business_progress(self):
        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)

        self.assertTrue(status["visible"])
        self.assertIsNone(status["selected_journey"])
        self.assertTrue(status["should_auto_show_welcome"])
        self.assertTrue(status["auto_show_welcome"])
        self.assertEqual(len(status["available_journeys"]), 3)
        self.assertEqual(status["progress_count"], 0)
        self.assertEqual(status["total_task_count"], 9)
        self.assertEqual(status["percent_complete"], 0)
        self.assertTrue(all(len(journey["tasks"]) == 3 for journey in status["available_journeys"]))
        self.assertTrue(all(not task["completed"] for task in tasks.values()))

    def test_task_metadata_includes_spotlight_target_selectors(self):
        task_definitions = get_task_definitions()
        expected_selectors = {
            "complete_business_profile": "[data-onboarding-target='business-settings']",
            "add_first_service": "[data-onboarding-target='services']",
            "set_availability": "[data-onboarding-target='availability']",
            "add_first_client": "[data-onboarding-target='clients']",
            "create_first_service_request": "[data-onboarding-target='service-requests']",
            "schedule_first_appointment": "[data-onboarding-target='appointments']",
            "configure_online_booking": "[data-onboarding-target='booking-settings']",
            "create_first_invoice": "[data-onboarding-target='invoices']",
            "send_or_download_invoice": "[data-onboarding-target='invoices']",
        }

        for task_key, selector in expected_selectors.items():
            with self.subTest(task_key=task_key):
                self.assertEqual(task_definitions[task_key]["target_selector"], selector)

    def test_status_helper_respects_skipped_steps(self):
        UserOnboardingState.objects.create(
            user=self.owner,
            business=self.business,
            selected_journey="setup_business",
            skipped_steps={"add_first_service": True},
        )

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)

        self.assertEqual(status["selected_journey"]["key"], "setup_business")
        self.assertFalse(status["should_auto_show_welcome"])
        self.assertTrue(tasks["add_first_service"]["skipped"])
        self.assertFalse(tasks["set_availability"]["skipped"])

    def test_status_helper_does_not_auto_show_after_welcome_is_dismissed(self):
        UserOnboardingState.objects.create(
            user=self.owner,
            business=self.business,
            completed_welcome=True,
            dismissed_at=timezone.now(),
        )

        status = get_onboarding_status(user=self.owner, business=self.business)

        self.assertTrue(status["visible"])
        self.assertFalse(status["should_auto_show_welcome"])

    def test_business_profile_completion_uses_safe_business_fields(self):
        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        self.assertFalse(tasks["complete_business_profile"]["completed"])

        self.business.email = "hello@guide.example"
        self.business.country = "Sint Maarten"
        self.business.save(update_fields=["email", "country", "updated_at"])

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        self.assertTrue(tasks["complete_business_profile"]["completed"])
        self.assertEqual(
            tasks["complete_business_profile"]["completion_source"],
            "business_profile_fields",
        )

    def test_adding_availability_completes_availability_task(self):
        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        self.assertFalse(tasks["set_availability"]["completed"])

        WeeklyAvailability.objects.create(
            business=self.business,
            day_of_week=WeeklyAvailability.DayOfWeek.MONDAY,
            start_time=time(9, 0),
            end_time=time(17, 0),
        )

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        self.assertTrue(tasks["set_availability"]["completed"])

    def test_completion_logic_updates_for_real_workspace_records(self):
        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        self.assertFalse(tasks["add_first_service"]["completed"])
        self.assertFalse(tasks["add_first_client"]["completed"])
        self.assertFalse(tasks["schedule_first_appointment"]["completed"])
        self.assertFalse(tasks["create_first_invoice"]["completed"])
        self.assertFalse(tasks["send_or_download_invoice"]["completed"])

        service = BusinessService.objects.create(
            business=self.business,
            name="Site visit",
        )
        client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="jamie@example.com",
            phone="+1 721 555 0101",
            company_name="Jamie Co",
            street_address="Front Street 12",
        )
        start_time = timezone.now() + timedelta(days=1)
        Appointment.objects.create(
            business=self.business,
            client=client,
            service=service,
            title="Site visit - Jamie Co",
            start_time=start_time,
            end_time=start_time + timedelta(hours=1),
        )
        invoice = Invoice.objects.create(
            business=self.business,
            client=client,
            invoice_number="INV-0001",
        )

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        self.assertTrue(tasks["add_first_service"]["completed"])
        self.assertTrue(tasks["add_first_client"]["completed"])
        self.assertTrue(tasks["schedule_first_appointment"]["completed"])
        self.assertTrue(tasks["create_first_invoice"]["completed"])
        self.assertFalse(tasks["send_or_download_invoice"]["completed"])

        invoice.status = Invoice.Status.SENT
        invoice.save(update_fields=["status", "updated_at"])

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        self.assertTrue(tasks["send_or_download_invoice"]["completed"])

    def test_paid_invoice_completes_send_or_download_invoice_task(self):
        client = Client.objects.create(
            business=self.business,
            first_name="Paid",
            last_name="Client",
            email="paid-client@example.com",
            phone="+1 721 555 0199",
            company_name="Paid Co",
            street_address="Front Street 19",
        )
        Invoice.objects.create(
            business=self.business,
            client=client,
            invoice_number="PAID-0001",
            status=Invoice.Status.PAID,
        )

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)

        self.assertTrue(tasks["send_or_download_invoice"]["completed"])

    def test_inactive_or_archived_clients_do_not_complete_client_task(self):
        Client.objects.create(
            business=self.business,
            first_name="Inactive",
            last_name="Client",
            email="inactive-client@example.com",
            phone="+1 721 555 0200",
            company_name="Inactive Co",
            street_address="Front Street 20",
            client_status=Client.ClientStatus.INACTIVE,
            is_active=True,
        )
        Client.objects.create(
            business=self.business,
            first_name="Archived",
            last_name="Client",
            email="archived-client@example.com",
            phone="+1 721 555 0201",
            company_name="Archived Co",
            street_address="Front Street 21",
            client_status=Client.ClientStatus.ARCHIVED,
            is_active=True,
        )
        Client.objects.create(
            business=self.business,
            first_name="Deactivated",
            last_name="Client",
            email="deactivated-client@example.com",
            phone="+1 721 555 0202",
            company_name="Deactivated Co",
            street_address="Front Street 22",
            client_status=Client.ClientStatus.ACTIVE,
            is_active=False,
        )

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)

        self.assertFalse(tasks["add_first_client"]["completed"])

    def test_completion_logic_updates_for_service_request_and_booking_setup(self):
        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        self.assertFalse(tasks["create_first_service_request"]["completed"])
        self.assertFalse(tasks["configure_online_booking"]["completed"])

        Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            first_name="Taylor",
            last_name="Requester",
            email="taylor@example.com",
            phone="+1 721 555 0102",
            company_name="Taylor Co",
        )
        BusinessBookingSettings.objects.create(
            business=self.business,
            booking_enabled=True,
        )

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        self.assertTrue(tasks["create_first_service_request"]["completed"])
        self.assertTrue(tasks["configure_online_booking"]["completed"])

    def test_invoice_dependency_changes_cta_to_add_client_when_client_missing(self):
        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        invoice_task = tasks["create_first_invoice"]

        self.assertTrue(invoice_task["has_missing_prerequisites"])
        self.assertEqual(
            invoice_task["prerequisite_message"], "Invoices work best after you add a client."
        )
        self.assertEqual(invoice_task["recommended_previous_task_key"], "add_first_client")
        self.assertEqual(invoice_task["effective_cta_label"], "Add Client")
        self.assertEqual(invoice_task["effective_cta_url"], reverse("staff_client_create"))
        self.assertEqual(invoice_task["target_selector"], "[data-onboarding-target='invoices']")
        self.assertEqual(
            invoice_task["effective_target_selector"],
            "[data-onboarding-target='clients']",
        )

    def test_online_booking_dependency_prefers_service_then_availability(self):
        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        booking_task = tasks["configure_online_booking"]

        self.assertTrue(booking_task["has_missing_prerequisites"])
        self.assertEqual(booking_task["recommended_previous_task_key"], "add_first_service")
        self.assertEqual(booking_task["effective_cta_label"], "Add Service")
        self.assertEqual(booking_task["effective_cta_url"], reverse("business_service_create"))
        self.assertEqual(
            booking_task["effective_target_selector"],
            "[data-onboarding-target='services']",
        )

        BusinessService.objects.create(
            business=self.business,
            name="Inspection",
        )

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        booking_task = tasks["configure_online_booking"]

        self.assertTrue(booking_task["has_missing_prerequisites"])
        self.assertEqual(booking_task["recommended_previous_task_key"], "set_availability")
        self.assertEqual(booking_task["effective_cta_label"], "Set Availability")
        self.assertEqual(booking_task["effective_cta_url"], reverse("business_booking_settings"))
        self.assertEqual(
            booking_task["effective_target_selector"],
            "[data-onboarding-target='availability']",
        )

    def test_send_invoice_dependency_changes_cta_to_create_invoice_when_invoice_missing(self):
        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        send_task = tasks["send_or_download_invoice"]

        self.assertTrue(send_task["has_missing_prerequisites"])
        self.assertEqual(send_task["recommended_previous_task_key"], "create_first_invoice")
        self.assertEqual(send_task["effective_cta_label"], "Create Invoice")
        self.assertEqual(send_task["effective_cta_url"], reverse("invoice_create"))
        self.assertEqual(
            send_task["effective_target_selector"],
            "[data-onboarding-target='invoices']",
        )

    def test_locked_tasks_do_not_expose_effective_spotlight_target(self):
        self.plan.allow_appointments = False
        self.plan.save(update_fields=["allow_appointments"])

        status = get_onboarding_status(user=self.owner, business=self.business)
        tasks = self._task_map(status)
        appointment_task = tasks["schedule_first_appointment"]

        self.assertTrue(appointment_task["locked"])
        self.assertEqual(
            appointment_task["target_selector"],
            "[data-onboarding-target='appointments']",
        )
        self.assertEqual(appointment_task["effective_target_selector"], "")

    def test_task_copy_does_not_include_unfinished_features(self):
        status = get_onboarding_status(user=self.owner, business=self.business)
        forbidden_terms = (
            "Marketing tools",
            "Stripe checkout",
            "Subscription payments",
            "Payment collection",
            "Quotes/estimates",
            "Documents/files",
            "Reminder automation",
            "Client portal",
            "Workspace switching",
        )
        rendered_copy = " ".join(
            " ".join(
                str(task.get(field, ""))
                for field in ("title", "description", "cta_label", "prerequisite_message")
            )
            for task in status["tasks"]
        )

        for term in forbidden_terms:
            with self.subTest(term=term):
                self.assertNotIn(term, rendered_copy)


class OnboardingVisibilityTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Visibility HQ",
            slug="visibility-hq",
        )

    def _user_with_role(self, role: str):
        user = TaskIOUser.objects.create_user(
            email=f"{role}@example.com",
            password="testpass123",
        )
        BusinessUser.objects.create(user=user, business=self.business, role=role)
        return user

    def test_owner_and_admin_can_view_onboarding(self):
        for role in (BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN):
            with self.subTest(role=role):
                user = self._user_with_role(role)

                self.assertTrue(user_can_view_onboarding(user, self.business))

    def test_staff_viewer_and_accountant_cannot_view_onboarding(self):
        for role in (
            BusinessUser.Role.STAFF,
            BusinessUser.Role.VIEWER,
            BusinessUser.Role.ACCOUNTANT,
        ):
            with self.subTest(role=role):
                user = self._user_with_role(role)

                self.assertFalse(user_can_view_onboarding(user, self.business))


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

    def test_pending_checkout_subscription_has_no_workspace_or_module_access(self):
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.PENDING_CHECKOUT,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
        )

        self.assertTrue(subscription.is_pending_checkout)
        self.assertFalse(subscription.has_access)
        self.assertFalse(self.business.has_active_subscription)
        self.assertFalse(business_has_active_subscription(self.business))
        self.assertFalse(can_use_module(self.business, "invoicing"))

    @override_settings(BETA_REGISTRATION_ENABLED=False)
    def test_disabled_beta_registration_does_not_change_existing_beta_subscription(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)
        BusinessSubscription.objects.create(
            business=self.business,
            plan=beta_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        self.assertTrue(self.business.has_active_subscription)
        self.assertTrue(business_has_active_subscription(self.business))
        self.assertTrue(can_use_module(self.business, "appointments"))
        self.assertTrue(can_use_module(self.business, "public_booking"))

    def test_default_trial_subscription_does_not_fallback_to_beta(self):
        ClarivoPlan.objects.filter(slug__in=ClarivoPlan.MOTIONMATE_PLAN_SLUGS).update(
            is_active=False,
        )
        ClarivoPlan.objects.filter(slug=BETA_PLAN_SLUG).update(is_active=True)

        subscription = create_default_trial_subscription(self.business)

        self.assertIsNone(subscription)
        self.assertFalse(BusinessSubscription.objects.filter(business=self.business).exists())

    def test_default_trial_subscription_uses_catalog_trial_duration(self):
        plan = ClarivoPlan.objects.get(slug=DEFAULT_PUBLIC_PAID_PLAN_SLUG)

        subscription = create_default_trial_subscription(self.business, plan=plan)

        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(
            subscription.trial_end - subscription.trial_start,
            timedelta(days=STANDARD_TRIAL_DAYS),
        )
        self.assertEqual(subscription.current_period_start, subscription.trial_start)
        self.assertEqual(subscription.current_period_end, subscription.trial_end)

    def test_default_trial_subscription_preserves_explicit_trial_day_override(self):
        plan = ClarivoPlan.objects.get(slug="starter")

        subscription = create_default_trial_subscription(self.business, plan=plan, trial_days=5)

        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.trial_end - subscription.trial_start, timedelta(days=5))
        self.assertEqual(subscription.current_period_start, subscription.trial_start)
        self.assertEqual(subscription.current_period_end, subscription.trial_end)

    def test_assign_subscription_plan_uses_catalog_default_trial_and_preserves_override(self):
        default_business = Business.objects.create(
            name="Default Trial Assignment",
            slug="default-trial-assignment",
        )
        override_business = Business.objects.create(
            name="Override Trial Assignment",
            slug="override-trial-assignment",
        )
        plan = ClarivoPlan.objects.get(slug="business")

        default_subscription = assign_business_subscription_plan(default_business, plan)
        override_subscription = assign_business_subscription_plan(
            override_business,
            plan,
            trial_days=3,
        )

        self.assertEqual(
            default_subscription.trial_end - default_subscription.trial_start,
            timedelta(days=STANDARD_TRIAL_DAYS),
        )
        self.assertEqual(
            override_subscription.trial_end - override_subscription.trial_start,
            timedelta(days=3),
        )


class MotionmatePlanCatalogTests(TestCase):
    def test_default_motionmate_plans_have_agreed_prices_limits_and_modules(self):
        expected = {
            "starter": {
                "usd_monthly": Decimal("39.00"),
                "eur_monthly": Decimal("39.00"),
                "usd_yearly": Decimal("390.00"),
                "eur_yearly": Decimal("390.00"),
                "users": 2,
                "staff": 1,
                "clients": 15,
                "invoices": 50,
                "appointments": 35,
                "public_bookings": 50,
            },
            "pro": {
                "usd_monthly": Decimal("79.00"),
                "eur_monthly": Decimal("79.00"),
                "usd_yearly": Decimal("790.00"),
                "eur_yearly": Decimal("790.00"),
                "users": 5,
                "staff": 4,
                "clients": 60,
                "invoices": 200,
                "appointments": 150,
                "public_bookings": 250,
            },
            "business": {
                "usd_monthly": Decimal("159.00"),
                "eur_monthly": Decimal("149.00"),
                "usd_yearly": Decimal("1590.00"),
                "eur_yearly": Decimal("1490.00"),
                "users": 10,
                "staff": 9,
                "clients": 150,
                "invoices": 500,
                "appointments": 400,
                "public_bookings": 750,
            },
        }

        plans = list(ClarivoPlan.motionmate_plans())

        self.assertEqual([plan.slug for plan in plans], ["starter", "pro", "business"])
        for plan in plans:
            with self.subTest(plan=plan.slug):
                expected_plan = expected[plan.slug]
                self.assertEqual(plan.price_monthly, expected_plan["usd_monthly"])
                self.assertEqual(plan.price_yearly, expected_plan["usd_yearly"])
                self.assertEqual(
                    Decimal(plan.regional_prices["usd"]["monthly"]),
                    expected_plan["usd_monthly"],
                )
                self.assertEqual(
                    Decimal(plan.regional_prices["usd"]["yearly"]),
                    expected_plan["usd_yearly"],
                )
                self.assertEqual(
                    Decimal(plan.regional_prices["eur"]["monthly"]),
                    expected_plan["eur_monthly"],
                )
                self.assertEqual(
                    Decimal(plan.regional_prices["eur"]["yearly"]),
                    expected_plan["eur_yearly"],
                )
                self.assertEqual(plan.max_users, expected_plan["users"])
                self.assertEqual(plan.staff_account_limit, expected_plan["staff"])
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
                self.assertTrue(plan.allows_module("appointments"))
                self.assertTrue(plan.allows_module("public_booking"))
                self.assertTrue(plan.allows_module("public_booking_requests"))
                self.assertTrue(plan.allows_module("public_request_form"))
                self.assertIn("total users", plan.user_limit_summary)

        self.assertTrue(ClarivoPlan.objects.get(slug="pro").is_recommended)
        self.assertFalse(ClarivoPlan.objects.get(slug="starter").is_recommended)
        self.assertFalse(ClarivoPlan.objects.get(slug="business").is_recommended)

    def test_motionmate_plans_exclude_inactive_public_plans(self):
        ClarivoPlan.objects.filter(slug="pro").update(is_active=False)

        public_slugs = list(ClarivoPlan.motionmate_plans().values_list("slug", flat=True))

        self.assertEqual(public_slugs, ["starter", "business"])
        self.assertNotIn("pro", public_slugs)
        self.assertNotIn(BETA_PLAN_SLUG, public_slugs)

    def test_internal_beta_plan_is_free_pro_equivalent_and_excluded_from_public_catalog(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)
        pro_plan = ClarivoPlan.objects.get(slug="pro")
        public_slugs = list(ClarivoPlan.motionmate_plans().values_list("slug", flat=True))

        self.assertEqual(beta_plan.name, BETA_PLAN_DISPLAY_NAME)
        self.assertEqual(beta_plan.price_monthly, Decimal("0.00"))
        self.assertEqual(beta_plan.price_yearly, Decimal("0.00"))
        self.assertTrue(beta_plan.is_active)
        self.assertFalse(beta_plan.is_recommended)
        self.assertNotIn(BETA_PLAN_SLUG, public_slugs)
        for field_name in (
            "max_users",
            "max_clients",
            "max_invoices_per_month",
            "max_appointments_per_month",
            "max_public_bookings_per_month",
            "allow_invoicing",
            "allow_appointments",
            "allow_memberships",
            "allow_public_booking",
            "allow_public_request_form",
        ):
            with self.subTest(field=field_name):
                self.assertEqual(getattr(beta_plan, field_name), getattr(pro_plan, field_name))

        self.assertTrue(beta_plan.allows_module("invoicing"))
        self.assertTrue(beta_plan.allows_module("appointments"))
        self.assertTrue(beta_plan.allows_module("public_booking"))
        self.assertTrue(beta_plan.allows_module("public_request_form"))

    def test_display_pricing_supports_usd_default_and_eur_business_context(self):
        plan = ClarivoPlan.objects.get(slug="business")
        dutch_business = Business.objects.create(
            name="Amsterdam Ops",
            slug="amsterdam-ops",
            country="Netherlands",
        )

        public_pricing = plan.get_display_pricing()
        dutch_pricing = plan.get_display_pricing(business=dutch_business)
        eur_pricing = plan.get_display_pricing(region=ClarivoPlan.EUR_PRICING_REGION)

        self.assertEqual(public_pricing["monthly_display"], "$159")
        self.assertEqual(public_pricing["yearly_display"], "$1,590")
        self.assertEqual(public_pricing["tax_note"], "")
        self.assertEqual(dutch_pricing["monthly_display"], "€149")
        self.assertEqual(dutch_pricing["yearly_display"], "€1,490")
        self.assertEqual(dutch_pricing["tax_note"], "")
        self.assertEqual(eur_pricing["monthly_display"], "€149")
        self.assertEqual(eur_pricing["yearly_display"], "€1,490")

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
        self.assertFalse(business_limit_reached(business, "appointments_per_month"))
        self.assertFalse(business_limit_reached(business, "public_bookings_per_month"))

    def _create_client(self, business, email: str, **overrides):
        defaults = {
            "business": business,
            "first_name": "Test",
            "last_name": "Client",
            "email": email,
            "phone": "+1 721 555 0000",
            "company_name": "Test Client Co",
            "street_address": "Front Street 1",
        }
        defaults.update(overrides)
        return Client.objects.create(**defaults)

    def test_active_client_usage_excludes_archived_and_inactive_clients(self):
        business = Business.objects.create(name="Active Client HQ", slug="active-client-hq")
        plan = ClarivoPlan.objects.create(
            name="Active Client Cap",
            slug="active-client-cap",
            max_clients=2,
            allow_invoicing=True,
            allow_appointments=True,
            allow_public_booking=True,
        )
        BusinessSubscription.objects.create(
            business=business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        self._create_client(
            business,
            "active@example.com",
            client_status=Client.ClientStatus.ACTIVE,
        )
        self._create_client(
            business,
            "prospect@example.com",
            client_status=Client.ClientStatus.PROSPECT,
        )
        self._create_client(
            business,
            "inactive-status@example.com",
            client_status=Client.ClientStatus.INACTIVE,
        )
        self._create_client(
            business,
            "archived-status@example.com",
            client_status=Client.ClientStatus.ARCHIVED,
        )
        self._create_client(
            business,
            "inactive-flag@example.com",
            is_active=False,
        )

        self.assertEqual(get_business_usage_count(business, "clients"), 2)
        self.assertTrue(business_limit_reached(business, "clients"))

    def test_monthly_usage_limits_count_current_month_records_only(self):
        business = Business.objects.create(name="Monthly Limit HQ", slug="monthly-limit-hq")
        plan = ClarivoPlan.objects.create(
            name="Monthly Cap",
            slug="monthly-cap",
            max_invoices_per_month=1,
            max_appointments_per_month=1,
            max_public_bookings_per_month=1,
            allow_invoicing=True,
            allow_appointments=True,
            allow_public_booking=True,
        )
        BusinessSubscription.objects.create(
            business=business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        client = self._create_client(business, "monthly-client@example.com")
        now = timezone.now()
        previous_month = now - timedelta(days=40)

        old_invoice = Invoice.objects.create(
            business=business,
            client=client,
            invoice_number="OLD-001",
        )
        Invoice.objects.filter(pk=old_invoice.pk).update(created_at=previous_month)
        old_appointment = Appointment.objects.create(
            business=business,
            client=client,
            title="Old appointment",
            start_time=previous_month,
            end_time=previous_month + timedelta(hours=1),
        )
        Appointment.objects.filter(pk=old_appointment.pk).update(created_at=now)
        old_booking = Lead.objects.create(
            business=business,
            lead_type=Lead.LeadType.REQUEST,
            status=Lead.Status.NEW,
            request_source=Lead.RequestSource.PUBLIC_BOOKING,
            first_name="Old",
            last_name="Booking",
            email="old-booking@example.com",
            phone="+1 721 555 1111",
            company_name="Old Booking Co",
        )
        Lead.objects.filter(pk=old_booking.pk).update(created_at=previous_month)

        self.assertFalse(business_limit_reached(business, "invoices_per_month"))
        self.assertFalse(business_limit_reached(business, "appointments_per_month"))
        self.assertFalse(business_limit_reached(business, "public_bookings_per_month"))

        Invoice.objects.create(
            business=business,
            client=client,
            invoice_number="CUR-001",
        )
        Appointment.objects.create(
            business=business,
            client=client,
            title="Current appointment",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )
        Lead.objects.create(
            business=business,
            lead_type=Lead.LeadType.REQUEST,
            status=Lead.Status.NEW,
            request_source=Lead.RequestSource.PUBLIC_BOOKING,
            first_name="Current",
            last_name="Booking",
            email="current-booking@example.com",
            phone="+1 721 555 2222",
            company_name="Current Booking Co",
        )

        self.assertTrue(business_limit_reached(business, "invoices_per_month"))
        self.assertTrue(business_limit_reached(business, "appointments_per_month"))
        self.assertTrue(business_limit_reached(business, "public_bookings_per_month"))

    def test_public_pricing_page_uses_final_dual_currency_prices_and_no_growth_plan(self):
        ClarivoPlan.objects.create(
            name="Growth",
            slug="growth",
            price_monthly=Decimal("49.00"),
            price_yearly=Decimal("490.00"),
            is_active=True,
        )

        response = self.client.get(reverse("home"), HTTP_HOST="localhost", secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "$39")
        self.assertContains(response, "€39")
        self.assertContains(response, "$79")
        self.assertContains(response, "€79")
        self.assertContains(response, "$159")
        self.assertContains(response, "€149")
        self.assertContains(response, "$1,590 yearly USD")
        self.assertContains(response, "EUR: €1,490 / year")
        self.assertContains(response, "Recommended")
        self.assertContains(response, "Client CRM")
        self.assertContains(response, "Online Booking")
        self.assertContains(response, "2 total users: owner + 1 staff account")
        self.assertNotContains(response, "$0.00")
        self.assertNotContains(response, BETA_PLAN_DISPLAY_NAME)
        self.assertNotContains(response, "Growth")
        self.assertNotContains(response, "Public Request Form")
        self.assertNotContains(response, "Public Booking")

    def test_home_uses_public_site_landing_template_and_assets(self):
        response = self.client.get(reverse("home"), HTTP_HOST="localhost", secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "public_site/home.html")
        self.assertTemplateUsed(response, "public_site/base.html")
        self.assertContains(response, "public_site/css/theme.min.css")
        self.assertContains(response, "public_site/js/theme.min.js")
        self.assertNotContains(response, "/static/assets/css/theme.min.css")
        self.assertContains(response, "Smarter workflows for")

    def test_public_site_preview_uses_namespaced_template_and_assets(self):
        response = self.client.get(reverse("site_preview"), HTTP_HOST="localhost", secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "public_site/home.html")
        self.assertTemplateUsed(response, "public_site/base.html")
        self.assertContains(response, "public_site/css/theme.min.css")
        self.assertContains(response, "public_site/js/theme.min.js")
        self.assertNotContains(response, "/static/assets/css/theme.min.css")
        self.assertContains(response, "Smarter workflows for")

    def test_public_site_templates_use_django_static_paths(self):
        template_names = [
            "public_site/base.html",
            "public_site/home.html",
        ]

        for template_name in template_names:
            with self.subTest(template_name=template_name):
                html = render_to_string(template_name)
                self.assertIn("public_site/", html)
                self.assertNotIn('href="assets/', html)
                self.assertNotIn('src="assets/', html)
                self.assertNotIn('content="assets/', html)
                self.assertNotIn("url(assets/", html)
                self.assertNotIn("public_site/assets/", html)

    def test_root_redirects_to_home_landing(self):
        response = self.client.get("/", HTTP_HOST="localhost", secure=True)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_starter_direct_urls_allow_included_modules_and_show_setup_state(self):
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
        appointment_response = self.client.get(reverse("appointment_list"))
        public_booking_response = self.client.get(reverse("public_booking", args=[business.slug]))

        self.assertEqual(client_response.status_code, 200)
        self.assertEqual(invoice_response.status_code, 200)
        self.assertEqual(appointment_response.status_code, 200)
        self.assertEqual(public_booking_response.status_code, 403)
        self.assertContains(
            public_booking_response,
            "Online Booking Unavailable",
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

    def test_business_settings_showcases_ready_online_booking_link(self):
        public_booking_plan = ClarivoPlan.objects.create(
            name="Online Booking",
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

        self.assertContains(response, "Online Booking Link")
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

    def _bulk_availability_payload(self, **overrides):
        payload = {
            "form_kind": "bulk_availability",
            "days": [
                WeeklyAvailability.DayOfWeek.MONDAY,
                WeeklyAvailability.DayOfWeek.WEDNESDAY,
                WeeklyAvailability.DayOfWeek.FRIDAY,
            ],
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
                self.assertContains(response, "Bulk")

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

    def test_bulk_weekly_availability_creates_selected_days(self):
        self._login_with_role(BusinessUser.Role.ADMIN)

        response = self.client.post(
            reverse("business_booking_settings"),
            self._bulk_availability_payload(),
            follow=True,
        )

        availability_blocks = list(
            WeeklyAvailability.objects.filter(business=self.business).order_by("day_of_week")
        )

        self.assertRedirects(response, reverse("business_booking_settings"))
        self.assertContains(response, "3 weekly availability blocks added.")
        self.assertEqual(len(availability_blocks), 3)
        self.assertEqual(
            [block.day_of_week for block in availability_blocks],
            [
                WeeklyAvailability.DayOfWeek.MONDAY,
                WeeklyAvailability.DayOfWeek.WEDNESDAY,
                WeeklyAvailability.DayOfWeek.FRIDAY,
            ],
        )
        self.assertTrue(all(block.start_time == time(9, 0) for block in availability_blocks))
        self.assertTrue(all(block.end_time == time(17, 0) for block in availability_blocks))
        self.assertTrue(all(block.staff_member is None for block in availability_blocks))
        self.assertFalse(WeeklyAvailability.objects.filter(business=self.other_business).exists())

    def test_staff_bulk_availability_is_added_to_own_schedule(self):
        self._login_with_role(BusinessUser.Role.STAFF)

        response = self.client.post(
            reverse("business_booking_settings"),
            self._bulk_availability_payload(
                staff_member="",
                days=[
                    WeeklyAvailability.DayOfWeek.TUESDAY,
                    WeeklyAvailability.DayOfWeek.THURSDAY,
                ],
            ),
            follow=True,
        )

        availability_blocks = list(
            WeeklyAvailability.objects.filter(business=self.business).order_by("day_of_week")
        )

        self.assertRedirects(response, reverse("business_booking_settings"))
        self.assertEqual(len(availability_blocks), 2)
        self.assertTrue(all(block.staff_member == self.user for block in availability_blocks))
        self.assertContains(response, "Booking Owner")

    def test_bulk_weekly_availability_requires_selected_days(self):
        self._login_with_role(BusinessUser.Role.OWNER)

        response = self.client.post(
            reverse("business_booking_settings"),
            self._bulk_availability_payload(days=[]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please correct the bulk availability errors below.")
        self.assertContains(response, "This field is required.")
        self.assertFalse(WeeklyAvailability.objects.filter(business=self.business).exists())

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
            "Online Booking is not included in the current workspace plan.",
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
        self.assertContains(response, "Online Booking requires setup")

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
        self.assertContains(response, "Online Booking Link")
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
        self.assertContains(response, "Online Booking")
        self.assertContains(response, "Current Usage")
        self.assertNotContains(response, "Marketing Tools")

    def test_subscription_page_shows_final_usd_and_eur_prices(self):
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
        self.assertContains(response, "$39")
        self.assertContains(response, "€39")
        self.assertContains(response, "$79")
        self.assertContains(response, "€79")
        self.assertContains(response, "$159")
        self.assertContains(response, "€149")
        self.assertNotContains(response, "ex. VAT")
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
        self.assertContains(response, "Total users/seats: using 3, Starter allows 2.")
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

    def test_downgrade_without_quota_or_module_loss_updates_immediately(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.business_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        response = self.client.post(
            reverse("business_subscription"),
            {"plan": self.pro_plan.id},
            follow=True,
        )

        subscription.refresh_from_db()
        self.assertRedirects(response, reverse("business_subscription"))
        self.assertEqual(subscription.plan, self.pro_plan)
        self.assertContains(response, "Workspace plan updated to Pro")
        self.assertNotContains(response, "Modules no longer included")

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

    def test_invitation_role_choices_follow_plan_packaging(self):
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=ClarivoPlan.objects.get(slug="starter"),
            status=BusinessSubscription.Status.ACTIVE,
        )
        self._login(self.owner, BusinessUser.Role.OWNER)

        starter_response = self.client.get(reverse("business_team_members"))
        starter_roles = {
            role_value
            for role_value, _role_label in starter_response.context["invite_form"]
            .fields["role"]
            .choices
        }

        self.assertIn(BusinessUser.Role.OWNER, starter_roles)
        self.assertIn(BusinessUser.Role.ADMIN, starter_roles)
        self.assertIn(BusinessUser.Role.STAFF, starter_roles)
        self.assertNotIn(BusinessUser.Role.ACCOUNTANT, starter_roles)
        self.assertNotIn(BusinessUser.Role.VIEWER, starter_roles)

        subscription.plan = ClarivoPlan.objects.get(slug="business")
        subscription.save(update_fields=["plan", "updated_at"])

        business_response = self.client.get(reverse("business_team_members"))
        business_roles = {
            role_value
            for role_value, _role_label in business_response.context["invite_form"]
            .fields["role"]
            .choices
        }

        self.assertIn(BusinessUser.Role.ACCOUNTANT, business_roles)
        self.assertIn(BusinessUser.Role.VIEWER, business_roles)

    def test_owner_can_deactivate_team_member(self):
        self._login(self.owner, BusinessUser.Role.OWNER)
        staff_user = TaskIOUser.objects.create_user(
            email="staff-to-remove@example.com",
            password="StrongPass123!",
        )
        staff_membership = BusinessUser.objects.create(
            user=staff_user,
            business=self.business,
            role=BusinessUser.Role.STAFF,
        )

        response = self.client.post(
            reverse("business_team_member_deactivate", args=[staff_membership.id]),
            follow=True,
        )

        staff_membership.refresh_from_db()
        self.assertRedirects(response, reverse("business_team_members"))
        self.assertFalse(staff_membership.is_active)
        self.assertContains(response, "was removed from the active team")

    def test_admin_can_deactivate_staff_team_member(self):
        self._login(self.admin, BusinessUser.Role.ADMIN)
        staff_user = TaskIOUser.objects.create_user(
            email="staff-admin-remove@example.com",
            password="StrongPass123!",
        )
        staff_membership = BusinessUser.objects.create(
            user=staff_user,
            business=self.business,
            role=BusinessUser.Role.STAFF,
        )

        response = self.client.post(
            reverse("business_team_member_deactivate", args=[staff_membership.id]),
            follow=True,
        )

        staff_membership.refresh_from_db()
        self.assertRedirects(response, reverse("business_team_members"))
        self.assertFalse(staff_membership.is_active)

    def test_admin_cannot_deactivate_owner_team_member(self):
        owner_membership = BusinessUser.objects.create(
            user=self.owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        self._login(self.admin, BusinessUser.Role.ADMIN)

        response = self.client.post(
            reverse("business_team_member_deactivate", args=[owner_membership.id]),
            follow=True,
        )

        owner_membership.refresh_from_db()
        self.assertRedirects(response, reverse("business_team_members"))
        self.assertTrue(owner_membership.is_active)
        self.assertContains(response, "You do not have permission to remove that workspace role.")

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
