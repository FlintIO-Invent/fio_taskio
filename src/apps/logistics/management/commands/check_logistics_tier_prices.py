"""Opt-in, read-only validation of staged Logistics tier Prices."""

from django.core.management.base import BaseCommand, CommandError

from apps.businesses.stripe_config import StripeConfigurationError, configure_stripe_sdk
from apps.logistics.stripe_prices import configured_tier_prices, validate_tier_stripe_price


class Command(BaseCommand):
    help = "Validate staged annual EUR tier Prices; never enables checkout or changes records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--verify-provider", action="store_true", help="Retrieve Prices from Stripe."
        )

    def handle(self, *args, **options):
        try:
            prices = configured_tier_prices()
            if options["verify_provider"]:
                sdk = configure_stripe_sdk()
                for slug, _, _ in prices:
                    validate_tier_stripe_price(plan_slug=slug, stripe_client=sdk)
        except StripeConfigurationError as exc:
            raise CommandError(f"{exc.code}: {exc}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                "Tier Price configuration valid; "
                + (
                    "provider Prices verified. "
                    if options["verify_provider"]
                    else "provider not contacted. "
                )
                + "Checkout eligibility is checked separately."
            )
        )
