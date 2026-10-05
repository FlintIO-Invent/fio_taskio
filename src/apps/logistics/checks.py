"""Opt-in pilot deployment checks; existing SERVICE checks remain untouched."""

from importlib.util import find_spec

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.db import connections
from django.db.utils import DatabaseError

from apps.businesses.stripe_config import StripeConfigurationError, validate_stripe_configuration

from .enrollment import TOKEN_LIFETIME
from .policy import LogisticsEligibilityPolicy, LogisticsUsageReviewPolicy

ATOMIC_SHARED_CACHES = {
    "django.core.cache.backends.redis.RedisCache": "redis",
    "django.core.cache.backends.memcached.PyMemcacheCache": "pymemcache",
    "django.core.cache.backends.memcached.PyLibMCCache": "pylibmc",
}


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
    issues.append(
        Warning(
            "Verify the deployment proxy supplies a trustworthy REMOTE_ADDR; forwarded headers are intentionally ignored.",
            id="logistics.W002",
        )
    )
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

    from apps.businesses.models import ClarivoPlan

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
            plan = (
                ClarivoPlan.objects.using(alias)
                .filter(slug="logistics", family="LOGISTICS")
                .first()
            )
            if plan is None or not plan.is_active:
                issues.append(
                    Error(
                        "Configure and activate the Logistics plan before pilot.",
                        id="logistics.E010",
                    )
                )
                continue
            mapping = settings.STRIPE_PRICE_ID_MAP
            currencies = [
                currency
                for currency in ("usd", "eur")
                if mapping.get(("logistics", "yearly", currency))
            ]
            if not currencies:
                issues.append(
                    Error(
                        "Configure at least one Logistics yearly USD/EUR Stripe Price ID.",
                        id="logistics.E011",
                    )
                )
            for currency in currencies:
                try:
                    configured_annual_price(plan, currency)
                except StripeConfigurationError:
                    issues.append(
                        Error(
                            f"Configure a positive matching Logistics annual {currency.upper()} price and Price mapping.",
                            id="logistics.E012",
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
