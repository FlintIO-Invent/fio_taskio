"""Central shipment lifecycle, membership and staff policy."""

from .parcel_policy import PARCEL_MANAGE_ROLES, PARCEL_VIEW_ROLES

SHIPMENT_VIEW_ROLES = PARCEL_VIEW_ROLES
SHIPMENT_MANAGE_ROLES = PARCEL_MANAGE_ROLES
ASSIGNABLE_SHIPMENT_STATUSES = frozenset({"DRAFT", "READY"})
ASSIGNABLE_PARCEL_STATUSES = frozenset({"REGISTERED", "RECEIVED"})
ALLOWED_TRANSITIONS = {
    "DRAFT": frozenset({"READY", "CANCELLED"}),
    "READY": frozenset({"DRAFT", "IN_TRANSIT", "CANCELLED"}),
    "IN_TRANSIT": frozenset({"ARRIVED"}),
    "ARRIVED": frozenset({"COMPLETED"}),
    "COMPLETED": frozenset(),
    "CANCELLED": frozenset(),
}
