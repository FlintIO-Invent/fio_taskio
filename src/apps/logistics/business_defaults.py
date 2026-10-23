"""Form suggestions only; saved operational and financial snapshots stay intact."""

from django import forms


def configure_transport_names(form, business, *, parcel=False):
    for kind in (("vessel",) if parcel else ("vessel", "carrier")):
        key = f"{kind}_name"
        field = form.fields[key]
        names = getattr(business, f"logistics_{kind}_names").splitlines()
        saved = getattr(form.instance, key) or ""
        initial = form.initial.get(key)
        if initial and initial not in names:
            names.append(initial)
        # Keep historical/ad-hoc values editable even after catalogue changes.
        if saved and saved not in names:
            names.append(saved)
        if form.is_bound:
            submitted = form.data.get(form.add_prefix(key), "")
            if submitted and submitted not in names:
                names.append(submitted)
        if not names:
            continue
        field.widget = forms.Select(choices=[("", "---------"), *((name, name) for name in names)])
        if not form.instance.pk and not form.is_bound:
            field.widget.attrs["data-default-name"] = getattr(business, f"logistics_default_{kind}")
            mode = form.initial.get("mode_of_transport" if parcel else "transport_mode")
            if kind == "carrier" or mode == "SEA":
                form.initial.setdefault(key, getattr(business, f"logistics_default_{kind}"))
