"""Central parcel lifecycle and staff role policy."""

from apps.businesses.utils import ALL_WORKSPACE_ROLES, LEAD_MANAGE_ROLES

PARCEL_VIEW_ROLES = ALL_WORKSPACE_ROLES
PARCEL_MANAGE_ROLES = LEAD_MANAGE_ROLES

# Delivered and cancelled are terminal. HOLD can resume at any operational stage;
# each resumption remains an explicit, attributable status event.
ALLOWED_TRANSITIONS = {
    "REGISTERED": frozenset({"RECEIVED", "CANCELLED", "HOLD"}),
    "RECEIVED": frozenset({"IN_TRANSIT", "CANCELLED", "HOLD"}),
    "IN_TRANSIT": frozenset({"ARRIVED", "HOLD"}),
    "ARRIVED": frozenset({"READY", "HOLD"}),
    "READY": frozenset({"DELIVERED", "HOLD"}),
    "HOLD": frozenset({"RECEIVED", "IN_TRANSIT", "ARRIVED", "READY", "CANCELLED"}),
    "DELIVERED": frozenset(),
    "CANCELLED": frozenset(),
}
