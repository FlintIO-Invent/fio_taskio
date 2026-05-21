from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.text import slugify

from .models import Client, Lead, ServiceCategory


def _service_category_queryset(*, business=None, instance=None, include_inactive=False):
    filters = Q()

    if business is not None:
        business_filters = Q(business=business)
        if not include_inactive:
            business_filters &= Q(is_active=True)
        filters |= business_filters

    if instance is not None and instance.pk and instance.category_id:
        filters |= Q(pk=instance.category_id)

    if not filters.children:
        return ServiceCategory.objects.none()

    return (
        ServiceCategory.objects.filter(filters)
        .select_related("business")
        .distinct()
        .order_by("name", "pk")
    )


class PrivateClientForm(forms.ModelForm):
    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = get_user_model().objects.none()

        if business is None:
            return

        self.fields["assigned_to"].queryset = (
            get_user_model()
            .objects.filter(
                business_memberships__business=business,
                business_memberships__is_active=True,
                business_memberships__business__is_active=True,
            )
            .distinct()
            .order_by("first_name", "last_name", "email")
        )

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

            # business details
            "business_legal_name",
            "trade_name",
            "industry",
            "business_description",
            "website",
            "registration_number",

            # contact context
            "job_title",
            "department",
            "secondary_email",
            "secondary_phone",
            "whatsapp_number",
            "preferred_language",
            "preferred_contact_method",

            # relationship / crm
            "lead_source",
            "client_status",
            "priority",
            "assigned_to",
            "interested_services",

            # location
            "street_address",
            "district",
            "country",
            "postal_code",

            # notes / consent
            "message",
            "communication_notes",
            "consent_to_contact",
            "notes",
        ]

        widgets = {
            # Dropdowns
            "client_type": forms.Select(attrs={"class": "form-select mb-3"}),
            "preferred_contact_method": forms.Select(attrs={"class": "form-select mb-3"}),
            "lead_source": forms.Select(attrs={"class": "form-select mb-3"}),
            "client_status": forms.Select(attrs={"class": "form-select mb-3"}),
            "priority": forms.Select(attrs={"class": "form-select mb-3"}),
            "assigned_to": forms.Select(attrs={"class": "form-select mb-3"}),
            "district": forms.Select(attrs={"class": "form-select"}),

            # Text inputs
            "company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "SimonSays N.V."}
            ),
            "business_legal_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "SimonSays N.V."}
            ),
            "trade_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "SimonSays"}
            ),
            "registration_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Registration number"}
            ),
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "First name"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Last name"}
            ),
            "department": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Department"}
            ),
            "preferred_language": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "English, Dutch, Spanish..."}
            ),
            "website": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://www.simonsays.com"}
            ),
            "secondary_email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "secondary@example.com"}
            ),
            "secondary_phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 (721) 456-7890"}
            ),
            "whatsapp_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 (721) 456-7890"}
            ),
            "industry": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "RETAIL, HOSPITALITY, etc."}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "name@example.com"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 (721) 456-7890"}
            ),
            "job_title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Owner / Manager / Operations"}
            ),
            "street_address": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Street address"}
            ),
            "country": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Country"}
            ),
            "postal_code": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Postal code"}
            ),

            # Textareas
            "business_description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Describe the client's business...",
                }
            ),
            "communication_notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Internal communication notes about the client...",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Internal notes about the client...",
                }
            ),
            "interested_services": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "What services are they interested in?",
                }
            ),
            "message": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Notes about the request / context...",
                }
            ),

            # Checkbox
            "consent_to_contact": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

        labels = {
            "client_type": "Client type",
            "company_name": "Company name",
            "business_legal_name": "Business legal name",
            "trade_name": "Trade name",
            "business_description": "Business description",
            "job_title": "Job title / role",
            "preferred_language": "Preferred language",
            "preferred_contact_method": "Preferred contact method",
            "lead_source": "Lead source",
            "client_status": "Client status",
            "priority": "Priority",
            "assigned_to": "Assigned to",
            "interested_services": "Interested services",
            "street_address": "Street Address",
            "postal_code": "Postal Code",
            "consent_to_contact": "I consent to be contacted via email, phone, or WhatsApp for requests and updates.",
        }


class PrivateLeadForm(forms.ModelForm):
    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.fields["category"].queryset = _service_category_queryset(
            business=business,
            instance=self.instance,
        )

    class Meta:
        model = Lead
        fields = [
            "lead_type",
            "status",
            "category",
            "first_name",
            "last_name",
            "company_name",
            "email",
            "phone",
            "street_address",
            "district",
            "country",
            "postal_code",
            "message",
            "notes",
            "consent_to_contact",
            "is_active",
        ]

        widgets = {
            "lead_type": forms.Select(attrs={"class": "form-select mb-3"}),
            "status": forms.Select(attrs={"class": "form-select mb-3"}),
            "category": forms.Select(attrs={"class": "form-select mb-3"}),
            "company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Company name"}
            ),
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "First name"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Last name"}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "name@example.com"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 (721) 456-7890"}
            ),
            "street_address": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Street address"}
            ),
            "district": forms.Select(attrs={"class": "form-select"}),
            "country": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Country"}
            ),
            "postal_code": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Postal code"}
            ),
            "message": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Describe the service request or lead context...",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Internal notes for your team...",
                }
            ),
            "consent_to_contact": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

        labels = {
            "lead_type": "Lead type",
            "status": "Status",
            "street_address": "Street Address",
            "postal_code": "Postal Code",
            "consent_to_contact": "Contact consent received",
            "is_active": "Active lead",
        }


class PublicLeadForm(forms.ModelForm):
    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.fields["category"].queryset = _service_category_queryset(business=business)

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


class ServiceCategoryForm(forms.ModelForm):
    class Meta:
        model = ServiceCategory
        fields = ["name", "code", "is_active"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Septic pumping"}
            ),
            "code": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "optional-code"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "code": "Optional. If left blank, Clarivo will generate a workspace-specific code from the name.",
        }

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.fields["code"].required = False

    def clean_code(self):
        raw_code = self.cleaned_data.get("code", "")
        normalized_code = slugify(raw_code).replace("-", "_") if raw_code else ""
        if raw_code and not normalized_code:
            raise forms.ValidationError("Enter a valid code.")
        return normalized_code

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name", "")
        code = cleaned_data.get("code") or slugify(name).replace("-", "_")

        if not self.business:
            raise forms.ValidationError("A current business is required to manage service categories.")

        if not code:
            self.add_error("name", "Enter a category name.")
            return cleaned_data

        queryset = ServiceCategory.objects.filter(
            business=self.business,
            code=code,
        )
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            self.add_error(
                "code",
                "This code is already used in the current workspace.",
            )

        cleaned_data["code"] = code
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.business = self.business
        instance.code = self.cleaned_data.get("code", instance.code)
        if commit:
            instance.save()
            self.save_m2m()
        return instance
