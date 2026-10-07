"""Business domain capabilities, independent of plans, subscriptions and users."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Business


SHARED_CAPABILITIES = frozenset({"workspace", "team", "clients", "invoicing"})
VERTICAL_CAPABILITIES = {
    "SERVICE": SHARED_CAPABILITIES
    | frozenset(
        {"services", "service_requests", "appointments", "public_booking", "booking_availability"}
    ),
    "LOGISTICS": SHARED_CAPABILITIES
    | frozenset({"services", "parcels", "tracking", "shipments", "manifests"}),
}
MODULE_CAPABILITY_ALIASES = {
    "crm": "clients",
    "client_management": "clients",
    "public_booking_requests": "public_booking",
    "public_request_form": "public_booking",
    "public_request": "public_booking",
}


def normalize_module_name(module_name: str) -> str:
    return module_name.strip().lower().replace("-", "_")


def business_has_capability(business: Business | None, module_name: str) -> bool:
    """Check the domain only; unknown verticals and capabilities fail closed."""
    if business is None:
        return False
    return vertical_has_capability(business.vertical, module_name)


def vertical_has_capability(vertical: str, module_name: str) -> bool:
    normalized_name = normalize_module_name(module_name)
    capability = MODULE_CAPABILITY_ALIASES.get(normalized_name, normalized_name)
    return capability in VERTICAL_CAPABILITIES.get(vertical, frozenset())


def plan_module_name(module_name: str) -> str:
    """Keep the existing plan entitlement for newly separated core workflows."""
    normalized_name = normalize_module_name(module_name)
    return {"team": "workspace", "services": "crm", "booking_availability": "crm"}.get(
        normalized_name, normalized_name
    )
