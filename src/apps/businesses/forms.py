from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .localization import (
    normalize_postal_code_for_country,
    uses_caribbean_address_format,
    uses_netherlands_address_format,
)
from .models import (
    Business,
    BusinessBookingSettings,
    BusinessUser,
    ClarivoPlan,
    WeeklyAvailability,
)
from .utils import can_assign_business_role, get_assignable_business_roles


class BusinessSettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_address_style()

    def _address_country(self) -> str:
        if self.is_bound:
            return (self.data.get(self.add_prefix("country")) or "").strip()
        return (getattr(self.instance, "country", "") or "").strip()

    def _apply_address_style(self) -> None:
        country = self._address_country()

        if uses_netherlands_address_format(country):
            self.fields["address_line_1"].label = "Street and house number"
            self.fields["address_line_1"].widget.attrs.update(
                {"placeholder": "Herengracht 101"}
            )
            self.fields["address_line_2"].label = "Apartment, suite, or unit"
            self.fields["city"].label = "City"
            self.fields["city"].widget.attrs.update({"placeholder": "Amsterdam"})
            self.fields["region"].label = "Province (optional)"
            self.fields["region"].widget.attrs.update({"placeholder": "North Holland"})
            self.fields["region"].help_text = (
                "Dutch postal addresses usually use postcode and city; province is optional."
            )
            self.fields["postal_code"].label = "Postcode"
            self.fields["postal_code"].widget.attrs.update({"placeholder": "1015 BJ"})
            self.fields["postal_code"].help_text = "Dutch format: 1234 AB."
        elif uses_caribbean_address_format(country):
            self.fields["address_line_1"].label = "Street address"
            self.fields["address_line_1"].widget.attrs.update(
                {"placeholder": "Front Street 12"}
            )
            self.fields["address_line_2"].label = "Apartment, suite, or landmark"
            self.fields["address_line_2"].widget.attrs.update(
                {"placeholder": "Suite, floor, or landmark"}
            )
            self.fields["city"].label = "Town / locality"
            self.fields["city"].widget.attrs.update({"placeholder": "Philipsburg"})
            self.fields["region"].label = "District / parish / island"
            self.fields["region"].widget.attrs.update({"placeholder": "District or island"})
            self.fields["postal_code"].label = "Postal code (optional)"
            self.fields["postal_code"].widget.attrs.update(
                {"placeholder": "Leave blank if unused"}
            )
            self.fields["postal_code"].help_text = (
                "Many Caribbean territories do not use postal codes; leave blank if not applicable."
            )

    def clean_postal_code(self):
        return normalize_postal_code_for_country(
            self.cleaned_data.get("postal_code"),
            self.cleaned_data.get("country") or self._address_country(),
        )

    class Meta:
        model = Business
        fields = [
            "name",
            "business_type",
            "email",
            "phone",
            "country",
            "currency",
            "timezone",
            "default_locale",
            "tax_label",
            "tax_rate",
            "invoice_prefix",
            "invoice_start_number",
            "address_line_1",
            "address_line_2",
            "city",
            "region",
            "postal_code",
            "address",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Acme Freight"}),
            "business_type": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Electrician, Cleaning Service, Consultant...",
                }
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "hello@example.com"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 721 555 0100"}
            ),
            "country": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Sint Maarten"}
            ),
            "currency": forms.Select(attrs={"class": "form-select"}),
            "timezone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Europe/Amsterdam"}
            ),
            "default_locale": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "nl-NL or en-SX"}
            ),
            "tax_label": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "VAT, BTW, GST, Tax"}
            ),
            "tax_rate": forms.NumberInput(
                attrs={"class": "form-control", "min": 0, "max": 100, "step": "1.00"}
            ),
            "invoice_prefix": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "INV"}
            ),
            "invoice_start_number": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "address_line_1": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Street and building number"}
            ),
            "address_line_2": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Suite, floor, or additional details",
                }
            ),
            "city": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Amsterdam or Philipsburg"}
            ),
            "region": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "North Holland, district, province, or state",
                }
            ),
            "postal_code": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Optional postal or ZIP code"}
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional address notes, landmarks, or mailing details",
                }
            ),
        }
        labels = {
            "business_type": "Business type / industry",
            "default_locale": "Default locale",
            "tax_label": "Tax label",
            "address_line_1": "Address line 1",
            "address_line_2": "Address line 2",
            "city": "City / locality",
            "region": "Region / district / province / state",
            "postal_code": "Postal code",
            "address": "Address notes",
        }
        help_texts = {
            "country": "Country or territory where this business primarily operates.",
            "timezone": "Use an IANA timezone like Europe/Amsterdam or America/Lower_Princes.",
            "default_locale": "Optional locale for future formatting, such as nl-NL, en-SX, or en-US.",
            "tax_label": "Examples: VAT, BTW, GST, Sales tax, or Tax.",
            "postal_code": "Optional. Useful in countries like the Netherlands. Businesses in Sint Maarten can leave this blank.",
            "address": "Optional extra directions, mailing notes, or legacy freeform address details.",
        }


class BusinessSubscriptionPlanForm(forms.Form):
    plan = forms.ModelChoiceField(
        queryset=ClarivoPlan.objects.none(),
        empty_label=None,
        widget=forms.HiddenInput(),
    )

    def __init__(self, *args, plans=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = plans if plans is not None else ClarivoPlan.objects.filter(is_active=True)
        self.fields["plan"].queryset = queryset


class BusinessBookingSettingsForm(forms.ModelForm):
    class Meta:
        model = BusinessBookingSettings
        fields = [
            "booking_enabled",
            "default_duration_minutes",
            "minimum_notice_hours",
            "maximum_days_ahead",
            "buffer_minutes",
            "confirmation_mode",
            "public_booking_instructions",
            "cancellation_policy_text",
            "reschedule_policy_text",
        ]
        widgets = {
            "booking_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "default_duration_minutes": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "step": 1}
            ),
            "minimum_notice_hours": forms.NumberInput(
                attrs={"class": "form-control", "min": 0, "step": 1}
            ),
            "maximum_days_ahead": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "step": 1}
            ),
            "buffer_minutes": forms.NumberInput(
                attrs={"class": "form-control", "min": 0, "step": 1}
            ),
            "confirmation_mode": forms.Select(attrs={"class": "form-select"}),
            "public_booking_instructions": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Optional instructions shown before customers submit a booking request.",
                }
            ),
            "cancellation_policy_text": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional cancellation policy text for public booking requests.",
                }
            ),
            "reschedule_policy_text": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional reschedule policy text for public booking requests.",
                }
            ),
        }
        labels = {
            "booking_enabled": "Enable public booking requests",
            "default_duration_minutes": "Default duration",
            "minimum_notice_hours": "Minimum notice",
            "maximum_days_ahead": "Maximum days ahead",
            "buffer_minutes": "Buffer time",
            "confirmation_mode": "Confirmation mode",
        }
        help_texts = {
            "booking_enabled": "Controls whether public visitors can submit booking requests for this workspace.",
            "default_duration_minutes": "Used as the default appointment request length.",
            "minimum_notice_hours": "How much advance notice public visitors must give before requesting a time.",
            "maximum_days_ahead": "How far into the future public visitors may request a time.",
            "buffer_minutes": "Optional spacing to reserve around requested appointment times.",
            "confirmation_mode": "Request-first/manual confirmation is the only supported behavior right now.",
        }

    def __init__(self, *args, business: Business | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        if business is not None:
            self.instance.business = business

    def clean(self):
        cleaned_data = super().clean()

        if self.business is None:
            raise ValidationError("A current business is required to manage booking settings.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.business = self.business
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class WeeklyAvailabilityForm(forms.ModelForm):
    class Meta:
        model = WeeklyAvailability
        fields = [
            "staff_member",
            "day_of_week",
            "start_time",
            "end_time",
            "is_active",
        ]
        widgets = {
            "staff_member": forms.Select(attrs={"class": "form-select"}),
            "day_of_week": forms.Select(attrs={"class": "form-select"}),
            "start_time": forms.TimeInput(
                attrs={"class": "form-control", "type": "time"},
                format="%H:%M",
            ),
            "end_time": forms.TimeInput(
                attrs={"class": "form-control", "type": "time"},
                format="%H:%M",
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "staff_member": "Staff member",
            "day_of_week": "Day",
            "start_time": "Start time",
            "end_time": "End time",
            "is_active": "Active",
        }
        help_texts = {
            "staff_member": "Leave blank to create a business-wide booking window.",
            "is_active": "Inactive blocks are ignored by public booking availability.",
        }

    def __init__(
        self,
        *args,
        business: Business | None = None,
        user=None,
        membership: BusinessUser | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.business = business
        self.user = user
        self.membership = membership
        if business is not None:
            self.instance.business = business
        self.fields["staff_member"].required = False
        self.fields["staff_member"].queryset = self._staff_member_queryset()
        self.fields["staff_member"].label_from_instance = self._staff_label
        self.fields["start_time"].input_formats = ["%H:%M"]
        self.fields["end_time"].input_formats = ["%H:%M"]

        if self._is_staff_member():
            self.fields["staff_member"].initial = user.pk if user is not None else None
            self.fields["staff_member"].disabled = True
            self.fields["staff_member"].help_text = (
                "Staff availability is added to your own schedule."
            )

    def _is_staff_member(self) -> bool:
        return self.membership is not None and self.membership.role == BusinessUser.Role.STAFF

    def _staff_member_queryset(self):
        if self.business is None:
            return get_user_model().objects.none()

        queryset = (
            get_user_model()
            .objects.filter(
                business_memberships__business=self.business,
                business_memberships__is_active=True,
                business_memberships__business__is_active=True,
                business_memberships__role__in=(
                    BusinessUser.Role.OWNER,
                    BusinessUser.Role.ADMIN,
                    BusinessUser.Role.STAFF,
                ),
                is_active=True,
            )
            .distinct()
            .order_by("first_name", "last_name", "email")
        )
        if self._is_staff_member() and self.user is not None:
            return queryset.filter(pk=self.user.pk)
        return queryset

    @staticmethod
    def _staff_label(user) -> str:
        get_full_name = getattr(user, "get_full_name", None)
        full_name = (get_full_name() if callable(get_full_name) else "") or getattr(
            user,
            "full_name",
            "",
        )
        return full_name.strip() or user.email

    def clean(self):
        cleaned_data = super().clean()

        if self.business is None:
            raise ValidationError("A current business is required to manage availability.")

        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        if start_time and end_time and end_time <= start_time:
            self.add_error("end_time", "End time must be after the start time.")

        if self._is_staff_member():
            cleaned_data["staff_member"] = self.user

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.business = self.business
        instance.staff_member = self.cleaned_data.get("staff_member")
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class BusinessInvitationForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "employee@example.com"}
        ),
    )
    role = forms.ChoiceField(
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, business: Business, membership: BusinessUser, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.membership = membership
        assignable_roles = set(get_assignable_business_roles(membership))
        self.fields["role"].choices = [
            (role_value, role_label)
            for role_value, role_label in BusinessUser.Role.choices
            if role_value in assignable_roles
        ]
        self.fields["email"].help_text = (
            "Use the employee's company-specific email address. Motionmate MVP keeps "
            "one active workspace per login and does not include a workspace switcher."
        )
        self.fields["role"].help_text = (
            "Each teammate has one role in this workspace. Use Admin if someone "
            "needs both staff and accountant access."
        )

    def clean_email(self) -> str:
        return (self.cleaned_data.get("email") or "").strip().lower()

    def clean_role(self) -> str:
        role = (self.cleaned_data.get("role") or "").strip()
        if not can_assign_business_role(self.membership, role):
            raise ValidationError("You do not have permission to invite that workspace role.")
        return role

    def clean(self):
        return super().clean()
