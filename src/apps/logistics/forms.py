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


class EnrollmentForm(forms.Form):
    """Only security inputs; approved business/contact fields are never resubmitted."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, application, request, **kwargs):
        from django.contrib.auth import get_user_model

        super().__init__(*args, **kwargs)
        self.application = application
        self.request = request
        self.authenticated_user = None
        self.existing = get_user_model().objects.filter(email__iexact=application.email).first()
        if self.existing and request.user.is_authenticated and request.user.pk == self.existing.pk:
            self.fields.clear()
            self.authenticated_user = request.user
        elif self.existing:
            self.fields.pop("password2")
            self.fields["password1"].label = "Existing account password"

    def clean(self):
        from django.contrib.auth import authenticate

        cleaned = super().clean()
        if self.existing and self.authenticated_user is None:
            self.authenticated_user = authenticate(
                self.request, email=self.existing.email, password=cleaned.get("password1")
            )
            if self.authenticated_user is None:
                raise forms.ValidationError("Unable to verify this account. Check your password.")
        elif not self.existing and cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", "Passwords do not match.")
        return cleaned


class ParcelRegistrationForm(forms.ModelForm):
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    class Meta:
        from .models import Parcel
        from .parcel_services import PARCEL_INPUT_FIELDS

        model = Parcel
        fields = ("client",) + PARCEL_INPUT_FIELDS

    def __init__(self, *args, business, **kwargs):
        from apps.crm.models import Client

        super().__init__(*args, **kwargs)
        self.instance.business = business
        self.fields["declared_value"].label = f"Declared value ({business.currency})"
        self.fields["client"].queryset = Client.objects.filter(business=business).order_by(
            "first_name", "last_name", "pk"
        )

    def save(self, commit=True):
        raise NotImplementedError("Use register_parcel with the validated form data.")


class ParcelEventForm(forms.Form):
    status = forms.ChoiceField(required=False)
    location = forms.CharField(max_length=255, required=False)
    public_message = forms.CharField(
        max_length=1000,
        required=False,
        widget=forms.Textarea,
        help_text="Customer-facing text. Keep private information in the internal note.",
    )
    internal_note = forms.CharField(max_length=2000, required=False, widget=forms.Textarea)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)
    expected_status = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, parcel, **kwargs):
        from .models import Parcel
        from .parcel_policy import ALLOWED_TRANSITIONS

        super().__init__(*args, **kwargs)
        allowed = ALLOWED_TRANSITIONS[parcel.current_status]
        self.fields["status"].choices = [("", "Tracking note (keep status)")] + [
            (value, label)
            for value, label in Parcel.Status.choices
            if value in allowed or self.is_bound
        ]
