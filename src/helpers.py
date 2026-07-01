from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from apps.crm.models import Client, Lead


def build_public_url(path: str, request=None) -> str:
    public_base_url = (
        getattr(settings, "MOTIONMATE_PUBLIC_BASE_URL", "") or ""
    ).strip().rstrip("/")
    safe_path = str(path or "")

    if public_base_url:
        if not safe_path:
            return public_base_url
        return f"{public_base_url}/{safe_path.lstrip('/')}"

    if request is not None:
        return request.build_absolute_uri(safe_path or "/")

    return safe_path


def upsert_client_from_lead(lead: Lead) -> tuple[Client, bool]:
    """Compatibility wrapper kept for active public-request lead capture flows."""
    from apps.crm.services import sync_client_from_lead

    return sync_client_from_lead(lead)
