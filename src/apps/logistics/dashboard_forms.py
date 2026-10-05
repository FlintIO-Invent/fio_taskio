"""Presentation helpers for Logistics forms in the shared dashboard theme."""

from django import forms


def style_dashboard_fields(fields):
    for field in fields.values():
        if field.widget.is_hidden:
            continue
        field.widget.attrs["class"] = (
            "form-select" if isinstance(field.widget, forms.Select) else "form-control"
        )
        if isinstance(field.widget, forms.Textarea):
            field.widget.attrs["rows"] = 3
