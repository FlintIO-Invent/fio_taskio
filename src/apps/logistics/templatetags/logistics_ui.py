from django import template

register = template.Library()


@register.filter
def logistics_status_badge(status):
    return {
        "REGISTERED": "badge-phoenix-info",
        "RECEIVED": "badge-phoenix-primary",
        "HOLD": "badge-phoenix-warning",
        "IN_TRANSIT": "badge-phoenix-info",
        "ARRIVED": "badge-phoenix-primary",
        "READY": "badge-phoenix-success",
        "DELIVERED": "badge-phoenix-success",
        "CANCELLED": "badge-phoenix-danger",
        "DRAFT": "badge-phoenix-secondary",
        "COMPLETED": "badge-phoenix-success",
    }.get(status, "badge-phoenix-secondary")
