"""Read-only readiness checks using the same validators as annual checkout."""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.businesses.models import BusinessSubscription
from apps.businesses.stripe_checkout import StripeCheckoutError
from apps.businesses.stripe_config import (
    StripeConfigurationError,
    configure_stripe_sdk,
    is_stripe_enabled,
    validate_stripe_configuration,
)
from apps.logistics.billing import (
    configured_annual_price,
    require_checkout_enrollment,
    validate_annual_stripe_price,
)
from apps.logistics.models import LogisticsApplication


class Command(BaseCommand):
    help = "Check an existing Logistics enrollment without creating checkout or changing records."

    def add_arguments(self, parser):
        parser.add_argument("--application-id", type=UUID, required=True)
        parser.add_argument(
            "--verify-provider",
            action="store_true",
            help="Also retrieve annual Prices from Stripe; never creates a session or payment.",
        )

    def handle(self, *args, **options):
        # Disabled Stripe is intentional for unrelated development. This command
        # explicitly diagnoses real billing, so report it even when checks skip it.
        failures = []
        if not is_stripe_enabled():
            failures.append(("stripe_disabled", "Set STRIPE_ENABLED=true for real checkout."))
        failures.extend((issue.id, issue.message) for issue in validate_stripe_configuration())
        application = (
            LogisticsApplication.objects.select_related("enrolled_user")
            .filter(pk=options["application_id"])
            .first()
        )
        if application is None:
            raise CommandError("logistics_application_invalid: Application not found.")
        subscription = (
            BusinessSubscription.objects.select_related("business", "plan")
            .filter(business_id=application.business_id)
            .first()
        )
        if subscription is None:
            raise CommandError("logistics_subscription_not_eligible: No enrolled subscription.")
        self.stdout.write(
            f"application={application.pk} business={subscription.business_id} "
            f"subscription={subscription.pk} status={subscription.status} "
            f"interval={subscription.billing_interval} currency={subscription.billing_currency}"
        )
        try:
            require_checkout_enrollment(subscription, application.enrolled_user)
        except (StripeCheckoutError, StripeConfigurationError) as exc:
            failures.append((exc.code, str(exc)))
        # Verify both requested currencies, independent of the enrolled currency.
        for currency in ("eur", "usd"):
            try:
                configured_annual_price(subscription.plan, currency)
            except StripeConfigurationError as exc:
                failures.append((exc.code, str(exc)))
        if not failures and options["verify_provider"]:
            try:
                sdk = configure_stripe_sdk()
                for currency in ("eur", "usd"):
                    validate_annual_stripe_price(
                        plan=subscription.plan, currency=currency, stripe_client=sdk
                    )
            except StripeConfigurationError as exc:
                failures.append((exc.code, str(exc)))
        for code, message in dict.fromkeys(failures):
            self.stderr.write(f"{code}: {message}")
        if failures:
            raise CommandError("Logistics checkout is not ready; no records changed.")
        self.stdout.write(
            self.style.SUCCESS(
                "Logistics checkout is ready"
                + (
                    " (both annual Stripe Prices verified)."
                    if options["verify_provider"]
                    else " (provider not contacted; use --verify-provider to verify Stripe Prices)."
                )
            )
        )
