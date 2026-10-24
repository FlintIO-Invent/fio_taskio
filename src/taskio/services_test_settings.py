"""Explicit, disposable local PostgreSQL settings; never inherit DATABASE_URL."""

import os

from .settings import *  # noqa: F403

port = os.environ.get("SERVICES_TEST_PG_PORT", "")
if not port.isdigit() or int(port) < 1024 or port == "5432":
    raise RuntimeError(
        "Set SERVICES_TEST_PG_PORT to a disposable localhost PostgreSQL port (not 5432)."
    )
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
        "PORT": port,
        "USER": os.environ.get("SERVICES_TEST_PG_USER", "mzero"),
        "NAME": "postgres",
        "TEST": {"NAME": "test_services_rollout"},
    }
}
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
