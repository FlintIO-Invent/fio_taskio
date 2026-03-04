from django import forms
from .models import Lead, Client

class PrivateClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            # basics
            "client_type",
            "first_name",
            "last_name",
            "company_name",
            "email",
            "phone",

            # crm context
            "job_title",
            "preferred_contact_method",
            "lead_source",
            "client_status",
            "priority",
            "interested_services",

            # location
            "street_address",
            "district",
            "country",
            "postal_code",

            # notes / consent
            "message",
            "consent_to_contact",
        ]

        widgets = {
            # Dropdowns
            "client_type": forms.Select(attrs={"class": "form-select mb-3"}),
            "preferred_contact_method": forms.Select(attrs={"class": "form-select mb-3"}),
            "lead_source": forms.Select(attrs={"class": "form-select mb-3"}),
            "client_status": forms.Select(attrs={"class": "form-select mb-3"}),
            "priority": forms.Select(attrs={"class": "form-select mb-3"}),
            "district": forms.Select(attrs={"class": "form-select"}),

            # Text Inputs
            "company_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "SimonSays N.V.",
            }),

            "first_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "First name",
            }),

            "last_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Last name",
            }),

            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "name@example.com",
            }),

            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "+1 (721) 456-7890",
            }),

            "job_title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Owner / Manager / Operations",
            }),

            "street_address": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Street address",
            }),

            "country": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Country",
            }),

            "postal_code": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Postal code",
            }),

            # Textarea
            "interested_services": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "What services are they interested in?",
            }),

            "message": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Notes about the request / context...",
            }),

            # Checkbox
            "consent_to_contact": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }

        labels = {
            "client_type": "Client type",
            "company_name": "Company name",
            "job_title": "Job title / role",
            "preferred_contact_method": "Preferred contact method",
            "lead_source": "Lead source",
            "client_status": "Client status",
            "priority": "Priority",
            "interested_services": "Interested services",
            "street_address": "Street Address",
            "postal_code": "Postal Code",
            "consent_to_contact": "I consent to be contacted via email, phone, or WhatsApp for requests and updates.",
        }

class PublicLeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = [
            "lead_type",
            "category",
            "first_name",
            "last_name",
            "company_name", 
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

            "company_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "SimonSays N.V.",
            }),
          

            # Text Inputs
            "first_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "First name",
            }),

            "last_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Last name",
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
                "value": "SXM",   
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


    class Meta:
        model = Client
        fields = [
            "first_name",
            "last_name",
            "company_name", 
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
            "district": forms.Select(attrs={
                "class": "form-select",
            }),

            "company_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "SimonSays N.V.",
            }),
          

            # Text Inputs
            "first_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "First name",
            }),

            "last_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Last name",
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
                "value": "SXM",   
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