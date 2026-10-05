from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError

from .models import LogisticsApplication


class LogisticsApplicationForm(forms.ModelForm):
    APPLICATION_STEPS = (
        (
            "business",
            "Business",
            "fa-building",
            "Tell us about your business and where you operate.",
            (
                "business_name",
                "trading_name",
                "registration_number",
                "website",
                "country",
                "timezone",
                "business_address",
                "preferred_currency",
            ),
        ),
        (
            "contact",
            "Contact",
            "fa-user",
            "Who should we contact about your application?",
            ("contact_first_name", "contact_last_name", "email", "phone", "whatsapp"),
        ),
        (
            "operations",
            "Operations",
            "fa-truck-fast",
            "Help us understand your parcel routes, volume and team.",
            (
                "operation_type",
                "routes",
                "monthly_parcel_estimate",
                "expected_staff_count",
                "location_count",
                "current_process_method",
                "current_process_details",
            ),
        ),
        (
            "requirements",
            "Requirements",
            "fa-list-check",
            "Select the features you need and share any special requirements.",
            (
                "customer_tracking_needed",
                "manifest_needed",
                "api_integration_needed",
                "custom_workflow",
                "custom_workflow_details",
                "multi_jurisdiction",
                "custom_pricing_requested",
                "operational_notes",
            ),
        ),
    )
    HALF_WIDTH_FIELDS = frozenset(
        {
            "trading_name",
            "registration_number",
            "country",
            "timezone",
            "contact_first_name",
            "contact_last_name",
            "phone",
            "whatsapp",
            "expected_staff_count",
            "location_count",
        }
    )

    class Meta:
        model = LogisticsApplication
        fields = LogisticsApplication.MATERIAL_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-check-input"
                if isinstance(field.widget, forms.CheckboxInput)
                else "form-select"
                if isinstance(field.widget, forms.Select)
                else "form-control"
            )
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 3
        self.fields[
            "timezone"
        ].help_text = "IANA timezone, for example America/Curacao or Europe/Amsterdam."
        self.fields[
            "registration_number"
        ].help_text = "Optional at submission; further registration details may be requested."
        for name, autocomplete in {
            "business_name": "organization",
            "contact_first_name": "given-name",
            "contact_last_name": "family-name",
            "email": "email",
            "phone": "tel",
            "whatsapp": "tel",
            "country": "country-name",
            "business_address": "street-address",
            "website": "url",
        }.items():
            self.fields[name].widget.attrs["autocomplete"] = autocomplete
        for name in ("phone", "whatsapp"):
            self.fields[name].widget.attrs["inputmode"] = "tel"
        for name in ("expected_staff_count", "location_count"):
            self.fields[name].widget.attrs["min"] = 1
        self.fields["timezone"].widget.attrs["placeholder"] = "e.g. America/Curacao"

    @property
    def application_steps(self):
        return [
            {
                "slug": slug,
                "label": label,
                "icon": icon,
                "description": description,
                "fields": [
                    {
                        "field": self[name],
                        "columns": "col-sm-6" if name in self.HALF_WIDTH_FIELDS else "",
                    }
                    for name in names
                ],
            }
            for slug, label, icon, description, names in self.APPLICATION_STEPS
        ]


class LogisticsSignupForm(LogisticsApplicationForm):
    """Credentials are transient form inputs, never application or decision fields."""

    use_existing_account = forms.BooleanField(
        label="I already have a Motionmate account",
        required=False,
        help_text="Use your existing account through secure sign-in and enrollment.",
    )
    password1 = forms.CharField(
        label="Password",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label="Confirm password",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.new_account_password = None
        if not settings.LOGISTICS_AUTO_APPROVE_ALL:
            for name in ("use_existing_account", "password1", "password2"):
                self.fields.pop(name)

    @property
    def application_steps(self):
        steps = super().application_steps
        if "password1" in self.fields:
            steps[1]["fields"].extend(
                {"field": self[name], "columns": ""}
                for name in ("use_existing_account", "password1", "password2")
            )
        return steps

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email", "").strip().casefold()
        User = get_user_model()
        if (
            "password1" not in self.fields
            or cleaned.get("use_existing_account")
            or User.objects.filter(email__iexact=email).exists()
        ):
            # Never treat a submitted password as authority over an existing user.
            cleaned.pop("password1", None)
            cleaned.pop("password2", None)
            return cleaned
        password = cleaned.get("password1")
        if not password:
            self.add_error("password1", "Set a password for your new account.")
        if not cleaned.get("password2"):
            self.add_error("password2", "Confirm your password.")
        elif password != cleaned["password2"]:
            self.add_error("password2", "Passwords do not match.")
        if password:
            candidate = User(
                email=email,
                first_name=cleaned.get("contact_first_name", "")[:30],
                last_name=cleaned.get("contact_last_name", "")[:30],
            )
            try:
                password_validation.validate_password(password, candidate)
            except ValidationError as exc:
                self.add_error("password1", exc)
        if not self.errors:
            self.new_account_password = password
        return cleaned


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
