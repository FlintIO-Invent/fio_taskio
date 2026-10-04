from django import forms

from .models import LogisticsApplication


class LogisticsApplicationForm(forms.ModelForm):
    class Meta:
        model = LogisticsApplication
        fields = LogisticsApplication.MATERIAL_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-check-input"
                if isinstance(field.widget, forms.CheckboxInput)
                else "form-control"
            )
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 3
        self.fields["timezone"].help_text = (
            "IANA timezone, for example America/Curacao or Europe/Amsterdam."
        )
        self.fields["registration_number"].help_text = (
            "Optional at submission; further registration details may be requested."
        )


class ApplicationReviewForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            ("APPROVED", "Approve"),
            ("DECLINED", "Decline"),
            ("REEVALUATE", "Reevaluate"),
            ("WITHDRAWN", "Record withdrawal"),
        ]
    )
    reason = forms.CharField(
        required=False,
        max_length=3000,
        widget=forms.Textarea,
        help_text="A reason is required for a manual decision.",
    )
    expected_revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") in {"APPROVED", "DECLINED", "WITHDRAWN"} and not cleaned.get(
            "reason"
        ):
            self.add_error("reason", "Explain the manual decision.")
        return cleaned
