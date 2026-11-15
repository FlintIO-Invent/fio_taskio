"""Process-local overrides outside production configuration and source snapshots."""

import os
from pathlib import Path

from ui_preview.core import load_session

ROOT, SESSION = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
SIDE_NAME = os.environ["MOTIONMATE_PREVIEW_SIDE"]
SIDE = SESSION[SIDE_NAME]
SOURCE = Path(SIDE["source"])
if (SOURCE / ".env").exists():
    raise RuntimeError("Preview snapshots must not contain an environment file.")

from taskio.settings import *  # noqa: E402,F403

DEBUG = True
SECRET_KEY = SIDE["secret"]
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = [f"http://127.0.0.1:{SIDE['http_port']}"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
        "PORT": SIDE["port"],
        "NAME": SIDE["database"],
        "USER": SESSION["db_user"],
        "PASSWORD": "",
        "CONN_MAX_AGE": 0,
    }
}
SESSION_COOKIE_NAME = f"mm_preview_{SESSION['id']}_{SIDE_NAME}"
CSRF_COOKIE_NAME = SESSION_COOKIE_NAME + "_csrf"
LANGUAGE_COOKIE_NAME = SESSION_COOKIE_NAME + "_language"
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"
SESSION_COOKIE_DOMAIN = CSRF_COOKIE_DOMAIN = None
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_HOST = EMAIL_HOST_USER = EMAIL_HOST_PASSWORD = ""
DEFAULT_FROM_EMAIL = "Motionmate Preview <no-reply@preview.test>"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
SERVICES_BOOKING_CACHE_ALIAS = "default"
MEDIA_ROOT = Path(SIDE["directory"]) / "media"
STATIC_ROOT = Path(SIDE["directory"]) / "collected-unused"
STATICFILES_DIRS = [SOURCE / "src/static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
STRIPE_ENABLED = False
STRIPE_SECRET_KEY = STRIPE_PUBLISHABLE_KEY = STRIPE_WEBHOOK_SECRET = ""
STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID = ""
STRIPE_PRICE_ID_MAP = STRIPE_LOGISTICS_TIER_PRICE_ID_MAP = {}
FREE_TEST_REGISTRATION_ENABLED = False
LOGISTICS_TEST_LAB_ENABLED = False
MOTIONMATE_ENVIRONMENT = "local"
LOGISTICS_LOCAL_BILLING_BYPASS = True
MOTIONMATE_PUBLIC_BASE_URL = f"http://127.0.0.1:{SIDE['http_port']}"
MIDDLEWARE = ["ui_preview.guard.PreviewMiddleware", *MIDDLEWARE]  # noqa: F405
