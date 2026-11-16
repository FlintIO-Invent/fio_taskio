"""Pure Services booking presentation; never changes validation or stored data."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import template
from django.utils import timezone
from django.utils.formats import date_format

register = template.Library()


def business_zone(business):
    try:
        return ZoneInfo(getattr(business, "timezone", "") or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return timezone.get_default_timezone()


@register.filter
def booking_time(value, business):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = value.astimezone(business_zone(business))
    return date_format(value, "M d, Y H:i")


@register.simple_tag
def booking_zone(business):
    return str(business_zone(business))


@register.simple_tag(takes_context=True)
def services_booking_scope(context):
    business = context.get("public_business") or context.get("current_business")
    if getattr(business, "vertical", None) != "SERVICE":
        return False
    lead = context.get("lead")
    if lead is not None and lead.lead_type != "REQUEST":
        return False
    form = context.get("form")
    if form is not None and "lead_type" in form.fields:
        return form["lead_type"].value() in (None, "", "REQUEST")
    return True


@register.simple_tag
def booking_widget(field):
    attrs = {}
    described = field.field.widget.attrs.get("aria-describedby", "").split()
    if field.help_text:
        described.append(f"{field.auto_id}_helptext")
    if field.errors:
        attrs["aria-invalid"] = "true"
        described.append(f"{field.auto_id}_errors")
    if described:
        attrs["aria-describedby"] = " ".join(dict.fromkeys(described))
    return field.as_widget(attrs=attrs)
