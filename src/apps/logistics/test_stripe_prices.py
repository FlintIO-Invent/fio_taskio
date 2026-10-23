"""E3 configuration only. Every provider operation is mocked."""

from copy import deepcopy
from io import StringIO
from unittest import mock

import stripe
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from pydantic import ValidationError

from apps.businesses.billing_policy import BILLABLE_PLAN_SLUGS, billing_offering
from apps.businesses.stripe_config import (
    StripeConfigurationError,
    get_stripe_price_id,
    resolve_stripe_price_id,
    validate_stripe_configuration,
)
from apps.businesses.test_logistics_billing import stripe_settings
from config import Settings

from .stripe_prices import TIER_YEARLY_EUR_CENTS, configured_tier_prices, validate_tier_stripe_price


def tier_map():
    return {(slug, "yearly", "eur"): f"price_{slug}" for slug in TIER_YEARLY_EUR_CENTS}


def provider_price(slug="logistics-core", **changes):
    price = {
        "id": f"price_{slug}",
        "active": True,
        "livemode": False,
        "currency": "eur",
        "type": "recurring",
        "billing_scheme": "per_unit",
        "unit_amount": TIER_YEARLY_EUR_CENTS[slug],
        "recurring": {"interval": "year", "interval_count": 1, "usage_type": "licensed"},
        "metadata": {},
    }
    price.update(changes)
    return price


@override_settings(
    **stripe_settings(),
    MOTIONMATE_ENVIRONMENT="local",
    STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=tier_map(),
)
class TierPriceTests(SimpleTestCase):
    def verify(self, price=None, slug="logistics-core"):
        sdk = mock.Mock()
        sdk.Price.retrieve.return_value = provider_price(slug) if price is None else price
        result = validate_tier_stripe_price(plan_slug=slug, stripe_client=sdk)
        sdk.Price.retrieve.assert_called_once_with(f"price_{slug}")
        sdk.Price.create.assert_not_called()
        sdk.Product.create.assert_not_called()
        sdk.Subscription.create.assert_not_called()
        sdk.checkout.Session.create.assert_not_called()
        return result

    def test_typed_settings_normalize_three_annual_eur_fields_only(self):
        names = [
            f"stripe_price_{slug.replace('-', '_')}_yearly_eur" for slug in TIER_YEARLY_EUR_CENTS
        ]
        config = Settings(_env_file=None, **dict.fromkeys(names, " price_test "))
        for name in names:
            self.assertEqual(getattr(config, name), "price_test")
            self.assertNotIn(name.replace("_eur", "_usd"), Settings.model_fields)
            self.assertNotIn(name.replace("_yearly", "_monthly"), Settings.model_fields)
        self.assertEqual(getattr(Settings(_env_file=None, **{names[0]: None}), names[0]), "")
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, **{names[0]: 123})
        self.assertEqual(set(settings.STRIPE_LOGISTICS_TIER_PRICE_ID_MAP), set(tier_map()))

    def test_all_three_prices_match_approved_amounts_and_hyphenated_tiers(self):
        self.assertEqual(
            TIER_YEARLY_EUR_CENTS,
            {
                "logistics-core": 170000,
                "logistics-growth": 230000,
                "logistics-scale": 300000,
            },
        )
        for slug in TIER_YEARLY_EUR_CENTS:
            self.assertEqual(self.verify(slug=slug), f"price_{slug}")
        self.assertEqual(
            self.verify(stripe.Price.construct_from(provider_price(), "sk_test_mock")),
            "price_logistics-core",
        )

    def test_all_tiers_ignore_absent_or_conflicting_price_metadata(self):
        for slug in TIER_YEARLY_EUR_CENTS:
            for metadata in ({}, None, {"motionmate_plan_slug": "logistics"}):
                with self.subTest(slug=slug, metadata=metadata):
                    self.assertEqual(
                        self.verify(provider_price(slug, metadata=metadata), slug), f"price_{slug}"
                    )
            price = provider_price(slug)
            price.pop("metadata")
            self.assertEqual(self.verify(price, slug), f"price_{slug}")

    def test_missing_invalid_duplicate_and_foreign_dimension_maps_reject(self):
        core = ("logistics-core", "yearly", "eur")
        cases = [None, {}, {core: "price_one"}]
        for value in ("", None, "prod_wrong", "price_", 123):
            cases.append({**tier_map(), core: value})
        cases.extend(
            [
                {**tier_map(), core: "price_logistics-growth"},
                {**tier_map(), core: "price_pro_yearly_eur"},
                {**tier_map(), ("logistics-core", "yearly", "usd"): "price_usd"},
                {**tier_map(), ("logistics-core", "monthly", "eur"): "price_monthly"},
                {**tier_map(), ("unknown", "yearly", "eur"): "price_unknown"},
            ]
        )
        for values in cases:
            with (
                self.subTest(values=values),
                override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=values),
            ):
                with self.assertRaises(StripeConfigurationError):
                    configured_tier_prices()

    def test_inactive_wrong_amount_tier_currency_interval_and_malformed_prices_reject(self):
        cases = [
            {"id": "price_wrong"},
            {"active": False},
            {"active": None},
            {"unit_amount": 170001},
            {"unit_amount": "170000"},
            {"unit_amount": 0},
            {"unit_amount": None},
            {"unit_amount": True},
            {"currency": "usd"},
            {"type": "one_time"},
            {"billing_scheme": "tiered"},
            {"recurring": None},
        ]
        for field, value in (
            ("interval", "month"),
            ("interval_count", 2),
            ("interval_count", True),
            ("usage_type", "metered"),
        ):
            recurring = deepcopy(provider_price()["recurring"])
            recurring[field] = value
            cases.append({"recurring": recurring})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(StripeConfigurationError):
                self.verify(provider_price(**changes))
        with self.assertRaises(StripeConfigurationError):
            self.verify([])

    def test_mode_isolation_and_nonproduction_live_key_block(self):
        with self.assertRaises(StripeConfigurationError):
            self.verify(provider_price(livemode=True))
        with override_settings(
            STRIPE_PUBLISHABLE_KEY="pk_live_test", STRIPE_SECRET_KEY="sk_live_test"
        ):
            for environment in ("local", "development", "staging", "unknown"):
                sdk = mock.Mock()
                with override_settings(MOTIONMATE_ENVIRONMENT=environment):
                    with self.assertRaises(StripeConfigurationError):
                        validate_tier_stripe_price(plan_slug="logistics-core", stripe_client=sdk)
                sdk.Price.retrieve.assert_not_called()
            with override_settings(MOTIONMATE_ENVIRONMENT="production"):
                with self.assertRaises(StripeConfigurationError):
                    self.verify(provider_price(livemode=False))
                self.assertEqual(self.verify(provider_price(livemode=True)), "price_logistics-core")
        for overrides in (
            {"STRIPE_SECRET_KEY": "sk_live_mixed"},
            {"STRIPE_SECRET_KEY": ""},
            {"STRIPE_ENABLED": False},
        ):
            with override_settings(**overrides), self.assertRaises(StripeConfigurationError):
                self.verify()

    def test_usd_monthly_legacy_and_service_not_accepted_by_tier_validator(self):
        for changes in (
            {"currency": "usd"},
            {"billing_interval": "monthly"},
            {"plan_slug": "logistics"},
            {"plan_slug": "pro"},
        ):
            sdk = mock.Mock()
            with self.assertRaises(StripeConfigurationError):
                validate_tier_stripe_price(
                    **{"plan_slug": "logistics-core", **changes}, stripe_client=sdk
                )
            sdk.Price.retrieve.assert_not_called()

    def test_provider_failure_is_sanitized(self):
        sdk = mock.Mock()
        sdk.Price.retrieve.side_effect = RuntimeError("secret provider response")
        with self.assertRaises(StripeConfigurationError) as raised:
            validate_tier_stripe_price(plan_slug="logistics-core", stripe_client=sdk)
        self.assertNotIn("secret provider response", str(raised.exception))

    def test_command_is_static_by_default_and_provider_verification_only_retrieves(self):
        out = StringIO()
        with mock.patch(
            "apps.logistics.management.commands.check_logistics_tier_prices.configure_stripe_sdk"
        ) as configure:
            call_command("check_logistics_tier_prices", stdout=out)
            configure.assert_not_called()
            self.assertIn("provider not contacted", out.getvalue())
            sdk = configure.return_value
            sdk.Price.retrieve.side_effect = lambda price_id: provider_price(
                price_id.removeprefix("price_")
            )
            call_command("check_logistics_tier_prices", verify_provider=True, stdout=out)
            self.assertEqual(sdk.Price.retrieve.call_count, 3)
            sdk.Price.create.assert_not_called()
            sdk.Subscription.create.assert_not_called()
            sdk.checkout.Session.create.assert_not_called()
        with override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP={}):
            with self.assertRaises(CommandError):
                call_command("check_logistics_tier_prices", stdout=StringIO())

    def test_test_resolution_is_separate_from_legacy_service_configuration(self):
        self.assertEqual(validate_stripe_configuration(), [])
        for slug in TIER_YEARLY_EUR_CENTS:
            self.assertNotIn(slug, BILLABLE_PLAN_SLUGS)
            self.assertFalse(billing_offering(slug).checkout_enabled)
            self.assertTrue(billing_offering(slug).test_checkout_enabled)
            self.assertEqual(
                get_stripe_price_id(plan_slug=slug, billing_interval="yearly", currency="eur"),
                f"price_{slug}",
            )
            self.assertEqual(resolve_stripe_price_id(f"price_{slug}").plan_slug, slug)
        for slug in ("logistics", "pro"):
            price_id = get_stripe_price_id(
                plan_slug=slug, billing_interval="yearly", currency="eur"
            )
            self.assertEqual(resolve_stripe_price_id(price_id).plan_slug, slug)
        with override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP={}):
            self.assertEqual(validate_stripe_configuration(), [])

    def test_tier_price_resolution_normalizes_configured_whitespace(self):
        with override_settings(
            STRIPE_LOGISTICS_TIER_PRICE_ID_MAP={
                key: f" {value} " for key, value in tier_map().items()
            }
        ):
            price_id = get_stripe_price_id(
                plan_slug="logistics-core", billing_interval="yearly", currency="eur"
            )
            self.assertEqual(resolve_stripe_price_id(price_id).plan_slug, "logistics-core")
