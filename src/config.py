from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

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
        description="Runtime environment name (for example: development or production).",
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
    email_backend: str = Field(
        default="django.core.mail.backends.console.EmailBackend",
        description="Django email backend path.",
    )
    log_level: str = Field(
        default="INFO",
        description="Application log level.",
    )

    @field_validator("allowed_hosts", "csrf_trusted_origins", mode="before")
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

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper() or "INFO"
        return value


settings = Settings()
