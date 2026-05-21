from django import forms
from django.core.exceptions import ValidationError

from .models import Business, BusinessUser, ClarivoPlan
from .utils import can_assign_business_role, get_assignable_business_roles


class BusinessSettingsForm(forms.ModelForm):
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
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Acme Freight"}
            ),
            "business_type": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Electrician, Cleaning Service, Consultant..."}
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
                attrs={"class": "form-control", "min": 0, "max": 100, "step": "0.01"}
            ),
            "invoice_prefix": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "INV"}
            ),
            "invoice_start_number": forms.NumberInput(
                attrs={"class": "form-control", "min": 1}
            ),
            "address_line_1": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Street and building number"}
            ),
            "address_line_2": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Suite, floor, or additional details"}
            ),
            "city": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Amsterdam or Philipsburg"}
            ),
            "region": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "North Holland, district, province, or state"}
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

    def clean_email(self) -> str:
        return (self.cleaned_data.get("email") or "").strip().lower()

    def clean_role(self) -> str:
        role = (self.cleaned_data.get("role") or "").strip()
        if not can_assign_business_role(self.membership, role):
            raise ValidationError("You do not have permission to invite that workspace role.")
        return role

    def clean(self):
        return super().clean()
