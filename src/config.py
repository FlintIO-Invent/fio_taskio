from __future__ import annotations
import os
from pathlib import Path
from typing import ClassVar
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent  # => .../fio_taskio/src


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
    model_config = SettingsConfigDict(
        env_file=BASE_DIR.parent / ".env",  # project root .env (optional)
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Core app settings ----
    env: str = Field(
        default="development",
        description="Runtime environment name (e.g., development/staging/production).",
    )

    debug: bool = Field(
        default=True,
        description="Enable debug mode (avoid True in production).",
    )

    # ---- Paths ----
    base_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent,
        description="Project base directory.",
    )
    
    data_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data",
        description="Directory for local data stage/artifacts.",
    )

    # ---- Django Credentials & Statics ----
    secret_key: str = Field(
        default="django-insecure-r+-lszd9tsss6t)f_gqqy8e3-l82xd-lm9kne%83jfe%r_27_h",
        description="Django secret key (override in production!).",
    )

    allowed_hosts: list[str] = Field(
        default=["127.0.0.1", "localhost"],
        description="List of allowed hosts for Django."
    )  

    django_base_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "src",
        description="Directory for local data stage/artifacts.",  )

    db_engine: str = Field(default="django.db.backends.postgresql")
    db_name: str = Field(default="taskio_database_dev")
    db_user: str = Field(default="taskio_user_dev")
    db_password: str = Field(default="self.taskio")
    db_host: str = Field(default="localhost")
    db_port: str = Field(default="5432")



settings = Settings()
