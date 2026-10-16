"""Opt-in pilot deployment checks; existing SERVICE checks remain untouched."""

import os
from importlib.util import find_spec

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.db import connections
from django.db.utils import DatabaseError

from apps.businesses.billing_policy import logistics_local_billing_bypass_enabled
from apps.businesses.stripe_config import StripeConfigurationError, validate_stripe_configuration

from .enrollment import TOKEN_LIFETIME
from .policy import LogisticsEligibilityPolicy, LogisticsUsageReviewPolicy
from .public_tracking import ATOMIC_SHARED_CACHES


@register("logistics", Tags.security)
def check_logistics_local_billing_bypass(app_configs, **kwargs):
    """Always checked at startup; independent of the opt-in deployment checks."""
    if (
        getattr(settings, "LOGISTICS_LOCAL_BILLING_BYPASS", False)
        and not logistics_local_billing_bypass_enabled()
    ):
        return [
            Error(
                "LOGISTICS_LOCAL_BILLING_BYPASS requires ENV=local and DEBUG=True.",
                hint="Set LOGISTICS_LOCAL_BILLING_BYPASS=False in Development/Staging and Production.",
                id="logistics.E014",
            )
        ]
    return []


@register("logistics", Tags.security, deploy=True)
def check_logistics_deployment(app_configs, **kwargs):
    if not getattr(settings, "LOGISTICS_DEPLOYMENT_CHECKS_ENABLED", False):
        return []
    issues = []
    if not settings.STRIPE_ENABLED:
        issues.append(
            Error("Logistics pilot requires configured Stripe billing.", id="logistics.E001")
        )
    if validate_stripe_configuration():
        # Shared Stripe checks already explain individual problems without secrets.
        issues.append(
            Error(
                "Resolve the existing Stripe configuration checks before Logistics pilot.",
                id="logistics.E002",
            )
        )
    try:
        policy = LogisticsEligibilityPolicy.model_validate(settings.LOGISTICS_ELIGIBILITY_POLICY)
        LogisticsUsageReviewPolicy.model_validate(settings.LOGISTICS_USAGE_REVIEW_POLICY)
        if not policy.supported_territories:
            issues.append(
                Error(
                    "Configure an explicit Logistics supported territory allowlist.",
                    id="logistics.E003",
                )
            )
    except (ValueError, TypeError, AttributeError):
        issues.append(
            Error(
                "Logistics eligibility/resource review configuration is invalid.",
                id="logistics.E004",
            )
        )
    if not 0 < TOKEN_LIFETIME.total_seconds() <= 30 * 86400:
        issues.append(
            Error(
                "Logistics enrollment lifetime must be positive and at most 30 days.",
                id="logistics.E005",
            )
        )
    alias = getattr(settings, "LOGISTICS_TRACKING_CACHE_ALIAS", "default")
    config = settings.CACHES.get(alias, {})
    backend = config.get("BACKEND")
    dependency = ATOMIC_SHARED_CACHES.get(backend)
    if not dependency or not config.get("LOCATION"):
        issues.append(
            Error(
                "Public tracking requires a shared Redis/Memcached cache with atomic add/incr.",
                id="logistics.E006",
            )
        )
    elif find_spec(dependency) is None:
        issues.append(
            Error(
                "Install the client dependency for the configured tracking cache backend.",
                id="logistics.E007",
            )
        )
    if settings.EMAIL_BACKEND in {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
    }:
        issues.append(
            Warning(
                "Configure pilot email delivery; enrollment links must currently be delivered privately by a reviewer.",
                id="logistics.W001",
            )
        )
    elif (
        settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
        and not settings.EMAIL_HOST
    ):
        issues.append(Error("Configure EMAIL_HOST for SMTP delivery.", id="logistics.E008"))
    mode = getattr(settings, "LOGISTICS_TRACKING_CLIENT_IP_MODE", "direct")
    if mode == "heroku" and not os.environ.get("DYNO"):
        issues.append(Error("Heroku tracking IP mode requires a Heroku dyno.", id="logistics.E015"))
    elif mode == "direct":
        issues.append(
            Warning(
                "Tracking limits socket peers; verify direct client connections or configure Heroku router mode on Heroku.",
                id="logistics.W002",
            )
        )
    elif mode != "heroku":
        issues.append(Error("Unsupported tracking client IP mode.", id="logistics.E015"))
    if not kwargs.get("databases"):
        issues.append(
            Warning(
                "Include --database default to verify the Logistics plan and migrations.",
                id="logistics.W003",
            )
        )
    return issues


@register("logistics", Tags.database, deploy=True)
def check_logistics_plan(app_configs, **kwargs):
    if not getattr(settings, "LOGISTICS_DEPLOYMENT_CHECKS_ENABLED", False):
        return []
    from django.db.migrations.executor import MigrationExecutor

    from apps.businesses.models import BusinessSubscription, ClarivoPlan
    from apps.businesses.plan_catalog import LOGISTICS_TIER_SLUGS

    from .billing import configured_annual_price
    from .models import LogisticsApplication

    issues = []
    for alias in kwargs.get("databases") or ():
        try:
            connection = connections[alias]
            executor = MigrationExecutor(connection)
            if executor.migration_plan(executor.loader.graph.leaf_nodes()):
                issues.append(
                    Error("Apply all migrations before Logistics pilot.", id="logistics.E009")
                )
            # Probe the new retention schema even when recorder history is inconsistent.
            LogisticsApplication.objects.using(alias).values("business_id_snapshot").first()
            legacy_subscriptions = BusinessSubscription.objects.using(alias).filter(
                plan__slug="logistics"
            )
            plan = ClarivoPlan.objects.using(alias).filter(slug="logistics").first()
            if legacy_subscriptions.exists() and (
                plan is None or plan.family != "LOGISTICS" or not plan.is_active
            ):
                issues.append(
                    Error(
                        "Existing legacy Logistics subscriptions require their active Logistics plan.",
                        id="logistics.E010",
                    )
                )
            # Retired contracts retain their plan and stored provider identity.
            # Optional legacy mappings are only used when handling old events;
            # they are never a prerequisite for startup or current tier billing.
            for tier in ClarivoPlan.objects.using(alias).filter(
                slug__in=LOGISTICS_TIER_SLUGS, is_active=True
            ):
                try:
                    configured_annual_price(tier, "eur")
                except StripeConfigurationError:
                    issues.append(
                        Error(
                            f"Active {tier.slug} requires complete capacities and eligible annual EUR TEST configuration.",
                            id="logistics.E016",
                        )
                    )
        except DatabaseError:
            issues.append(
                Error(
                    "Logistics database/schema is unavailable; apply migrations and retry.",
                    id="logistics.E013",
                )
            )
    return issues
