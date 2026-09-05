import json
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib import admin
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.checks import run_checks
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import Client as DjangoClient
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from apps.accounts.beta_registration import BETA_PLAN_DISPLAY_NAME, BETA_PLAN_SLUG
from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice, InvoiceLine
from apps.crm.models import ActivityLog, BusinessService, Client, Lead, ServiceCategory
from config import Settings
from helpers import build_public_url

from . import stripe_checkout, stripe_config, stripe_portal, stripe_webhooks
from .business_data_inventory import (
    DIRECT_BUSINESS_RELATION_REGISTRY,
    FuturePurgeReadiness,
    InventoryClassification,
    build_business_data_inventory,
    find_unregistered_direct_business_relations,
)
from .business_data_operations import (
    BusinessDeactivationError,
    deactivate_business,
)
from .business_data_purge import BusinessPurgeError, purge_business
from .business_resolution import (
    BusinessMatchKind,
    BusinessResolutionError,
    resolve_business_candidates,
)
from .checks import check_stripe_configuration
from .localization import format_money_for_business, parse_localized_decimal
from .models import (
    BillingProviderWebhookEvent,
    Business,
    BusinessBookingSettings,
    BusinessDataOperation,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    SubscriptionAccessMode,
    SubscriptionNotification,
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
    PUBLIC_PRICING_CURRENCY_SESSION_KEY,
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
from .subscription_notifications import (
    build_subscription_notification_email_context,
    deliver_subscription_notification,
    enqueue_subscription_notification,
    get_subscription_notification_recipients,
)
from .subscription_reminders import enqueue_due_subscription_reminders
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
                return_value=(
                    create_result
                    if create_result is not None
                    else {
                        "id": "bps_test_portal",
                        "url": "https://billing.stripe.test/session",
                    }
                ),
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


class SubscriptionNotificationOutboxTests(TestCase):
    def setUp(self):
        self.owner = TaskIOUser.objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
        )
        self.staff = TaskIOUser.objects.create_user(
            email="staff@example.com",
            password="StrongPass123!",
        )
        self.inactive_owner = TaskIOUser.objects.create_user(
            email="inactive-owner@example.com",
            password="StrongPass123!",
        )
        self.inactive_owner.is_active = False
        self.inactive_owner.save(update_fields=["is_active"])
        self.business = Business.objects.create(
            name="Notification Workspace",
            slug="notification-workspace",
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
        BusinessUser.objects.create(
            user=self.inactive_owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        other_business = Business.objects.create(
            name="Other Notification Workspace",
            slug="other-notification-workspace",
        )
        BusinessUser.objects.create(
            user=TaskIOUser.objects.create_user(
                email="other-owner@example.com",
                password="StrongPass123!",
            ),
            business=other_business,
            role=BusinessUser.Role.OWNER,
        )
        self.plan = ClarivoPlan.objects.get(slug="pro")
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.ACTIVE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_notification",
            provider_subscription_id="sub_notification",
            provider_price_id="price_pro_monthly_usd",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

    def test_recipient_selection_uses_active_business_owners_only(self):
        recipients = get_subscription_notification_recipients(self.business)

        self.assertEqual([recipient["email"] for recipient in recipients], ["owner@example.com"])
        self.assertEqual(recipients[0]["user"], self.owner)

    def test_enqueue_creates_deduplicated_pending_notification_without_email(self):
        context = {"trial_start": datetime(2026, 7, 1, tzinfo=UTC)}

        first = enqueue_subscription_notification(
            subscription=self.subscription,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_context=context,
            source_provider_event_id="evt_trial",
            context_summary={
                "trial_end": datetime(2026, 7, 15, tzinfo=UTC),
                "provider_subscription_id": self.subscription.provider_subscription_id,
            },
        )
        second = enqueue_subscription_notification(
            subscription=self.subscription,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_context=context,
            source_provider_event_id="evt_trial_duplicate",
            context_summary={"trial_end": datetime(2026, 7, 15, tzinfo=UTC)},
        )

        notification = SubscriptionNotification.objects.get()
        self.assertEqual(first, [notification])
        self.assertEqual(second, [notification])
        self.assertEqual(notification.status, SubscriptionNotification.Status.PENDING)
        self.assertEqual(notification.recipient_email, "owner@example.com")
        self.assertTrue(notification.deduplication_key.startswith("subscription:"))
        self.assertEqual(notification.source_provider_event_id, "evt_trial")
        self.assertEqual(mail.outbox, [])
        self.assertNotIn(
            self.subscription.provider_subscription_id,
            json.dumps(notification.context_summary),
        )

    def test_existing_sent_notification_is_not_reset_by_duplicate_enqueue(self):
        notification = enqueue_subscription_notification(
            subscription=self.subscription,
            notification_type=SubscriptionNotification.NotificationType.SUBSCRIPTION_ACTIVATED,
            deduplication_context={"period_start": datetime(2026, 7, 15, tzinfo=UTC)},
            source_provider_event_id="evt_activation",
        )[0]
        notification.status = SubscriptionNotification.Status.SENT
        notification.attempt_count = 3
        notification.sent_at = timezone.now()
        notification.save(update_fields=["status", "attempt_count", "sent_at", "updated_at"])

        duplicate = enqueue_subscription_notification(
            subscription=self.subscription,
            notification_type=SubscriptionNotification.NotificationType.SUBSCRIPTION_ACTIVATED,
            deduplication_context={"period_start": datetime(2026, 7, 15, tzinfo=UTC)},
            source_provider_event_id="evt_activation_duplicate",
        )[0]

        duplicate.refresh_from_db()
        self.assertEqual(duplicate.pk, notification.pk)
        self.assertEqual(duplicate.status, SubscriptionNotification.Status.SENT)
        self.assertEqual(duplicate.attempt_count, 3)
        self.assertEqual(SubscriptionNotification.objects.count(), 1)

    def test_missing_owner_email_creates_visible_failed_notification_without_fallback(self):
        BusinessUser.objects.filter(business=self.business, role=BusinessUser.Role.OWNER).update(
            is_active=False,
        )

        notifications = enqueue_subscription_notification(
            subscription=self.subscription,
            notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_STARTED,
            deduplication_context={"past_due_since": datetime(2026, 7, 5, tzinfo=UTC)},
            source_provider_event_id="evt_missing_owner",
        )

        notification = notifications[0]
        self.assertEqual(notification.status, SubscriptionNotification.Status.FAILED)
        self.assertEqual(notification.recipient_email, "")
        self.assertIn("No active owner", notification.last_error)
        self.assertNotIn("cus_notification", notification.last_error)

    def test_beta_and_unknown_notification_types_are_rejected_without_rows(self):
        beta_subscription = BusinessSubscription.objects.create(
            business=Business.objects.create(name="Beta Notify", slug="beta-notify"),
            plan=ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG),
            status=BusinessSubscription.Status.ACTIVE,
            payment_provider=BusinessSubscription.PaymentProvider.LOCAL,
        )

        self.assertEqual(
            enqueue_subscription_notification(
                subscription=beta_subscription,
                notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
                deduplication_context={"trial_start": datetime(2026, 7, 1, tzinfo=UTC)},
            ),
            [],
        )
        with self.assertRaises(ValueError):
            enqueue_subscription_notification(
                subscription=self.subscription,
                notification_type="trial_ending_soon",
                deduplication_context={"trial_end": datetime(2026, 7, 15, tzinfo=UTC)},
            )
        self.assertFalse(SubscriptionNotification.objects.exists())


class SubscriptionNotificationDeliveryTests(TestCase):
    def setUp(self):
        self.owner = TaskIOUser.objects.create_user(
            email="delivery-owner@example.com",
            password="StrongPass123!",
        )
        self.business = Business.objects.create(
            name="Delivery <Workspace>",
            slug="delivery-workspace",
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
            status=BusinessSubscription.Status.TRIALING,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_delivery",
            provider_subscription_id="sub_delivery",
            provider_price_id="price_pro_monthly_usd",
            trial_start=datetime(2026, 7, 1, tzinfo=UTC),
            trial_end=datetime(2026, 7, 15, tzinfo=UTC),
        )
        self.notification = enqueue_subscription_notification(
            subscription=self.subscription,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_context={"trial_start": self.subscription.trial_start},
            source_provider_event_id="evt_delivery_trial",
            context_summary={"trial_end": self.subscription.trial_end},
        )[0]

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net",
        MOTIONMATE_SUPPORT_EMAIL="support@motionmate.net",
    )
    def test_pending_notification_delivers_plain_text_and_html_then_marks_sent(self):
        result = deliver_subscription_notification(self.notification)

        self.notification.refresh_from_db()
        self.assertEqual(result.status, "sent")
        self.assertEqual(self.notification.status, SubscriptionNotification.Status.SENT)
        self.assertEqual(self.notification.attempt_count, 1)
        self.assertIsNotNone(self.notification.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["delivery-owner@example.com"])
        self.assertIn("Your Motionmate Pro trial has started", message.subject)
        self.assertIn("July 15, 2026", message.body)
        self.assertIn("https://www.motionmate.net/businesses/subscription/", message.body)
        self.assertNotIn("sub_delivery", message.body)
        self.assertEqual(len(message.alternatives), 1)
        self.assertIn("Delivery &lt;Workspace&gt;", message.alternatives[0][0])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net",
    )
    def test_sent_notification_is_skipped_and_not_delivered_twice(self):
        first = deliver_subscription_notification(self.notification)
        second = deliver_subscription_notification(self.notification)

        self.notification.refresh_from_db()
        self.assertEqual(first.status, "sent")
        self.assertEqual(second.status, "skipped")
        self.assertEqual(self.notification.attempt_count, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_missing_recipient_fails_safely_and_remains_retryable(self):
        notification = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.subscription,
            notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_STARTED,
            recipient_email="",
            deduplication_key="subscription:missing-recipient",
            context_summary={"grace_period_ends_at": datetime(2026, 7, 12, tzinfo=UTC).isoformat()},
        )

        result = deliver_subscription_notification(notification)
        notification.refresh_from_db()

        self.assertEqual(result.status, "failed")
        self.assertEqual(notification.status, SubscriptionNotification.Status.FAILED)
        self.assertEqual(notification.attempt_count, 1)
        self.assertIn("Recipient email", notification.last_error)
        self.assertEqual(mail.outbox, [])

    def test_email_backend_failure_marks_failed_without_changing_subscription_state(self):
        original_status = self.subscription.status
        original_trial_end = self.subscription.trial_end

        with mock.patch(
            "apps.businesses.subscription_notifications.send_templated_email",
            side_effect=RuntimeError("smtp password leaked? no"),
        ):
            result = deliver_subscription_notification(self.notification)

        self.notification.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.notification.status, SubscriptionNotification.Status.FAILED)
        self.assertEqual(self.notification.attempt_count, 1)
        self.assertEqual(self.notification.last_error, "RuntimeError: email delivery failed")
        self.assertEqual(self.subscription.status, original_status)
        self.assertEqual(self.subscription.trial_end, original_trial_end)

    @override_settings(MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net")
    def test_email_context_uses_trusted_motionmate_link_only(self):
        context = build_subscription_notification_email_context(self.notification)

        self.assertEqual(
            context["action_url"],
            "https://www.motionmate.net/businesses/subscription/",
        )
        self.assertNotIn("stripe", context["action_url"].lower())
        body = render_to_string("emails/subscription_notification_body.txt", context)
        self.assertNotIn("sub_delivery", body)


class SendSubscriptionNotificationsCommandTests(TestCase):
    def setUp(self):
        owner = TaskIOUser.objects.create_user(
            email="command-owner@example.com",
            password="StrongPass123!",
        )
        self.business = Business.objects.create(
            name="Command Workspace",
            slug="command-workspace",
        )
        BusinessUser.objects.create(
            user=owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=ClarivoPlan.objects.get(slug="pro"),
            status=BusinessSubscription.Status.ACTIVE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_command",
            provider_subscription_id="sub_command",
            provider_price_id="price_pro_monthly_usd",
            current_period_start=datetime(2026, 7, 15, tzinfo=UTC),
            current_period_end=datetime(2026, 8, 15, tzinfo=UTC),
        )

    def _notification(self, key: str, **overrides):
        defaults = {
            "business": self.business,
            "subscription": self.subscription,
            "notification_type": SubscriptionNotification.NotificationType.SUBSCRIPTION_ACTIVATED,
            "recipient_email": "command-owner@example.com",
            "deduplication_key": key,
            "context_summary": {
                "current_period_end": datetime(2026, 8, 15, tzinfo=UTC).isoformat(),
            },
        }
        defaults.update(overrides)
        return SubscriptionNotification.objects.create(**defaults)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net",
    )
    def test_command_sends_pending_notifications_with_limit_and_reports_remaining(self):
        first = self._notification("subscription:command:first")
        second = self._notification("subscription:command:second")
        output = StringIO()

        call_command("send_subscription_notifications", limit=1, stdout=output)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, SubscriptionNotification.Status.SENT)
        self.assertEqual(second.status, SubscriptionNotification.Status.PENDING)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Eligible: 2", output.getvalue())
        self.assertIn("Sent: 1", output.getvalue())
        self.assertIn("Remaining eligible: 1", output.getvalue())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_dry_run_sends_nothing_and_changes_nothing(self):
        notification = self._notification("subscription:command:dry-run")
        output = StringIO()

        call_command("send_subscription_notifications", dry_run=True, stdout=output)

        notification.refresh_from_db()
        self.assertEqual(notification.status, SubscriptionNotification.Status.PENDING)
        self.assertEqual(notification.attempt_count, 0)
        self.assertEqual(mail.outbox, [])
        self.assertIn("Dry run only", output.getvalue())
        self.assertIn("Skipped: 1", output.getvalue())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net",
    )
    def test_retry_failed_includes_failed_notifications_without_creating_duplicates(self):
        notification = self._notification(
            "subscription:command:retry",
            status=SubscriptionNotification.Status.FAILED,
            attempt_count=1,
            last_error="temporary delivery failure",
        )
        output = StringIO()

        call_command("send_subscription_notifications", retry_failed=True, stdout=output)

        notification.refresh_from_db()
        self.assertEqual(notification.status, SubscriptionNotification.Status.SENT)
        self.assertEqual(notification.attempt_count, 2)
        self.assertEqual(SubscriptionNotification.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_one_failed_delivery_does_not_stop_batch(self):
        first = self._notification("subscription:command:fail-first")
        second = self._notification("subscription:command:send-second")
        output = StringIO()
        errors = StringIO()

        with mock.patch(
            "apps.businesses.subscription_notifications.send_templated_email",
            side_effect=[RuntimeError("smtp outage"), True],
        ):
            call_command(
                "send_subscription_notifications",
                stdout=output,
                stderr=errors,
            )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, SubscriptionNotification.Status.FAILED)
        self.assertEqual(second.status, SubscriptionNotification.Status.SENT)
        self.assertIn("Failed: 1", output.getvalue())
        self.assertIn("Sent: 1", output.getvalue())


class SubscriptionReminderDiscoveryTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 1, 12, tzinfo=UTC)
        self.plan = ClarivoPlan.objects.get(slug="pro")
        self.sequence = 0

    def _subscription(
        self,
        *,
        status=BusinessSubscription.Status.TRIALING,
        trial_end=None,
        past_due_since=None,
        grace_period_ends_at=None,
        payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
        plan=None,
        cancel_at_period_end=False,
        current_period_end=None,
        owner=True,
        business_name=None,
    ):
        self.sequence += 1
        suffix = self.sequence
        business = Business.objects.create(
            name=business_name or f"Reminder Workspace {suffix}",
            slug=f"reminder-workspace-{suffix}",
            timezone="Europe/Amsterdam",
        )
        if owner:
            owner_user = TaskIOUser.objects.create_user(
                email=f"reminder-owner-{suffix}@example.com",
                password="StrongPass123!",
            )
            BusinessUser.objects.create(
                user=owner_user,
                business=business,
                role=BusinessUser.Role.OWNER,
            )
        plan = plan or self.plan
        return BusinessSubscription.objects.create(
            business=business,
            plan=plan,
            status=status,
            payment_provider=payment_provider,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id=(
                "cus_reminder"
                if payment_provider == BusinessSubscription.PaymentProvider.STRIPE
                else ""
            ),
            provider_subscription_id=(
                f"sub_reminder_{suffix}"
                if payment_provider == BusinessSubscription.PaymentProvider.STRIPE
                else ""
            ),
            provider_price_id=(
                "price_pro_monthly_usd"
                if payment_provider == BusinessSubscription.PaymentProvider.STRIPE
                else ""
            ),
            trial_start=self.now - timedelta(days=11),
            trial_end=trial_end,
            current_period_end=current_period_end or trial_end,
            cancel_at_period_end=cancel_at_period_end,
            past_due_since=past_due_since,
            grace_period_ends_at=grace_period_ends_at,
        )

    def _run(self, **kwargs):
        return enqueue_due_subscription_reminders(evaluation_time=self.now, **kwargs)

    def test_new_reminder_types_are_valid_and_beta_is_excluded(self):
        valid_types = {choice.value for choice in SubscriptionNotification.NotificationType}

        self.assertIn("trial_ending_3_days", valid_types)
        self.assertIn("trial_ending_1_day", valid_types)
        self.assertIn("payment_grace_ending_1_day", valid_types)
        self.assertIn("restricted_mode_started", valid_types)

        beta_subscription = self._subscription(
            plan=ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG),
            payment_provider=BusinessSubscription.PaymentProvider.LOCAL,
            trial_end=self.now + timedelta(days=3),
        )
        result = enqueue_subscription_notification(
            subscription=beta_subscription,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS,
            deduplication_context={"trial_end": beta_subscription.trial_end},
        )

        self.assertEqual(result, [])
        self.assertFalse(SubscriptionNotification.objects.exists())
        with self.assertRaises(ValueError):
            self._run(notification_type="subscription_warning")

    def test_trial_three_day_window_uses_exact_boundaries(self):
        self._subscription(trial_end=self.now + timedelta(hours=72))
        summary = self._run(
            notification_type=SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS
        )
        self.assertEqual(
            summary.created_counts[SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS],
            1,
        )

        SubscriptionNotification.objects.all().delete()
        BusinessSubscription.objects.all().delete()
        self._subscription(trial_end=self.now + timedelta(hours=72, seconds=1))
        self._subscription(trial_end=self.now + timedelta(hours=24, seconds=1))
        self._subscription(trial_end=self.now + timedelta(hours=24))
        summary = self._run(
            notification_type=SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS
        )
        self.assertEqual(
            summary.created_counts[SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS],
            1,
        )
        notification = SubscriptionNotification.objects.get()
        self.assertEqual(
            notification.context_summary["trial_end"],
            (self.now + timedelta(hours=24, seconds=1)).isoformat(),
        )

    def test_trial_one_day_window_does_not_backfill_three_day_reminder(self):
        self._subscription(trial_end=self.now + timedelta(hours=24))
        self._subscription(trial_end=self.now + timedelta(seconds=1))
        self._subscription(trial_end=self.now)
        self._subscription(trial_end=self.now - timedelta(seconds=1))

        summary = self._run()

        self.assertEqual(
            summary.created_counts[SubscriptionNotification.NotificationType.TRIAL_ENDING_1_DAY],
            2,
        )
        self.assertEqual(
            summary.created_counts[SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS],
            0,
        )
        self.assertEqual(SubscriptionNotification.objects.count(), 2)

    def test_trial_reminders_skip_non_trial_pending_and_scheduled_cancellation(self):
        self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            trial_end=self.now + timedelta(days=3),
        )
        self._subscription(
            status=BusinessSubscription.Status.PENDING_CHECKOUT,
            trial_end=self.now + timedelta(days=3),
        )
        self._subscription(
            trial_end=self.now + timedelta(days=3),
            cancel_at_period_end=True,
            current_period_end=self.now + timedelta(days=3),
        )

        summary = self._run()

        self.assertEqual(summary.created_total, 0)
        self.assertFalse(SubscriptionNotification.objects.exists())

    def test_repeated_trial_runs_are_idempotent_per_recipient(self):
        self._subscription(trial_end=self.now + timedelta(days=3))

        first = self._run()
        second = self._run()

        self.assertEqual(first.created_total, 1)
        self.assertEqual(second.created_total, 0)
        self.assertEqual(second.duplicate_count, 1)
        self.assertEqual(SubscriptionNotification.objects.count(), 1)

    def test_grace_one_day_and_restricted_windows_use_exact_boundaries(self):
        past_due_since = self.now - timedelta(days=6)
        self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=past_due_since,
            grace_period_ends_at=self.now + timedelta(hours=24),
        )
        self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=past_due_since,
            grace_period_ends_at=self.now + timedelta(seconds=1),
        )
        self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=past_due_since,
            grace_period_ends_at=self.now,
        )

        summary = self._run()

        self.assertEqual(
            summary.created_counts[
                SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY
            ],
            2,
        )
        self.assertEqual(
            summary.created_counts[
                SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED
            ],
            1,
        )

    def test_grace_reminders_skip_recovered_cancelled_missing_and_non_stripe_states(self):
        self._subscription(
            status=BusinessSubscription.Status.ACTIVE,
            past_due_since=self.now - timedelta(days=1),
            grace_period_ends_at=self.now + timedelta(hours=12),
        )
        self._subscription(
            status=BusinessSubscription.Status.CANCELLED,
            past_due_since=self.now - timedelta(days=1),
            grace_period_ends_at=self.now + timedelta(hours=12),
        )
        self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=None,
            grace_period_ends_at=self.now + timedelta(hours=12),
        )
        self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            payment_provider=BusinessSubscription.PaymentProvider.LOCAL,
            past_due_since=self.now - timedelta(days=1),
            grace_period_ends_at=self.now + timedelta(hours=12),
        )

        summary = self._run()

        self.assertEqual(summary.created_total, 0)
        self.assertFalse(SubscriptionNotification.objects.exists())

    def test_restricted_mode_catches_up_and_second_episode_creates_new_row(self):
        subscription = self._subscription(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since=self.now - timedelta(days=8),
            grace_period_ends_at=self.now - timedelta(days=1),
        )

        first = self._run()
        duplicate = self._run()
        subscription.past_due_since = self.now + timedelta(days=1)
        subscription.grace_period_ends_at = self.now + timedelta(days=8)
        subscription.save(update_fields=["past_due_since", "grace_period_ends_at", "updated_at"])
        later = self.now + timedelta(days=9)
        second_episode = enqueue_due_subscription_reminders(evaluation_time=later)

        self.assertEqual(
            first.created_counts[SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED],
            1,
        )
        self.assertEqual(duplicate.duplicate_count, 1)
        self.assertEqual(
            second_episode.created_counts[
                SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED
            ],
            1,
        )
        self.assertEqual(SubscriptionNotification.objects.count(), 2)

    def test_dry_run_limit_and_command_at_do_not_send_email(self):
        first = self._subscription(trial_end=self.now + timedelta(days=3))
        self._subscription(trial_end=self.now + timedelta(days=3))
        output = StringIO()

        call_command(
            "enqueue_subscription_reminders",
            at=self.now.isoformat(),
            limit=1,
            stdout=output,
        )

        self.assertEqual(SubscriptionNotification.objects.count(), 1)
        notification = SubscriptionNotification.objects.get()
        self.assertEqual(notification.subscription, first)
        self.assertEqual(mail.outbox, [])
        self.assertIn("Eligible subscriptions evaluated: 1", output.getvalue())

        dry_output = StringIO()
        SubscriptionNotification.objects.all().delete()
        call_command(
            "enqueue_subscription_reminders",
            at=self.now.isoformat(),
            dry_run=True,
            stdout=dry_output,
        )
        self.assertEqual(SubscriptionNotification.objects.count(), 0)
        self.assertEqual(mail.outbox, [])
        self.assertIn("Dry run only", dry_output.getvalue())

    def test_command_rejects_naive_and_malformed_at_values(self):
        with self.assertRaises(CommandError):
            call_command("enqueue_subscription_reminders", at="2026-08-01T12:00:00")
        with self.assertRaises(CommandError):
            call_command("enqueue_subscription_reminders", at="not-a-datetime")


class SubscriptionReminderDeliveryRelevanceTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 1, 12, tzinfo=UTC)
        owner = TaskIOUser.objects.create_user(
            email="reminder-delivery-owner@example.com",
            password="StrongPass123!",
        )
        self.business = Business.objects.create(
            name="Reminder Delivery <Workspace>",
            slug="reminder-delivery-workspace",
            timezone="Europe/Amsterdam",
        )
        BusinessUser.objects.create(
            user=owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=ClarivoPlan.objects.get(slug="pro"),
            status=BusinessSubscription.Status.TRIALING,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_reminder_delivery",
            provider_subscription_id="sub_reminder_delivery",
            provider_price_id="price_pro_monthly_usd",
            trial_start=self.now - timedelta(days=11),
            trial_end=self.now + timedelta(days=3),
            current_period_end=self.now + timedelta(days=3),
        )

    def _enqueue_trial_reminder(self):
        enqueue_due_subscription_reminders(evaluation_time=self.now)
        return SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS
        )

    def _set_past_due(self, *, grace_period_ends_at):
        self.subscription.status = BusinessSubscription.Status.PAST_DUE
        self.subscription.past_due_since = self.now - timedelta(days=6)
        self.subscription.grace_period_ends_at = grace_period_ends_at
        self.subscription.trial_end = None
        self.subscription.current_period_end = grace_period_ends_at
        self.subscription.save(
            update_fields=[
                "status",
                "past_due_since",
                "grace_period_ends_at",
                "trial_end",
                "current_period_end",
                "updated_at",
            ]
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net",
    )
    def test_relevant_trial_reminder_sends_normally(self):
        notification = self._enqueue_trial_reminder()

        with mock.patch(
            "apps.businesses.subscription_notifications.timezone.now",
            return_value=self.now,
        ):
            result = deliver_subscription_notification(notification)

        notification.refresh_from_db()
        self.assertEqual(result.status, "sent")
        self.assertEqual(notification.status, SubscriptionNotification.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)

    def test_obsolete_trial_reminder_is_cancelled_after_activation_or_cancellation(self):
        notification = self._enqueue_trial_reminder()
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.subscription.current_period_end = self.now + timedelta(days=30)
        self.subscription.save(update_fields=["status", "current_period_end", "updated_at"])

        with mock.patch(
            "apps.businesses.subscription_notifications.timezone.now",
            return_value=self.now,
        ):
            result = deliver_subscription_notification(notification)
        notification.refresh_from_db()

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(notification.status, SubscriptionNotification.Status.CANCELLED)
        self.assertEqual(mail.outbox, [])

    def test_grace_reminder_is_cancelled_after_recovery_or_grace_expiry(self):
        self._set_past_due(grace_period_ends_at=self.now + timedelta(hours=12))
        enqueue_due_subscription_reminders(evaluation_time=self.now)
        notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY
        )
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.subscription.past_due_since = None
        self.subscription.grace_period_ends_at = None
        self.subscription.current_period_end = self.now + timedelta(days=30)
        self.subscription.save(
            update_fields=[
                "status",
                "past_due_since",
                "grace_period_ends_at",
                "current_period_end",
                "updated_at",
            ]
        )

        with mock.patch(
            "apps.businesses.subscription_notifications.timezone.now",
            return_value=self.now,
        ):
            result = deliver_subscription_notification(notification)
        notification.refresh_from_db()

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(notification.status, SubscriptionNotification.Status.CANCELLED)
        self.assertEqual(mail.outbox, [])

    def test_restricted_notification_is_cancelled_after_recovery(self):
        self._set_past_due(grace_period_ends_at=self.now - timedelta(hours=1))
        enqueue_due_subscription_reminders(evaluation_time=self.now)
        notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED
        )
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.subscription.past_due_since = None
        self.subscription.grace_period_ends_at = None
        self.subscription.current_period_end = self.now + timedelta(days=30)
        self.subscription.save(
            update_fields=[
                "status",
                "past_due_since",
                "grace_period_ends_at",
                "current_period_end",
                "updated_at",
            ]
        )

        with mock.patch(
            "apps.businesses.subscription_notifications.timezone.now",
            return_value=self.now,
        ):
            result = deliver_subscription_notification(notification)
        notification.refresh_from_db()

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(notification.status, SubscriptionNotification.Status.CANCELLED)
        self.assertEqual(mail.outbox, [])

    @override_settings(MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net")
    def test_reminder_templates_use_exact_timezone_dates_and_safe_content(self):
        notification = self._enqueue_trial_reminder()

        context = build_subscription_notification_email_context(notification)
        body = render_to_string("emails/subscription_notification_body.txt", context)
        html_body = render_to_string("emails/subscription_notification_body.html", context)

        self.assertIn("Your Motionmate trial ends in 3 days", context["email_subject"])
        self.assertIn("Pro", body)
        self.assertIn("August 4, 2026 at 2:00 PM CEST", body)
        self.assertIn("$", body)
        self.assertIn("monthly", body)
        self.assertIn("https://www.motionmate.net/businesses/subscription/", body)
        self.assertNotIn("sub_reminder_delivery", body)
        self.assertIn("Reminder Delivery &lt;Workspace&gt;", html_body)

        self._set_past_due(grace_period_ends_at=self.now + timedelta(hours=12))
        enqueue_due_subscription_reminders(evaluation_time=self.now)
        grace_notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY
        )
        grace_body = render_to_string(
            "emails/subscription_notification_body.txt",
            build_subscription_notification_email_context(grace_notification),
        )
        self.assertIn("workspace becomes read-only", grace_body)
        self.assertIn("Stripe confirms successful payment", grace_body)

        SubscriptionNotification.objects.all().delete()
        self._set_past_due(grace_period_ends_at=self.now - timedelta(hours=1))
        enqueue_due_subscription_reminders(evaluation_time=self.now)
        restricted_notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED
        )
        restricted_body = render_to_string(
            "emails/subscription_notification_body.txt",
            build_subscription_notification_email_context(restricted_notification),
        )
        self.assertIn(
            "Existing plan-permitted business data remains available for viewing", restricted_body
        )
        self.assertNotIn("deleted", restricted_body.lower())


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
        self.assertFalse(SubscriptionNotification.objects.exists())

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
        self.assertFalse(SubscriptionNotification.objects.exists())

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
        notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED
        )
        self.assertEqual(notification.recipient_email, "webhook-owner@example.com")
        self.assertEqual(notification.source_provider_event_id, "evt_checkout_trialing")
        self.assertEqual(mail.outbox, [])

    def test_trialing_to_active_enqueues_activation_notification_once(self):
        self.subscription.status = BusinessSubscription.Status.TRIALING
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.trial_start = self._datetime(self._timestamp(2026, 7, 1))
        self.subscription.trial_end = self._datetime(self._timestamp(2026, 7, 15))
        self.subscription.save(
            update_fields=[
                "status",
                "provider_customer_id",
                "provider_subscription_id",
                "trial_start",
                "trial_end",
                "updated_at",
            ]
        )
        payload = self._event(
            event_id="evt_subscription_activated_once",
            event_type="customer.subscription.updated",
            event_object=self._remote_subscription(status="active"),
            created=self._timestamp(2026, 7, 15),
        )

        with override_settings(**self._valid_stripe_settings()):
            first_response = self._signed_post(payload)
            duplicate_response = self._signed_post(payload)

        self.subscription.refresh_from_db()
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.SUBSCRIPTION_ACTIVATED
            ).count(),
            1,
        )
        self.assertEqual(mail.outbox, [])

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
        notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_STARTED
        )
        self.assertEqual(notification.source_provider_event_id, "evt_invoice_failed_past_due")
        self.assertEqual(notification.recipient_email, "webhook-owner@example.com")
        self.assertEqual(mail.outbox, [])

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
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_STARTED
            ).count(),
            1,
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
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_STARTED
            ).count(),
            1,
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
        notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_STARTED
        )
        self.assertEqual(
            notification.context_summary["grace_period_ends_at"],
            (self._datetime(event_created) + timedelta(days=7)).isoformat(),
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
            event_object=self._remote_subscription(
                status="active",
                current_period_end=int((timezone.now() + timedelta(days=30)).timestamp()),
            ),
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
        notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.PAYMENT_RECOVERED
        )
        self.assertEqual(
            notification.source_provider_event_id,
            "evt_subscription_active_clears_grace",
        )
        self.assertEqual(
            notification.context_summary["past_due_since"],
            self._datetime(self._timestamp(2026, 7, 5)).isoformat(),
        )

    def test_scheduled_cancellation_enqueues_once_for_current_period(self):
        self.subscription.provider_customer_id = "cus_test_motionmate"
        self.subscription.provider_subscription_id = "sub_test_motionmate"
        self.subscription.status = BusinessSubscription.Status.ACTIVE
        self.subscription.current_period_start = self._datetime(self._timestamp(2026, 7, 1))
        self.subscription.current_period_end = self._datetime(self._timestamp(2026, 8, 1))
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "status",
                "current_period_start",
                "current_period_end",
                "updated_at",
            ]
        )
        first_payload = self._event(
            event_id="evt_cancel_scheduled_first",
            event_type="customer.subscription.updated",
            event_object=self._remote_subscription(status="active", cancel_at_period_end=True),
            created=self._timestamp(2026, 7, 10),
        )
        second_payload = self._event(
            event_id="evt_cancel_scheduled_second",
            event_type="customer.subscription.updated",
            event_object=self._remote_subscription(status="active", cancel_at_period_end=True),
            created=self._timestamp(2026, 7, 11),
        )

        with override_settings(**self._valid_stripe_settings()):
            first_response = self._signed_post(first_payload)
            second_response = self._signed_post(second_payload)

        self.subscription.refresh_from_db()
        notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.CANCELLATION_SCHEDULED
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(self.subscription.cancel_at_period_end)
        self.assertEqual(notification.source_provider_event_id, "evt_cancel_scheduled_first")
        self.assertEqual(
            notification.context_summary["cancel_effective_at"],
            self._datetime(self._timestamp(2026, 8, 1)).isoformat(),
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
        self.assertFalse(SubscriptionNotification.objects.exists())

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
        notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.SUBSCRIPTION_CANCELLED
        )
        self.assertEqual(
            notification.context_summary["cancelled_at"],
            self._datetime(event_created).isoformat(),
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
        self.assertFalse(SubscriptionNotification.objects.exists())

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
        self.assertFalse(SubscriptionNotification.objects.exists())


class SubscriptionBillingLifecycleEndToEndTests(TestCase):
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
            "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
        }
        settings_overrides.update(overrides)
        return settings_overrides

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

    def _signed_post(self, payload: dict, *, secret: str = "whsec_motionmate"):
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
        created: int,
    ) -> dict:
        return {
            "id": event_id,
            "object": "event",
            "api_version": "2025-06-30.basil",
            "created": created,
            "livemode": False,
            "type": event_type,
            "data": {"object": event_object},
        }

    def _metadata(
        self,
        subscription: BusinessSubscription,
        *,
        user: TaskIOUser | None = None,
    ) -> dict[str, str]:
        return {
            "motionmate_business_id": str(subscription.business_id),
            "motionmate_subscription_id": str(subscription.pk),
            "motionmate_user_id": str(user.pk if user is not None else ""),
            "plan_slug": subscription.plan.slug,
            "billing_interval": subscription.billing_interval,
            "billing_currency": subscription.billing_currency,
        }

    def _checkout_session(
        self,
        subscription: BusinessSubscription,
        *,
        user: TaskIOUser | None = None,
        session_id: str = "cs_test_lifecycle",
        provider_subscription_id: str = "sub_lifecycle",
        provider_customer_id: str = "cus_lifecycle",
    ) -> dict:
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
            "metadata": self._metadata(subscription, user=user),
        }

    def _remote_subscription(
        self,
        subscription: BusinessSubscription,
        *,
        provider_subscription_id: str | None = None,
        provider_customer_id: str | None = None,
        status: str = "active",
        trial_start: int | None = None,
        trial_end: int | None = None,
        current_period_start: int | None = None,
        current_period_end: int | None = None,
        cancel_at_period_end: bool = False,
        canceled_at: int | None = None,
    ) -> dict:
        interval = subscription.billing_interval or BusinessSubscription.BillingInterval.MONTHLY
        currency = subscription.billing_currency or BusinessSubscription.BillingCurrency.USD
        stripe_interval = (
            "year" if interval == BusinessSubscription.BillingInterval.YEARLY else "month"
        )
        provider_subscription_id = (
            provider_subscription_id or subscription.provider_subscription_id or "sub_lifecycle"
        )
        provider_customer_id = (
            provider_customer_id or subscription.provider_customer_id or "cus_lifecycle"
        )
        trial_start = trial_start if trial_start is not None else self._timestamp(2026, 7, 19)
        trial_end = trial_end if trial_end is not None else self._timestamp(2026, 8, 2)
        current_period_start = (
            current_period_start
            if current_period_start is not None
            else self._timestamp(2026, 7, 19)
        )
        current_period_end = (
            current_period_end if current_period_end is not None else self._timestamp(2026, 8, 19)
        )
        if canceled_at is None and status in {"canceled", "incomplete_expired"}:
            canceled_at = self._timestamp(2026, 8, 19)

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
            "metadata": self._metadata(subscription),
            "items": {
                "object": "list",
                "data": [
                    {
                        "id": "si_lifecycle",
                        "object": "subscription_item",
                        "price": {
                            "id": f"price_{subscription.plan.slug}_{interval}_{currency}",
                            "object": "price",
                            "currency": currency,
                            "recurring": {"interval": stripe_interval},
                        },
                    }
                ],
            },
        }

    @staticmethod
    def _stripe_client(*, retrieved_subscription: dict):
        subscription_api = SimpleNamespace(
            retrieve=mock.Mock(return_value=retrieved_subscription),
        )
        return SimpleNamespace(Subscription=subscription_api), subscription_api

    def _stripe_checkout_client(
        self,
        *,
        session_id: str,
        checkout_url: str,
    ):
        session_api = SimpleNamespace(
            create=mock.Mock(
                return_value={
                    "id": session_id,
                    "url": checkout_url,
                    "expires_at": self._timestamp(2026, 7, 19, 13),
                },
            ),
        )
        checkout_api = SimpleNamespace(Session=session_api)
        return SimpleNamespace(checkout=checkout_api), session_api

    def _create_owner_business_subscription(
        self,
        *,
        slug: str = "lifecycle-workspace",
        status: str = BusinessSubscription.Status.ACTIVE,
        provider_subscription_id: str = "sub_lifecycle",
        provider_customer_id: str = "cus_lifecycle",
        provider_updated_at: datetime | None = None,
        past_due_since: datetime | None = None,
        grace_period_ends_at: datetime | None = None,
    ) -> tuple[TaskIOUser, Business, BusinessSubscription]:
        user = TaskIOUser.objects.create_user(
            email=f"{slug}@example.com",
            password="StrongPass123!",
        )
        business = Business.objects.create(
            name=slug.replace("-", " ").title(),
            slug=slug,
            country="Sint Maarten",
        )
        BusinessUser.objects.create(
            user=user,
            business=business,
            role=BusinessUser.Role.OWNER,
        )
        plan = ClarivoPlan.objects.get(slug="pro")
        period_start = self._datetime(self._timestamp(2026, 7, 19))
        period_end = self._datetime(self._timestamp(2026, 8, 19))
        subscription = BusinessSubscription.objects.create(
            business=business,
            plan=plan,
            status=status,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_price_id="price_pro_monthly_usd",
            provider_customer_id=provider_customer_id,
            provider_subscription_id=provider_subscription_id,
            provider_updated_at=provider_updated_at,
            current_period_start=period_start,
            current_period_end=period_end,
            past_due_since=past_due_since,
            grace_period_ends_at=grace_period_ends_at,
        )
        return user, business, subscription

    def test_successful_trial_lifecycle_from_registration_to_active(self):
        plan = ClarivoPlan.objects.get(slug="starter")

        def fake_checkout(*, request, subscription, user):
            subscription.provider_price_id = "price_starter_monthly_usd"
            subscription.provider_checkout_session_id = "cs_lifecycle_registration"
            subscription.checkout_session_expires_at = self._datetime(
                self._timestamp(2026, 7, 19, 13)
            )
            subscription.save(
                update_fields=[
                    "provider_price_id",
                    "provider_checkout_session_id",
                    "checkout_session_expires_at",
                    "updated_at",
                ]
            )
            return "https://checkout.stripe.test/lifecycle"

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch(
                "apps.accounts.views.create_trial_checkout_session",
                side_effect=fake_checkout,
            ):
                response = self.client.post(
                    reverse("register_business"),
                    {
                        "first_name": "Jane",
                        "last_name": "Owner",
                        "email": "starter-lifecycle@example.com",
                        "business_name": "Starter Lifecycle",
                        "business_email": "hello@starter-lifecycle.test",
                        "country": "Sint Maarten",
                        "plan": plan.slug,
                        "billing_interval": "monthly",
                        "pricing_currency": "usd",
                        "password1": "StrongPass123!",
                        "password2": "StrongPass123!",
                    },
                )

        business = Business.objects.get(slug="starter-lifecycle")
        user = TaskIOUser.objects.get(email="starter-lifecycle@example.com")
        subscription = BusinessSubscription.objects.get(business=business)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://checkout.stripe.test/lifecycle")
        self.assertEqual(subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertEqual(subscription.plan.slug, "starter")
        self.assertEqual(subscription.access_mode, SubscriptionAccessMode.NONE)

        trial_start = self._timestamp(2026, 7, 19)
        trial_end = self._timestamp(2026, 8, 2)
        trialing_remote = self._remote_subscription(
            subscription,
            provider_subscription_id="sub_lifecycle_registration",
            provider_customer_id="cus_lifecycle_registration",
            status="trialing",
            trial_start=trial_start,
            trial_end=trial_end,
            current_period_start=trial_start,
            current_period_end=trial_end,
        )
        stripe_client, _subscription_api = self._stripe_client(
            retrieved_subscription=trialing_remote,
        )
        checkout_payload = self._event(
            event_id="evt_lifecycle_checkout_completed",
            event_type="checkout.session.completed",
            event_object=self._checkout_session(
                subscription,
                user=user,
                session_id="cs_lifecycle_registration",
                provider_subscription_id="sub_lifecycle_registration",
                provider_customer_id="cus_lifecycle_registration",
            ),
            created=trial_start,
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                webhook_response = self._signed_post(checkout_payload)

        subscription.refresh_from_db()
        self.assertEqual(webhook_response.status_code, 200)
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(subscription.plan.slug, "starter")
        self.assertEqual(
            subscription.access_mode_at(self._datetime(self._timestamp(2026, 7, 20))),
            SubscriptionAccessMode.FULL,
        )
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED
            ).count(),
            1,
        )

        reminder_summary = enqueue_due_subscription_reminders(
            evaluation_time=self._datetime(self._timestamp(2026, 7, 31)),
        )
        self.assertEqual(
            reminder_summary.created_counts[
                SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS
            ],
            1,
        )

        active_remote = self._remote_subscription(
            subscription,
            provider_subscription_id="sub_lifecycle_registration",
            provider_customer_id="cus_lifecycle_registration",
            status="active",
            trial_start=trial_start,
            trial_end=trial_end,
            current_period_start=self._timestamp(2026, 8, 2),
            current_period_end=self._timestamp(2026, 9, 2),
        )
        active_payload = self._event(
            event_id="evt_lifecycle_subscription_active",
            event_type="customer.subscription.updated",
            event_object=active_remote,
            created=self._timestamp(2026, 8, 2),
        )

        with override_settings(**self._valid_stripe_settings()):
            active_response = self._signed_post(active_payload)

        subscription.refresh_from_db()
        self.assertEqual(active_response.status_code, 200)
        self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertEqual(
            subscription.access_mode_at(self._datetime(self._timestamp(2026, 8, 3))),
            SubscriptionAccessMode.FULL,
        )
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.SUBSCRIPTION_ACTIVATED
            ).count(),
            1,
        )
        self.assertEqual(mail.outbox, [])

    def test_eur_pricing_lifecycle_from_public_selector_to_webhook(self):
        pricing_response = self.client.get(f"{reverse('home')}?currency=eur")
        self.assertEqual(pricing_response.context["selected_pricing_currency"], "eur")
        self.assertEqual(
            self.client.session[PUBLIC_PRICING_CURRENCY_SESSION_KEY],
            "eur",
        )

        registration_response = self.client.get(
            f"{reverse('register_business')}?plan=pro&interval=monthly&currency=eur",
        )
        self.assertEqual(registration_response.context["selected_pricing_currency"], "eur")
        self.assertContains(registration_response, "Europe/EUR pricing")
        self.assertContains(registration_response, "€79 / month after trial")

        checkout_client, session_api = self._stripe_checkout_client(
            session_id="cs_eur_lifecycle",
            checkout_url="https://checkout.stripe.test/eur-lifecycle",
        )
        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_checkout,
                "configure_stripe_sdk",
                return_value=checkout_client,
            ):
                response = self.client.post(
                    reverse("register_business"),
                    {
                        "first_name": "Euro",
                        "last_name": "Owner",
                        "email": "eur-lifecycle@example.com",
                        "business_name": "EUR Lifecycle",
                        "business_email": "hello@eur-lifecycle.test",
                        "country": "Germany",
                        "plan": "pro",
                        "billing_interval": "monthly",
                        "pricing_currency": "eur",
                        "password1": "StrongPass123!",
                        "password2": "StrongPass123!",
                    },
                )

        business = Business.objects.get(slug="eur-lifecycle")
        user = TaskIOUser.objects.get(email="eur-lifecycle@example.com")
        subscription = BusinessSubscription.objects.get(business=business)
        checkout_kwargs = session_api.create.call_args.kwargs
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://checkout.stripe.test/eur-lifecycle")
        self.assertEqual(subscription.plan.slug, "pro")
        self.assertEqual(
            subscription.billing_interval, BusinessSubscription.BillingInterval.MONTHLY
        )
        self.assertEqual(subscription.billing_currency, BusinessSubscription.BillingCurrency.EUR)
        self.assertEqual(subscription.provider_price_id, "price_pro_monthly_eur")
        self.assertEqual(
            checkout_kwargs["line_items"],
            [{"price": "price_pro_monthly_eur", "quantity": 1}],
        )
        self.assertEqual(checkout_kwargs["metadata"]["billing_currency"], "eur")

        trial_start = self._timestamp(2026, 7, 19)
        trial_end = self._timestamp(2026, 8, 2)
        trialing_remote = self._remote_subscription(
            subscription,
            provider_subscription_id="sub_eur_lifecycle",
            provider_customer_id="cus_eur_lifecycle",
            status="trialing",
            trial_start=trial_start,
            trial_end=trial_end,
            current_period_start=trial_start,
            current_period_end=trial_end,
        )
        stripe_client, _subscription_api = self._stripe_client(
            retrieved_subscription=trialing_remote,
        )
        checkout_payload = self._event(
            event_id="evt_eur_lifecycle_checkout_completed",
            event_type="checkout.session.completed",
            event_object=self._checkout_session(
                subscription,
                user=user,
                session_id="cs_eur_lifecycle",
                provider_subscription_id="sub_eur_lifecycle",
                provider_customer_id="cus_eur_lifecycle",
            ),
            created=trial_start,
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                webhook_response = self._signed_post(checkout_payload)

        subscription.refresh_from_db()
        self.assertEqual(webhook_response.status_code, 200)
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(subscription.plan.slug, "pro")
        self.assertEqual(
            subscription.billing_interval, BusinessSubscription.BillingInterval.MONTHLY
        )
        self.assertEqual(subscription.billing_currency, BusinessSubscription.BillingCurrency.EUR)
        self.assertEqual(subscription.provider_price_id, "price_pro_monthly_eur")

    def test_usd_pricing_lifecycle_from_public_selector_to_webhook(self):
        session = self.client.session
        session[PUBLIC_PRICING_CURRENCY_SESSION_KEY] = "eur"
        session.save()

        pricing_response = self.client.get(f"{reverse('home')}?currency=usd")
        self.assertEqual(pricing_response.context["selected_pricing_currency"], "usd")
        self.assertEqual(
            self.client.session[PUBLIC_PRICING_CURRENCY_SESSION_KEY],
            "usd",
        )

        registration_response = self.client.get(
            f"{reverse('register_business')}?plan=business&interval=yearly&currency=usd",
        )
        self.assertEqual(registration_response.context["selected_pricing_currency"], "usd")
        self.assertContains(registration_response, "International/USD pricing")
        self.assertContains(registration_response, "$1,590 / year after trial")

        checkout_client, session_api = self._stripe_checkout_client(
            session_id="cs_usd_lifecycle",
            checkout_url="https://checkout.stripe.test/usd-lifecycle",
        )
        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_checkout,
                "configure_stripe_sdk",
                return_value=checkout_client,
            ):
                response = self.client.post(
                    reverse("register_business"),
                    {
                        "first_name": "Dollar",
                        "last_name": "Owner",
                        "email": "usd-lifecycle@example.com",
                        "business_name": "USD Lifecycle",
                        "business_email": "hello@usd-lifecycle.test",
                        "country": "Sint Maarten",
                        "plan": "business",
                        "billing_interval": "yearly",
                        "pricing_currency": "usd",
                        "password1": "StrongPass123!",
                        "password2": "StrongPass123!",
                    },
                )

        business = Business.objects.get(slug="usd-lifecycle")
        user = TaskIOUser.objects.get(email="usd-lifecycle@example.com")
        subscription = BusinessSubscription.objects.get(business=business)
        checkout_kwargs = session_api.create.call_args.kwargs
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://checkout.stripe.test/usd-lifecycle")
        self.assertEqual(subscription.plan.slug, "business")
        self.assertEqual(subscription.billing_interval, BusinessSubscription.BillingInterval.YEARLY)
        self.assertEqual(subscription.billing_currency, BusinessSubscription.BillingCurrency.USD)
        self.assertEqual(subscription.provider_price_id, "price_business_yearly_usd")
        self.assertEqual(
            checkout_kwargs["line_items"],
            [{"price": "price_business_yearly_usd", "quantity": 1}],
        )
        self.assertEqual(checkout_kwargs["metadata"]["billing_currency"], "usd")

        trial_start = self._timestamp(2026, 7, 19)
        trial_end = self._timestamp(2026, 8, 2)
        trialing_remote = self._remote_subscription(
            subscription,
            provider_subscription_id="sub_usd_lifecycle",
            provider_customer_id="cus_usd_lifecycle",
            status="trialing",
            trial_start=trial_start,
            trial_end=trial_end,
            current_period_start=trial_start,
            current_period_end=trial_end,
        )
        stripe_client, _subscription_api = self._stripe_client(
            retrieved_subscription=trialing_remote,
        )
        checkout_payload = self._event(
            event_id="evt_usd_lifecycle_checkout_completed",
            event_type="checkout.session.completed",
            event_object=self._checkout_session(
                subscription,
                user=user,
                session_id="cs_usd_lifecycle",
                provider_subscription_id="sub_usd_lifecycle",
                provider_customer_id="cus_usd_lifecycle",
            ),
            created=trial_start,
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                webhook_response = self._signed_post(checkout_payload)

        subscription.refresh_from_db()
        self.assertEqual(webhook_response.status_code, 200)
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(subscription.plan.slug, "business")
        self.assertEqual(subscription.billing_interval, BusinessSubscription.BillingInterval.YEARLY)
        self.assertEqual(subscription.billing_currency, BusinessSubscription.BillingCurrency.USD)
        self.assertEqual(subscription.provider_price_id, "price_business_yearly_usd")

    def test_failed_payment_recovery_lifecycle_requires_verified_webhook(self):
        user, business, subscription = self._create_owner_business_subscription(
            slug="recovery-lifecycle",
        )
        self.client.force_login(user)
        self.client.session[CURRENT_BUSINESS_SESSION_KEY] = business.pk
        self.client.session.save()

        past_due_remote = self._remote_subscription(subscription, status="past_due")
        stripe_client, _subscription_api = self._stripe_client(
            retrieved_subscription=past_due_remote,
        )
        failed_payload = self._event(
            event_id="evt_lifecycle_payment_failed",
            event_type="invoice.payment_failed",
            event_object={
                "id": "in_lifecycle_failed",
                "object": "invoice",
                "subscription": subscription.provider_subscription_id,
                "status": "open",
            },
            created=self._timestamp(2026, 7, 20),
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                failed_response = self._signed_post(failed_payload)

        subscription.refresh_from_db()
        self.assertEqual(failed_response.status_code, 200)
        self.assertEqual(subscription.status, BusinessSubscription.Status.PAST_DUE)
        self.assertEqual(
            subscription.access_mode_at(self._datetime(self._timestamp(2026, 7, 21))),
            SubscriptionAccessMode.FULL,
        )
        self.assertEqual(
            subscription.access_mode_at(self._datetime(self._timestamp(2026, 7, 27))),
            SubscriptionAccessMode.RESTRICTED,
        )
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_STARTED
            ).count(),
            1,
        )

        reminder_summary = enqueue_due_subscription_reminders(
            evaluation_time=self._datetime(self._timestamp(2026, 7, 26)),
        )
        self.assertEqual(
            reminder_summary.created_counts[
                SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY
            ],
            1,
        )

        return_response = self.client.get(f"{reverse('business_subscription')}?billing_return=1")
        subscription.refresh_from_db()
        self.assertEqual(return_response.status_code, 200)
        self.assertEqual(subscription.status, BusinessSubscription.Status.PAST_DUE)
        self.assertEqual(
            subscription.access_mode_at(self._datetime(self._timestamp(2026, 7, 28))),
            SubscriptionAccessMode.RESTRICTED,
        )

        active_remote = self._remote_subscription(
            subscription,
            status="active",
            current_period_start=self._timestamp(2026, 7, 28),
            current_period_end=self._timestamp(2026, 8, 28),
        )
        paid_payload = self._event(
            event_id="evt_lifecycle_payment_recovered",
            event_type="invoice.paid",
            event_object={
                "id": "in_lifecycle_paid",
                "object": "invoice",
                "subscription": subscription.provider_subscription_id,
                "status": "paid",
            },
            created=self._timestamp(2026, 7, 28),
        )
        stripe_client, _subscription_api = self._stripe_client(
            retrieved_subscription=active_remote,
        )

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch.object(
                stripe_webhooks,
                "configure_stripe_sdk",
                return_value=stripe_client,
            ):
                paid_response = self._signed_post(paid_payload)

        subscription.refresh_from_db()
        self.assertEqual(paid_response.status_code, 200)
        self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertIsNone(subscription.past_due_since)
        self.assertIsNone(subscription.grace_period_ends_at)
        self.assertEqual(
            subscription.access_mode_at(self._datetime(self._timestamp(2026, 7, 29))),
            SubscriptionAccessMode.FULL,
        )
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.PAYMENT_RECOVERED
            ).count(),
            1,
        )

    def test_cancellation_lifecycle_schedules_then_removes_access(self):
        _user, _business, subscription = self._create_owner_business_subscription(
            slug="cancellation-lifecycle",
        )
        scheduled_remote = self._remote_subscription(
            subscription,
            status="active",
            cancel_at_period_end=True,
            current_period_start=self._timestamp(2026, 7, 19),
            current_period_end=self._timestamp(2026, 8, 19),
        )
        scheduled_payload = self._event(
            event_id="evt_lifecycle_cancel_scheduled",
            event_type="customer.subscription.updated",
            event_object=scheduled_remote,
            created=self._timestamp(2026, 7, 25),
        )

        with override_settings(**self._valid_stripe_settings()):
            scheduled_response = self._signed_post(scheduled_payload)

        subscription.refresh_from_db()
        self.assertEqual(scheduled_response.status_code, 200)
        self.assertTrue(subscription.cancel_at_period_end)
        self.assertEqual(
            subscription.access_mode_at(self._datetime(self._timestamp(2026, 8, 18))),
            SubscriptionAccessMode.FULL,
        )
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.CANCELLATION_SCHEDULED
            ).count(),
            1,
        )

        cancelled_remote = self._remote_subscription(
            subscription,
            status="canceled",
            cancel_at_period_end=False,
            canceled_at=self._timestamp(2026, 8, 19),
            current_period_start=self._timestamp(2026, 7, 19),
            current_period_end=self._timestamp(2026, 8, 19),
        )
        cancelled_payload = self._event(
            event_id="evt_lifecycle_cancel_effective",
            event_type="customer.subscription.deleted",
            event_object=cancelled_remote,
            created=self._timestamp(2026, 8, 19),
        )

        with override_settings(**self._valid_stripe_settings()):
            cancelled_response = self._signed_post(cancelled_payload)

        subscription.refresh_from_db()
        self.assertEqual(cancelled_response.status_code, 200)
        self.assertEqual(subscription.status, BusinessSubscription.Status.CANCELLED)
        self.assertEqual(subscription.access_mode, SubscriptionAccessMode.NONE)
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.SUBSCRIPTION_CANCELLED
            ).count(),
            1,
        )

    def test_duplicate_and_stale_events_do_not_downgrade_or_duplicate_notifications(self):
        _user, _business, subscription = self._create_owner_business_subscription(
            slug="stale-lifecycle",
            provider_updated_at=self._datetime(self._timestamp(2026, 7, 25)),
        )
        active_payload = self._event(
            event_id="evt_lifecycle_duplicate_active",
            event_type="customer.subscription.updated",
            event_object=self._remote_subscription(subscription, status="active"),
            created=self._timestamp(2026, 7, 25),
        )
        stale_payload = self._event(
            event_id="evt_lifecycle_stale_past_due",
            event_type="customer.subscription.updated",
            event_object=self._remote_subscription(subscription, status="past_due"),
            created=self._timestamp(2026, 7, 20),
        )

        with override_settings(**self._valid_stripe_settings()):
            first_response = self._signed_post(active_payload)
            duplicate_response = self._signed_post(active_payload)
            stale_response = self._signed_post(stale_payload)

        subscription.refresh_from_db()
        stale_record = BillingProviderWebhookEvent.objects.get(
            event_id="evt_lifecycle_stale_past_due"
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(stale_response.status_code, 200)
        self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertEqual(
            subscription.provider_updated_at,
            self._datetime(self._timestamp(2026, 7, 25)),
        )
        self.assertEqual(stale_record.status, BillingProviderWebhookEvent.Status.PROCESSED)
        self.assertFalse(SubscriptionNotification.objects.exists())

    def test_beta_lifecycle_remains_stripe_independent(self):
        user = TaskIOUser.objects.create_user(
            email="beta-lifecycle@example.com",
            password="StrongPass123!",
        )
        business = Business.objects.create(name="Beta Lifecycle", slug="beta-lifecycle")
        BusinessUser.objects.create(
            user=user,
            business=business,
            role=BusinessUser.Role.OWNER,
        )
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)
        subscription = BusinessSubscription.objects.create(
            business=business,
            plan=beta_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        self.assertEqual(subscription.access_mode, SubscriptionAccessMode.FULL)
        self.assertEqual(subscription.payment_provider, "")
        self.assertEqual(subscription.provider_customer_id, "")
        self.assertEqual(subscription.provider_subscription_id, "")
        self.assertFalse(
            get_customer_portal_availability(
                business=business,
                user=user,
                subscription=subscription,
            ).can_open
        )
        self.assertFalse(
            get_payment_recovery_portal_availability(
                business=business,
                user=user,
                subscription=subscription,
            ).can_open
        )

        reminder_summary = enqueue_due_subscription_reminders(
            evaluation_time=self._datetime(self._timestamp(2026, 7, 26)),
        )
        enqueue_subscription_notification(
            subscription=subscription,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_context={"beta": "ignored"},
        )

        self.assertEqual(reminder_summary.created_total, 0)
        self.assertFalse(SubscriptionNotification.objects.exists())


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
        european_business = Business.objects.create(
            name="Berlin Ops",
            slug="berlin-ops",
            country="Germany",
        )

        public_pricing = plan.get_display_pricing()
        european_pricing = plan.get_display_pricing(business=european_business)
        eur_pricing = plan.get_display_pricing(region=ClarivoPlan.EUR_PRICING_REGION)

        self.assertEqual(public_pricing["monthly_display"], "$159")
        self.assertEqual(public_pricing["yearly_display"], "$1,590")
        self.assertEqual(public_pricing["tax_note"], "")
        self.assertEqual(european_pricing["monthly_display"], "€149")
        self.assertEqual(european_pricing["yearly_display"], "€1,490")
        self.assertEqual(european_pricing["tax_note"], "")
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

    def test_public_pricing_page_defaults_to_usd_prices_and_no_growth_plan(self):
        ClarivoPlan.objects.create(
            name="Growth",
            slug="growth",
            price_monthly=Decimal("49.00"),
            price_yearly=Decimal("490.00"),
            is_active=True,
        )

        response = self.client.get(reverse("home"), HTTP_HOST="localhost", secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_pricing_currency"], "usd")
        self.assertContains(response, "$39")
        self.assertContains(response, "$79")
        self.assertContains(response, "$159")
        self.assertContains(response, "$1,590 yearly USD")
        self.assertContains(response, "International/USD pricing")
        self.assertContains(response, "Europe/EUR")
        self.assertContains(
            response,
            f"{reverse('register_business')}?plan=business&amp;interval=monthly&amp;currency=usd",
        )
        self.assertContains(response, "interval=yearly&amp;currency=usd")
        self.assertContains(response, "Recommended")
        self.assertContains(response, "Client CRM")
        self.assertContains(response, "Online Booking")
        self.assertContains(response, "2 total users: owner + 1 staff account")
        self.assertNotContains(response, "€39")
        self.assertNotContains(response, "€79")
        self.assertNotContains(response, "€149")
        self.assertNotContains(response, "EUR:")
        self.assertNotContains(response, "€1,490")
        self.assertNotContains(response, "$0.00")
        self.assertNotContains(response, BETA_PLAN_DISPLAY_NAME)
        self.assertNotContains(response, "Growth")
        self.assertNotContains(response, "Public Request Form")
        self.assertNotContains(response, "Public Booking")

    def test_public_pricing_page_can_select_eur_as_primary_prices(self):
        response = self.client.get(
            f"{reverse('home')}?currency=eur",
            HTTP_HOST="localhost",
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_pricing_currency"], "eur")
        self.assertEqual(
            self.client.session[PUBLIC_PRICING_CURRENCY_SESSION_KEY],
            "eur",
        )
        self.assertContains(response, "€39")
        self.assertContains(response, "€79")
        self.assertContains(response, "€149")
        self.assertContains(response, "€1,490 yearly EUR")
        self.assertContains(response, "Europe/EUR pricing")
        self.assertContains(
            response,
            f"{reverse('register_business')}?plan=business&amp;interval=monthly&amp;currency=eur",
        )
        self.assertContains(response, "interval=yearly&amp;currency=eur")
        self.assertNotContains(response, "$159")
        self.assertNotContains(response, "$1,590 yearly USD")

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

        get_response = self.client.get(
            reverse("accept_business_invitation", args=[invitation.token])
        )
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
        self.assertFalse(
            BusinessUser.objects.filter(
                business=self.business, user__email=invitation.email
            ).exists()
        )

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


class BusinessAdminDeletionProtectionTests(TestCase):
    def setUp(self):
        self.superuser = TaskIOUser.objects.create_superuser(
            email="system-admin@example.com",
            password="StrongPass123!",
        )
        self.business = Business.objects.create(
            name="Protected Workspace",
            slug="protected-workspace",
        )
        self.client.force_login(self.superuser)

    def test_business_object_deletion_is_unavailable_even_to_superusers(self):
        model_admin = admin.site._registry[Business]

        response = self.client.get(
            reverse("admin:businesses_business_delete", args=[self.business.pk])
        )

        self.assertFalse(model_admin.has_delete_permission(response.wsgi_request, self.business))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())

    def test_business_bulk_deletion_is_unavailable_and_admin_explains_workflow(self):
        model_admin = admin.site._registry[Business]
        change_response = self.client.get(
            reverse("admin:businesses_business_change", args=[self.business.pk])
        )
        changelist_response = self.client.get(reverse("admin:businesses_business_changelist"))

        actions = model_admin.get_actions(changelist_response.wsgi_request)

        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, model_admin.deletion_workflow_notice)
        self.assertNotIn("delete_selected", actions)
        self.assertNotContains(changelist_response, 'value="delete_selected"')


class BusinessResolutionTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Resolver Workspace",
            slug="resolver-workspace",
            email="contact@resolver.example",
            is_active=True,
        )

    def test_lookup_requires_exactly_one_identifier(self):
        with self.assertRaises(BusinessResolutionError):
            resolve_business_candidates()
        with self.assertRaises(BusinessResolutionError):
            resolve_business_candidates(
                business_id=self.business.pk,
                slug=self.business.slug,
            )

    def test_lookup_by_id_returns_structured_candidate(self):
        candidates = resolve_business_candidates(business_id=str(self.business.pk))

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.business_id, self.business.pk)
        self.assertEqual(candidate.business_name, self.business.name)
        self.assertEqual(candidate.slug, self.business.slug)
        self.assertEqual(candidate.business_contact_email, self.business.email)
        self.assertTrue(candidate.is_active)
        self.assertEqual(candidate.matches[0].matched_by, BusinessMatchKind.PRIMARY_KEY)

    def test_lookup_by_slug_returns_correct_candidate(self):
        candidates = resolve_business_candidates(slug=self.business.slug)

        self.assertEqual([candidate.business_id for candidate in candidates], [self.business.pk])
        self.assertEqual(candidates[0].matches[0].matched_by, BusinessMatchKind.SLUG)

    def test_user_email_matching_is_case_insensitive(self):
        user = TaskIOUser.objects.create_user(
            email="member@resolver.example",
            password="StrongPass123!",
        )
        BusinessUser.objects.create(
            user=user,
            business=self.business,
            role=BusinessUser.Role.ACCOUNTANT,
        )

        candidates = resolve_business_candidates(email=" MEMBER@RESOLVER.EXAMPLE ")

        self.assertEqual([candidate.business_id for candidate in candidates], [self.business.pk])
        match = candidates[0].matches[0]
        self.assertEqual(match.matched_by, BusinessMatchKind.MEMBER_EMAIL)
        self.assertEqual(match.membership_role, BusinessUser.Role.ACCOUNTANT)
        self.assertTrue(match.membership_is_active)

    def test_business_contact_email_matching_is_case_insensitive(self):
        candidates = resolve_business_candidates(email="CONTACT@RESOLVER.EXAMPLE")

        self.assertEqual([candidate.business_id for candidate in candidates], [self.business.pk])
        self.assertEqual(candidates[0].matches[0].matched_by, BusinessMatchKind.CONTACT_EMAIL)

    def test_multiple_email_matches_remain_multiple(self):
        member_business = Business.objects.create(
            name="Member Match",
            slug="member-match",
        )
        member = TaskIOUser.objects.create_user(
            email="shared@resolver.example",
            password="StrongPass123!",
        )
        BusinessUser.objects.create(
            user=member,
            business=member_business,
            role=BusinessUser.Role.STAFF,
        )
        contact_business = Business.objects.create(
            name="Contact Match",
            slug="contact-match",
            email="shared@resolver.example",
        )

        candidates = resolve_business_candidates(email="shared@resolver.example")

        self.assertEqual(
            {candidate.business_id for candidate in candidates},
            {member_business.pk, contact_business.pk},
        )

    def test_duplicate_matches_for_one_business_are_merged(self):
        shared_email = "both@resolver.example"
        self.business.email = shared_email
        self.business.save(update_fields=["email", "updated_at"])
        member = TaskIOUser.objects.create_user(
            email=shared_email,
            password="StrongPass123!",
        )
        BusinessUser.objects.create(
            user=member,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )

        candidates = resolve_business_candidates(email=shared_email.upper())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].business_id, self.business.pk)
        self.assertEqual(
            {match.matched_by for match in candidates[0].matches},
            {BusinessMatchKind.MEMBER_EMAIL, BusinessMatchKind.CONTACT_EMAIL},
        )

    def test_inactive_membership_is_discoverable(self):
        user = TaskIOUser.objects.create_user(
            email="inactive@resolver.example",
            password="StrongPass123!",
        )
        BusinessUser.objects.create(
            user=user,
            business=self.business,
            role=BusinessUser.Role.VIEWER,
            is_active=False,
        )

        candidates = resolve_business_candidates(email=user.email)

        self.assertEqual(len(candidates), 1)
        match = candidates[0].matches[0]
        self.assertEqual(match.membership_role, BusinessUser.Role.VIEWER)
        self.assertFalse(match.membership_is_active)

    def test_tenant_customer_and_invitation_emails_are_not_resolution_sources(self):
        Client.objects.create(
            business=self.business,
            first_name="Client",
            last_name="Only",
            email="client-only@resolver.example",
            phone="",
            company_name="",
            street_address="",
        )
        Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.INTEREST,
            first_name="Lead",
            last_name="Only",
            email="lead-only@resolver.example",
            phone="",
            company_name="",
        )
        BusinessInvitation.objects.create(
            business=self.business,
            email="invitation-only@resolver.example",
            role=BusinessUser.Role.STAFF,
        )

        for email in (
            "client-only@resolver.example",
            "lead-only@resolver.example",
            "invitation-only@resolver.example",
        ):
            with self.subTest(email=email):
                self.assertEqual(resolve_business_candidates(email=email), ())


class BusinessDataOperationTests(TestCase):
    def test_audit_model_has_snapshot_ids_without_business_or_user_relations(self):
        relation_fields = [
            field for field in BusinessDataOperation._meta.get_fields() if field.is_relation
        ]

        self.assertEqual(relation_fields, [])
        self.assertFalse(BusinessDataOperation._meta.get_field("operation_id").editable)
        self.assertTrue(BusinessDataOperation._meta.get_field("operation_id").unique)

    def test_audit_record_uses_only_snapshot_ids_and_non_pii_metadata(self):
        operation = BusinessDataOperation.objects.create(
            business_id_snapshot=987654321,
            mode=BusinessDataOperation.Mode.DEACTIVATE,
            operator_id_snapshot=123456789,
            reason_reference="SUPPORT-1001",
            record_counts={"clients": 4, "invoices": 2},
        )

        operation.refresh_from_db()

        self.assertIsNotNone(operation.operation_id)
        self.assertEqual(operation.business_id_snapshot, 987654321)
        self.assertEqual(operation.operator_id_snapshot, 123456789)
        self.assertEqual(operation.status, BusinessDataOperation.Status.STARTED)
        self.assertEqual(operation.reason_reference, "SUPPORT-1001")
        self.assertEqual(operation.record_counts, {"clients": 4, "invoices": 2})
        self.assertIsNone(operation.completed_at)
        self.assertEqual(operation.error_code, "")


class BusinessDataInventoryCommandTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Inventory Workspace",
            slug="inventory-workspace",
            email="private-contact@inventory.example",
        )
        self.other_business = Business.objects.create(
            name="Other Workspace",
            slug="other-inventory-workspace",
            email="other-private-contact@inventory.example",
        )

    def _command_output(self, *, output_format="json", **lookup):
        output = StringIO()
        call_command(
            "inspect_business_data",
            output_format=output_format,
            stdout=output,
            **lookup,
        )
        return output.getvalue()

    def _json_inventory(self):
        return json.loads(self._command_output(business_id=self.business.pk))

    @staticmethod
    def _records_by_key(inventory):
        return {record["key"]: record for record in inventory["records"]}

    def _client(self, *, business, suffix):
        return Client.objects.create(
            business=business,
            first_name="Inventory",
            last_name=suffix,
            email=f"client-{suffix}@inventory.example",
            phone="+1 721 555 0100",
            company_name=f"Client {suffix}",
            street_address="1 Inventory Street",
        )

    def test_command_requires_exactly_one_lookup_argument(self):
        with self.assertRaises(CommandError):
            call_command("inspect_business_data", stdout=StringIO())

        with self.assertRaises(CommandError):
            call_command(
                "inspect_business_data",
                business_id=self.business.pk,
                slug=self.business.slug,
                stdout=StringIO(),
            )

    def test_missing_business_returns_nonzero_with_clear_message(self):
        output = StringIO()

        with self.assertRaises(CommandError):
            call_command(
                "inspect_business_data",
                business_id=999999,
                stdout=output,
            )

        self.assertIn("No business matched", output.getvalue())

    def test_ambiguous_email_lists_all_candidates_and_requires_business_id(self):
        user = TaskIOUser.objects.create_user(
            email="shared-operator@inventory.example",
            password="StrongPass123!",
        )
        BusinessUser.objects.create(
            business=self.business,
            user=user,
            role=BusinessUser.Role.OWNER,
        )
        BusinessUser.objects.create(
            business=self.other_business,
            user=user,
            role=BusinessUser.Role.VIEWER,
            is_active=False,
        )
        BusinessInvitation.objects.create(
            business=self.business,
            email="invitee@inventory.example",
            token="never-display-this-invitation-token",
        )
        output = StringIO()

        with self.assertRaises(CommandError):
            call_command(
                "inspect_business_data",
                email="SHARED-OPERATOR@INVENTORY.EXAMPLE",
                stdout=output,
            )

        rendered = output.getvalue()
        self.assertIn(f"Business ID={self.business.pk}", rendered)
        self.assertIn(f"Business ID={self.other_business.pk}", rendered)
        self.assertIn("matched_by=member_email", rendered)
        self.assertIn("rerun using --business-id", rendered)
        self.assertNotIn(self.business.email, rendered)
        self.assertNotIn(self.other_business.email, rendered)
        self.assertNotIn("never-display-this-invitation-token", rendered)

    def test_exact_business_id_outputs_inventory_in_text_and_json(self):
        text_output = self._command_output(
            output_format="text",
            business_id=self.business.pk,
        )
        json_output = self._json_inventory()
        summary = json_output["summary"]

        self.assertIn(f"Selected Business ID: {self.business.pk}", text_output)
        self.assertIn(f"- Business slug: {summary['business_slug']}", text_output)
        self.assertIn(
            "- Total directly and indirectly owned records: "
            f"{summary['total_directly_and_indirectly_owned_records']}",
            text_output,
        )
        self.assertIn(
            f"- Overall future-purge readiness: {summary['future_purge_readiness']}",
            text_output,
        )
        self.assertEqual(
            json_output["selected_business"]["business_id"],
            self.business.pk,
        )
        self.assertTrue(json_output["informational_only"])

    def test_unique_slug_and_email_lookups_produce_the_same_inventory(self):
        by_slug = json.loads(self._command_output(slug=self.business.slug))
        by_email = json.loads(self._command_output(email=self.business.email.upper()))

        self.assertEqual(
            by_slug["selected_business"]["business_id"],
            self.business.pk,
        )
        self.assertEqual(by_slug["summary"], by_email["summary"])

    def test_command_executes_no_database_writes_or_audit_operations(self):
        output = StringIO()
        initial_operation_count = BusinessDataOperation.objects.count()

        with CaptureQueriesContext(connection) as captured_queries:
            call_command(
                "inspect_business_data",
                business_id=self.business.pk,
                output_format="json",
                stdout=output,
            )

        write_verbs = {"ALTER", "CREATE", "DELETE", "DROP", "INSERT", "REPLACE", "UPDATE"}
        executed_verbs = {
            query["sql"].lstrip().partition(" ")[0].upper()
            for query in captured_queries.captured_queries
        }
        self.assertTrue(executed_verbs.isdisjoint(write_verbs))
        self.assertEqual(BusinessDataOperation.objects.count(), initial_operation_count)
        self.business.refresh_from_db()
        self.assertTrue(self.business.is_active)

    def test_inventory_counts_cascade_set_null_invoice_and_indirect_records(self):
        BusinessBookingSettings.objects.create(business=self.business)
        WeeklyAvailability.objects.create(
            business=self.business,
            day_of_week=WeeklyAvailability.DayOfWeek.MONDAY,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        category = ServiceCategory.objects.create(
            business=self.business,
            name="Inventory Category",
        )
        service = BusinessService.objects.create(
            business=self.business,
            category=category,
            name="Inventory Service",
        )
        lead = Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            first_name="Inventory",
            last_name="Lead",
            email="lead@inventory.example",
            phone="+1 721 555 0101",
            company_name="Lead Company",
            category=category,
            requested_service=service,
        )
        client = self._client(business=self.business, suffix="owned")
        ActivityLog.objects.create(
            business=self.business,
            lead=lead,
            client=client,
            action_type=ActivityLog.ActionType.STATUS_CHANGED,
        )
        now = timezone.now()
        appointment = Appointment.objects.create(
            business=self.business,
            client=client,
            service=service,
            source_lead=lead,
            title="Inventory appointment",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
        )
        invoice = Invoice.objects.create(
            business=self.business,
            client=client,
            appointment=appointment,
            invoice_number="INV-INVENTORY-1",
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            service=service,
            description="Inventory line",
            quantity=1,
            unit_price=Decimal("25.00"),
        )

        inventory = self._json_inventory()
        records = self._records_by_key(inventory)

        self.assertEqual(records["business_booking_settings"]["total_count"], 1)
        self.assertEqual(records["weekly_availability"]["total_count"], 1)
        self.assertEqual(records["business_services"]["classification"], "cascade")
        self.assertEqual(records["service_categories"]["classification"], "set_null_orphan_risk")
        self.assertEqual(records["leads"]["total_count"], 1)
        self.assertEqual(records["clients"]["total_count"], 1)
        self.assertEqual(records["activity_logs"]["total_count"], 1)
        self.assertEqual(records["appointments"]["total_count"], 1)
        self.assertEqual(records["invoices"]["total_count"], 1)
        self.assertEqual(records["invoices"]["classification"], "protect_blocker")
        self.assertEqual(records["invoice_lines"]["total_count"], 1)
        self.assertEqual(records["invoice_lines"]["classification"], "indirect")
        self.assertEqual(inventory["summary"]["set_null_orphan_risk_count"], 4)
        self.assertEqual(inventory["summary"]["protect_blocker_count"], 1)
        self.assertTrue(inventory["billing_assessment"]["invoice_protect_would_block_delete"])
        self.assertEqual(
            inventory["summary"]["future_purge_readiness"],
            FuturePurgeReadiness.BLOCKED_BY_FINANCIAL_RETENTION,
        )

    def test_shared_and_system_users_are_protected_without_exposing_email(self):
        shared_user = TaskIOUser.objects.create_user(
            email="shared-user@inventory.example",
            password="StrongPass123!",
        )
        system_user = TaskIOUser.objects.create_superuser(
            email="system-user@inventory.example",
            password="StrongPass123!",
        )
        BusinessUser.objects.create(
            business=self.business,
            user=shared_user,
            role=BusinessUser.Role.STAFF,
        )
        BusinessUser.objects.create(
            business=self.other_business,
            user=shared_user,
            role=BusinessUser.Role.VIEWER,
            is_active=False,
        )
        BusinessUser.objects.create(
            business=self.business,
            user=system_user,
            role=BusinessUser.Role.ADMIN,
        )

        rendered = self._command_output(business_id=self.business.pk)
        inventory = json.loads(rendered)
        impacts = {impact["user_id"]: impact for impact in inventory["user_impact"]}

        self.assertTrue(impacts[shared_user.pk]["appears_shared"])
        self.assertEqual(
            impacts[shared_user.pk]["other_business_membership_count"],
            1,
        )
        self.assertTrue(impacts[shared_user.pk]["automatic_account_deletion_prohibited"])
        self.assertTrue(impacts[system_user.pk]["is_staff"])
        self.assertTrue(impacts[system_user.pk]["is_superuser"])
        self.assertTrue(impacts[system_user.pk]["automatic_account_deletion_prohibited"])
        self.assertEqual(inventory["summary"]["shared_user_count"], 1)
        self.assertEqual(inventory["summary"]["protected_or_system_user_count"], 2)
        self.assertNotIn(shared_user.email, rendered)
        self.assertNotIn(system_user.email, rendered)

    def test_cross_business_relationship_is_a_future_purge_blocker(self):
        selected_client = self._client(business=self.business, suffix="selected")
        other_client = self._client(business=self.other_business, suffix="other")
        now = timezone.now()
        other_appointment = Appointment.objects.create(
            business=self.other_business,
            client=other_client,
            title="Other appointment",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
        )
        Appointment.objects.filter(pk=other_appointment.pk).update(client_id=selected_client.pk)

        inventory = self._json_inventory()
        checks = {check["check_code"]: check for check in inventory["integrity_checks"]}

        check = checks["cross_tenant_external_appointment_client"]
        self.assertEqual(check["severity"], "blocker")
        self.assertEqual(check["affected_count"], 1)
        self.assertEqual(
            inventory["summary"]["future_purge_readiness"],
            FuturePurgeReadiness.BLOCKED_BY_INTEGRITY,
        )
        self.assertGreater(
            inventory["summary"]["cross_tenant_integrity_blocker_count"],
            0,
        )

    def test_null_business_legacy_records_are_not_attributed_to_selected_business(self):
        self._client(business=None, suffix="legacy-null")

        inventory = self._json_inventory()
        records = self._records_by_key(inventory)
        checks = {check["check_code"]: check for check in inventory["integrity_checks"]}

        self.assertEqual(records["clients"]["total_count"], 0)
        self.assertGreaterEqual(
            checks["legacy_null_business_crm_client"]["affected_count"],
            1,
        )
        self.assertEqual(
            inventory["summary"]["total_directly_and_indirectly_owned_records"],
            1,
        )

    def test_webhooks_and_provider_state_are_counted_without_exposing_identifiers(self):
        plan = ClarivoPlan.objects.get(slug="pro")
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY,
            billing_currency=BusinessSubscription.BillingCurrency.USD,
            provider_customer_id="cus_inventory_secret",
            provider_subscription_id="sub_inventory_secret",
            provider_checkout_session_id="cs_inventory_secret",
            provider_price_id="price_inventory_secret",
            current_period_end=timezone.now() + timedelta(days=30),
        )
        BillingProviderWebhookEvent.objects.create(
            event_id="evt_inventory_secret",
            event_type="customer.subscription.updated",
            object_id=subscription.provider_subscription_id,
            payload_summary={
                "motionmate_business_id": str(self.business.pk),
                "motionmate_subscription_id": str(subscription.pk),
                "provider_subscription_id": subscription.provider_subscription_id,
                "private_payload_value": "never-display-webhook-payload",
            },
        )
        BusinessInvitation.objects.create(
            business=self.business,
            email="private-invitee@inventory.example",
            token="never-display-inventory-token",
        )

        rendered = self._command_output(business_id=self.business.pk)
        inventory = json.loads(rendered)
        billing = inventory["billing_assessment"]

        self.assertEqual(billing["correlated_webhook_event_count"], 1)
        self.assertTrue(billing["provider_customer_id_present"])
        self.assertTrue(billing["provider_subscription_id_present"])
        self.assertTrue(billing["provider_checkout_id_present"])
        self.assertTrue(billing["provider_price_id_present"])
        self.assertTrue(billing["future_stripe_closure_required"])
        for secret in (
            "cus_inventory_secret",
            "sub_inventory_secret",
            "cs_inventory_secret",
            "price_inventory_secret",
            "evt_inventory_secret",
            "never-display-webhook-payload",
            "never-display-inventory-token",
            "private-invitee@inventory.example",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, rendered)

    def test_database_sessions_are_counted_without_exposing_contents(self):
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session["private_test_value"] = "never-display-session-contents"
        session.save()

        rendered = self._command_output(business_id=self.business.pk)
        records = self._records_by_key(json.loads(rendered))

        self.assertEqual(records["sessions"]["active_count"], 1)
        self.assertEqual(records["sessions"]["total_count"], 1)
        self.assertNotIn("never-display-session-contents", rendered)
        self.assertNotIn(session.session_key, rendered)

    def test_completeness_guard_detects_missing_and_accepts_current_registry(self):
        self.assertEqual(find_unregistered_direct_business_relations(), ())

        registry_without_invoices = tuple(
            registration
            for registration in DIRECT_BUSINESS_RELATION_REGISTRY
            if registration.model_label != "billings.Invoice"
        )

        self.assertIn(
            "billings.Invoice.business",
            find_unregistered_direct_business_relations(registry_without_invoices),
        )

    def test_inventory_service_accepts_exact_instance_or_id_and_is_serializable(self):
        by_instance = build_business_data_inventory(self.business).to_dict()
        by_id = build_business_data_inventory(self.business.pk).to_dict()

        self.assertEqual(by_instance["summary"], by_id["summary"])
        self.assertEqual(
            self._records_by_key(by_instance)["business"]["classification"],
            InventoryClassification.TENANT_ROOT,
        )
        json.dumps(by_instance)


class BusinessDeactivationTests(TestCase):
    reason_reference = "TEST-CLEANUP-001"

    def setUp(self):
        self.plan = ClarivoPlan.objects.get(slug="pro")
        self.business = Business.objects.create(
            name="Private Deactivation Workspace",
            slug="deactivation-workspace",
            email="private-business@deactivation.example",
        )
        self.other_business = Business.objects.create(
            name="Other Preserved Workspace",
            slug="other-preserved-workspace",
        )
        now = timezone.now()
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.TRIALING,
            trial_start=now,
            trial_end=now + timedelta(days=14),
            current_period_start=now,
            current_period_end=now + timedelta(days=14),
        )
        self.other_subscription = BusinessSubscription.objects.create(
            business=self.other_business,
            plan=self.plan,
            status=BusinessSubscription.Status.TRIALING,
            trial_start=now,
            trial_end=now + timedelta(days=14),
            current_period_start=now,
            current_period_end=now + timedelta(days=14),
        )
        self.owner = TaskIOUser.objects.create_user(
            email="private-owner@deactivation.example",
            password="StrongPass123!",
        )
        self.membership = BusinessUser.objects.create(
            business=self.business,
            user=self.owner,
            role=BusinessUser.Role.OWNER,
        )

    def _run_command(self, *, execute=False, confirmation=None):
        output = StringIO()
        options = {
            "business_id": self.business.pk,
            "reason_reference": self.reason_reference,
            "execute": execute,
            "stdout": output,
        }
        if confirmation is not None:
            options["confirm_business_id"] = confirmation
        call_command("deactivate_business", **options)
        return output.getvalue()

    @staticmethod
    def _create_session(*, user=None, business_id=None, private_value=""):
        client = DjangoClient()
        if user is not None:
            client.force_login(user)
        session = client.session
        if business_id is not None:
            session[CURRENT_BUSINESS_SESSION_KEY] = business_id
        if private_value:
            session["private_test_value"] = private_value
        session.save()
        return session.session_key

    def _create_tenant_records(self):
        category = ServiceCategory.objects.create(
            business=self.business,
            name="Private Category",
        )
        service = BusinessService.objects.create(
            business=self.business,
            category=category,
            name="Private Service",
            unit_price=Decimal("45.00"),
        )
        lead = Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            first_name="Private",
            last_name="Lead",
            email="private-lead@deactivation.example",
            phone="+1 721 555 0100",
            company_name="Private Client",
            category=category,
            requested_service=service,
        )
        client = Client.objects.create(
            business=self.business,
            first_name="Private",
            last_name="Client",
            email="private-client@deactivation.example",
            phone="+1 721 555 0101",
            company_name="Private Client",
            street_address="1 Private Street",
        )
        activity = ActivityLog.objects.create(
            business=self.business,
            lead=lead,
            client=client,
            action_type=ActivityLog.ActionType.STATUS_CHANGED,
        )
        now = timezone.now()
        appointment = Appointment.objects.create(
            business=self.business,
            client=client,
            service=service,
            source_lead=lead,
            title="Private appointment",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
        )
        invoice = Invoice.objects.create(
            business=self.business,
            client=client,
            appointment=appointment,
            invoice_number="INV-DEACTIVATE-1",
        )
        invoice_line = InvoiceLine.objects.create(
            invoice=invoice,
            service=service,
            description="Private invoice line",
            quantity=1,
            unit_price=Decimal("45.00"),
        )
        booking_settings = BusinessBookingSettings.objects.create(
            business=self.business,
            booking_enabled=True,
        )
        return {
            "category": category,
            "service": service,
            "lead": lead,
            "client": client,
            "activity": activity,
            "appointment": appointment,
            "invoice": invoice,
            "invoice_line": invoice_line,
            "booking_settings": booking_settings,
        }

    def test_dry_run_performs_no_writes_and_creates_no_audit_operation(self):
        pending = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.subscription,
            recipient_email=self.owner.email,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_key="dry-run-pending",
        )
        session_key = self._create_session(
            user=self.owner,
            business_id=self.business.pk,
            private_value="never-render-dry-run-session-data",
        )
        initial_operations = BusinessDataOperation.objects.count()

        with CaptureQueriesContext(connection) as captured_queries:
            rendered = self._run_command()

        write_verbs = {"ALTER", "CREATE", "DELETE", "DROP", "INSERT", "REPLACE", "UPDATE"}
        executed_verbs = {
            query["sql"].lstrip().partition(" ")[0].upper()
            for query in captured_queries.captured_queries
        }
        self.assertTrue(executed_verbs.isdisjoint(write_verbs))
        self.business.refresh_from_db()
        pending.refresh_from_db()
        self.assertTrue(self.business.is_active)
        self.assertEqual(pending.status, SubscriptionNotification.Status.PENDING)
        self.assertTrue(Session.objects.filter(session_key=session_key).exists())
        self.assertEqual(BusinessDataOperation.objects.count(), initial_operations)
        self.assertIn("DRY RUN ONLY", rendered)
        self.assertIn(f"Business ID: {self.business.pk}", rendered)
        self.assertIn(f"Business slug: {self.business.slug}", rendered)
        self.assertIn("Subscription state: trialing", rendered)
        self.assertNotIn("never-render-dry-run-session-data", rendered)
        self.assertNotIn(session_key, rendered)
        self.assertNotIn(self.owner.email, rendered)

    def test_execution_requires_an_exact_numeric_confirmation(self):
        for confirmation in (None, self.other_business.pk, self.owner.email):
            with self.subTest(confirmation=confirmation):
                with self.assertRaises(CommandError):
                    self._run_command(execute=True, confirmation=confirmation)

        self.business.refresh_from_db()
        self.assertTrue(self.business.is_active)
        self.assertFalse(BusinessDataOperation.objects.exists())

    def test_exact_confirmation_deactivates_only_selected_business_and_preserves_data(self):
        records = self._create_tenant_records()
        initial_plan_values = {
            plan.pk: (plan.is_active, plan.updated_at) for plan in ClarivoPlan.objects.all()
        }
        user_count = TaskIOUser.objects.count()

        with (
            mock.patch.object(stripe_checkout, "configure_stripe_sdk") as checkout_sdk,
            mock.patch.object(stripe_portal, "configure_stripe_sdk") as portal_sdk,
        ):
            rendered = self._run_command(
                execute=True,
                confirmation=self.business.pk,
            )

        self.business.refresh_from_db()
        self.other_business.refresh_from_db()
        self.subscription.refresh_from_db()
        self.membership.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertFalse(self.business.is_active)
        self.assertTrue(self.other_business.is_active)
        self.assertTrue(self.membership.is_active)
        self.assertTrue(self.owner.is_active)
        self.assertEqual(TaskIOUser.objects.count(), user_count)
        self.assertTrue(BusinessSubscription.objects.filter(pk=self.subscription.pk).exists())
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.TRIALING)
        for record in records.values():
            self.assertTrue(record.__class__.objects.filter(pk=record.pk).exists())
        self.assertEqual(
            {plan.pk: (plan.is_active, plan.updated_at) for plan in ClarivoPlan.objects.all()},
            initial_plan_values,
        )
        checkout_sdk.assert_not_called()
        portal_sdk.assert_not_called()
        self.assertIn("was deactivated successfully", rendered)

    def test_pending_notifications_are_cancelled_and_sent_history_is_preserved(self):
        pending = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.subscription,
            recipient_email=self.owner.email,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_key="deactivation-pending",
        )
        failed = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.subscription,
            recipient_email=self.owner.email,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_ENDING_1_DAY,
            deduplication_key="deactivation-failed",
            status=SubscriptionNotification.Status.FAILED,
            last_error="Prior safe error",
        )
        sent_at = timezone.now() - timedelta(hours=1)
        sent = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.subscription,
            recipient_email=self.owner.email,
            notification_type=SubscriptionNotification.NotificationType.SUBSCRIPTION_ACTIVATED,
            deduplication_key="deactivation-sent",
            status=SubscriptionNotification.Status.SENT,
            sent_at=sent_at,
            last_error="",
        )

        result = deactivate_business(
            business_id=self.business.pk,
            reason_reference=self.reason_reference,
        )

        pending.refresh_from_db()
        failed.refresh_from_db()
        sent.refresh_from_db()
        self.assertEqual(pending.status, SubscriptionNotification.Status.CANCELLED)
        self.assertEqual(failed.status, SubscriptionNotification.Status.CANCELLED)
        self.assertEqual(sent.status, SubscriptionNotification.Status.SENT)
        self.assertEqual(sent.sent_at, sent_at)
        self.assertEqual(result.notification_count_cancelled, 2)

    def test_sessions_are_invalidated_selectively_for_sole_and_shared_users(self):
        shared_user = TaskIOUser.objects.create_user(
            email="shared-user@deactivation.example",
            password="StrongPass123!",
        )
        BusinessUser.objects.create(
            business=self.business,
            user=shared_user,
            role=BusinessUser.Role.STAFF,
        )
        BusinessUser.objects.create(
            business=self.other_business,
            user=shared_user,
            role=BusinessUser.Role.VIEWER,
        )
        sole_user_target_session = self._create_session(
            user=self.owner,
            business_id=self.business.pk,
        )
        sole_user_unscoped_session = self._create_session(user=self.owner)
        shared_user_target_session = self._create_session(
            user=shared_user,
            business_id=self.business.pk,
        )
        shared_user_other_session = self._create_session(
            user=shared_user,
            business_id=self.other_business.pk,
        )
        unrelated_user = TaskIOUser.objects.create_user(
            email="unrelated-user@deactivation.example",
            password="StrongPass123!",
        )
        unrelated_session = self._create_session(user=unrelated_user)

        result = deactivate_business(
            business_id=self.business.pk,
            reason_reference=self.reason_reference,
        )

        self.assertFalse(
            Session.objects.filter(
                session_key__in=(
                    sole_user_target_session,
                    sole_user_unscoped_session,
                    shared_user_target_session,
                )
            ).exists()
        )
        self.assertTrue(Session.objects.filter(session_key=shared_user_other_session).exists())
        self.assertTrue(Session.objects.filter(session_key=unrelated_session).exists())
        self.assertEqual(result.session_summary.sessions_to_invalidate, 3)

    def test_corrupted_sessions_are_skipped_without_warning_or_failure(self):
        corrupted_session = Session.objects.create(
            session_key="corrupted-session-for-deactivation",
            session_data="not-a-valid-signed-session",
            expire_date=timezone.now() + timedelta(days=1),
        )

        with self.assertNoLogs("django.security.SuspiciousSession", level="WARNING"):
            result = deactivate_business(
                business_id=self.business.pk,
                reason_reference=self.reason_reference,
            )

        self.assertTrue(Session.objects.filter(pk=corrupted_session.pk).exists())
        self.assertEqual(result.session_summary.corrupted_sessions_skipped, 1)

    @override_settings(SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies")
    def test_unsupported_session_backend_fails_safely_without_writes(self):
        with self.assertRaises(CommandError) as raised:
            self._run_command(
                execute=True,
                confirmation=self.business.pk,
            )

        self.business.refresh_from_db()
        self.assertTrue(self.business.is_active)
        self.assertFalse(BusinessDataOperation.objects.exists())
        self.assertIn("session_backend_unsupported", str(raised.exception))

    def test_inactive_business_is_blocked_from_workspace_roles_and_tenant_routes(self):
        UserOnboardingState.objects.create(user=self.owner, business=self.business)
        self.business.is_active = False
        self.business.save(update_fields=["is_active", "updated_at"])
        role_routes = (
            "agent_dashboard",
            "staff_client_list",
            "staff_lead_create",
            "invoice_list",
            "invoice_create",
            "appointment_list",
            "appointment_create",
            "business_settings",
        )

        for role in BusinessUser.Role.values:
            user = TaskIOUser.objects.create_user(
                email=f"{role}@inactive-access.example",
                password="StrongPass123!",
            )
            BusinessUser.objects.create(business=self.business, user=user, role=role)
            client = DjangoClient()
            client.force_login(user)
            for route_name in role_routes:
                with self.subTest(role=role, route=route_name):
                    response = client.get(reverse(route_name))
                    self.assertNotEqual(response.status_code, 200)

        before = UserOnboardingState.objects.get(user=self.owner, business=self.business)
        client = DjangoClient()
        client.force_login(self.owner)
        response = client.post(
            reverse("agent_dashboard"),
            {"onboarding_action": "dismiss_welcome"},
        )
        self.assertNotEqual(response.status_code, 200)
        before.refresh_from_db()
        self.assertIsNone(before.dismissed_at)

    def test_inactive_business_rejects_public_submissions_and_invitation_acceptance(self):
        invitation = BusinessInvitation.objects.create(
            business=self.business,
            email="invitee@inactive.example",
            role=BusinessUser.Role.STAFF,
            token="inactive-business-invitation",
        )
        self.business.is_active = False
        self.business.save(update_fields=["is_active", "updated_at"])
        lead_count = Lead.objects.count()
        appointment_count = Appointment.objects.count()

        public_request_response = self.client.post(
            reverse("public_request", args=[self.business.slug]),
            {},
        )
        public_booking_response = self.client.post(
            reverse("public_booking", args=[self.business.slug]),
            {},
        )
        invitation_response = self.client.post(
            reverse("accept_business_invitation", args=[invitation.token]),
            {},
        )

        self.assertEqual(public_request_response.status_code, 404)
        self.assertEqual(public_booking_response.status_code, 404)
        self.assertEqual(invitation_response.status_code, 302)
        self.assertEqual(Lead.objects.count(), lead_count)
        self.assertEqual(Appointment.objects.count(), appointment_count)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, BusinessInvitation.Status.PENDING)

    def test_inactive_business_cannot_open_checkout_or_portal_sessions(self):
        self.business.is_active = False
        self.business.save(update_fields=["is_active", "updated_at"])
        self.subscription.status = BusinessSubscription.Status.PENDING_CHECKOUT
        self.subscription.payment_provider = BusinessSubscription.PaymentProvider.STRIPE
        self.subscription.billing_interval = BusinessSubscription.BillingInterval.MONTHLY
        self.subscription.billing_currency = BusinessSubscription.BillingCurrency.USD
        self.subscription.provider_customer_id = "cus_private_deactivation"
        self.subscription.provider_subscription_id = "sub_private_deactivation"
        self.subscription.save()

        with mock.patch.object(stripe_checkout, "configure_stripe_sdk") as checkout_sdk:
            with self.assertRaises(StripeCheckoutError):
                resume_trial_checkout_session(
                    request=RequestFactory().post("/billing/checkout/resume/"),
                    subscription=self.subscription,
                    user=self.owner,
                )
        with mock.patch.object(stripe_portal, "configure_stripe_sdk") as portal_sdk:
            with self.assertRaises(StripeCustomerPortalError):
                create_customer_portal_session(
                    request=RequestFactory().post("/billing/portal/"),
                    business=self.business,
                    user=self.owner,
                    subscription=self.subscription,
                )

        checkout_sdk.assert_not_called()
        portal_sdk.assert_not_called()

    def test_background_notification_generation_and_delivery_skip_inactive_business(self):
        self.business.is_active = False
        self.business.save(update_fields=["is_active", "updated_at"])
        self.subscription.payment_provider = BusinessSubscription.PaymentProvider.STRIPE
        self.subscription.save(update_fields=["payment_provider", "updated_at"])

        generated = enqueue_subscription_notification(
            subscription=self.subscription,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_context="inactive-generation",
        )
        pending = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.subscription,
            recipient_email=self.owner.email,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_key="inactive-delivery",
        )
        with mock.patch("apps.notifications.emails.send_templated_email") as send_email:
            delivery = deliver_subscription_notification(pending)

        self.assertEqual(generated, [])
        self.assertEqual(delivery.status, "cancelled")
        send_email.assert_not_called()

    def test_repeated_deactivation_is_a_noop_without_duplicate_side_effects(self):
        session_key = self._create_session(
            user=self.owner,
            business_id=self.business.pk,
        )
        first = deactivate_business(
            business_id=self.business.pk,
            reason_reference=self.reason_reference,
        )
        operation_count = BusinessDataOperation.objects.count()

        second = deactivate_business(
            business_id=self.business.pk,
            reason_reference=self.reason_reference,
        )

        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertIsNone(second.audit_operation_id)
        self.assertEqual(BusinessDataOperation.objects.count(), operation_count)
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())

    def test_completed_audit_contains_only_snapshot_ids_and_non_pii_counts(self):
        session_key = self._create_session(
            user=self.owner,
            business_id=self.business.pk,
            private_value="private-session-payload",
        )
        self.subscription.provider_customer_id = "cus_private_audit"
        self.subscription.provider_subscription_id = "sub_private_audit"
        self.subscription.save(
            update_fields=[
                "provider_customer_id",
                "provider_subscription_id",
                "updated_at",
            ]
        )

        result = deactivate_business(
            business_id=self.business.pk,
            reason_reference=self.reason_reference,
            operator_id=self.owner.pk,
        )

        operation = BusinessDataOperation.objects.get(operation_id=result.audit_operation_id)
        serialized_metadata = json.dumps(
            {
                "business_id_snapshot": operation.business_id_snapshot,
                "operator_id_snapshot": operation.operator_id_snapshot,
                "reason_reference": operation.reason_reference,
                "record_counts": operation.record_counts,
                "error_code": operation.error_code,
            },
            sort_keys=True,
        )
        self.assertEqual(operation.status, BusinessDataOperation.Status.COMPLETED)
        self.assertIsNotNone(operation.completed_at)
        self.assertEqual(operation.business_id_snapshot, self.business.pk)
        self.assertEqual(operation.operator_id_snapshot, self.owner.pk)
        self.assertTrue(operation.record_counts)
        for private_value in (
            self.business.name,
            self.business.email,
            self.owner.email,
            session_key,
            "private-session-payload",
            "cus_private_audit",
            "sub_private_audit",
        ):
            with self.subTest(private_value=private_value):
                self.assertNotIn(private_value, serialized_metadata)

    def test_failure_after_state_change_rolls_back_and_records_safe_error_code(self):
        pending = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.subscription,
            recipient_email=self.owner.email,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_key="rollback-pending",
        )
        session_key = self._create_session(
            user=self.owner,
            business_id=self.business.pk,
        )

        with mock.patch(
            "apps.businesses.business_data_operations._complete_operation",
            side_effect=RuntimeError("private injected failure detail"),
        ):
            with self.assertRaises(BusinessDeactivationError) as raised:
                deactivate_business(
                    business_id=self.business.pk,
                    reason_reference=self.reason_reference,
                )

        self.assertEqual(raised.exception.error_code, "deactivation_failed")
        self.business.refresh_from_db()
        pending.refresh_from_db()
        self.assertTrue(self.business.is_active)
        self.assertEqual(pending.status, SubscriptionNotification.Status.PENDING)
        self.assertTrue(Session.objects.filter(session_key=session_key).exists())
        operation = BusinessDataOperation.objects.get()
        self.assertEqual(operation.status, BusinessDataOperation.Status.FAILED)
        self.assertIsNotNone(operation.completed_at)
        self.assertEqual(operation.error_code, "deactivation_failed")
        self.assertEqual(operation.record_counts, {})
        self.assertNotIn("private injected failure detail", operation.error_code)


class BusinessPurgeTests(TestCase):
    reason_reference = "TEST-PURGE-001"

    def setUp(self):
        self.plan = ClarivoPlan.objects.get(slug="pro")
        self.business = Business.objects.create(
            name="Private Purge Workspace",
            slug="private-purge-workspace",
            email="private-business@purge.example",
            is_active=False,
        )
        self.other_business = Business.objects.create(
            name="Other Untouched Workspace",
            slug="other-untouched-workspace",
        )
        now = timezone.now()
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.TRIALING,
            trial_start=now,
            trial_end=now + timedelta(days=14),
            current_period_start=now,
            current_period_end=now + timedelta(days=14),
        )
        self.owner = TaskIOUser.objects.create_user(
            email="private-owner@purge.example",
            password="StrongPass123!",
        )
        BusinessUser.objects.create(
            business=self.business,
            user=self.owner,
            role=BusinessUser.Role.OWNER,
        )

    def _run_command(
        self,
        *,
        execute=False,
        confirmation=None,
        reason_reference=None,
        confirm_test_financial_data=False,
        delete_eligible_users=False,
        business_id=None,
    ):
        output = StringIO()
        options = {
            "business_id": business_id or self.business.pk,
            "execute": execute,
            "confirm_test_financial_data": confirm_test_financial_data,
            "delete_eligible_users": delete_eligible_users,
            "stdout": output,
        }
        if confirmation is not None:
            options["confirm_business_id"] = confirmation
        if reason_reference is not None:
            options["reason_reference"] = reason_reference
        call_command("purge_business", **options)
        return output.getvalue()

    @staticmethod
    def _create_session(*, user=None, business_id=None, private_value=""):
        client = DjangoClient()
        if user is not None:
            client.force_login(user)
        session = client.session
        if business_id is not None:
            session[CURRENT_BUSINESS_SESSION_KEY] = business_id
        if private_value:
            session["private_test_value"] = private_value
        session.save()
        return session.session_key

    def _create_tenant_graph(self):
        category = ServiceCategory.objects.create(
            business=self.business,
            name="Private Purge Category",
        )
        service = BusinessService.objects.create(
            business=self.business,
            category=category,
            name="Private Purge Service",
            unit_price=Decimal("80.00"),
        )
        lead = Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            first_name="Private",
            last_name="Lead",
            email="private-lead@purge.example",
            phone="+1 721 555 0200",
            company_name="Private Lead Company",
            category=category,
            requested_service=service,
        )
        client = Client.objects.create(
            business=self.business,
            first_name="Private",
            last_name="Client",
            email="private-client@purge.example",
            phone="+1 721 555 0201",
            company_name="Private Client Company",
            street_address="1 Purge Street",
            assigned_to=self.owner,
        )
        activity = ActivityLog.objects.create(
            business=self.business,
            actor=self.owner,
            lead=lead,
            client=client,
            action_type=ActivityLog.ActionType.STATUS_CHANGED,
        )
        now = timezone.now()
        appointment = Appointment.objects.create(
            business=self.business,
            client=client,
            service=service,
            source_lead=lead,
            title="Private purge appointment",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
        )
        invoice = Invoice.objects.create(
            business=self.business,
            client=client,
            appointment=appointment,
            invoice_number="INV-PURGE-1",
        )
        invoice_line = InvoiceLine.objects.create(
            invoice=invoice,
            service=service,
            description="Private purge line",
            quantity=1,
            unit_price=Decimal("80.00"),
        )
        booking_settings = BusinessBookingSettings.objects.create(
            business=self.business,
            booking_enabled=True,
        )
        availability = WeeklyAvailability.objects.create(
            business=self.business,
            day_of_week=WeeklyAvailability.DayOfWeek.MONDAY,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        invitation = BusinessInvitation.objects.create(
            business=self.business,
            email="private-invitee@purge.example",
            role=BusinessUser.Role.STAFF,
            token="private-purge-invitation-token",
        )
        onboarding = UserOnboardingState.objects.create(
            business=self.business,
            user=self.owner,
        )
        notification = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.subscription,
            recipient_email=self.owner.email,
            notification_type=SubscriptionNotification.NotificationType.TRIAL_STARTED,
            deduplication_key="private-purge-notification",
        )
        return {
            "category": category,
            "service": service,
            "lead": lead,
            "client": client,
            "activity": activity,
            "appointment": appointment,
            "invoice": invoice,
            "invoice_line": invoice_line,
            "booking_settings": booking_settings,
            "availability": availability,
            "invitation": invitation,
            "onboarding": onboarding,
            "notification": notification,
        }

    def test_dry_run_makes_no_changes_or_audit_writes(self):
        records = self._create_tenant_graph()
        session_key = self._create_session(
            user=self.owner,
            business_id=self.business.pk,
            private_value="never-render-purge-session",
        )

        with CaptureQueriesContext(connection) as captured_queries:
            rendered = self._run_command()

        write_verbs = {"ALTER", "CREATE", "DELETE", "DROP", "INSERT", "REPLACE", "UPDATE"}
        executed_verbs = {
            query["sql"].lstrip().partition(" ")[0].upper()
            for query in captured_queries.captured_queries
        }
        self.assertTrue(executed_verbs.isdisjoint(write_verbs))
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())
        for record in records.values():
            self.assertTrue(record.__class__.objects.filter(pk=record.pk).exists())
        self.assertTrue(Session.objects.filter(session_key=session_key).exists())
        self.assertFalse(BusinessDataOperation.objects.exists())
        self.assertIn("DRY RUN ONLY", rendered)
        self.assertIn("WARNING: invoices and invoice lines", rendered)
        self.assertNotIn("never-render-purge-session", rendered)
        self.assertNotIn(session_key, rendered)

    def test_active_business_and_confirmation_mismatch_are_rejected(self):
        with self.assertRaises(CommandError):
            self._run_command(
                execute=True,
                reason_reference=self.reason_reference,
            )
        with self.assertRaises(CommandError):
            self._run_command(
                execute=True,
                confirmation=self.business.pk,
            )
        with self.assertRaises(CommandError):
            self._run_command(
                execute=True,
                confirmation=self.other_business.pk,
                reason_reference=self.reason_reference,
            )
        self.assertFalse(BusinessDataOperation.objects.exists())

        self.business.is_active = True
        self.business.save(update_fields=["is_active", "updated_at"])
        with self.assertRaises(CommandError) as raised:
            self._run_command(
                execute=True,
                confirmation=self.business.pk,
                reason_reference=self.reason_reference,
            )

        self.assertIn("business_active", str(raised.exception))
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())
        operation = BusinessDataOperation.objects.get()
        self.assertEqual(operation.status, BusinessDataOperation.Status.FAILED)
        self.assertEqual(operation.error_code, "business_active")

    def test_cross_tenant_integrity_blockers_prevent_purge(self):
        selected_client = Client.objects.create(
            business=self.business,
            first_name="Selected",
            last_name="Client",
            email="selected-client@purge.example",
            phone="",
            company_name="Selected",
            street_address="",
        )
        other_client = Client.objects.create(
            business=self.other_business,
            first_name="Other",
            last_name="Client",
            email="other-client@purge.example",
            phone="",
            company_name="Other",
            street_address="",
        )
        now = timezone.now()
        other_appointment = Appointment.objects.create(
            business=self.other_business,
            client=other_client,
            title="Other appointment",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
        )
        Appointment.objects.filter(pk=other_appointment.pk).update(client_id=selected_client.pk)

        with self.assertRaises(BusinessPurgeError) as raised:
            purge_business(
                business_id=self.business.pk,
                reason_reference=self.reason_reference,
            )

        self.assertEqual(raised.exception.error_code, "cross_tenant_integrity_blockers")
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())
        self.assertTrue(Client.objects.filter(pk=selected_client.pk).exists())

    def test_stripe_identifiers_and_correlated_webhooks_prevent_purge_without_api_calls(self):
        with mock.patch.object(stripe_checkout, "configure_stripe_sdk") as checkout_sdk:
            self.subscription.provider_customer_id = "cus_private_purge"
            self.subscription.save(update_fields=["provider_customer_id", "updated_at"])
            with self.assertRaises(BusinessPurgeError) as identifier_error:
                purge_business(
                    business_id=self.business.pk,
                    reason_reference=self.reason_reference,
                )
            self.assertEqual(identifier_error.exception.error_code, "stripe_references_present")
            self.subscription.provider_customer_id = ""
            self.subscription.save(update_fields=["provider_customer_id", "updated_at"])

            BillingProviderWebhookEvent.objects.create(
                event_id="evt_private_purge",
                event_type="customer.subscription.updated",
                payload_summary={"motionmate_business_id": str(self.business.pk)},
            )
            with self.assertRaises(BusinessPurgeError) as webhook_error:
                purge_business(
                    business_id=self.business.pk,
                    reason_reference=self.reason_reference,
                )

        self.assertEqual(webhook_error.exception.error_code, "stripe_references_present")
        checkout_sdk.assert_not_called()
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())

    def test_invoices_require_explicit_test_financial_data_confirmation(self):
        records = self._create_tenant_graph()

        with self.assertRaises(BusinessPurgeError) as raised:
            purge_business(
                business_id=self.business.pk,
                reason_reference=self.reason_reference,
            )

        self.assertEqual(
            raised.exception.error_code,
            "test_financial_data_confirmation_required",
        )
        self.assertTrue(Invoice.objects.filter(pk=records["invoice"].pk).exists())
        self.assertTrue(InvoiceLine.objects.filter(pk=records["invoice_line"].pk).exists())

    def test_confirmed_purge_explicitly_removes_all_tenant_records_and_preserves_shared_data(self):
        records = self._create_tenant_graph()
        business_id = self.business.pk
        plan_count = ClarivoPlan.objects.count()
        plan_updated_at = self.plan.updated_at
        other_client = Client.objects.create(
            business=self.other_business,
            first_name="Other",
            last_name="Preserved",
            email="other-preserved@purge.example",
            phone="",
            company_name="Other",
            street_address="",
        )
        target_session = self._create_session(
            user=self.owner,
            business_id=business_id,
        )
        other_session = self._create_session(business_id=self.other_business.pk)
        corrupted = Session.objects.create(
            session_key="corrupted-purge-session",
            session_data="undecodable-purge-data",
            expire_date=timezone.now() + timedelta(days=1),
        )

        with (
            self.assertNoLogs("django.security.SuspiciousSession", level="WARNING"),
            mock.patch.object(stripe_checkout, "configure_stripe_sdk") as checkout_sdk,
            mock.patch.object(stripe_portal, "configure_stripe_sdk") as portal_sdk,
        ):
            result = purge_business(
                business_id=business_id,
                reason_reference=self.reason_reference,
                confirm_test_financial_data=True,
            )

        self.assertTrue(result.purged)
        self.assertFalse(Business.objects.filter(pk=business_id).exists())
        self.assertFalse(Invoice.objects.filter(pk=records["invoice"].pk).exists())
        self.assertFalse(InvoiceLine.objects.filter(pk=records["invoice_line"].pk).exists())
        for model in (
            Appointment,
            ActivityLog,
            Lead,
            Client,
            BusinessService,
            ServiceCategory,
            BusinessInvitation,
            UserOnboardingState,
            WeeklyAvailability,
            SubscriptionNotification,
            BusinessSubscription,
            BusinessBookingSettings,
            BusinessUser,
        ):
            self.assertFalse(model.objects.filter(business_id=business_id).exists())
        self.assertTrue(TaskIOUser.objects.filter(pk=self.owner.pk).exists())
        self.assertEqual(ClarivoPlan.objects.count(), plan_count)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.updated_at, plan_updated_at)
        self.assertTrue(Business.objects.filter(pk=self.other_business.pk).exists())
        self.assertTrue(Client.objects.filter(pk=other_client.pk).exists())
        self.assertFalse(Session.objects.filter(session_key=target_session).exists())
        self.assertTrue(Session.objects.filter(session_key=other_session).exists())
        self.assertTrue(Session.objects.filter(pk=corrupted.pk).exists())
        checkout_sdk.assert_not_called()
        portal_sdk.assert_not_called()
        self.assertEqual(result.deletion_counts["invoices"], 1)
        self.assertEqual(result.deletion_counts["invoice_lines"], 1)
        self.assertEqual(result.deletion_counts["service_categories"], 1)

    def test_delete_eligible_users_is_opt_in_and_preserves_protected_users(self):
        eligible_user = TaskIOUser.objects.create_user(
            email="eligible-user@purge.example",
            password="StrongPass123!",
        )
        operator_user = TaskIOUser.objects.create_user(
            email="operator-user@purge.example",
            password="StrongPass123!",
        )
        shared_user = TaskIOUser.objects.create_user(
            email="shared-user@purge.example",
            password="StrongPass123!",
        )
        staff_user = TaskIOUser.objects.create_user(
            email="staff-user@purge.example",
            password="StrongPass123!",
            is_staff=True,
        )
        superuser = TaskIOUser.objects.create_superuser(
            email="superuser@purge.example",
            password="StrongPass123!",
        )
        for user in (eligible_user, operator_user, shared_user, staff_user, superuser):
            BusinessUser.objects.create(
                business=self.business,
                user=user,
                role=BusinessUser.Role.STAFF,
            )
        BusinessUser.objects.create(
            business=self.other_business,
            user=shared_user,
            role=BusinessUser.Role.VIEWER,
            is_active=False,
        )

        result = purge_business(
            business_id=self.business.pk,
            reason_reference=self.reason_reference,
            delete_eligible_users=True,
            operator_id=operator_user.pk,
        )

        self.assertFalse(TaskIOUser.objects.filter(pk=eligible_user.pk).exists())
        self.assertFalse(TaskIOUser.objects.filter(pk=self.owner.pk).exists())
        for user in (operator_user, shared_user, staff_user, superuser):
            self.assertTrue(TaskIOUser.objects.filter(pk=user.pk).exists())
        decisions = {decision.user_id: decision for decision in result.user_decisions}
        self.assertIn("command_operator", decisions[operator_user.pk].reason_codes)
        self.assertIn("other_memberships", decisions[shared_user.pk].reason_codes)
        self.assertIn("staff_user", decisions[staff_user.pk].reason_codes)
        self.assertIn("superuser", decisions[superuser.pk].reason_codes)

    def test_failure_after_deletions_rolls_back_everything_and_marks_audit_failed(self):
        records = self._create_tenant_graph()
        session_key = self._create_session(
            user=self.owner,
            business_id=self.business.pk,
        )

        with mock.patch(
            "apps.businesses.business_data_purge._verify_purge_complete",
            side_effect=RuntimeError("private injected purge failure"),
        ):
            with self.assertRaises(BusinessPurgeError) as raised:
                purge_business(
                    business_id=self.business.pk,
                    reason_reference=self.reason_reference,
                    confirm_test_financial_data=True,
                )

        self.assertEqual(raised.exception.error_code, "purge_failed")
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())
        for record in records.values():
            self.assertTrue(record.__class__.objects.filter(pk=record.pk).exists())
        self.assertTrue(Session.objects.filter(session_key=session_key).exists())
        operation = BusinessDataOperation.objects.get()
        self.assertEqual(operation.mode, BusinessDataOperation.Mode.PURGE)
        self.assertEqual(operation.status, BusinessDataOperation.Status.FAILED)
        self.assertEqual(operation.error_code, "purge_failed")
        self.assertNotIn("private injected purge failure", operation.error_code)

    def test_completed_audit_survives_without_pii_and_missing_target_is_idempotent(self):
        records = self._create_tenant_graph()
        business_id = self.business.pk
        private_session = self._create_session(
            user=self.owner,
            business_id=business_id,
            private_value="private-purge-session-payload",
        )

        result = purge_business(
            business_id=business_id,
            reason_reference=self.reason_reference,
            confirm_test_financial_data=True,
        )

        operation = BusinessDataOperation.objects.get(operation_id=result.audit_operation_id)
        self.assertEqual(operation.mode, BusinessDataOperation.Mode.PURGE)
        self.assertEqual(operation.status, BusinessDataOperation.Status.COMPLETED)
        self.assertIsNotNone(operation.completed_at)
        metadata = json.dumps(operation.record_counts, sort_keys=True)
        for private_value in (
            self.business.name,
            self.business.email,
            self.owner.email,
            records["client"].email,
            private_session,
            "private-purge-session-payload",
        ):
            with self.subTest(private_value=private_value):
                self.assertNotIn(private_value, metadata)

        operation_count = BusinessDataOperation.objects.count()
        rendered = self._run_command(
            execute=True,
            confirmation=business_id,
            reason_reference=self.reason_reference,
            confirm_test_financial_data=True,
            business_id=business_id,
        )
        self.assertIn("not found or has already been purged", rendered)
        self.assertEqual(BusinessDataOperation.objects.count(), operation_count)
