from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent  # => .../fio_taskio/src


class Settings(BaseSettings):
    """
    Application configuration settings.

    Loads configuration values from environment variables
    and optional `.env` files.
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(
        default="development",
        description="Runtime environment name: local, development, staging or production.",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode. Keep this False outside local development.",
    )

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"development", "dev", "local"}:
                return True
        return value

    base_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent,
        description="Project base directory.",
    )
    data_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data",
        description="Directory for local data stage/artifacts.",
    )
    django_base_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "src",
        description="Directory containing the Django project package.",
    )

    secret_key: str | None = Field(
        default=None,
        description="Django secret key. Required whenever DEBUG is False.",
    )
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1", "localhost"],
        description="Allowed hosts for Django.",
    )
    csrf_trusted_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Trusted origins for CSRF protection.",
    )

    db_engine: str = Field(default="django.db.backends.postgresql")
    db_name: str = Field(default="taskio_database_dev")
    db_user: str = Field(default="taskio_user_dev")
    db_password: str = Field(default="self.taskio")
    db_host: str = Field(default="localhost")
    db_port: str = Field(default="5432")
    database_url: str | None = Field(
        default=None,
        description="Full database connection URL. Overrides individual DB_* settings when set.",
    )

    secure_ssl_redirect: bool | None = Field(
        default=None,
        description="Force HTTPS redirects when running in production.",
    )
    session_cookie_secure: bool | None = Field(
        default=None,
        description="Mark session cookies as secure-only.",
    )
    csrf_cookie_secure: bool | None = Field(
        default=None,
        description="Mark CSRF cookies as secure-only.",
    )
    secure_hsts_seconds: int | None = Field(
        default=None,
        description="HTTP Strict Transport Security max-age in seconds.",
    )
    secure_hsts_include_subdomains: bool = Field(
        default=False,
        description="Apply HSTS to subdomains.",
    )
    secure_hsts_preload: bool = Field(
        default=False,
        description="Advertise HSTS preload eligibility.",
    )
    use_x_forwarded_proto: bool | None = Field(
        default=None,
        description="Trust X-Forwarded-Proto from a proxy such as Heroku.",
    )
    secure_referrer_policy: str = Field(
        default="strict-origin-when-cross-origin",
        description="Referrer policy for Django responses.",
    )

    default_from_email: str = Field(
        default="no-reply@motionmate.local",
        description="Default sender email address.",
    )
    server_email: str | None = Field(
        default=None,
        description="Sender address for server error emails. Defaults to DEFAULT_FROM_EMAIL.",
    )
    email_backend: str = Field(
        default="django.core.mail.backends.console.EmailBackend",
        description="Django email backend path.",
    )
    email_host: str = Field(
        default="",
        description="SMTP host used when EMAIL_BACKEND is Django's SMTP backend.",
    )
    email_port: int | None = Field(
        default=None,
        description="SMTP port. Defaults to 465 with SSL, 587 with TLS, otherwise 25.",
    )
    email_host_user: str = Field(
        default="",
        description="SMTP username.",
    )
    email_host_password: str = Field(
        default="",
        description="SMTP password.",
    )
    email_use_tls: bool = Field(
        default=False,
        description="Use STARTTLS for SMTP email delivery.",
    )
    email_use_ssl: bool = Field(
        default=False,
        description="Use SSL/TLS for SMTP email delivery.",
    )
    email_timeout: int = Field(
        default=10,
        description="Timeout in seconds for SMTP email operations.",
    )
    motionmate_public_base_url: str = Field(
        default="",
        description="Canonical public application URL used when building links for emails.",
    )
    beta_registration_enabled: bool = Field(
        default=False,
        description="Enable hidden Beta business registration links.",
    )
    beta_registration_token: str = Field(
        default="",
        description="Reusable private token for hidden Beta business registration links.",
    )
    free_test_registration_enabled: bool = Field(
        default=False,
        description="Enable private tier-locked free-test registration links.",
    )
    free_test_starter_token: str = Field(
        default="",
        description="Reusable private token for Starter free-test registration.",
    )
    free_test_pro_token: str = Field(
        default="",
        description="Reusable private token for Pro free-test registration.",
    )
    free_test_business_token: str = Field(
        default="",
        description="Reusable private token for Business free-test registration.",
    )
    motionmate_support_email: str = Field(
        default="",
        description="Support email address shown in transactional emails.",
    )
    stripe_enabled: bool = Field(
        default=False,
        description="Enable Stripe subscription billing configuration validation.",
    )
    stripe_publishable_key: str = Field(
        default="",
        description="Stripe publishable key from the deployment environment.",
    )
    stripe_secret_key: str = Field(
        default="",
        description="Stripe secret key from the deployment environment.",
    )
    stripe_webhook_secret: str = Field(
        default="",
        description="Stripe webhook signing secret from the deployment environment.",
    )
    stripe_customer_portal_configuration_id: str = Field(
        default="",
        description="Stripe Customer Portal configuration ID from the deployment environment.",
    )
    subscription_payment_grace_days: str = Field(
        default="7",
        description="Motionmate payment-failure access grace period in days.",
    )
    stripe_price_starter_monthly_usd: str = Field(default="")
    stripe_price_starter_yearly_usd: str = Field(default="")
    stripe_price_starter_monthly_eur: str = Field(default="")
    stripe_price_starter_yearly_eur: str = Field(default="")
    stripe_price_pro_monthly_usd: str = Field(default="")
    stripe_price_pro_yearly_usd: str = Field(default="")
    stripe_price_pro_monthly_eur: str = Field(default="")
    stripe_price_pro_yearly_eur: str = Field(default="")
    stripe_price_business_monthly_usd: str = Field(default="")
    stripe_price_business_yearly_usd: str = Field(default="")
    stripe_price_business_monthly_eur: str = Field(default="")
    stripe_price_business_yearly_eur: str = Field(default="")
    stripe_price_logistics_yearly_usd: str = Field(default="")
    stripe_price_logistics_yearly_eur: str = Field(default="")
    logistics_local_billing_bypass: bool = Field(
        default=False,
        description="Allow pending Logistics operations only with ENV=local and DEBUG=True.",
    )
    logistics_test_lab_enabled: bool = Field(default=False)
    logistics_test_lab_database_id: str = Field(default="")
    logistics_test_lab_staging_app: str = Field(default="")
    logistics_test_lab_entitlement_approval: str = Field(default="")
    logistics_rule_version: str = Field(default="pilot-v1", min_length=1, max_length=100)
    logistics_auto_approve_all: bool = Field(
        default=True,
        description="Auto-approve valid Logistics applications; eligibility reasons remain advisory.",
    )
    logistics_deployment_checks_enabled: bool = Field(default=False)
    logistics_tracking_cache_alias: str = Field(default="default", min_length=1)
    logistics_tracking_cache_backend: str = Field(
        default="django.core.cache.backends.locmem.LocMemCache"
    )
    logistics_tracking_cache_location: str = Field(default="")
    logistics_tracking_cache_key_prefix: str = Field(default="clarivo-logistics-tracking")
    logistics_tracking_client_ip_mode: Literal["direct", "heroku"] = "direct"
    logistics_auto_approve_monthly_parcels: int = Field(default=1000, ge=0)
    logistics_review_above_monthly_parcels: int = Field(default=5000, ge=0)
    logistics_high_resource_monthly_parcels: int = Field(default=10000, ge=1)
    logistics_auto_approve_staff_count: int = Field(default=10, ge=1)
    logistics_auto_approve_location_count: int = Field(default=1, ge=1)
    logistics_usage_approaching_ratio: float = Field(default=0.8, gt=0, le=1)
    logistics_monthly_event_review_threshold: int | None = Field(default=None, ge=0)
    logistics_supported_territories: Annotated[list[str], NoDecode] = Field(default_factory=list)
    logistics_registration_required_for_auto_approval: bool = Field(default=True)
    log_level: str = Field(
        default="INFO",
        description="Application log level.",
    )

    @field_validator(
        "allowed_hosts", "csrf_trusted_origins", "logistics_supported_territories", mode="before"
    )
    @classmethod
    def parse_list_env(cls, value: object) -> object:
        if value is None:
            return []

        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return []

            if normalized.startswith("["):
                try:
                    parsed = json.loads(normalized)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]

            return [item.strip() for item in normalized.split(",") if item.strip()]

        if isinstance(value, (tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]

        return value

    @field_validator("email_port", mode="before")
    @classmethod
    def normalize_optional_int(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("email_timeout", mode="before")
    @classmethod
    def normalize_email_timeout(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return 10
        return value

    @field_validator("motionmate_public_base_url", mode="before")
    @classmethod
    def normalize_public_base_url(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value

    @field_validator(
        "beta_registration_token",
        "free_test_starter_token",
        "free_test_pro_token",
        "free_test_business_token",
        mode="before",
    )
    @classmethod
    def normalize_private_registration_token(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "subscription_payment_grace_days",
        "stripe_publishable_key",
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_customer_portal_configuration_id",
        "stripe_price_starter_monthly_usd",
        "stripe_price_starter_yearly_usd",
        "stripe_price_starter_monthly_eur",
        "stripe_price_starter_yearly_eur",
        "stripe_price_pro_monthly_usd",
        "stripe_price_pro_yearly_usd",
        "stripe_price_pro_monthly_eur",
        "stripe_price_pro_yearly_eur",
        "stripe_price_business_monthly_usd",
        "stripe_price_business_yearly_usd",
        "stripe_price_business_monthly_eur",
        "stripe_price_business_yearly_eur",
        "stripe_price_logistics_yearly_usd",
        "stripe_price_logistics_yearly_eur",
        mode="before",
    )
    @classmethod
    def normalize_stripe_secret_setting(cls, value: object) -> object:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper() or "INFO"
        return value


settings = Settings()
