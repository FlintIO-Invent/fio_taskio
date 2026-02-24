from django import forms
from .models import Lead


class PublicLeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = [
            "lead_type",
            "category",
            "first_name",
            "last_name",
            "email",
            "phone",
            "street_address",
            "district",
            "country",        # make sure this exists in your model
            "postal_code",
            "message",
            "consent_to_contact",
        ]

        widgets = {

            # Dropdowns
            "lead_type": forms.Select(attrs={
                "class": "form-select mb-3",
            }),

            "category": forms.Select(attrs={
                "class": "form-select mb-3",
            }),

            "district": forms.Select(attrs={
                "class": "form-select",
            }),

            # Text Inputs
            "first_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "First name",
            }),

            "last_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Last name (optional)",
            }),

            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "name@example.com",
            }),

            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "+1 (721) 456-7890",
            }),

            "street_address": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Street address",
            }),

            "country": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Country",
                "value": "SXM",   # optional default
            }),

            "postal_code": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Postal code",
            }),

            # Textarea
            "message": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Tell us what you need...",
            }),

            # Checkbox
            "consent_to_contact": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }

        labels = {
            "lead_type": "What can we help with?",
            "category": "Service category",
            "street_address": "Street Address",
            "postal_code": "Postal Code",
            "consent_to_contact": "I consent to be contacted via email and phone for service requests and updates.",
        }