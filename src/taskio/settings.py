"""
Django settings for taskio project.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.config import settings
except ImportError:
    from config import settings

from apps.businesses.billing_policy import BILLING_OFFERINGS
from apps.businesses.plan_catalog import (
    PUBLIC_PRICING_CURRENCIES,
)
from apps.logistics.policy import LogisticsEligibilityPolicy, LogisticsUsageReviewPolicy

BASE_DIR = Path(__file__).resolve().parent.parent
RUNNING_TESTS = (
    "test" in sys.argv
    or "pytest" in Path(sys.argv[0]).name
    or bool(os.environ.get("PYTEST_CURRENT_TEST"))
)

AUTH_USER_MODEL = "accounts.TaskIOUser"

DEBUG = settings.debug
MOTIONMATE_ENVIRONMENT = settings.env.strip().lower()

if settings.secret_key:
    SECRET_KEY = settings.secret_key
elif DEBUG:
    SECRET_KEY = "motionmate-local-development-secret-key"
else:
    raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG=False.")

ALLOWED_HOSTS = settings.allowed_hosts
CSRF_TRUSTED_ORIGINS = settings.csrf_trusted_origins

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.businesses",
    "apps.crm",
    "apps.appointments",
    "apps.billings",
    "apps.logistics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "taskio.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.businesses.context_processors.current_business",
            ],
        },
    },
]

WSGI_APPLICATION = "taskio.wsgi.application"

if settings.database_url:
    DATABASES = {
        "default": dj_database_url.parse(
            settings.database_url,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": settings.db_engine,
            "NAME": settings.db_name,
            "USER": settings.db_user,
            "PASSWORD": settings.db_password,
            "HOST": settings.db_host,
            "PORT": settings.db_port,
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [settings.django_base_dir / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

if not DEBUG and not RUNNING_TESTS:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }


def _secure_bool(value: bool | None, default_when_debug_false: bool) -> bool:
    if value is not None:
        return value
    return False if DEBUG or RUNNING_TESTS else default_when_debug_false


def _secure_int(value: int | None, default_when_debug_false: int) -> int:
    if value is not None:
        return value
    return 0 if DEBUG or RUNNING_TESTS else default_when_debug_false


SECURE_SSL_REDIRECT = _secure_bool(settings.secure_ssl_redirect, True)
SESSION_COOKIE_SECURE = _secure_bool(settings.session_cookie_secure, True)
CSRF_COOKIE_SECURE = _secure_bool(settings.csrf_cookie_secure, True)
SECURE_HSTS_SECONDS = _secure_int(settings.secure_hsts_seconds, 3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    bool(settings.secure_hsts_include_subdomains) if SECURE_HSTS_SECONDS else False
)
SECURE_HSTS_PRELOAD = bool(settings.secure_hsts_preload) if SECURE_HSTS_SECONDS else False
SECURE_REFERRER_POLICY = settings.secure_referrer_policy

if _secure_bool(settings.use_x_forwarded_proto, True):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DEFAULT_FROM_EMAIL = settings.default_from_email
SERVER_EMAIL = settings.server_email or DEFAULT_FROM_EMAIL
EMAIL_BACKEND = settings.email_backend
EMAIL_HOST = settings.email_host
EMAIL_PORT = settings.email_port or (
    465 if settings.email_use_ssl else 587 if settings.email_use_tls else 25
)
EMAIL_HOST_USER = settings.email_host_user
EMAIL_HOST_PASSWORD = settings.email_host_password
EMAIL_USE_TLS = settings.email_use_tls
EMAIL_USE_SSL = settings.email_use_ssl
EMAIL_TIMEOUT = settings.email_timeout
MOTIONMATE_PUBLIC_BASE_URL = settings.motionmate_public_base_url
BETA_REGISTRATION_ENABLED = settings.beta_registration_enabled
BETA_REGISTRATION_TOKEN = settings.beta_registration_token
FREE_TEST_REGISTRATION_ENABLED = settings.free_test_registration_enabled
FREE_TEST_STARTER_TOKEN = settings.free_test_starter_token
FREE_TEST_PRO_TOKEN = settings.free_test_pro_token
FREE_TEST_BUSINESS_TOKEN = settings.free_test_business_token
MOTIONMATE_SUPPORT_EMAIL = settings.motionmate_support_email
STRIPE_ENABLED = settings.stripe_enabled
STRIPE_PUBLISHABLE_KEY = settings.stripe_publishable_key
STRIPE_SECRET_KEY = settings.stripe_secret_key
STRIPE_WEBHOOK_SECRET = settings.stripe_webhook_secret
STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID = settings.stripe_customer_portal_configuration_id
SUBSCRIPTION_PAYMENT_GRACE_DAYS = settings.subscription_payment_grace_days
STRIPE_PRICE_ID_MAP = {
    (plan_slug, billing_interval, currency): getattr(
        settings,
        f"stripe_price_{plan_slug}_{billing_interval}_{currency}",
    )
    for plan_slug, offering in BILLING_OFFERINGS.items()
    for billing_interval in offering.intervals
    for currency in PUBLIC_PRICING_CURRENCIES
}

LOGISTICS_AUTO_APPROVE_ALL = settings.logistics_auto_approve_all
LOGISTICS_LOCAL_BILLING_BYPASS = settings.logistics_local_billing_bypass
LOGISTICS_ELIGIBILITY_POLICY = LogisticsEligibilityPolicy(
    rule_version=settings.logistics_rule_version,
    auto_approve_monthly_parcels=settings.logistics_auto_approve_monthly_parcels,
    review_above_monthly_parcels=settings.logistics_review_above_monthly_parcels,
    high_resource_monthly_parcels=settings.logistics_high_resource_monthly_parcels,
    auto_approve_staff_count=settings.logistics_auto_approve_staff_count,
    auto_approve_location_count=settings.logistics_auto_approve_location_count,
    supported_territories=tuple(settings.logistics_supported_territories),
    registration_required_for_auto_approval=settings.logistics_registration_required_for_auto_approval,
)

LOGISTICS_USAGE_REVIEW_POLICY = LogisticsUsageReviewPolicy(
    approaching_ratio=settings.logistics_usage_approaching_ratio,
    monthly_event_review_threshold=settings.logistics_monthly_event_review_threshold,
)

LOGISTICS_DEPLOYMENT_CHECKS_ENABLED = settings.logistics_deployment_checks_enabled
LOGISTICS_TRACKING_CACHE_ALIAS = settings.logistics_tracking_cache_alias
# A dedicated tracking cache leaves SERVICE cache behavior unchanged.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "logistics_tracking": {
        "BACKEND": settings.logistics_tracking_cache_backend,
        "LOCATION": settings.logistics_tracking_cache_location,
        "KEY_PREFIX": settings.logistics_tracking_cache_key_prefix,
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": settings.log_level,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": settings.log_level,
            "propagate": False,
        },
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
