from __future__ import annotations
from typing import Tuple
from apps.crm.models import Client, Lead
from apps.crm.services import sync_client_from_lead


def upsert_client_from_lead(lead: Lead) -> Tuple[Client, bool]:
    """Compatibility wrapper kept for active public-request lead capture flows."""
    return sync_client_from_lead(lead)
