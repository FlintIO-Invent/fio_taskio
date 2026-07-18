import json
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core import mail
from django.core.checks import run_checks
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import Client as DjangoClient
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

from . import stripe_checkout, stripe_config, stripe_portal, stripe_webhooks
from .checks import check_stripe_configuration
from .localization import format_money_for_business, parse_localized_decimal
from .models import (
    BillingProviderWebhookEvent,
    Business,
    BusinessBookingSettings,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    SubscriptionAccessMode,
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
    STRIPE_CHECK_INVALID_CUSTOMER_PORTAL_CONFIGURATION_ID,
    STRIPE_CHECK_INVALID_PRICE_ID,
    STRIPE_CHECK_INVALID_PUBLISHABLE_KEY,
    STRIPE_CHECK_INVALID_SECRET_KEY,
    STRIPE_CHECK_MISSING_CUSTOMER_PORTAL_CONFIGURATION_ID,
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
    get_stripe_customer_portal_configuration_id,
    get_stripe_mode,
    get_stripe_price_id,
    is_stripe_enabled,
    resolve_stripe_price_id,
    validate_stripe_configuration,
)
from .stripe_portal import (
    PAYMENT_RECOVERY_NOT_AVAILABLE_MESSAGE,
    PORTAL_OPEN_FAILED_MESSAGE,
    PORTAL_TEMPORARILY_UNAVAILABLE_MESSAGE,
    StripeCustomerPortalError,
    create_customer_portal_session,
    create_payment_recovery_portal_session,
    get_customer_portal_availability,
    get_payment_recovery_portal_availability,
)
from .subscription_grace import (
    SUBSCRIPTION_CHECK_INVALID_PAYMENT_GRACE_DAYS,
    get_subscription_payment_grace_days,
    validate_subscription_grace_configuration,
)
from .utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    MULTI_WORKSPACE_EMAIL_MESSAGE,
    SAME_WORKSPACE_EMAIL_MESSAGE,
    assign_business_subscription_plan,
    business_can_modify_workspace,
    business_can_view_workspace,
    business_has_active_subscription,
    business_has_restricted_subscription,
    business_is_trialing,
    business_limit_reached,
    business_module_required,
    business_required,
    business_role_required,
    business_workspace_access_required,
    can_use_module,
    can_view_module,
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
            "STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "bpc_test_motionmate",
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
            stripe_customer_portal_configuration_id=" bpc_replace_me ",
            subscription_payment_grace_days=" 7 ",
            stripe_price_pro_monthly_usd=" price_pro_monthly_usd ",
        )

        self.assertEqual(app_settings.stripe_publishable_key, "pk_test_replace_me")
        self.assertEqual(app_settings.stripe_secret_key, "")
        self.assertEqual(app_settings.stripe_webhook_secret, "whsec_replace_me")
        self.assertEqual(app_settings.stripe_customer_portal_configuration_id, "bpc_replace_me")
        self.assertEqual(app_settings.subscription_payment_grace_days, "7")
        self.assertEqual(app_settings.stripe_price_pro_monthly_usd, "price_pro_monthly_usd")

    @override_settings(
        STRIPE_ENABLED=False,
        STRIPE_PUBLISHABLE_KEY="",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
        STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID="",
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
            STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID="bpc_test_motionmate",
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

    def test_customer_portal_configuration_id_is_required_and_shape_validated(self):
        with override_settings(**self._valid_stripe_settings()):
            self.assertEqual(
                get_stripe_customer_portal_configuration_id(),
                "bpc_test_motionmate",
            )
            self.assertNotIn(
                STRIPE_CHECK_MISSING_CUSTOMER_PORTAL_CONFIGURATION_ID,
                self._stripe_check_ids(),
            )

        with override_settings(
            **self._valid_stripe_settings(STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID=" ")
        ):
            self.assertIn(
                STRIPE_CHECK_MISSING_CUSTOMER_PORTAL_CONFIGURATION_ID,
                self._stripe_check_ids(),
            )

        with override_settings(
            **self._valid_stripe_settings(
                STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID="pcfg_test_motionmate"
            )
        ):
            self.assertIn(
                STRIPE_CHECK_INVALID_CUSTOMER_PORTAL_CONFIGURATION_ID,
                self._stripe_check_ids(),
            )

    def test_subscription_payment_grace_days_defaults_and_validates_range(self):
        with override_settings():
            self.assertEqual(get_subscription_payment_grace_days(), 7)
            self.assertEqual(validate_subscription_grace_configuration(), [])

        for value, expected in (("0", 0), ("7", 7), ("30", 30), (14, 14)):
            with self.subTest(value=value):
                with override_settings(SUBSCRIPTION_PAYMENT_GRACE_DAYS=value):
                    self.assertEqual(get_subscription_payment_grace_days(), expected)
                    self.assertEqual(validate_subscription_grace_configuration(), [])

        for value in ("-1", "31", "not-days", "7.5", True):
            with self.subTest(value=value):
                with override_settings(SUBSCRIPTION_PAYMENT_GRACE_DAYS=value):
                    issues = validate_subscription_grace_configuration()
                    self.assertEqual(
                        {issue.id for issue in issues},
                        {SUBSCRIPTION_CHECK_INVALID_PAYMENT_GRACE_DAYS},
                    )
                    self.assertIn(
                        SUBSCRIPTION_CHECK_INVALID_PAYMENT_GRACE_DAYS,
                        {check.id for check in check_stripe_configuration(None)},
                    )

        with override_settings(
            STRIPE_ENABLED=False,
            STRIPE_PUBLISHABLE_KEY="",
            STRIPE_SECRET_KEY="",
            STRIPE_WEBHOOK_SECRET="",
            STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID="",
            STRIPE_PRICE_ID_MAP={},
            SUBSCRIPTION_PAYMENT_GRACE_DAYS="",
        ):
            self.assertEqual(get_subscription_payment_grace_days(), 7)
            self.assertEqual(check_stripe_configuration(None), [])

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

    def test_price_id_reverse_mapping_resolves_exact_public_plan_dimensions(self):
        with override_settings(STRIPE_PRICE_ID_MAP=self._price_map()):
            price_metadata = resolve_stripe_price_id(" price_pro_yearly_eur ")

        self.assertEqual(price_metadata.price_id, "price_pro_yearly_eur")
        self.assertEqual(price_metadata.plan_slug, "pro")
        self.assertEqual(price_metadata.billing_interval, "yearly")
        self.assertEqual(price_metadata.currency, "eur")

    def test_price_id_reverse_mapping_rejects_unknown_or_ambiguous_price_ids(self):
        with override_settings(STRIPE_PRICE_ID_MAP=self._price_map()):
            with self.assertRaisesMessage(
                StripeConfigurationError,
                "Stripe Price ID is not configured for Motionmate.",
            ):
                resolve_stripe_price_id("price_unknown")

        with override_settings(
            STRIPE_PRICE_ID_MAP=self._price_map(
                overrides={
                    ("starter", "monthly", "usd"): "price_shared",
                    ("pro", "monthly", "usd"): "price_shared",
                }
            )
        ):
            with self.assertRaisesMessage(
                StripeConfigurationError,
                "Stripe Price ID maps to more than one Motionmate plan.",
            ):
                resolve_stripe_price_id("price_shared")

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
            STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID="",
            STRIPE_PRICE_ID_MAP={},
        ):
            error_ids = {error.id for error in check_stripe_configuration(None)}

        self.assertIn(STRIPE_CHECK_MISSING_PUBLISHABLE_KEY, error_ids)
        self.assertIn(STRIPE_CHECK_MISSING_SECRET_KEY, error_ids)
        self.assertIn(STRIPE_CHECK_MISSING_WEBHOOK_SECRET, error_ids)
        self.assertIn(STRIPE_CHECK_MISSING_CUSTOMER_PORTAL_CONFIGURATION_ID, error_ids)
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
                with mock.patch.object(
                    stripe_config.stripe.billing_portal.Session,
                    "create",
                ) as create_portal_session:
                    self.assertEqual(check_stripe_configuration(None), [])

        create_customer.assert_not_called()
        create_portal_session.assert_not_called()

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

    def test_checkout_webhook_and_customer_portal_routes_exist(self):
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
        self.assertIn("billing/webhooks/stripe/", route_text)
        self.assertIn("billing/customer-portal/", route_text)
        self.assertIn("billing_customer_portal", route_text)
        self.assertIn("billing/payment-recovery/", route_text)
        self.assertIn("billing_payment_recovery", route_text)


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
            "STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "bpc_test_motionmate",
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


class StripeCustomerPortalServiceTests(TestCase):
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
            "STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "bpc_test_motionmate",
            "STRIPE_PRICE_ID_MAP": self._price_map(),
        }
        settings_overrides.update(overrides)
        return settings_overrides

    def setUp(self):
        self.factory = RequestFactory()
        self.owner = TaskIOUser.objects.create_user(
            email="portal-owner@example.com",
            password="StrongPass123!",
        )
        self.staff = TaskIOUser.objects.create_user(
            email="portal-staff@example.com",
            password="StrongPass123!",
        )
        self.business = Business.objects.create(
            name="Portal Workspace",
            slug="portal-workspace",
        )
        BusinessUser.objects.create(
            user=self.owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        BusinessUser.objects.create(
            user=self.staff,
            business=self.business,
            role=BusinessUser.Role.STAFF,
        )
        self.plan = ClarivoPlan.objects.get(slug="pro")

    def _request(self):
        return self.factory.post(
            reverse("billing_customer_portal"),
            {
                "customer": "cus_browser_tamper",
                "return_url": "https://evil.example/return",
                "configuration": "bpc_browser_tamper",
            },
            secure=True,
            HTTP_HOST="testserver",
        )

    def _subscription(self, **overrides):
        now = timezone.now()
        defaults = {
            "business": self.business,
            "plan": self.plan,
            "status": BusinessSubscription.Status.ACTIVE,
            "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
            "billing_interval": BusinessSubscription.BillingInterval.MONTHLY,
            "billing_currency": BusinessSubscription.BillingCurrency.USD,
            "provider_customer_id": "cus_portal_workspace",
            "provider_subscription_id": "sub_portal_workspace",
            "provider_price_id": "price_pro_monthly_usd",
            "current_period_start": now - timedelta(days=1),
            "current_period_end": now + timedelta(days=29),
        }
        defaults.update(overrides)
        return BusinessSubscription.objects.create(**defaults)

    def _stripe_client(self, *, create_result=None, create_side_effect=None):
        session_api = SimpleNamespace(
            create=mock.Mock(
                return_value=create_result
                if create_result is not None
                else {
                    "id": "bps_test_portal",
                    "url": "https://billing.stripe.test/session",
                },
                side_effect=create_side_effect,
            )
        )
        return SimpleNamespace(billing_portal=SimpleNamespace(Session=session_api)), session_api

    def test_portal_eligibility_allows_accessible_stripe_trial_active_and_scheduled_cancel(self):
        now = timezone.now()
        cases = (
            {
                "status": BusinessSubscription.Status.TRIALING,
                "trial_start": now - timedelta(days=1),
                "trial_end": now + timedelta(days=13),
                "current_period_start": now - timedelta(days=1),
                "current_period_end": now + timedelta(days=13),
            },
            {"status": BusinessSubscription.Status.ACTIVE},
            {
                "status": BusinessSubscription.Status.TRIALING,
                "cancel_at_period_end": True,
                "trial_start": now - timedelta(days=1),
                "trial_end": now + timedelta(days=1),
                "current_period_start": now - timedelta(days=1),
                "current_period_end": now + timedelta(days=29),
            },
            {
                "status": BusinessSubscription.Status.ACTIVE,
                "cancel_at_period_end": True,
            },
        )

        with override_settings(**self._valid_stripe_settings()):
            for fields in cases:
                with self.subTest(
                    status=fields["status"], cancel=fields.get("cancel_at_period_end")
                ):
                    BusinessSubscription.objects.filter(business=self.business).delete()
                    subscription = self._subscription(**fields)

                    availability = get_customer_portal_availability(
                        business=self.business,
                        user=self.owner,
                        subscription=subscription,
                        at_time=now,
                    )

                    self.assertTrue(availability.can_open)
                    self.assertEqual(availability.reason, "eligible")

    def test_portal_eligibility_denies_ineligible_statuses_and_invalid_local_state(self):
        now = timezone.now()
        inactive_plan = ClarivoPlan.objects.create(
            name="Inactive Portal Plan",
            slug="inactive-portal-plan",
            is_active=False,
        )
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)
        inactive_business = Business.objects.create(
            name="Inactive Portal Workspace",
            slug="inactive-portal-workspace",
            is_active=False,
        )
        BusinessUser.objects.create(
            user=self.owner,
            business=inactive_business,
            role=BusinessUser.Role.OWNER,
        )
        cases = (
            (
                {"status": BusinessSubscription.Status.PENDING_CHECKOUT},
                "status_not_allowed",
            ),
            (
                {
                    "status": BusinessSubscription.Status.TRIALING,
                    "trial_start": now - timedelta(days=15),
                    "trial_end": now - timedelta(days=1),
                    "current_period_start": now - timedelta(days=15),
                    "current_period_end": now - timedelta(days=1),
                },
                BusinessSubscription.AccessCode.TRIAL_EXPIRED,
            ),
            (
                {
                    "status": BusinessSubscription.Status.ACTIVE,
                    "current_period_start": now - timedelta(days=40),
                    "current_period_end": now - timedelta(days=1),
                },
                BusinessSubscription.AccessCode.PROVIDER_STATE_STALE,
            ),
            ({"status": BusinessSubscription.Status.EXPIRED}, "status_not_allowed"),
            ({"status": BusinessSubscription.Status.CANCELLED}, "status_not_allowed"),
            ({"status": BusinessSubscription.Status.PAST_DUE}, "status_not_allowed"),
            ({"status": "surprise"}, "status_not_allowed"),
            ({"plan": beta_plan}, "non_public_plan"),
            ({"plan": inactive_plan}, BusinessSubscription.AccessCode.PLAN_INACTIVE),
            (
                {
                    "business": inactive_business,
                    "provider_customer_id": "cus_inactive_business",
                    "provider_subscription_id": "sub_inactive_business",
                },
                BusinessSubscription.AccessCode.BUSINESS_INACTIVE,
            ),
            (
                {"payment_provider": BusinessSubscription.PaymentProvider.LOCAL},
                "non_stripe_provider",
            ),
            ({"provider_customer_id": ""}, "invalid_provider_customer_id"),
            ({"provider_subscription_id": ""}, "invalid_provider_subscription_id"),
            ({"provider_customer_id": "customer_bad"}, "invalid_provider_customer_id"),
            ({"provider_subscription_id": "subscription_bad"}, "invalid_provider_subscription_id"),
        )

        with override_settings(**self._valid_stripe_settings()):
            for fields, expected_reason in cases:
                with self.subTest(expected_reason=expected_reason):
                    BusinessSubscription.objects.filter(
                        business__in=[self.business, inactive_business]
                    ).delete()
                    subscription = self._subscription(**fields)
                    business = fields.get("business", self.business)

                    availability = get_customer_portal_availability(
                        business=business,
                        user=self.owner,
                        subscription=subscription,
                        at_time=now,
                    )

                    self.assertFalse(availability.can_open)
                    self.assertEqual(availability.reason, expected_reason)

    def test_portal_eligibility_requires_owner_and_enabled_stripe_configuration(self):
        subscription = self._subscription()

        with override_settings(**self._valid_stripe_settings()):
            staff_availability = get_customer_portal_availability(
                business=self.business,
                user=self.staff,
                subscription=subscription,
            )
        self.assertFalse(staff_availability.can_open)
        self.assertEqual(staff_availability.reason, "owner_required")

        with override_settings(STRIPE_ENABLED=False):
            disabled_availability = get_customer_portal_availability(
                business=self.business,
                user=self.owner,
                subscription=subscription,
            )
        self.assertFalse(disabled_availability.can_open)
        self.assertEqual(disabled_availability.reason, "stripe_disabled")

        with override_settings(
            **self._valid_stripe_settings(STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID="")
        ):
            missing_config_availability = get_customer_portal_availability(
                business=self.business,
                user=self.owner,
                subscription=subscription,
            )
        self.assertFalse(missing_config_availability.can_open)
        self.assertEqual(
            missing_config_availability.reason,
            "portal_configuration_unavailable",
        )

    def test_create_portal_session_uses_local_provider_ids_and_trusted_return_url(self):
        subscription = self._subscription()
        original_values = (
            subscription.status,
            subscription.provider_customer_id,
            subscription.provider_subscription_id,
            subscription.current_period_end,
        )
        stripe_client, session_api = self._stripe_client()

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_portal,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                portal_url = create_customer_portal_session(
                    request=self._request(),
                    business=self.business,
                    user=self.owner,
                    subscription=subscription,
                )

        subscription.refresh_from_db()
        create_kwargs = session_api.create.call_args.kwargs

        self.assertEqual(portal_url, "https://billing.stripe.test/session")
        self.assertEqual(create_kwargs["customer"], "cus_portal_workspace")
        self.assertEqual(create_kwargs["configuration"], "bpc_test_motionmate")
        self.assertTrue(
            create_kwargs["return_url"].endswith("/businesses/subscription/?billing_return=1")
        )
        self.assertNotIn("cus_browser_tamper", create_kwargs.values())
        self.assertNotIn("https://evil.example/return", create_kwargs.values())
        self.assertNotIn("bpc_browser_tamper", create_kwargs.values())
        self.assertEqual(
            (
                subscription.status,
                subscription.provider_customer_id,
                subscription.provider_subscription_id,
                subscription.current_period_end,
            ),
            original_values,
        )

    def test_portal_creation_failures_do_not_mutate_local_subscription(self):
        subscription = self._subscription()
        original_updated_at = subscription.updated_at
        stripe_client, _session_api = self._stripe_client(
            create_side_effect=Exception("stripe exploded")
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_portal,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                with self.assertRaises(StripeCustomerPortalError) as error:
                    create_customer_portal_session(
                        request=self._request(),
                        business=self.business,
                        user=self.owner,
                        subscription=subscription,
                    )

        subscription.refresh_from_db()
        self.assertEqual(error.exception.user_message, PORTAL_OPEN_FAILED_MESSAGE)
        self.assertNotIn("stripe exploded", error.exception.user_message)
        self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertEqual(subscription.updated_at, original_updated_at)
        self.assertEqual(subscription.provider_customer_id, "cus_portal_workspace")
        self.assertEqual(subscription.provider_subscription_id, "sub_portal_workspace")

    def test_missing_or_invalid_portal_url_fails_safely_without_storing_url(self):
        for create_result in ({"id": "bps_missing_url"}, {"url": "http://evil.example"}):
            with self.subTest(create_result=create_result):
                BusinessSubscription.objects.filter(business=self.business).delete()
                subscription = self._subscription()
                stripe_client, _session_api = self._stripe_client(create_result=create_result)

                with override_settings(**self._valid_stripe_settings()):
                    with mock.patch.object(
                        stripe_portal,
                        "configure_stripe_sdk",
                        return_value=stripe_client,
                    ):
                        with self.assertRaisesMessage(
                            StripeCustomerPortalError,
                            "Stripe Customer Portal Session did not return a usable URL.",
                        ):
                            create_customer_portal_session(
                                request=self._request(),
                                business=self.business,
                                user=self.owner,
                                subscription=subscription,
                            )

                subscription.refresh_from_db()
                self.assertEqual(subscription.provider_checkout_session_id, "")
                self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)

    def test_payment_recovery_portal_eligibility_allows_past_due_during_and_after_grace(self):
        now = timezone.now()
        cases = (
            {
                "past_due_since": now - timedelta(days=1),
                "grace_period_ends_at": now + timedelta(days=6),
            },
            {
                "past_due_since": now - timedelta(days=10),
                "grace_period_ends_at": now - timedelta(days=3),
            },
        )

        with override_settings(**self._valid_stripe_settings()):
            for fields in cases:
                with self.subTest(grace_period_ends_at=fields["grace_period_ends_at"]):
                    BusinessSubscription.objects.filter(business=self.business).delete()
                    subscription = self._subscription(
                        status=BusinessSubscription.Status.PAST_DUE,
                        **fields,
                    )

                    availability = get_payment_recovery_portal_availability(
                        business=self.business,
                        user=self.owner,
                        subscription=subscription,
                    )

                    self.assertTrue(availability.can_open)
                    self.assertEqual(availability.reason, "eligible")

    def test_payment_recovery_portal_denies_invalid_states_and_non_owners(self):
        now = timezone.now()
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)
        cases = (
            ({"status": BusinessSubscription.Status.ACTIVE}, "status_not_allowed"),
            ({"status": BusinessSubscription.Status.PENDING_CHECKOUT}, "status_not_allowed"),
            ({"status": BusinessSubscription.Status.CANCELLED}, "status_not_allowed"),
            ({"plan": beta_plan}, "non_public_plan"),
            ({"provider_customer_id": ""}, "invalid_provider_customer_id"),
            ({"provider_subscription_id": ""}, "invalid_provider_subscription_id"),
            (
                {"payment_provider": BusinessSubscription.PaymentProvider.LOCAL},
                "non_stripe_provider",
            ),
        )

        with override_settings(**self._valid_stripe_settings()):
            for fields, expected_reason in cases:
                with self.subTest(expected_reason=expected_reason):
                    BusinessSubscription.objects.filter(business=self.business).delete()
                    subscription_fields = {
                        "status": BusinessSubscription.Status.PAST_DUE,
                        "past_due_since": now - timedelta(days=1),
                        "grace_period_ends_at": now + timedelta(days=6),
                        **fields,
                    }
                    subscription = self._subscription(**subscription_fields)

                    availability = get_payment_recovery_portal_availability(
                        business=self.business,
                        user=self.owner,
                        subscription=subscription,
                    )

                    self.assertFalse(availability.can_open)
                    self.assertEqual(availability.reason, expected_reason)

            BusinessSubscription.objects.filter(business=self.business).delete()
            staff_subscription = self._subscription(
                status=BusinessSubscription.Status.PAST_DUE,
                past_due_since=now - timedelta(days=1),
                grace_period_ends_at=now + timedelta(days=6),
            )
            staff_availability = get_payment_recovery_portal_availability(
                business=self.business,
                user=self.staff,
                subscription=staff_subscription,
            )
            self.assertFalse(staff_availability.can_open)
            self.assertEqual(staff_availability.reason, "owner_required")

    def test_create_payment_recovery_portal_session_uses_local_provider_ids(self):
        now = timezone.now()
        subscription = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            provider_customer_id="cus_recovery_workspace",
            provider_subscription_id="sub_recovery_workspace",
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        original_values = (
            subscription.status,
            subscription.past_due_since,
            subscription.grace_period_ends_at,
            subscription.provider_customer_id,
        )
        stripe_client, session_api = self._stripe_client()

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_portal,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                portal_url = create_payment_recovery_portal_session(
                    request=self._request(),
                    business=self.business,
                    user=self.owner,
                    subscription=subscription,
                )

        subscription.refresh_from_db()
        create_kwargs = session_api.create.call_args.kwargs
        self.assertEqual(portal_url, "https://billing.stripe.test/session")
        self.assertEqual(create_kwargs["customer"], "cus_recovery_workspace")
        self.assertEqual(create_kwargs["configuration"], "bpc_test_motionmate")
        self.assertTrue(
            create_kwargs["return_url"].endswith("/businesses/subscription/?billing_return=1")
        )
        self.assertEqual(
            (
                subscription.status,
                subscription.past_due_since,
                subscription.grace_period_ends_at,
                subscription.provider_customer_id,
            ),
            original_values,
        )

    def test_payment_recovery_portal_failures_do_not_mutate_subscription(self):
        now = timezone.now()
        subscription = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=1),
            grace_period_ends_at=now + timedelta(days=6),
        )
        original_updated_at = subscription.updated_at
        stripe_client, _session_api = self._stripe_client(
            create_side_effect=Exception("stripe recovery outage")
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_portal,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                with self.assertRaises(StripeCustomerPortalError) as error:
                    create_payment_recovery_portal_session(
                        request=self._request(),
                        business=self.business,
                        user=self.owner,
                        subscription=subscription,
                    )

        subscription.refresh_from_db()
        self.assertEqual(error.exception.user_message, PORTAL_OPEN_FAILED_MESSAGE)
        self.assertNotIn("stripe recovery outage", error.exception.user_message)
        self.assertEqual(subscription.status, BusinessSubscription.Status.PAST_DUE)
        self.assertEqual(subscription.updated_at, original_updated_at)


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
        self.assertContains(response, "Confirming your subscription")
        self.assertContains(response, "Your payment method was received.")
        self.assertContains(response, "Your 14-day trial will become available")
        self.assertNotContains(response, reverse("agent_dashboard"))
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertFalse(self.subscription.has_access)
        self.assertIsNone(self.subscription.trial_start)

    def test_success_page_links_dashboard_only_after_local_access_is_active(self):
        self.subscription.status = BusinessSubscription.Status.TRIALING
        self.subscription.trial_start = timezone.now()
        self.subscription.trial_end = timezone.now() + timedelta(days=14)
        self.subscription.save(update_fields=["status", "trial_start", "trial_end", "updated_at"])

        response = self.client.get(reverse("billing_checkout_success"))

        self.assertContains(response, "Your 14-day trial is active")
        self.assertContains(response, reverse("agent_dashboard"))

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


class StripeWebhookProcessingTests(TestCase):
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
            "STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "bpc_test_motionmate",
            "STRIPE_PRICE_ID_MAP": self._price_map(),
        }
        settings_overrides.update(overrides)
        return settings_overrides

    def setUp(self):
        self.user = TaskIOUser.objects.create_user(
            email="webhook-owner@example.com",
            password="StrongPass123!",
        )
        self.business = Business.objects.create(
            name="Webhook Workspace",
            slug="webhook-workspace",
            country="Sint Maarten",
        )
        BusinessUser.objects.create(
            user=self.user,
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
            provider_price_id="price_pro_monthly_usd",
            provider_checkout_session_id="cs_test_pending",
        )

    @staticmethod
    def _timestamp(year: int, month: int, day: int, hour: int = 12) -> int:
        return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp())

    @staticmethod
    def _datetime(value: int) -> datetime:
        return datetime.fromtimestamp(value, tz=UTC)

    def _signature_header(self, body: str, *, secret: str = "whsec_motionmate") -> str:
        timestamp = int(timezone.now().timestamp())
        signature = stripe_config.stripe.WebhookSignature._compute_signature(
            f"{timestamp}.{body}",
            secret,
        )
        return f"t={timestamp},v1={signature}"

    def _signed_post(
        self,
        payload: dict,
        *,
        secret: str = "whsec_motionmate",
    ):
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return self.client.post(
            reverse("stripe_billing_webhook"),
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=self._signature_header(body, secret=secret),
        )

    def _event(
        self,
        *,
        event_id: str,
        event_type: str,
        event_object: dict,
        created: int | None = None,
    ) -> dict:
        return {
            "id": event_id,
            "object": "event",
            "api_version": "2025-06-30.basil",
            "created": created or self._timestamp(2026, 7, 1),
            "livemode": False,
            "type": event_type,
            "data": {"object": event_object},
        }

    def _metadata(self, subscription: BusinessSubscription | None = None) -> dict[str, str]:
        subscription = subscription or self.subscription
        return {
            "motionmate_business_id": str(subscription.business_id),
            "motionmate_subscription_id": str(subscription.pk),
            "motionmate_user_id": str(self.user.pk),
            "plan_slug": subscription.plan.slug,
            "billing_interval": subscription.billing_interval,
            "billing_currency": subscription.billing_currency,
        }

    def _checkout_session(
        self,
        *,
        subscription: BusinessSubscription | None = None,
        session_id: str = "cs_test_pending",
        provider_subscription_id: str = "sub_test_motionmate",
        provider_customer_id: str = "cus_test_motionmate",
        metadata: dict[str, str] | None = None,
    ) -> dict:
        subscription = subscription or self.subscription
        return {
            "id": session_id,
            "object": "checkout.session",
            "mode": "subscription",
            "status": "complete",
            "customer": provider_customer_id,
            "subscription": provider_subscription_id,
            "client_reference_id": (
                f"business:{subscription.business_id}:subscription:{subscription.pk}"
            ),
            "metadata": metadata or self._metadata(subscription),
        }

    def _remote_subscription(
        self,
        *,
        local_subscription: BusinessSubscription | None = None,
        provider_subscription_id: str = "sub_test_motionmate",
        provider_customer_id: str = "cus_test_motionmate",
        status: str = "trialing",
        price_id: str | None = None,
        trial_start: int | None = None,
        trial_end: int | None = None,
        current_period_start: int | None = None,
        current_period_end: int | None = None,
        cancel_at_period_end: bool = False,
        canceled_at: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        local_subscription = local_subscription or self.subscription
        interval = local_subscription.billing_interval
        currency = local_subscription.billing_currency
        price_id = price_id or f"price_{local_subscription.plan.slug}_{interval}_{currency}"
        stripe_interval = (
            "year" if interval == BusinessSubscription.BillingInterval.YEARLY else "month"
        )
        trial_start = trial_start if trial_start is not None else self._timestamp(2026, 7, 1)
        trial_end = trial_end if trial_end is not None else self._timestamp(2026, 7, 15)
        current_period_start = (
            current_period_start
            if current_period_start is not None
            else self._timestamp(2026, 7, 1)
        )
        current_period_end = (
            current_period_end if current_period_end is not None else self._timestamp(2026, 8, 1)
        )
        if canceled_at is None and status in {"canceled", "incomplete_expired"}:
            canceled_at = self._timestamp(2026, 7, 10)

        return {
            "id": provider_subscription_id,
            "object": "subscription",
            "customer": provider_customer_id,
            "status": status,
            "trial_start": trial_start,
            "trial_end": trial_end,
            "current_period_start": current_period_start,
            "current_period_end": current_period_end,
            "cancel_at_period_end": cancel_at_period_end,
            "canceled_at": canceled_at,
            "metadata": metadata if metadata is not None else self._metadata(local_subscription),
            "items": {
                "object": "list",
                "data": [
                    {
                        "id": "si_test_motionmate",
                        "object": "subscription_item",
                        "price": {
                            "id": price_id,
                            "object": "price",
                            "currency": currency,
                            "recurring": {"interval": stripe_interval},
                        },
                    }
                ],
            },
        }

    def _stripe_client(self, *, retrieved_subscription: dict):
        subscription_api = SimpleNamespace(
            retrieve=mock.Mock(return_value=retrieved_subscription),
        )
        return SimpleNamespace(Subscription=subscription_api), subscription_api

    @override_settings(
        STRIPE_ENABLED=True,
        STRIPE_PUBLISHABLE_KEY="pk_test_motionmate",
        STRIPE_SECRET_KEY="sk_test_motionmate",
        STRIPE_WEBHOOK_SECRET="whsec_motionmate",
        STRIPE_PRICE_ID_MAP={},
    )
    def test_invalid_signature_payloads_do_not_create_event_or_mutate_subscription(self):
        payload = self._event(
            event_id="evt_signature",
            event_type="checkout.session.expired",
            event_object={"id": "cs_test_expired", "object": "checkout.session"},
        )
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)

        missing_signature = self.client.post(
            reverse("stripe_billing_webhook"),
            data=body,
            content_type="application/json",
        )
        bad_signature = self.client.post(
            reverse("stripe_billing_webhook"),
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=bad",
        )
        wrong_secret = self.client.post(
            reverse("stripe_billing_webhook"),
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=self._signature_header(body, secret="whsec_wrong"),
        )
        malformed_body = "{not json"
        malformed_json = self.client.post(
            reverse("stripe_billing_webhook"),
            data=malformed_body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=self._signature_header(malformed_body),
        )

        self.assertEqual(missing_signature.status_code, 400)
        self.assertEqual(bad_signature.status_code, 400)
        self.assertEqual(wrong_secret.status_code, 400)
        self.assertEqual(malformed_json.status_code, 400)
        self.assertFalse(BillingProviderWebhookEvent.objects.exists())
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertEqual(self.subscription.provider_subscription_id, "")

    def test_valid_ignored_event_is_recorded_without_login(self):
        payload = self._event(
            event_id="evt_ignored",
            event_type="checkout.session.expired",
            event_object={"id": "cs_test_expired", "object": "checkout.session"},
        )

        with override_settings(**self._valid_stripe_settings()):
            response = self._signed_post(payload)

        event_record = BillingProviderWebhookEvent.objects.get(event_id="evt_ignored")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(event_record.status, BillingProviderWebhookEvent.Status.IGNORED)
        self.assertEqual(event_record.attempt_count, 1)

    def test_unrelated_subscription_event_is_ignored_before_price_validation(self):
        provider_object = self._remote_subscription(
            provider_subscription_id="sub_unrelated",
            provider_customer_id="cus_unrelated",
            price_id="price_external",
            metadata={},
        )
        payload = self._event(
            event_id="evt_unrelated_subscription",
            event_type="customer.subscription.updated",
            event_object=provider_object,
        )

        with override_settings(**self._valid_stripe_settings()):
            response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        event_record = BillingProviderWebhookEvent.objects.get(
            event_id="evt_unrelated_subscription"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(event_record.status, BillingProviderWebhookEvent.Status.IGNORED)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertEqual(self.subscription.provider_subscription_id, "")

    def test_checkout_completed_reconciles_trialing_subscription_and_dates(self):
        event_created = int(timezone.now().timestamp())
        trial_start = int((timezone.now() - timedelta(days=1)).timestamp())
        trial_end = int((timezone.now() + timedelta(days=13)).timestamp())
        current_period_end = trial_end
        remote_subscription = self._remote_subscription(
            status="trialing",
            trial_start=trial_start,
            trial_end=trial_end,
            current_period_start=trial_start,
            current_period_end=current_period_end,
        )
        stripe_client, subscription_api = self._stripe_client(
            retrieved_subscription=remote_subscription,
        )
        payload = self._event(
            event_id="evt_checkout_trialing",
            event_type="checkout.session.completed",
            event_object=self._checkout_session(),
            created=event_created,
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        event_record = BillingProviderWebhookEvent.objects.get(event_id="evt_checkout_trialing")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(event_record.status, BillingProviderWebhookEvent.Status.PROCESSED)
        subscription_api.retrieve.assert_called_once_with(
            "sub_test_motionmate",
            expand=["items.data.price"],
        )
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertTrue(self.subscription.has_access)
        self.assertEqual(self.subscription.provider_customer_id, "cus_test_motionmate")
        self.assertEqual(self.subscription.provider_subscription_id, "sub_test_motionmate")
        self.assertEqual(self.subscription.provider_checkout_session_id, "cs_test_pending")
        self.assertEqual(self.subscription.provider_price_id, "price_pro_monthly_usd")
        self.assertEqual(self.subscription.trial_start, self._datetime(trial_start))
        self.assertEqual(self.subscription.trial_end, self._datetime(trial_end))
        self.assertEqual(self.subscription.current_period_end, self._datetime(current_period_end))
        self.assertEqual(self.subscription.provider_updated_at, self._datetime(event_created))

    def test_duplicate_processed_event_does_not_apply_twice(self):
        remote_subscription = self._remote_subscription(status="active")
        stripe_client, subscription_api = self._stripe_client(
            retrieved_subscription=remote_subscription,
        )
        payload = self._event(
            event_id="evt_duplicate_checkout",
            event_type="checkout.session.completed",
            event_object=self._checkout_session(),
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                first_response = self._signed_post(payload)
                second_response = self._signed_post(payload)

        event_record = BillingProviderWebhookEvent.objects.get(event_id="evt_duplicate_checkout")
        self.subscription.refresh_from_db()
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(event_record.status, BillingProviderWebhookEvent.Status.PROCESSED)
        self.assertEqual(event_record.attempt_count, 1)
        subscription_api.retrieve.assert_called_once()
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.ACTIVE)

    def test_checkout_completed_keeps_pending_when_stripe_subscription_cannot_be_retrieved(self):
        subscription_api = SimpleNamespace(retrieve=mock.Mock(side_effect=Exception("timeout")))
        stripe_client = SimpleNamespace(Subscription=subscription_api)
        payload = self._event(
            event_id="evt_checkout_retry",
            event_type="checkout.session.completed",
            event_object=self._checkout_session(),
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        event_record = BillingProviderWebhookEvent.objects.get(event_id="evt_checkout_retry")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(event_record.status, BillingProviderWebhookEvent.Status.FAILED)
        self.assertEqual(event_record.attempt_count, 1)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertEqual(self.subscription.provider_customer_id, "")
        self.assertEqual(self.subscription.provider_subscription_id, "")

    def test_checkout_completed_price_mismatch_fails_without_granting_access(self):
        remote_subscription = self._remote_subscription(
            status="trialing",
            price_id="price_business_monthly_usd",
        )
        stripe_client, _subscription_api = self._stripe_client(
            retrieved_subscription=remote_subscription,
        )
        payload = self._event(
            event_id="evt_checkout_price_mismatch",
            event_type="checkout.session.completed",
            event_object=self._checkout_session(),
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        event_record = BillingProviderWebhookEvent.objects.get(
            event_id="evt_checkout_price_mismatch"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(event_record.status, BillingProviderWebhookEvent.Status.FAILED)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertFalse(self.subscription.has_access)
        self.assertEqual(self.subscription.provider_subscription_id, "")

    def test_subscription_events_map_statuses_and_sync_cancellation_dates(self):
        cases = (
            ("trialing", BusinessSubscription.Status.TRIALING),
            ("active", BusinessSubscription.Status.ACTIVE),
            ("past_due", BusinessSubscription.Status.PAST_DUE),
            ("unpaid", BusinessSubscription.Status.PAST_DUE),
            ("canceled", BusinessSubscription.Status.CANCELLED),
            ("incomplete", BusinessSubscription.Status.PENDING_CHECKOUT),
            ("incomplete_expired", BusinessSubscription.Status.CANCELLED),
            ("paused", BusinessSubscription.Status.PAST_DUE),
        )

        with override_settings(**self._valid_stripe_settings()):
            for index, (provider_status, local_status) in enumerate(cases, start=1):
                with self.subTest(provider_status=provider_status):
                    business = Business.objects.create(
                        name=f"Webhook Status {index}",
                        slug=f"webhook-status-{index}",
                    )
                    local_subscription = BusinessSubscription.objects.create(
                        business=business,
                        plan=self.plan,
                        status=BusinessSubscription.Status.PENDING_CHECKOUT,
                        payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
                        billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
                        billing_currency=BusinessSubscription.BillingCurrency.USD,
                        provider_price_id="price_pro_monthly_usd",
                        provider_customer_id=f"cus_status_{index}",
                        provider_subscription_id=f"sub_status_{index}",
                    )
                    event_created = self._timestamp(2026, 7, index)
                    provider_object = self._remote_subscription(
                        local_subscription=local_subscription,
                        provider_subscription_id=f"sub_status_{index}",
                        provider_customer_id=f"cus_status_{index}",
                        status=provider_status,
                    )
                    payload = self._event(
                        event_id=f"evt_subscription_{provider_status}",
                        event_type="customer.subscription.updated",
                        event_object=provider_object,
                        created=event_created,
                    )

                    response = self._signed_post(payload)

                    local_subscription.refresh_from_db()
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(local_subscription.status, local_status)
                    self.assertEqual(
                        local_subscription.provider_updated_at,
                        self._datetime(event_created),
                    )
                    if local_status == BusinessSubscription.Status.CANCELLED:
                        self.assertIsNotNone(local_subscription.cancelled_at)

    def test_invoice_paid_syncs_known_subscription_without_touching_customer_invoices(self):
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.PAST_DUE
        self.subscription.past_due_since = self._datetime(self._timestamp(2026, 7, 1))
        self.subscription.grace_period_ends_at = self._datetime(self._timestamp(2026, 7, 8))
        self.subscription.last_payment_failure_at = self._datetime(self._timestamp(2026, 7, 1))
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "past_due_since",
                "grace_period_ends_at",
                "last_payment_failure_at",
                "updated_at",
            ]
        )
        remote_subscription = self._remote_subscription(status="active")
        stripe_client, subscription_api = self._stripe_client(
            retrieved_subscription=remote_subscription,
        )
        payload = self._event(
            event_id="evt_invoice_paid",
            event_type="invoice.paid",
            event_object={
                "id": "in_test_paid",
                "object": "invoice",
                "subscription": "sub_test_motionmate",
                "status": "paid",
            },
            created=self._timestamp(2026, 7, 3),
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        subscription_api.retrieve.assert_called_once()
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertIsNone(self.subscription.past_due_since)
        self.assertIsNone(self.subscription.grace_period_ends_at)
        self.assertEqual(
            self.subscription.last_payment_failure_at,
            self._datetime(self._timestamp(2026, 7, 1)),
        )
        self.assertEqual(Invoice.objects.count(), 0)

    def test_invoice_payment_failed_only_marks_past_due_when_stripe_status_does(self):
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "updated_at",
            ]
        )
        active_subscription = self._remote_subscription(status="active")
        past_due_subscription = self._remote_subscription(status="past_due")
        subscription_api = SimpleNamespace(
            retrieve=mock.Mock(side_effect=[active_subscription, past_due_subscription]),
        )
        stripe_client = SimpleNamespace(Subscription=subscription_api)

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                active_response = self._signed_post(
                    self._event(
                        event_id="evt_invoice_failed_active",
                        event_type="invoice.payment_failed",
                        event_object={
                            "id": "in_test_failed_active",
                            "object": "invoice",
                            "subscription": "sub_test_motionmate",
                            "status": "open",
                        },
                        created=self._timestamp(2026, 7, 4),
                    )
                )
                past_due_response = self._signed_post(
                    self._event(
                        event_id="evt_invoice_failed_past_due",
                        event_type="invoice.payment_failed",
                        event_object={
                            "id": "in_test_failed_past_due",
                            "object": "invoice",
                            "subscription": "sub_test_motionmate",
                            "status": "open",
                        },
                        created=self._timestamp(2026, 7, 5),
                    )
                )

        self.subscription.refresh_from_db()
        self.assertEqual(active_response.status_code, 200)
        self.assertEqual(past_due_response.status_code, 200)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PAST_DUE)
        self.assertEqual(
            self.subscription.past_due_since,
            self._datetime(self._timestamp(2026, 7, 5)),
        )
        self.assertEqual(
            self.subscription.grace_period_ends_at,
            self._datetime(self._timestamp(2026, 7, 12)),
        )
        self.assertEqual(
            self.subscription.last_payment_failure_at,
            self._datetime(self._timestamp(2026, 7, 5)),
        )
        self.assertEqual(self.subscription.last_payment_failure_reason, "payment_failed")

    def test_repeated_payment_failures_do_not_extend_grace(self):
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "updated_at",
            ]
        )
        past_due_subscription = self._remote_subscription(status="past_due")
        subscription_api = SimpleNamespace(
            retrieve=mock.Mock(side_effect=[past_due_subscription, past_due_subscription]),
        )
        stripe_client = SimpleNamespace(Subscription=subscription_api)

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                first_response = self._signed_post(
                    self._event(
                        event_id="evt_first_payment_failed",
                        event_type="invoice.payment_failed",
                        event_object={
                            "id": "in_first_payment_failed",
                            "object": "invoice",
                            "subscription": "sub_test_motionmate",
                            "status": "open",
                        },
                        created=self._timestamp(2026, 7, 5),
                    )
                )
                second_response = self._signed_post(
                    self._event(
                        event_id="evt_second_payment_failed",
                        event_type="invoice.payment_failed",
                        event_object={
                            "id": "in_second_payment_failed",
                            "object": "invoice",
                            "subscription": "sub_test_motionmate",
                            "status": "open",
                        },
                        created=self._timestamp(2026, 7, 8),
                    )
                )

        self.subscription.refresh_from_db()
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            self.subscription.past_due_since,
            self._datetime(self._timestamp(2026, 7, 5)),
        )
        self.assertEqual(
            self.subscription.grace_period_ends_at,
            self._datetime(self._timestamp(2026, 7, 12)),
        )
        self.assertEqual(
            self.subscription.last_payment_failure_at,
            self._datetime(self._timestamp(2026, 7, 8)),
        )

    def test_duplicate_payment_failure_event_does_not_change_grace_twice(self):
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "updated_at",
            ]
        )
        stripe_client, subscription_api = self._stripe_client(
            retrieved_subscription=self._remote_subscription(status="past_due"),
        )
        payload = self._event(
            event_id="evt_duplicate_payment_failed",
            event_type="invoice.payment_failed",
            event_object={
                "id": "in_duplicate_payment_failed",
                "object": "invoice",
                "subscription": "sub_test_motionmate",
                "status": "open",
            },
            created=self._timestamp(2026, 7, 5),
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                first_response = self._signed_post(payload)
                second_response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        event_record = BillingProviderWebhookEvent.objects.get(
            event_id="evt_duplicate_payment_failed"
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(event_record.attempt_count, 1)
        subscription_api.retrieve.assert_called_once()
        self.assertEqual(
            self.subscription.past_due_since,
            self._datetime(self._timestamp(2026, 7, 5)),
        )
        self.assertEqual(
            self.subscription.grace_period_ends_at,
            self._datetime(self._timestamp(2026, 7, 12)),
        )

    def test_subscription_past_due_event_initializes_missing_grace_state(self):
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "updated_at",
            ]
        )
        event_created = self._timestamp(2026, 7, 6)
        payload = self._event(
            event_id="evt_subscription_past_due_grace",
            event_type="customer.subscription.updated",
            event_object=self._remote_subscription(status="past_due"),
            created=event_created,
        )

        with override_settings(**self._valid_stripe_settings()):
            response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PAST_DUE)
        self.assertEqual(self.subscription.past_due_since, self._datetime(event_created))
        self.assertEqual(
            self.subscription.grace_period_ends_at,
            self._datetime(event_created) + timedelta(days=7),
        )

    def test_recovery_subscription_events_clear_current_grace_state(self):
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.PAST_DUE
        self.subscription.past_due_since = self._datetime(self._timestamp(2026, 7, 5))
        self.subscription.grace_period_ends_at = self._datetime(self._timestamp(2026, 7, 12))
        self.subscription.last_payment_failure_at = self._datetime(self._timestamp(2026, 7, 5))
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "past_due_since",
                "grace_period_ends_at",
                "last_payment_failure_at",
                "updated_at",
            ]
        )
        payload = self._event(
            event_id="evt_subscription_active_clears_grace",
            event_type="customer.subscription.updated",
            event_object=self._remote_subscription(status="active"),
            created=self._timestamp(2026, 7, 9),
        )

        with override_settings(**self._valid_stripe_settings()):
            response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertIsNone(self.subscription.past_due_since)
        self.assertIsNone(self.subscription.grace_period_ends_at)
        self.assertEqual(self.subscription.access_mode, SubscriptionAccessMode.FULL)
        self.assertTrue(self.subscription.can_modify_workspace)
        self.assertEqual(
            self.subscription.last_payment_failure_at,
            self._datetime(self._timestamp(2026, 7, 5)),
        )

    def test_newer_cancellation_is_not_overwritten_by_older_paid_invoice(self):
        newer_timestamp = self._timestamp(2026, 7, 10)
        older_timestamp = self._timestamp(2026, 7, 5)
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.CANCELLED
        self.subscription.provider_updated_at = self._datetime(newer_timestamp)
        self.subscription.cancelled_at = self._datetime(newer_timestamp)
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "provider_updated_at",
                "cancelled_at",
                "updated_at",
            ]
        )
        stripe_client, _subscription_api = self._stripe_client(
            retrieved_subscription=self._remote_subscription(status="active"),
        )
        payload = self._event(
            event_id="evt_stale_invoice_paid",
            event_type="invoice.paid",
            event_object={
                "id": "in_stale_paid",
                "object": "invoice",
                "subscription": "sub_test_motionmate",
                "status": "paid",
            },
            created=older_timestamp,
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.CANCELLED)
        self.assertEqual(self.subscription.provider_updated_at, self._datetime(newer_timestamp))

    def test_cancellation_event_clears_current_grace_state(self):
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.PAST_DUE
        self.subscription.past_due_since = self._datetime(self._timestamp(2026, 7, 5))
        self.subscription.grace_period_ends_at = self._datetime(self._timestamp(2026, 7, 12))
        self.subscription.last_payment_failure_at = self._datetime(self._timestamp(2026, 7, 5))
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "past_due_since",
                "grace_period_ends_at",
                "last_payment_failure_at",
                "updated_at",
            ]
        )
        event_created = self._timestamp(2026, 7, 9)
        payload = self._event(
            event_id="evt_subscription_cancelled_clears_grace",
            event_type="customer.subscription.updated",
            event_object=self._remote_subscription(status="canceled", canceled_at=event_created),
            created=event_created,
        )

        with override_settings(**self._valid_stripe_settings()):
            response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.CANCELLED)
        self.assertIsNone(self.subscription.past_due_since)
        self.assertIsNone(self.subscription.grace_period_ends_at)
        self.assertEqual(
            self.subscription.last_payment_failure_at,
            self._datetime(self._timestamp(2026, 7, 5)),
        )

    def test_stale_subscription_event_does_not_overwrite_newer_cancelled_state(self):
        newer_timestamp = self._timestamp(2026, 7, 10)
        older_timestamp = self._timestamp(2026, 7, 5)
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.CANCELLED
        self.subscription.provider_updated_at = self._datetime(newer_timestamp)
        self.subscription.cancelled_at = self._datetime(newer_timestamp)
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "provider_updated_at",
                "cancelled_at",
                "updated_at",
            ]
        )
        payload = self._event(
            event_id="evt_stale_active",
            event_type="customer.subscription.updated",
            event_object=self._remote_subscription(status="active"),
            created=older_timestamp,
        )

        with override_settings(**self._valid_stripe_settings()):
            response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        event_record = BillingProviderWebhookEvent.objects.get(event_id="evt_stale_active")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(event_record.status, BillingProviderWebhookEvent.Status.PROCESSED)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.CANCELLED)
        self.assertEqual(self.subscription.provider_updated_at, self._datetime(newer_timestamp))
        self.assertEqual(self.subscription.cancelled_at, self._datetime(newer_timestamp))

    def test_beta_subscription_metadata_is_ignored_without_adding_provider_ids(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)
        beta_business = Business.objects.create(name="Webhook Beta", slug="webhook-beta")
        beta_subscription = BusinessSubscription.objects.create(
            business=beta_business,
            plan=beta_plan,
            status=BusinessSubscription.Status.ACTIVE,
            payment_provider=BusinessSubscription.PaymentProvider.LOCAL,
            billing_interval="",
            billing_currency="",
        )
        metadata = {
            "motionmate_business_id": str(beta_business.pk),
            "motionmate_subscription_id": str(beta_subscription.pk),
            "plan_slug": beta_plan.slug,
            "billing_interval": "",
            "billing_currency": "",
        }
        provider_object = self._remote_subscription(
            local_subscription=beta_subscription,
            provider_subscription_id="sub_test_beta",
            provider_customer_id="cus_test_beta",
            metadata=metadata,
        )
        provider_object["items"]["data"][0]["price"]["id"] = "price_pro_monthly_usd"
        provider_object["items"]["data"][0]["price"]["currency"] = "usd"
        provider_object["items"]["data"][0]["price"]["recurring"] = {"interval": "month"}
        payload = self._event(
            event_id="evt_beta_ignored",
            event_type="customer.subscription.created",
            event_object=provider_object,
        )

        with override_settings(**self._valid_stripe_settings()):
            response = self._signed_post(payload)

        beta_subscription.refresh_from_db()
        event_record = BillingProviderWebhookEvent.objects.get(event_id="evt_beta_ignored")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(event_record.status, BillingProviderWebhookEvent.Status.IGNORED)
        self.assertEqual(beta_subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertEqual(beta_subscription.provider_customer_id, "")
        self.assertEqual(beta_subscription.provider_subscription_id, "")


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
        trial_start = timezone.now()
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.TRIALING,
            trial_start=trial_start,
            trial_end=trial_start + timedelta(days=14),
            current_period_start=trial_start,
            current_period_end=trial_start + timedelta(days=14),
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


class SubscriptionEffectiveAccessPolicyTests(TestCase):
    @staticmethod
    def _at(day: int, hour: int = 12) -> datetime:
        return datetime(2026, 7, day, hour, tzinfo=UTC)

    def setUp(self):
        self.counter = 0
        self.starter_plan = ClarivoPlan.objects.get(slug="starter")
        self.pro_plan = ClarivoPlan.objects.get(slug="pro")
        self.business_plan = ClarivoPlan.objects.get(slug="business")
        self.beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)

    def _business(self, *, is_active: bool = True) -> Business:
        self.counter += 1
        return Business.objects.create(
            name=f"Access Policy {self.counter}",
            slug=f"access-policy-{self.counter}",
            is_active=is_active,
        )

    def _subscription(
        self,
        *,
        status: str,
        plan: ClarivoPlan | None = None,
        business: Business | None = None,
        **overrides,
    ) -> BusinessSubscription:
        return BusinessSubscription.objects.create(
            business=business or self._business(),
            plan=plan or self.pro_plan,
            status=status,
            **overrides,
        )

    def test_public_trials_keep_selected_plan_entitlements_before_trial_end(self):
        now = self._at(1)
        for plan in (self.starter_plan, self.pro_plan, self.business_plan):
            with self.subTest(plan=plan.slug):
                subscription = self._subscription(
                    status=BusinessSubscription.Status.TRIALING,
                    plan=plan,
                    trial_start=now - timedelta(days=1),
                    trial_end=now + timedelta(days=1),
                    current_period_start=now - timedelta(days=1),
                    current_period_end=now + timedelta(days=1),
                )

                self.assertTrue(subscription.has_access_at(now))
                self.assertTrue(subscription.can_use_module_at("client_management", now))
                self.assertEqual(subscription.plan, plan)
                self.assertEqual(
                    subscription.can_use_module_at("appointments", now),
                    plan.allows_module("appointments"),
                )
                self.assertEqual(
                    subscription.can_use_module_at("public_booking", now),
                    plan.allows_module("public_booking"),
                )

    def test_trial_access_uses_exact_trial_end_boundary_without_mutating_status(self):
        end_at = self._at(4)
        subscription = self._subscription(
            status=BusinessSubscription.Status.TRIALING,
            trial_start=end_at - timedelta(days=14),
            trial_end=end_at,
            current_period_start=end_at - timedelta(days=14),
            current_period_end=end_at,
        )
        original_updated_at = subscription.updated_at

        self.assertTrue(subscription.has_access_at(end_at - timedelta(seconds=1)))
        self.assertFalse(subscription.has_access_at(end_at))
        self.assertFalse(subscription.has_access_at(end_at + timedelta(seconds=1)))
        self.assertEqual(
            subscription.effective_access_status_at(end_at),
            BusinessSubscription.AccessCode.TRIAL_EXPIRED,
        )

        subscription.refresh_from_db()
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(subscription.updated_at, original_updated_at)

    def test_trial_missing_end_fails_closed(self):
        now = self._at(5)
        subscription = self._subscription(status=BusinessSubscription.Status.TRIALING)

        state = subscription.effective_access_state_at(now)

        self.assertFalse(state.has_access)
        self.assertEqual(state.code, BusinessSubscription.AccessCode.TRIAL_MISSING_END)
        self.assertTrue(state.billing_attention_required)
        self.assertFalse(subscription.can_use_module_at("invoicing", now))

    def test_stripe_active_period_uses_exact_current_period_boundary(self):
        end_at = self._at(8)
        subscription = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_access_policy",
            provider_subscription_id="sub_access_policy",
            provider_price_id="price_pro_monthly_usd",
            current_period_start=end_at - timedelta(days=30),
            current_period_end=end_at,
        )

        self.assertTrue(subscription.has_access_at(end_at - timedelta(seconds=1)))
        self.assertFalse(subscription.has_access_at(end_at))
        self.assertFalse(subscription.has_access_at(end_at + timedelta(seconds=1)))
        self.assertEqual(
            subscription.effective_access_status_at(end_at),
            BusinessSubscription.AccessCode.PROVIDER_STATE_STALE,
        )

    def test_stripe_active_missing_period_fails_closed_but_manual_active_and_beta_remain_valid(
        self,
    ):
        now = self._at(9)
        stripe_subscription = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_missing_period",
            provider_subscription_id="sub_missing_period",
            provider_price_id="price_pro_monthly_usd",
        )
        manual_subscription = self._subscription(status=BusinessSubscription.Status.ACTIVE)
        beta_subscription = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            plan=self.beta_plan,
        )

        self.assertFalse(stripe_subscription.has_access_at(now))
        self.assertEqual(
            stripe_subscription.effective_access_status_at(now),
            BusinessSubscription.AccessCode.PROVIDER_PERIOD_MISSING,
        )
        self.assertTrue(manual_subscription.has_access_at(now))
        self.assertTrue(beta_subscription.has_access_at(now))
        self.assertTrue(beta_subscription.can_use_module_at("appointments", now))

    def test_scheduled_cancellation_allows_access_only_until_effective_end(self):
        end_at = self._at(12)
        active_subscription = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            cancel_at_period_end=True,
            current_period_start=end_at - timedelta(days=30),
            current_period_end=end_at,
        )
        trial_subscription = self._subscription(
            status=BusinessSubscription.Status.TRIALING,
            cancel_at_period_end=True,
            trial_start=end_at - timedelta(days=14),
            trial_end=end_at,
            current_period_start=end_at - timedelta(days=14),
            current_period_end=end_at + timedelta(days=16),
        )

        for subscription in (active_subscription, trial_subscription):
            with self.subTest(subscription=subscription.pk):
                before_state = subscription.effective_access_state_at(end_at - timedelta(seconds=1))
                boundary_state = subscription.effective_access_state_at(end_at)

                self.assertTrue(before_state.has_access)
                self.assertEqual(
                    before_state.code,
                    BusinessSubscription.AccessCode.CANCELS_AT_PERIOD_END,
                )
                self.assertEqual(before_state.access_ends_at, end_at)
                self.assertFalse(boundary_state.has_access)

    def test_past_due_grace_keeps_selected_plan_access_until_exact_boundary(self):
        start_at = self._at(13)
        grace_end = start_at + timedelta(days=7)

        for plan in (self.starter_plan, self.pro_plan, self.business_plan):
            with self.subTest(plan=plan.slug):
                subscription = self._subscription(
                    status=BusinessSubscription.Status.PAST_DUE,
                    plan=plan,
                    payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
                    billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
                    billing_currency=BusinessSubscription.BillingCurrency.USD,
                    provider_customer_id=f"cus_grace_{plan.slug}",
                    provider_subscription_id=f"sub_grace_{plan.slug}",
                    provider_price_id=f"price_{plan.slug}_monthly_usd",
                    past_due_since=start_at,
                    grace_period_ends_at=grace_end,
                    current_period_start=start_at - timedelta(days=30),
                    current_period_end=grace_end + timedelta(days=23),
                )

                before_state = subscription.effective_access_state_at(
                    grace_end - timedelta(seconds=1)
                )
                boundary_state = subscription.effective_access_state_at(grace_end)
                after_state = subscription.effective_access_state_at(
                    grace_end + timedelta(seconds=1)
                )

                self.assertTrue(before_state.has_access)
                self.assertEqual(before_state.mode, SubscriptionAccessMode.FULL)
                self.assertEqual(before_state.code, BusinessSubscription.AccessCode.PAST_DUE_GRACE)
                self.assertTrue(before_state.billing_attention_required)
                self.assertTrue(before_state.payment_recovery_available)
                self.assertEqual(before_state.access_ends_at, grace_end)
                self.assertFalse(boundary_state.has_access)
                self.assertEqual(boundary_state.mode, SubscriptionAccessMode.RESTRICTED)
                self.assertTrue(boundary_state.can_view_workspace)
                self.assertFalse(boundary_state.can_modify_workspace)
                self.assertEqual(
                    boundary_state.code,
                    BusinessSubscription.AccessCode.PAST_DUE_GRACE_EXPIRED,
                )
                self.assertFalse(after_state.has_access)
                self.assertEqual(after_state.mode, SubscriptionAccessMode.RESTRICTED)
                self.assertTrue(subscription.can_use_module_at("client_management", start_at))
                self.assertFalse(subscription.can_use_module_at("client_management", grace_end))
                self.assertTrue(subscription.can_view_module_at("client_management", grace_end))
                self.assertEqual(
                    subscription.can_use_module_at("appointments", start_at),
                    plan.allows_module("appointments"),
                )
                self.assertEqual(
                    subscription.can_view_module_at("appointments", grace_end),
                    plan.allows_module("appointments"),
                )
                self.assertEqual(
                    subscription.can_use_module_at("public_booking", start_at),
                    plan.allows_module("public_booking"),
                )

    def test_past_due_missing_or_malformed_grace_state_fails_closed_without_side_effects(self):
        now = self._at(14)
        cases = (
            {"past_due_since": now, "grace_period_ends_at": None},
            {"past_due_since": None, "grace_period_ends_at": now + timedelta(days=1)},
            {
                "past_due_since": now,
                "grace_period_ends_at": now - timedelta(seconds=1),
            },
        )

        for index, fields in enumerate(cases, start=1):
            with self.subTest(index=index):
                subscription = self._subscription(
                    status=BusinessSubscription.Status.PAST_DUE,
                    payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
                    billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
                    billing_currency=BusinessSubscription.BillingCurrency.USD,
                    provider_customer_id=f"cus_missing_grace_{index}",
                    provider_subscription_id=f"sub_missing_grace_{index}",
                    provider_price_id="price_pro_monthly_usd",
                    **fields,
                )
                original_updated_at = subscription.updated_at

                with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                    state = subscription.effective_access_state_at(now)

                subscription.refresh_from_db()
                self.assertFalse(state.has_access)
                self.assertEqual(
                    state.code,
                    BusinessSubscription.AccessCode.PAST_DUE_MISSING_GRACE_STATE,
                )
                self.assertTrue(state.payment_recovery_available)
                self.assertEqual(subscription.updated_at, original_updated_at)
                configure_sdk.assert_not_called()

    def test_zero_day_past_due_grace_denies_access_at_failure_time(self):
        failure_at = self._at(15)
        subscription = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_zero_grace",
            provider_subscription_id="sub_zero_grace",
            provider_price_id="price_pro_monthly_usd",
            past_due_since=failure_at,
            grace_period_ends_at=failure_at,
        )

        state = subscription.effective_access_state_at(failure_at)

        self.assertFalse(state.has_access)
        self.assertEqual(state.mode, SubscriptionAccessMode.RESTRICTED)
        self.assertEqual(state.code, BusinessSubscription.AccessCode.PAST_DUE_GRACE_EXPIRED)

    def test_access_mode_helpers_distinguish_full_restricted_and_none(self):
        now = self._at(16)
        restricted_subscription = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_restricted_mode",
            provider_subscription_id="sub_restricted_mode",
            provider_price_id="price_pro_monthly_usd",
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        active_subscription = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=29),
        )
        cancelled_subscription = self._subscription(status=BusinessSubscription.Status.CANCELLED)

        self.assertEqual(active_subscription.access_mode_at(now), SubscriptionAccessMode.FULL)
        self.assertTrue(active_subscription.has_access_at(now))
        self.assertTrue(active_subscription.can_modify_workspace_at(now))

        self.assertEqual(
            restricted_subscription.access_mode_at(now),
            SubscriptionAccessMode.RESTRICTED,
        )
        self.assertFalse(restricted_subscription.has_access_at(now))
        self.assertFalse(restricted_subscription.can_modify_workspace_at(now))
        self.assertTrue(restricted_subscription.can_view_workspace_at(now))
        self.assertTrue(restricted_subscription.can_view_module_at("crm", now))
        self.assertFalse(restricted_subscription.can_use_module_at("crm", now))

        self.assertEqual(cancelled_subscription.access_mode_at(now), SubscriptionAccessMode.NONE)
        self.assertFalse(cancelled_subscription.can_view_workspace_at(now))
        self.assertFalse(cancelled_subscription.can_modify_workspace_at(now))

    def test_restricted_mode_requires_public_paid_stripe_identity(self):
        now = self._at(17)
        cases = (
            {"provider_customer_id": ""},
            {"provider_subscription_id": ""},
            {"provider_price_id": ""},
            {"billing_interval": "weekly"},
            {"billing_currency": "xcd"},
            {"plan": self.beta_plan},
        )

        for index, overrides in enumerate(cases, start=1):
            with self.subTest(index=index):
                fields = {
                    "status": BusinessSubscription.Status.PAST_DUE,
                    "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
                    "billing_interval": BusinessSubscription.BillingInterval.MONTHLY,
                    "billing_currency": BusinessSubscription.BillingCurrency.USD,
                    "provider_customer_id": f"cus_invalid_identity_{index}",
                    "provider_subscription_id": f"sub_invalid_identity_{index}",
                    "provider_price_id": "price_pro_monthly_usd",
                    "past_due_since": now - timedelta(days=10),
                    "grace_period_ends_at": now - timedelta(days=3),
                }
                fields.update(overrides)
                subscription = self._subscription(**fields)

                state = subscription.effective_access_state_at(now)

                self.assertEqual(state.mode, SubscriptionAccessMode.NONE)
                self.assertFalse(state.can_view_workspace)
                self.assertEqual(
                    state.code,
                    BusinessSubscription.AccessCode.PAST_DUE_PROVIDER_IDENTITY_INVALID,
                )

    def test_access_mode_evaluation_has_no_write_or_stripe_side_effects(self):
        now = self._at(18)
        subscription = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_side_effect_free",
            provider_subscription_id="sub_side_effect_free",
            provider_price_id="price_pro_monthly_usd",
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        original_updated_at = subscription.updated_at

        with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
            state = subscription.effective_access_state_at(now)

        subscription.refresh_from_db()
        self.assertEqual(state.mode, SubscriptionAccessMode.RESTRICTED)
        self.assertEqual(subscription.updated_at, original_updated_at)
        configure_sdk.assert_not_called()

    def test_fail_closed_statuses_inactive_records_and_unknown_statuses(self):
        now = self._at(14)
        inactive_business_subscription = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            business=self._business(is_active=False),
        )
        inactive_plan = ClarivoPlan.objects.create(
            name="Inactive Plan",
            slug="inactive-plan-access",
            is_active=False,
        )
        inactive_plan_subscription = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            plan=inactive_plan,
        )
        cases = (
            (
                self._subscription(status=BusinessSubscription.Status.PENDING_CHECKOUT),
                BusinessSubscription.AccessCode.PENDING_CHECKOUT,
            ),
            (
                self._subscription(status=BusinessSubscription.Status.PAST_DUE),
                BusinessSubscription.AccessCode.BILLING_PAST_DUE,
            ),
            (
                self._subscription(status=BusinessSubscription.Status.CANCELLED),
                BusinessSubscription.AccessCode.SUBSCRIPTION_CANCELLED,
            ),
            (
                self._subscription(status=BusinessSubscription.Status.EXPIRED),
                BusinessSubscription.AccessCode.SUBSCRIPTION_EXPIRED,
            ),
            (
                self._subscription(status="surprise"),
                BusinessSubscription.AccessCode.UNSUPPORTED_STATUS,
            ),
            (
                inactive_business_subscription,
                BusinessSubscription.AccessCode.BUSINESS_INACTIVE,
            ),
            (
                inactive_plan_subscription,
                BusinessSubscription.AccessCode.PLAN_INACTIVE,
            ),
        )

        for subscription, code in cases:
            with self.subTest(code=code):
                state = subscription.effective_access_state_at(now)

                self.assertFalse(state.has_access)
                self.assertEqual(state.code, code)
                self.assertTrue(state.billing_attention_required)
                self.assertFalse(subscription.can_use_module_at("invoicing", now))

    def test_expired_subscription_does_not_apply_limits_or_change_plan(self):
        business = self._business()
        subscription = self._subscription(
            business=business,
            plan=self.business_plan,
            status=BusinessSubscription.Status.EXPIRED,
        )

        self.assertFalse(business_limit_reached(business, "users"))
        self.assertFalse(can_use_module(business, "appointments"))
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan, self.business_plan)


class ReconcileSubscriptionAccessCommandTests(TestCase):
    @staticmethod
    def _now() -> datetime:
        return datetime(2026, 7, 20, 12, tzinfo=UTC)

    def setUp(self):
        self.counter = 0
        self.plan = ClarivoPlan.objects.get(slug="pro")
        self.beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)

    def _business(self) -> Business:
        self.counter += 1
        return Business.objects.create(
            name=f"Reconcile Workspace {self.counter}",
            slug=f"reconcile-workspace-{self.counter}",
        )

    def _subscription(self, *, plan: ClarivoPlan | None = None, **overrides):
        defaults = {
            "business": self._business(),
            "plan": plan or self.plan,
            "status": BusinessSubscription.Status.ACTIVE,
        }
        defaults.update(overrides)
        return BusinessSubscription.objects.create(**defaults)

    def _call_command(self, *, dry_run: bool = False) -> str:
        output = StringIO()
        with mock.patch("django.utils.timezone.now", return_value=self._now()):
            call_command(
                "reconcile_subscription_access",
                dry_run=dry_run,
                stdout=output,
            )
        return output.getvalue()

    def test_dry_run_reports_expired_local_trials_without_database_or_email_side_effects(self):
        subscription = self._subscription(
            status=BusinessSubscription.Status.TRIALING,
            trial_start=self._now() - timedelta(days=20),
            trial_end=self._now() - timedelta(days=1),
            current_period_start=self._now() - timedelta(days=20),
            current_period_end=self._now() - timedelta(days=1),
        )

        with mock.patch("apps.businesses.stripe_config.configure_stripe_sdk") as stripe_sdk:
            output = self._call_command(dry_run=True)

        subscription.refresh_from_db()
        self.assertIn("Dry run only; no subscription records were changed.", output)
        self.assertIn("Expired local trials: 1", output)
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(mail.outbox, [])
        stripe_sdk.assert_not_called()

    def test_expired_local_trials_transition_to_expired_idempotently(self):
        subscription = self._subscription(
            status=BusinessSubscription.Status.TRIALING,
            trial_start=self._now() - timedelta(days=20),
            trial_end=self._now(),
            current_period_start=self._now() - timedelta(days=20),
            current_period_end=self._now(),
        )

        first_output = self._call_command()
        second_output = self._call_command()

        subscription.refresh_from_db()
        self.assertEqual(subscription.status, BusinessSubscription.Status.EXPIRED)
        self.assertIn("Expired local trials: 1", first_output)
        self.assertIn("Expired local trials: 0", second_output)

    def test_future_trials_past_due_missing_grace_and_beta_remain_unchanged(self):
        future_trial = self._subscription(
            status=BusinessSubscription.Status.TRIALING,
            trial_start=self._now() - timedelta(days=1),
            trial_end=self._now() + timedelta(days=1),
            current_period_start=self._now() - timedelta(days=1),
            current_period_end=self._now() + timedelta(days=1),
        )
        past_due = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_missing_grace_reconcile",
            provider_subscription_id="sub_missing_grace_reconcile",
            provider_price_id="price_pro_monthly_usd",
        )
        beta = self._subscription(
            plan=self.beta_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        output = self._call_command()

        future_trial.refresh_from_db()
        past_due.refresh_from_db()
        beta.refresh_from_db()
        self.assertEqual(future_trial.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(past_due.status, BusinessSubscription.Status.PAST_DUE)
        self.assertEqual(beta.status, BusinessSubscription.Status.ACTIVE)
        self.assertIn("Future trials unchanged: 1", output)
        self.assertIn("Past due missing grace fields: 1", output)
        self.assertIn("Beta subscriptions unchanged: 1", output)

    def test_past_due_grace_reporting_does_not_extend_or_mutate(self):
        within_grace = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_within_grace",
            provider_subscription_id="sub_within_grace",
            provider_price_id="price_pro_monthly_usd",
            past_due_since=self._now() - timedelta(days=1),
            grace_period_ends_at=self._now() + timedelta(days=6),
        )
        expired_grace = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_expired_grace",
            provider_subscription_id="sub_expired_grace",
            provider_price_id="price_pro_monthly_usd",
            past_due_since=self._now() - timedelta(days=10),
            grace_period_ends_at=self._now() - timedelta(days=3),
        )
        missing_grace = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_missing_grace",
            provider_subscription_id="sub_missing_grace",
            provider_price_id="price_pro_monthly_usd",
        )
        original_values = {
            subscription.pk: (
                subscription.status,
                subscription.past_due_since,
                subscription.grace_period_ends_at,
                subscription.updated_at,
            )
            for subscription in (within_grace, expired_grace, missing_grace)
        }

        with mock.patch("apps.businesses.stripe_config.configure_stripe_sdk") as stripe_sdk:
            output = self._call_command(dry_run=True)

        self.assertIn("Dry run only; no subscription records were changed.", output)
        self.assertIn("Restricted after grace: 1", output)
        self.assertIn("Past due within grace: 1", output)
        self.assertIn("Past due grace expired: 1", output)
        self.assertIn("Past due missing grace fields: 1", output)
        stripe_sdk.assert_not_called()
        self.assertEqual(mail.outbox, [])
        for subscription in (within_grace, expired_grace, missing_grace):
            subscription.refresh_from_db()
            self.assertEqual(
                (
                    subscription.status,
                    subscription.past_due_since,
                    subscription.grace_period_ends_at,
                    subscription.updated_at,
                ),
                original_values[subscription.pk],
            )

    def test_completed_scheduled_cancellations_transition_only_at_boundary(self):
        completed = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            cancel_at_period_end=True,
            current_period_start=self._now() - timedelta(days=30),
            current_period_end=self._now(),
        )
        future = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            cancel_at_period_end=True,
            current_period_start=self._now() - timedelta(days=29),
            current_period_end=self._now() + timedelta(seconds=1),
        )

        output = self._call_command()

        completed.refresh_from_db()
        future.refresh_from_db()
        self.assertEqual(completed.status, BusinessSubscription.Status.CANCELLED)
        self.assertEqual(future.status, BusinessSubscription.Status.ACTIVE)
        self.assertIn("Completed scheduled cancellations: 1", output)

    def test_provider_states_are_reported_without_inventing_statuses(self):
        expired_provider_trial = self._subscription(
            status=BusinessSubscription.Status.TRIALING,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            trial_start=self._now() - timedelta(days=20),
            trial_end=self._now(),
            current_period_start=self._now() - timedelta(days=20),
            current_period_end=self._now(),
            provider_customer_id="cus_provider_trial",
            provider_subscription_id="sub_provider_trial",
        )
        stale_active = self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            current_period_start=self._now() - timedelta(days=30),
            current_period_end=self._now(),
            provider_customer_id="cus_provider_active",
            provider_subscription_id="sub_provider_active",
        )

        output = self._call_command()

        expired_provider_trial.refresh_from_db()
        stale_active.refresh_from_db()
        self.assertEqual(expired_provider_trial.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(stale_active.status, BusinessSubscription.Status.ACTIVE)
        self.assertIn("Expired provider trials requiring reconciliation: 1", output)
        self.assertIn("Stale provider subscriptions requiring reconciliation: 1", output)


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

    def test_workspace_access_guard_allows_restricted_reads_and_denies_writes_for_json(self):
        business = Business.objects.create(name="Restricted HQ", slug="restricted-hq")
        plan = ClarivoPlan.objects.get(slug="pro")
        now = timezone.now()
        BusinessUser.objects.create(user=self.user, business=business, role=BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=business,
            plan=plan,
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_guard_restricted",
            provider_subscription_id="sub_guard_restricted",
            provider_price_id="price_pro_monthly_usd",
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )

        @business_workspace_access_required(access="read")
        def read_view(request):
            return HttpResponse("read ok")

        @business_workspace_access_required(access="write")
        def write_view(request):
            return HttpResponse("write ok")

        read_request = self._build_request({CURRENT_BUSINESS_SESSION_KEY: business.id})
        write_request = self.factory.post(
            "/guarded/",
            HTTP_ACCEPT="application/json",
        )
        write_request.user = self.user
        write_request.session = {CURRENT_BUSINESS_SESSION_KEY: business.id}

        read_response = read_view(read_request)
        write_response = write_view(write_request)

        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(read_response.content, b"read ok")
        self.assertEqual(write_response.status_code, 403)
        self.assertEqual(
            json.loads(write_response.content),
            {
                "error": "subscription_restricted",
                "message": "This workspace is currently read-only. Update the subscription to make changes.",
            },
        )

    def test_module_access_guard_preserves_plan_modules_in_restricted_mode(self):
        business = Business.objects.create(name="Restricted Modules", slug="restricted-modules")
        starter_plan = ClarivoPlan.objects.get(slug="starter")
        starter_plan.allow_invoicing = False
        starter_plan.save(update_fields=["allow_invoicing", "updated_at"])
        now = timezone.now()
        BusinessUser.objects.create(user=self.user, business=business, role=BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=business,
            plan=starter_plan,
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_module_restricted",
            provider_subscription_id="sub_module_restricted",
            provider_price_id="price_starter_monthly_usd",
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )

        @business_module_required("crm", access="read")
        def crm_read_view(request):
            return HttpResponse("crm read ok")

        @business_module_required("invoicing", access="read")
        def invoice_read_view(request):
            return HttpResponse("invoice read ok")

        self.assertTrue(business_can_view_workspace(business))
        self.assertFalse(business_can_modify_workspace(business))
        self.assertTrue(business_has_restricted_subscription(business))
        self.assertTrue(can_view_module(business, "crm"))
        self.assertFalse(can_use_module(business, "crm"))

        crm_request = self._build_request({CURRENT_BUSINESS_SESSION_KEY: business.id})
        invoice_request = self.factory.get("/guarded/", HTTP_ACCEPT="application/json")
        invoice_request.user = self.user
        invoice_request.session = {CURRENT_BUSINESS_SESSION_KEY: business.id}

        crm_response = crm_read_view(crm_request)
        invoice_response = invoice_read_view(invoice_request)

        self.assertEqual(crm_response.status_code, 200)
        self.assertEqual(crm_response.content, b"crm read ok")
        self.assertEqual(invoice_response.status_code, 403)
        self.assertEqual(json.loads(invoice_response.content)["error"], "subscription_unavailable")


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
        self.settings_access_plan = ClarivoPlan.objects.create(
            name="Settings Access",
            slug="settings-access-plan",
        )

    def _enable_full_subscription(self):
        if BusinessSubscription.objects.filter(business=self.business).exists():
            return
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.settings_access_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

    def _login_with_role(self, role: str):
        self._enable_full_subscription()
        BusinessUser.objects.update_or_create(
            user=self.user,
            business=self.business,
            defaults={"role": role, "is_active": True},
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

    def _enable_full_subscription(self):
        if BusinessSubscription.objects.filter(business=self.business).exists():
            return
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.public_booking_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

    def _login_with_role(self, role: str):
        self._enable_full_subscription()
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
        BusinessUser.objects.update_or_create(
            user=self.user,
            business=self.business,
            defaults={"role": role, "is_active": True},
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
            "STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "bpc_test_motionmate",
            "STRIPE_PRICE_ID_MAP": self._price_map(),
        }
        settings_overrides.update(overrides)
        return settings_overrides

    def _stripe_subscription(self, **overrides):
        now = timezone.now()
        defaults = {
            "business": self.business,
            "plan": self.pro_plan,
            "status": BusinessSubscription.Status.ACTIVE,
            "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
            "billing_interval": BusinessSubscription.BillingInterval.MONTHLY,
            "billing_currency": BusinessSubscription.BillingCurrency.USD,
            "provider_customer_id": "cus_subscription_view",
            "provider_subscription_id": "sub_subscription_view",
            "provider_price_id": "price_pro_monthly_usd",
            "current_period_start": now - timedelta(days=1),
            "current_period_end": now + timedelta(days=29),
        }
        defaults.update(overrides)
        return BusinessSubscription.objects.create(**defaults)

    def _stripe_portal_client(self, *, url: str = "https://billing.stripe.test/session"):
        session_api = SimpleNamespace(create=mock.Mock(return_value={"id": "bps_view", "url": url}))
        return SimpleNamespace(billing_portal=SimpleNamespace(Session=session_api)), session_api

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

    def test_subscription_page_shows_owner_safe_effective_access_messages(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        inactive_plan = ClarivoPlan.objects.create(
            name="Inactive Owner State",
            slug="inactive-owner-state",
            is_active=False,
        )
        states = (
            (
                {
                    "plan": self.pro_plan,
                    "status": BusinessSubscription.Status.PENDING_CHECKOUT,
                    "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
                    "billing_interval": BusinessSubscription.BillingInterval.MONTHLY,
                    "billing_currency": BusinessSubscription.BillingCurrency.USD,
                    "provider_checkout_session_id": "cs_owner_state",
                },
                "Complete your payment setup to start your 14-day trial.",
            ),
            (
                {
                    "plan": self.pro_plan,
                    "status": BusinessSubscription.Status.TRIALING,
                    "trial_start": now - timedelta(days=1),
                    "trial_end": now + timedelta(days=1),
                    "current_period_start": now - timedelta(days=1),
                    "current_period_end": now + timedelta(days=1),
                },
                "Your Pro trial ends on",
            ),
            (
                {
                    "plan": self.pro_plan,
                    "status": BusinessSubscription.Status.TRIALING,
                    "trial_start": now - timedelta(days=15),
                    "trial_end": now - timedelta(days=1),
                    "current_period_start": now - timedelta(days=15),
                    "current_period_end": now - timedelta(days=1),
                },
                "Your free trial has ended.",
            ),
            (
                {
                    "plan": self.pro_plan,
                    "status": BusinessSubscription.Status.ACTIVE,
                },
                "Your Pro subscription is active.",
            ),
            (
                {
                    "plan": self.pro_plan,
                    "status": BusinessSubscription.Status.ACTIVE,
                    "cancel_at_period_end": True,
                    "current_period_start": now - timedelta(days=10),
                    "current_period_end": now + timedelta(days=1),
                },
                "Your Pro subscription will remain available until",
            ),
            (
                {
                    "plan": self.pro_plan,
                    "status": BusinessSubscription.Status.PAST_DUE,
                },
                "There is a payment issue with your subscription.",
            ),
            (
                {
                    "plan": self.pro_plan,
                    "status": BusinessSubscription.Status.CANCELLED,
                },
                "Your subscription is no longer active.",
            ),
            (
                {
                    "plan": self.pro_plan,
                    "status": BusinessSubscription.Status.ACTIVE,
                    "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
                    "billing_interval": BusinessSubscription.BillingInterval.MONTHLY,
                    "billing_currency": BusinessSubscription.BillingCurrency.USD,
                    "provider_customer_id": "cus_hidden_owner_state",
                    "provider_subscription_id": "sub_hidden_owner_state",
                    "provider_price_id": "price_pro_monthly_usd",
                    "current_period_start": now - timedelta(days=40),
                    "current_period_end": now - timedelta(days=1),
                },
                "We could not confirm your latest subscription period.",
            ),
            (
                {
                    "plan": inactive_plan,
                    "status": BusinessSubscription.Status.ACTIVE,
                },
                "This workspace plan is inactive.",
            ),
        )

        for fields, expected_copy in states:
            with self.subTest(expected_copy=expected_copy):
                BusinessSubscription.objects.filter(business=self.business).delete()
                BusinessSubscription.objects.create(business=self.business, **fields)

                response = self.client.get(reverse("business_subscription"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, expected_copy)
                self.assertNotContains(response, "cus_hidden_owner_state")
                self.assertNotContains(response, "sub_hidden_owner_state")
                self.assertNotContains(response, "Customer Portal")

    def test_eligible_owner_can_post_to_customer_portal_route(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        subscription = self._stripe_subscription()
        stripe_client, session_api = self._stripe_portal_client()

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_portal,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                response = self.client.post(
                    reverse("billing_customer_portal"),
                    {
                        "customer": "cus_browser_tamper",
                        "return_url": "https://evil.example/return",
                        "configuration": "bpc_browser_tamper",
                    },
                )

        subscription.refresh_from_db()
        create_kwargs = session_api.create.call_args.kwargs

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://billing.stripe.test/session")
        self.assertEqual(create_kwargs["customer"], "cus_subscription_view")
        self.assertEqual(create_kwargs["configuration"], "bpc_test_motionmate")
        self.assertTrue(
            create_kwargs["return_url"].endswith(
                reverse("business_subscription") + "?billing_return=1"
            )
        )
        self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertEqual(subscription.provider_customer_id, "cus_subscription_view")
        self.assertEqual(subscription.provider_subscription_id, "sub_subscription_view")

    def test_customer_portal_route_rejects_get_staff_unauthenticated_and_missing_csrf(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        self._stripe_subscription()
        stripe_client, session_api = self._stripe_portal_client()

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_portal,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                get_response = self.client.get(reverse("billing_customer_portal"))

        self.assertEqual(get_response.status_code, 405)
        session_api.create.assert_not_called()

        self.client.logout()
        self.client.force_login(self.user)
        BusinessUser.objects.filter(user=self.user, business=self.business).update(
            role=BusinessUser.Role.STAFF
        )
        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                staff_response = self.client.post(reverse("billing_customer_portal"))
        self.assertEqual(staff_response.status_code, 403)
        configure_sdk.assert_not_called()

        self.client.logout()
        unauthenticated_response = self.client.post(reverse("billing_customer_portal"))
        self.assertEqual(unauthenticated_response.status_code, 302)
        self.assertIn(reverse("business_login"), unauthenticated_response.url)

        csrf_client = DjangoClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        csrf_session = csrf_client.session
        csrf_session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        csrf_session.save()
        BusinessUser.objects.filter(user=self.user, business=self.business).update(
            role=BusinessUser.Role.OWNER
        )
        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                csrf_response = csrf_client.post(reverse("billing_customer_portal"))
        self.assertEqual(csrf_response.status_code, 403)
        configure_sdk.assert_not_called()

    def test_owner_can_post_to_payment_recovery_route_during_and_after_grace(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        cases = (
            {
                "past_due_since": now - timedelta(days=1),
                "grace_period_ends_at": now + timedelta(days=6),
            },
            {
                "past_due_since": now - timedelta(days=10),
                "grace_period_ends_at": now - timedelta(days=3),
            },
        )

        with override_settings(**self._valid_stripe_settings()):
            for fields in cases:
                with self.subTest(grace_period_ends_at=fields["grace_period_ends_at"]):
                    BusinessSubscription.objects.filter(business=self.business).delete()
                    subscription = self._stripe_subscription(
                        status=BusinessSubscription.Status.PAST_DUE,
                        **fields,
                    )
                    stripe_client, session_api = self._stripe_portal_client()

                    with mock.patch.object(
                        stripe_portal,
                        "configure_stripe_sdk",
                        return_value=stripe_client,
                    ):
                        response = self.client.post(
                            reverse("billing_payment_recovery"),
                            {
                                "customer": "cus_browser_tamper",
                                "return_url": "https://evil.example/return",
                                "configuration": "bpc_browser_tamper",
                                "amount": "1",
                                "price": "price_browser_tamper",
                            },
                        )

                    subscription.refresh_from_db()
                    create_kwargs = session_api.create.call_args.kwargs
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.url, "https://billing.stripe.test/session")
                    self.assertEqual(create_kwargs["customer"], "cus_subscription_view")
                    self.assertEqual(create_kwargs["configuration"], "bpc_test_motionmate")
                    self.assertTrue(
                        create_kwargs["return_url"].endswith(
                            reverse("business_subscription") + "?billing_return=1"
                        )
                    )
                    self.assertEqual(subscription.status, BusinessSubscription.Status.PAST_DUE)

    def test_payment_recovery_route_rejects_get_staff_active_beta_and_missing_csrf(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=1),
            grace_period_ends_at=now + timedelta(days=6),
        )
        stripe_client, session_api = self._stripe_portal_client()

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_portal,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                get_response = self.client.get(reverse("billing_payment_recovery"))

        self.assertEqual(get_response.status_code, 405)
        session_api.create.assert_not_called()

        self.client.logout()
        self.client.force_login(self.user)
        BusinessUser.objects.filter(user=self.user, business=self.business).update(
            role=BusinessUser.Role.STAFF
        )
        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                staff_response = self.client.post(reverse("billing_payment_recovery"))
        self.assertEqual(staff_response.status_code, 403)
        configure_sdk.assert_not_called()

        self.client.logout()
        self._login_with_role(BusinessUser.Role.OWNER)
        BusinessSubscription.objects.filter(business=self.business).delete()
        self._stripe_subscription(status=BusinessSubscription.Status.ACTIVE)
        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                active_response = self.client.post(
                    reverse("billing_payment_recovery"),
                    follow=True,
                )
        self.assertRedirects(active_response, reverse("business_subscription"))
        self.assertContains(active_response, PAYMENT_RECOVERY_NOT_AVAILABLE_MESSAGE)
        configure_sdk.assert_not_called()

        BusinessSubscription.objects.filter(business=self.business).delete()
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)
        BusinessSubscription.objects.create(
            business=self.business,
            plan=beta_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                beta_response = self.client.post(
                    reverse("billing_payment_recovery"),
                    follow=True,
                )
        self.assertRedirects(beta_response, reverse("business_subscription"))
        self.assertNotContains(beta_response, "Fix payment")
        configure_sdk.assert_not_called()

        csrf_client = DjangoClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        csrf_session = csrf_client.session
        csrf_session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        csrf_session.save()
        BusinessUser.objects.filter(user=self.user, business=self.business).update(
            role=BusinessUser.Role.OWNER
        )
        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                csrf_response = csrf_client.post(reverse("billing_payment_recovery"))
        self.assertEqual(csrf_response.status_code, 403)
        configure_sdk.assert_not_called()

    def test_customer_portal_missing_provider_ids_and_stripe_failures_show_safe_messages(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        self._stripe_subscription(provider_customer_id="")

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                missing_id_response = self.client.post(
                    reverse("billing_customer_portal"),
                    follow=True,
                )

        self.assertRedirects(missing_id_response, reverse("business_subscription"))
        self.assertContains(missing_id_response, PORTAL_TEMPORARILY_UNAVAILABLE_MESSAGE)
        configure_sdk.assert_not_called()

        BusinessSubscription.objects.filter(business=self.business).delete()
        subscription = self._stripe_subscription()
        stripe_client, _session_api = self._stripe_portal_client()
        stripe_client.billing_portal.Session.create.side_effect = Exception("raw stripe outage")

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_portal,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                failure_response = self.client.post(
                    reverse("billing_customer_portal"),
                    follow=True,
                )

        subscription.refresh_from_db()
        self.assertRedirects(failure_response, reverse("business_subscription"))
        self.assertContains(failure_response, PORTAL_OPEN_FAILED_MESSAGE)
        self.assertNotContains(failure_response, "raw stripe outage")
        self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertEqual(subscription.provider_customer_id, "cus_subscription_view")

    def test_subscription_page_renders_portal_controls_without_calling_stripe(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        self._stripe_subscription(
            status=BusinessSubscription.Status.TRIALING,
            trial_start=now - timedelta(days=1),
            trial_end=now + timedelta(days=13),
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=13),
            provider_customer_id="cus_hidden_template",
            provider_subscription_id="sub_hidden_template",
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                response = self.client.get(reverse("business_subscription"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manage billing")
        self.assertContains(response, "Your 14-day trial is active")
        self.assertContains(response, "Billing management is securely hosted by Stripe")
        self.assertNotContains(response, "cus_hidden_template")
        self.assertNotContains(response, "sub_hidden_template")
        configure_sdk.assert_not_called()

    def test_subscription_page_hides_portal_for_pending_past_due_cancelled_and_beta(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)
        cases = (
            (
                {
                    "plan": self.pro_plan,
                    "status": BusinessSubscription.Status.PENDING_CHECKOUT,
                    "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
                    "billing_interval": BusinessSubscription.BillingInterval.MONTHLY,
                    "billing_currency": BusinessSubscription.BillingCurrency.USD,
                },
                "Complete payment setup",
            ),
            (
                {"plan": self.pro_plan, "status": BusinessSubscription.Status.PAST_DUE},
                "There is a payment issue",
            ),
            (
                {"plan": self.pro_plan, "status": BusinessSubscription.Status.CANCELLED},
                "Your subscription is no longer active",
            ),
            (
                {"plan": beta_plan, "status": BusinessSubscription.Status.ACTIVE},
                "Beta",
            ),
        )

        with override_settings(**self._valid_stripe_settings()):
            for fields, expected_copy in cases:
                with self.subTest(expected_copy=expected_copy):
                    BusinessSubscription.objects.filter(business=self.business).delete()
                    BusinessSubscription.objects.create(business=self.business, **fields)

                    response = self.client.get(reverse("business_subscription"))

                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, expected_copy)
                    self.assertNotContains(response, "Manage billing")
                    self.assertNotContains(response, "Stripe Customer Portal")

    def test_subscription_page_shows_payment_recovery_during_and_after_grace(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        cases = (
            (
                {
                    "past_due_since": now - timedelta(days=1),
                    "grace_period_ends_at": now + timedelta(days=6),
                },
                "Your account will remain available until",
            ),
            (
                {
                    "past_due_since": now - timedelta(days=10),
                    "grace_period_ends_at": now - timedelta(days=3),
                },
                "Your Motionmate workspace is temporarily read-only because the payment grace period has ended.",
            ),
        )

        with override_settings(**self._valid_stripe_settings()):
            for fields, expected_copy in cases:
                with self.subTest(expected_copy=expected_copy):
                    BusinessSubscription.objects.filter(business=self.business).delete()
                    self._stripe_subscription(
                        status=BusinessSubscription.Status.PAST_DUE,
                        provider_customer_id="cus_hidden_recovery",
                        provider_subscription_id="sub_hidden_recovery",
                        **fields,
                    )

                    with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                        response = self.client.get(reverse("business_subscription"))

                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, "Motionmate subscription billing")
                    self.assertContains(response, expected_copy)
                    if "remain available" in expected_copy:
                        self.assertContains(
                            response,
                            "We could not process your latest Motionmate payment",
                        )
                    else:
                        self.assertContains(
                            response,
                            "Update your payment method to restore full access after Stripe confirms a successful payment.",
                        )
                    self.assertContains(response, "Fix payment")
                    self.assertContains(response, reverse("billing_payment_recovery"))
                    self.assertNotContains(response, "Manage billing")
                    self.assertNotContains(response, "change plans")
                    if "remain available" in expected_copy:
                        self.assertNotContains(response, "read-only")
                    else:
                        self.assertContains(response, "read-only")
                    self.assertNotContains(response, "cus_hidden_recovery")
                    self.assertNotContains(response, "sub_hidden_recovery")
                    configure_sdk.assert_not_called()

    def test_customer_portal_return_page_is_non_authoritative(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        subscription = self._stripe_subscription(
            status=BusinessSubscription.Status.TRIALING,
            trial_start=timezone.now() - timedelta(days=1),
            trial_end=timezone.now() + timedelta(days=13),
            current_period_start=timezone.now() - timedelta(days=1),
            current_period_end=timezone.now() + timedelta(days=13),
        )
        original_values = (
            subscription.status,
            subscription.plan_id,
            subscription.trial_end,
            subscription.current_period_end,
            subscription.provider_customer_id,
            subscription.provider_subscription_id,
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                response = self.client.get(
                    reverse("business_subscription"),
                    {
                        "billing_return": "1",
                        "status": "active",
                        "provider_customer_id": "cus_browser_tamper",
                        "plan": self.business_plan.pk,
                    },
                )

        subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your billing update is being confirmed.")
        self.assertContains(
            response,
            "Full access will return after Stripe confirms a successful payment.",
        )
        self.assertEqual(
            (
                subscription.status,
                subscription.plan_id,
                subscription.trial_end,
                subscription.current_period_end,
                subscription.provider_customer_id,
                subscription.provider_subscription_id,
            ),
            original_values,
        )
        configure_sdk.assert_not_called()

    def test_payment_recovery_return_page_is_non_authoritative(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        subscription = self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        original_values = (
            subscription.status,
            subscription.past_due_since,
            subscription.grace_period_ends_at,
            subscription.plan_id,
            subscription.provider_customer_id,
            subscription.provider_subscription_id,
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(stripe_portal, "configure_stripe_sdk") as configure_sdk:
                response = self.client.get(
                    reverse("business_subscription"),
                    {
                        "billing_return": "1",
                        "status": "active",
                        "paid": "true",
                        "past_due_since": "",
                        "provider_customer_id": "cus_browser_tamper",
                    },
                )

        subscription.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your billing update is being confirmed.")
        self.assertContains(
            response,
            "Full access will return after Stripe confirms a successful payment.",
        )
        self.assertEqual(
            (
                subscription.status,
                subscription.past_due_since,
                subscription.grace_period_ends_at,
                subscription.plan_id,
                subscription.provider_customer_id,
                subscription.provider_subscription_id,
            ),
            original_values,
        )
        configure_sdk.assert_not_called()

    def test_direct_paid_module_routes_require_effective_subscription_access(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        states = (
            {
                "status": BusinessSubscription.Status.PENDING_CHECKOUT,
                "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
                "billing_interval": BusinessSubscription.BillingInterval.MONTHLY,
                "billing_currency": BusinessSubscription.BillingCurrency.USD,
            },
            {
                "status": BusinessSubscription.Status.TRIALING,
                "trial_start": now - timedelta(days=15),
                "trial_end": now - timedelta(days=1),
                "current_period_start": now - timedelta(days=15),
                "current_period_end": now - timedelta(days=1),
            },
            {"status": BusinessSubscription.Status.PAST_DUE},
            {"status": BusinessSubscription.Status.EXPIRED},
        )

        for fields in states:
            with self.subTest(status=fields["status"]):
                BusinessSubscription.objects.filter(business=self.business).delete()
                BusinessSubscription.objects.create(
                    business=self.business,
                    plan=self.pro_plan,
                    **fields,
                )

                response = self.client.get(reverse("invoice_list"), follow=True)

                self.assertRedirects(response, reverse("business_subscription"))
                self.assertContains(response, "Invoicing is not available")

    def test_direct_paid_module_routes_remain_available_during_past_due_grace(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=1),
            grace_period_ends_at=now + timedelta(days=6),
        )

        response = self.client.get(reverse("invoice_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invoices")

    def test_owner_dashboard_allows_grace_access_and_warns_without_redirecting(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=1),
            grace_period_ends_at=now + timedelta(days=6),
        )

        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "We could not process your latest Motionmate payment")
        self.assertContains(response, "Fix payment")

    def test_non_owner_dashboard_sees_neutral_grace_notice_without_billing_controls(self):
        self._login_with_role(BusinessUser.Role.STAFF)
        now = timezone.now()
        self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=1),
            grace_period_ends_at=now + timedelta(days=6),
        )

        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Your business subscription requires attention from the account owner.",
        )
        self.assertNotContains(response, "Fix payment")
        self.assertNotContains(response, "Manage billing")
        self.assertNotContains(response, "cus_subscription_view")

    def test_restricted_workspace_allows_read_pages_and_hides_mutation_controls(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        client = Client.objects.create(
            business=self.business,
            first_name="Read",
            last_name="Only",
            email="readonly@example.com",
            phone="+1 721 555 1000",
        )
        Invoice.objects.create(
            business=self.business,
            client=client,
            invoice_number="MM-RO-1",
            status=Invoice.Status.DRAFT,
        )
        Appointment.objects.create(
            business=self.business,
            client=client,
            title="Read-only visit",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
        )
        BusinessService.objects.create(
            business=self.business,
            name="Read-only service",
            unit_price=Decimal("25.00"),
        )

        responses = {
            "dashboard": self.client.get(reverse("agent_dashboard")),
            "clients": self.client.get(reverse("staff_client_list")),
            "invoices": self.client.get(reverse("invoice_list")),
            "appointments": self.client.get(reverse("appointment_list")),
            "services": self.client.get(reverse("business_service_list")),
            "team": self.client.get(reverse("business_team_members")),
        }

        for name, response in responses.items():
            with self.subTest(name=name):
                self.assertEqual(response.status_code, 200)

        self.assertContains(
            responses["dashboard"],
            "Your Motionmate workspace is temporarily read-only because the payment grace period has ended.",
        )
        self.assertContains(responses["clients"], "readonly@example.com")
        self.assertNotContains(responses["clients"], "Create Client")
        self.assertNotContains(responses["invoices"], "Create Invoice")
        self.assertNotContains(responses["appointments"], "Schedule Appointment")
        self.assertContains(responses["services"], "Read-only service")
        self.assertNotContains(responses["services"], "Create service")
        self.assertNotContains(responses["team"], "Send invitation")

    def test_restricted_workspace_denies_direct_mutation_routes_and_json_actions(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        client = Client.objects.create(
            business=self.business,
            first_name="Blocked",
            last_name="Client",
            email="blocked@example.com",
            phone="+1 721 555 1001",
        )
        invoice = Invoice.objects.create(
            business=self.business,
            client=client,
            invoice_number="MM-BLOCKED-1",
            status=Invoice.Status.DRAFT,
        )

        create_response = self.client.get(reverse("staff_client_create"), follow=True)
        invite_response = self.client.post(
            reverse("business_team_members"),
            {"email": "new-staff@example.com", "role": BusinessUser.Role.STAFF},
            follow=True,
        )
        json_response = self.client.post(
            reverse("invoice_change_status", args=[invoice.id]),
            {"status": Invoice.Status.SENT},
            HTTP_ACCEPT="application/json",
        )

        invoice.refresh_from_db()

        self.assertRedirects(create_response, reverse("business_subscription"))
        self.assertContains(create_response, "This workspace is currently read-only")
        self.assertRedirects(invite_response, reverse("business_subscription"))
        self.assertFalse(BusinessInvitation.objects.filter(email="new-staff@example.com").exists())
        self.assertEqual(json_response.status_code, 403)
        self.assertEqual(
            json.loads(json_response.content),
            {
                "error": "subscription_restricted",
                "message": "This workspace is currently read-only. Update the subscription to make changes.",
            },
        )
        self.assertEqual(invoice.status, Invoice.Status.DRAFT)

    def test_restricted_non_owner_sees_neutral_banner_without_recovery_controls(self):
        self._login_with_role(BusinessUser.Role.STAFF)
        now = timezone.now()
        self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )

        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This Motionmate workspace is temporarily read-only.",
        )
        self.assertContains(
            response,
            "The account owner needs to update the subscription to restore full access.",
        )
        self.assertNotContains(response, "Fix payment")
        self.assertNotContains(response, "cus_subscription_view")

    def test_restricted_public_booking_shows_neutral_unavailable_message_without_creating_records(
        self,
    ):
        now = timezone.now()
        self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )

        response = self.client.post(
            reverse("public_booking", args=[self.business.slug]),
            {"email": "customer@example.com"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(
            response,
            "Online booking is temporarily unavailable. Please contact the business directly.",
            status_code=403,
        )
        self.assertNotContains(response, "payment", status_code=403)
        self.assertFalse(Lead.objects.filter(email="customer@example.com").exists())

    def test_restricted_owner_can_open_payment_recovery_but_browser_return_does_not_restore_access(
        self,
    ):
        self._login_with_role(BusinessUser.Role.OWNER)
        now = timezone.now()
        subscription = self._stripe_subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )
        stripe_client, session_api = self._stripe_portal_client()

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_portal,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                recovery_response = self.client.post(reverse("billing_payment_recovery"))

            return_response = self.client.get(
                f"{reverse('business_subscription')}?billing_return=1",
            )

        subscription.refresh_from_db()

        self.assertEqual(recovery_response.status_code, 302)
        self.assertEqual(recovery_response.url, "https://billing.stripe.test/session")
        self.assertEqual(session_api.create.call_args.kwargs["customer"], "cus_subscription_view")
        self.assertEqual(subscription.status, BusinessSubscription.Status.PAST_DUE)
        self.assertEqual(subscription.access_mode, SubscriptionAccessMode.RESTRICTED)
        self.assertContains(return_response, "Your billing update is being confirmed.")
        self.assertContains(
            return_response,
            "Full access will return after Stripe confirms a successful payment.",
        )

    def test_direct_core_crm_routes_require_effective_subscription_access(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.pro_plan,
            status=BusinessSubscription.Status.EXPIRED,
        )

        response = self.client.get(reverse("staff_client_list"), follow=True)

        self.assertRedirects(response, reverse("business_subscription"))
        self.assertContains(response, "Client Management is not available")

    def test_team_invitation_post_requires_effective_subscription_access(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.business_plan,
            status=BusinessSubscription.Status.EXPIRED,
        )

        response = self.client.post(
            reverse("business_team_members"),
            {"email": "blocked-staff@example.com", "role": BusinessUser.Role.STAFF},
            follow=True,
        )

        self.assertRedirects(response, reverse("business_subscription"))
        self.assertContains(response, "Workspace is not available")
        self.assertFalse(
            BusinessInvitation.objects.filter(email="blocked-staff@example.com").exists()
        )

    def test_owner_dashboard_redirects_billing_attention_states_without_looping(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.pro_plan,
            status=BusinessSubscription.Status.EXPIRED,
        )

        response = self.client.get(reverse("agent_dashboard"), follow=True)

        self.assertRedirects(response, reverse("business_subscription"))
        self.assertContains(response, "Review your Motionmate subscription")

    def test_owner_can_change_subscription_plan_and_keep_trialing_status(self):
        self._login_with_role(BusinessUser.Role.OWNER)
        trial_start = timezone.now()
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.starter_plan,
            status=BusinessSubscription.Status.TRIALING,
            trial_start=trial_start,
            trial_end=trial_start + timedelta(days=14),
            current_period_start=trial_start,
            current_period_end=trial_start + timedelta(days=14),
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

    def _enable_team_subscription(self):
        return BusinessSubscription.objects.create(
            business=self.business,
            plan=ClarivoPlan.objects.get(slug="business"),
            status=BusinessSubscription.Status.ACTIVE,
        )

    def _enable_restricted_subscription(self):
        now = timezone.now()
        return BusinessSubscription.objects.create(
            business=self.business,
            plan=ClarivoPlan.objects.get(slug="business"),
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_invite_restricted",
            provider_subscription_id="sub_invite_restricted",
            provider_price_id="price_business_monthly_usd",
            past_due_since=now - timedelta(days=10),
            grace_period_ends_at=now - timedelta(days=3),
        )

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

    def test_restricted_workspace_invitation_acceptance_is_read_only(self):
        self._enable_restricted_subscription()
        invitation = BusinessInvitation.objects.create(
            business=self.business,
            email="restricted-invitee@example.com",
            role=BusinessUser.Role.STAFF,
            token="restricted-invite-token",
            invited_by=self.owner,
        )

        get_response = self.client.get(reverse("accept_business_invitation", args=[invitation.token]))
        post_response = self.client.post(
            reverse("accept_business_invitation", args=[invitation.token]),
            {
                "first_name": "Restricted",
                "last_name": "Invitee",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            follow=True,
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "This workspace is temporarily read-only.")
        self.assertNotContains(get_response, "Create account and join workspace")
        self.assertRedirects(
            post_response,
            reverse("accept_business_invitation", args=[invitation.token]),
        )
        self.assertFalse(TaskIOUser.objects.filter(email=invitation.email).exists())
        self.assertFalse(BusinessUser.objects.filter(business=self.business, user__email=invitation.email).exists())

    def test_owner_can_deactivate_team_member(self):
        self._enable_team_subscription()
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
        self._enable_team_subscription()
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
        self._enable_team_subscription()
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
        self._enable_team_subscription()
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
        self._enable_team_subscription()
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
        self._enable_team_subscription()
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
        self._enable_team_subscription()
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
        self._enable_team_subscription()
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
