"""Platform PWA resources: no workspace context, session data or domain models."""

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_safe

PWA_ASSETS = (
    "assets/css/pwa.css",
    "assets/js/pwa.js",
    "assets/img/favicons/motionmate-logo.svg",
    "assets/img/favicons/android-chrome-192x192.png",
    "assets/img/favicons/android-chrome-512x512.png",
    "assets/img/favicons/apple-touch-icon.png",
)


@require_safe
def manifest(request):
    response = JsonResponse(
        {
            "id": reverse("agent_dashboard"),
            "name": "Motionmate",
            "short_name": "Motionmate",
            "start_url": reverse("agent_dashboard"),
            "scope": reverse("pwa_scope"),
            "display": "standalone",
            "theme_color": "#ffffff",
            "background_color": "#f5f7fa",
            "icons": [
                {
                    "src": static(f"assets/img/favicons/android-chrome-{size}x{size}.png"),
                    "sizes": f"{size}x{size}",
                    "type": "image/png",
                    "purpose": "any",
                }
                for size in (192, 512)
            ],
        },
        content_type="application/manifest+json",
    )
    response["Cache-Control"] = "public, max-age=0, must-revalidate"
    return response


@require_safe
def offline(request):
    # Deliberately omit request: authenticated context processors must never run.
    response = HttpResponse(render_to_string("pwa/offline.html"))
    response["Cache-Control"] = "public, max-age=0, must-revalidate"
    return response


@require_safe
def service_worker(request):
    offline_url = reverse("pwa_offline")
    assets = [static(asset) for asset in PWA_ASSETS]
    context = {
        "assets_json": json.dumps([offline_url, *assets]),
        "offline_json": json.dumps(offline_url),
        "scope_json": json.dumps(reverse("pwa_scope")),
        "tracking_json": json.dumps(reverse("logistics_public_tracking")),
        "static_json": json.dumps(settings.STATIC_URL),
    }
    source = render_to_string("pwa/service-worker.js", context)
    # Version the cache on source/content changes, including un-hashed local assets.
    digest = hashlib.sha256(source.encode())
    digest.update(render_to_string("pwa/offline.html").encode())
    for asset in PWA_ASSETS:
        asset_path = finders.find(asset)
        if asset_path:
            digest.update(Path(asset_path).read_bytes())
    source = source.replace("__PWA_VERSION__", digest.hexdigest()[:16])
    response = HttpResponse(source, content_type="text/javascript")
    response["Service-Worker-Allowed"] = reverse("pwa_scope")
    add_never_cache_headers(response)
    return response


class PrivateResponseCacheMiddleware:
    """Keep dynamic private responses out of browser/shared HTTP caches."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = request.resolver_match
        if match and match.url_name in {
            "pwa_manifest",
            "pwa_manifest_legacy",
            "pwa_service_worker",
            "pwa_offline",
        }:
            return response
        # Includes login/logout redirects after authentication changes, anonymous
        # permission redirects, errors and APIs; static is handled by WhiteNoise.
        scope = reverse("pwa_scope")
        app_paths = (
            "accounts/",
            "crm/",
            "businesses/",
            "appointments/",
            "billings/",
            "billing/",
            "logistics/",
            "admin/",
        )
        # Public tracking already matches the path policy: do not resolve its
        # lazy authenticated user/session merely to set response headers.
        if request.path.startswith(tuple(scope + path for path in app_paths)) or getattr(
            getattr(request, "user", None), "is_authenticated", False
        ):
            add_never_cache_headers(response)
        return response
