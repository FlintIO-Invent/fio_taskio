"""Services-only BoundField rendering; no form mutation, validation or data access."""

from django import template
from django.forms import CheckboxInput

register = template.Library()


@register.simple_tag
def settings_control(field, dom_prefix=""):
    if dom_prefix not in ("", None, "bulk_"):
        raise ValueError("Unknown Settings DOM namespace")
    control_id = "id_bulk_" + field.name if dom_prefix else field.auto_id
    help_id, error_id = control_id + "_helptext", control_id + "_error"
    described = field.field.widget.attrs.get("aria-describedby", "").split()
    if field.help_text:
        described.append(help_id)
    if field.errors:
        described.append(error_id)
    attrs = {"id": control_id}
    if described:
        attrs["aria-describedby"] = " ".join(dict.fromkeys(described))
    if field.errors:
        attrs["aria-invalid"] = "true"
    return {
        "id": control_id,
        "help_id": help_id,
        "error_id": error_id,
        "describedby": attrs.get("aria-describedby", ""),
        "checkbox": isinstance(field.field.widget, CheckboxInput),
        "fieldset": field.use_fieldset,
        "widget": field.as_widget(attrs=attrs),
    }
