from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from .models import SaaSUserProfile, TaskIOUser


class CustomerForm(forms.ModelForm):
    class Meta:
        model = TaskIOUser
        fields = ["email", "first_name", "last_name", "date_of_birth", "phone", "address"]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned = super().clean()
        return cleaned


class CustomerRegistrationForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Password",
        strip=False,
        help_text=password_validation.password_validators_help_text_html(),
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Create a password"}
        ),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Repeat your password"}
        ),
    )

    class Meta:
        model = TaskIOUser
        fields = [
            "email",
            "first_name",
            "last_name",
            "company_name",
            "phone",
            "address",
            "date_of_birth",
        ]
        widgets = {
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "name@example.com"}
            ),
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Jane"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Doe"}
            ),
            "company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Acme Freight"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 721 555 0100"}
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "Business address",
                    "rows": 3,
                }
            ),
            "date_of_birth": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
        }
        labels = {
            "company_name": "Company name",
            "date_of_birth": "Date of birth",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company_name"].required = False
        self.fields["phone"].required = False
        self.fields["address"].required = False
        self.fields["date_of_birth"].required = False

    def clean_email(self) -> str:
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if TaskIOUser.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords do not match.")

        if password1:
            user = TaskIOUser(
                email=cleaned_data.get("email", ""),
                first_name=cleaned_data.get("first_name", ""),
                last_name=cleaned_data.get("last_name", ""),
            )
            try:
                password_validation.validate_password(password1, user=user)
            except ValidationError as exc:
                self.add_error("password1", exc)

        return cleaned_data

    def save(self, commit: bool = True) -> TaskIOUser:
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.incorporation_status = "UNINCORPORATED"
        user.assigned_location = "CARIBBEAN"
        user.is_active = True
        user.set_password(self.cleaned_data["password1"])

        if commit:
            user.save()

        return user


class SaaSBasicInfoForm(forms.ModelForm):
    class Meta:
        model = TaskIOUser
        fields = [
            "first_name",
            "last_name",
            "email",
            "company_name",
            "phone",
            "assigned_location",
            "date_of_birth",
            "address",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Jane"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Doe"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "name@example.com"}),
            "company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Acme Freight"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 721 555 0100"}
            ),
            "assigned_location": forms.Select(attrs={"class": "form-select"}),
            "date_of_birth": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Business or mailing address",
                }
            ),
        }

    def clean_email(self) -> str:
        email = (self.cleaned_data.get("email") or "").strip().lower()
        qs = TaskIOUser.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Another account is already using this email.")
        return email


class SaaSWorkspaceSettingsForm(forms.ModelForm):
    class Meta:
        model = SaaSUserProfile
        fields = [
            "workspace_name",
            "billing_email",
            "support_email",
            "website",
            "tax_id",
        ]
        widgets = {
            "workspace_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Clarivo Workspace"}
            ),
            "billing_email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "billing@example.com"}
            ),
            "support_email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "support@example.com"}
            ),
            "website": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://example.com"}
            ),
            "tax_id": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "TIN / VAT / registration number"}
            ),
        }


class SaaSInvoiceSettingsForm(forms.ModelForm):
    class Meta:
        model = SaaSUserProfile
        fields = [
            "currency_code",
            "invoice_prefix",
            "invoice_default_due_days",
            "invoice_accent_color",
            "show_company_address_on_invoice",
            "show_tax_id_on_invoice",
            "payment_instructions",
            "invoice_footer_note",
        ]
        widgets = {
            "currency_code": forms.Select(attrs={"class": "form-select"}),
            "invoice_prefix": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "INV"}
            ),
            "invoice_default_due_days": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 90}
            ),
            "invoice_accent_color": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "#2C7BE5"}
            ),
            "payment_instructions": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Bank details, transfer notes, or payment links",
                }
            ),
            "invoice_footer_note": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Thank you message or standard invoice footer",
                }
            ),
        }
