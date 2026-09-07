from __future__ import annotations

from apps.businesses.models import Business, BusinessUser
from apps.businesses.utils import (
    CLIENT_MANAGE_ROLES,
    LEAD_MANAGE_ROLES,
    SERVICE_MANAGEMENT_ROLES,
    membership_has_any_role,
)

from .types import ImportAccessDecision, ImportType

IMPORT_ROLES: dict[ImportType, tuple[str, ...]] = {
    ImportType.CLIENTS: CLIENT_MANAGE_ROLES,
    ImportType.LEADS: LEAD_MANAGE_ROLES,
    ImportType.SERVICES: SERVICE_MANAGEMENT_ROLES,
}


def user_can_import(business: Business | None, user, import_type: ImportType | str) -> bool:
    if business is None or not business.is_active or not getattr(user, "is_authenticated", False):
        return False
    try:
        normalized_import_type = ImportType(import_type)
    except ValueError:
        return False

    membership = BusinessUser.objects.filter(
        business=business,
        user=user,
        is_active=True,
    ).first()
    return membership_has_any_role(membership, IMPORT_ROLES[normalized_import_type])


def check_import_access(
    business: Business | None,
    user,
    import_type: ImportType | str,
) -> ImportAccessDecision:
    if user_can_import(business, user, import_type):
        return ImportAccessDecision(True, "allowed")
    return ImportAccessDecision(
        False,
        "permission_denied",
        "You do not have permission to import this type of data.",
    )


def check_import_capacity(
    *,
    business: Business,
    import_type: ImportType | str,
    requested_rows: int,
    capacity_checker=None,
) -> ImportAccessDecision:
    """Entity blocks must inject a quota checker; missing quota policy never grants access."""

    ImportType(import_type)
    if requested_rows < 0:
        raise ValueError("Requested row count cannot be negative.")
    if capacity_checker is None:
        return ImportAccessDecision(
            False,
            "capacity_check_not_configured",
            "Import capacity has not been configured for this import type.",
        )
    return capacity_checker(business=business, requested_rows=requested_rows)
