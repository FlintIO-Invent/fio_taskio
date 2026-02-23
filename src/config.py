from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration settings.

    Loads configuration values from environment variables
    and optional `.env` files.

    Attributes:
        env (str):
            Runtime environment name.

        debug (bool):
            Indicates whether debug mode is enabled.

    Notes:
        - Environment variables override `.env` values.
        - Should be instantiated once and reused.
        - Do not enable debug mode in production.
    """

    # ---- Pydantic Settings configuration ----
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="APP_",            # e.g. APP_ENV, APP_DEBUG, ...
        env_file=".env",              # local dev convenience
        env_file_encoding="utf-8",
        extra="ignore",               # ignore unknown env vars
        case_sensitive=False,         # set True if you want strict casing
    )

    # ---- Core app settings ----
    env: str = Field(
        default="development",
        description="Runtime environment name (e.g., development/staging/production).",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode (avoid True in production).",
    )

    # ---- Paths ----
    base_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent,
        description="Project base directory.",
    )
    data_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data",
        description="Directory for local data files/artifacts.",
    )


settings = Settings()


