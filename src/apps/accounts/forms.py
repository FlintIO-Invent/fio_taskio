from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.beta_registration import (
    BETA_PLAN_DISPLAY_NAME,
    BETA_PLAN_SLUG,
    beta_registration_token_is_configured,
)
from apps.businesses.models import (
    Business,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
)
from apps.businesses.plan_catalog import (
    DEFAULT_PUBLIC_PAID_PLAN_SLUG,
    PUBLIC_PAID_PLAN_SLUG_SET,
    PUBLIC_PAID_PLAN_SLUGS,
    STANDARD_TRIAL_DAYS,
    is_public_paid_plan_slug,
    normalize_plan_slug,
    normalize_public_paid_plan_slug,
)
from apps.businesses.utils import create_default_trial_subscription, generate_business_slug

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
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Jane"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Doe"}),
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
            "date_of_birth": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
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


class BusinessRegistrationForm(forms.Form):
    PLAN_QUERY_SLUGS = PUBLIC_PAID_PLAN_SLUG_SET

    first_name = forms.CharField(
        label="Owner first name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Jane"}),
    )
    last_name = forms.CharField(
        label="Owner last name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Doe"}),
    )
    email = forms.EmailField(
        label="Owner login email",
        help_text="Use the email address you want to sign in with. This will become the workspace owner login for this business.",
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "owner@example.com"}
        ),
    )
    business_name = forms.CharField(
        label="Business name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Acme Freight"}),
    )
    business_email = forms.EmailField(
        label="Business email",
        help_text="Use the public contact or billing email for the business. It can be different from the owner login email.",
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "hello@acmefreight.com"}
        ),
    )
    country = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Sint Maarten"}),
    )
    plan = forms.ModelChoiceField(
        label="Trial plan",
        queryset=ClarivoPlan.objects.none(),
        required=False,
        empty_label=None,
        to_field_name="slug",
        help_text=f"Your workspace starts with the standard {STANDARD_TRIAL_DAYS}-day trial. You can change plans after signup.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
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

    def __init__(
        self,
        *args,
        selected_plan_slug: str | None = None,
        beta_eligible: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.beta_eligible = beta_eligible
        plans = self._plan_queryset()
        submitted_plan_slug = (
            self.data.get(self.add_prefix("plan")) if self.is_bound else selected_plan_slug
        )
        self.selected_plan_for_display = self._default_plan(
            plans,
            submitted_plan_slug,
            beta_eligible=beta_eligible,
        )
        self.fields["plan"].queryset = plans
        self.fields["plan"].label_from_instance = self._plan_label
        self.fields["plan"].initial = self.selected_plan_for_display
        if not beta_eligible:
            self.fields["plan"].widget = forms.HiddenInput()

    def _plan_queryset(self):
        if (
            not self.beta_eligible
            or not getattr(settings, "BETA_REGISTRATION_ENABLED", False)
            or not beta_registration_token_is_configured()
        ):
            return ClarivoPlan.motionmate_plans()

        return ClarivoPlan.objects.filter(
            is_active=True,
            slug__in=(*PUBLIC_PAID_PLAN_SLUGS, BETA_PLAN_SLUG),
        ).order_by(ClarivoPlan.motionmate_plan_ordering(), "pk")

    @staticmethod
    def _plan_label(plan: ClarivoPlan) -> str:
        if plan.slug == BETA_PLAN_SLUG:
            return BETA_PLAN_DISPLAY_NAME

        label = plan.name
        if plan.is_recommended:
            label = f"{label} (Recommended)"
        return label

    @staticmethod
    def _default_plan(
        plans,
        selected_plan_slug: str | None = None,
        *,
        beta_eligible: bool = False,
    ) -> ClarivoPlan | None:
        normalized_slug = normalize_plan_slug(selected_plan_slug)
        if beta_eligible and normalized_slug == BETA_PLAN_SLUG:
            selected_plan = plans.filter(slug=BETA_PLAN_SLUG).first()
            if selected_plan is not None:
                return selected_plan

        public_plan_slug = normalize_public_paid_plan_slug(selected_plan_slug)
        if public_plan_slug is not None:
            selected_plan = plans.filter(slug=public_plan_slug).first()
            if selected_plan is not None:
                return selected_plan

        default_plan = plans.filter(slug=DEFAULT_PUBLIC_PAID_PLAN_SLUG).first()
        if default_plan is not None:
            return default_plan

        recommended_plan = plans.filter(is_recommended=True).first()
        if recommended_plan is not None:
            return recommended_plan

        return plans.first()

    def clean_email(self) -> str:
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if TaskIOUser.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email

    def clean_business_email(self) -> str:
        return (self.cleaned_data.get("business_email") or "").strip().lower()

    def clean_plan(self) -> ClarivoPlan | None:
        plan = self.cleaned_data.get("plan")
        if plan is None:
            return None

        if plan.slug == BETA_PLAN_SLUG:
            if (
                not self.beta_eligible
                or not getattr(settings, "BETA_REGISTRATION_ENABLED", False)
                or not beta_registration_token_is_configured()
                or not plan.is_active
            ):
                raise ValidationError("Select a valid trial plan.")
            return plan

        if not is_public_paid_plan_slug(plan.slug):
            raise ValidationError("Select a valid trial plan.")

        return plan

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
                company_name=cleaned_data.get("business_name", ""),
            )
            try:
                password_validation.validate_password(password1, user=user)
            except ValidationError as exc:
                self.add_error("password1", exc)

        return cleaned_data

    @transaction.atomic
    def save(self) -> tuple[TaskIOUser, Business, BusinessUser, BusinessSubscription | None]:
        user = TaskIOUser.objects.create_user(
            email=self.cleaned_data["email"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            password=self.cleaned_data["password1"],
            incorporation_status="UNINCORPORATED",
            assigned_location="CARIBBEAN",
            company_name=self.cleaned_data["business_name"],
        )

        business = Business.objects.create(
            name=self.cleaned_data["business_name"],
            slug=generate_business_slug(self.cleaned_data["business_name"]),
            email=self.cleaned_data["business_email"],
            country=self.cleaned_data["country"],
        )

        membership = BusinessUser.objects.create(
            user=user,
            business=business,
            role=BusinessUser.Role.OWNER,
        )
        selected_plan = self.cleaned_data.get("plan")
        if selected_plan is not None and selected_plan.slug == BETA_PLAN_SLUG:
            subscription = BusinessSubscription.objects.create(
                business=business,
                plan=selected_plan,
                status=BusinessSubscription.Status.ACTIVE,
            )
        else:
            subscription = create_default_trial_subscription(
                business,
                plan=selected_plan,
            )

        profile = SaaSUserProfile.get_or_create_for_user(user)
        profile.workspace_name = business.name
        profile.billing_email = business.email or user.email
        profile.save(update_fields=["workspace_name", "billing_email", "updated_at"])

        return user, business, membership, subscription


class BusinessLoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": "form-control form-icon-input", "placeholder": "name@example.com"}
        ),
    )
    password = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control form-icon-input pe-6", "placeholder": "Password"}
        ),
    )

    def clean_email(self) -> str:
        return (self.cleaned_data.get("email") or "").strip().lower()


class MotionmatePasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(
            {
                "class": "form-control form-icon-input",
                "placeholder": "owner@example.com",
                "autocomplete": "email",
            }
        )


class MotionmateSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Create a new password",
                "autocomplete": "new-password",
            }
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Repeat your new password",
                "autocomplete": "new-password",
            }
        )


class MotionmatePasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Current password",
                "autocomplete": "current-password",
            }
        )
        self.fields["new_password1"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Create a new password",
                "autocomplete": "new-password",
            }
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Repeat your new password",
                "autocomplete": "new-password",
            }
        )


class InvitationExistingUserLoginForm(forms.Form):
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Enter your password"}
        ),
    )


class InvitationAcceptanceSignupForm(forms.Form):
    first_name = forms.CharField(
        label="First name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Jane"}),
    )
    last_name = forms.CharField(
        label="Last name",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Doe"}),
    )
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

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords do not match.")

        if password1:
            user = TaskIOUser(
                first_name=cleaned_data.get("first_name", ""),
                last_name=cleaned_data.get("last_name", ""),
            )
            try:
                password_validation.validate_password(password1, user=user)
            except ValidationError as exc:
                self.add_error("password1", exc)

        return cleaned_data

    def save(self, invitation: BusinessInvitation) -> TaskIOUser:
        user = TaskIOUser.objects.create_user(
            email=invitation.email,
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            password=self.cleaned_data["password1"],
            incorporation_status="UNINCORPORATED",
            assigned_location="CARIBBEAN",
            company_name=invitation.business.name,
        )
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
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "name@example.com"}
            ),
            "company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Acme Freight"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 721 555 0100"}
            ),
            "assigned_location": forms.Select(attrs={"class": "form-select"}),
            "date_of_birth": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
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
                attrs={"class": "form-control", "placeholder": "Motionmate Workspace"}
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
