from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from apps.businesses.localization import (
    format_money_for_business,
    localized_price_input_example,
    parse_localized_decimal,
)
from apps.businesses.models import BusinessUser, WeeklyAvailability

from .models import BusinessService, Client, Lead, ServiceCategory
from .services import CLIENT_REQUIRED_FIELDS_FOR_REQUEST_CONVERSION


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


def _bookable_service_queryset(*, business=None):
    if business is None:
        return BusinessService.objects.none()

    return (
        BusinessService.objects.filter(
            business=business,
            is_active=True,
            is_bookable_online=True,
        )
        .select_related("business", "category")
        .order_by("name", "pk")
    )


def _public_booking_staff_queryset(*, business=None):
    if business is None:
        return get_user_model().objects.none()

    return (
        get_user_model()
        .objects.filter(
            business_memberships__business=business,
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


def _public_staff_label(user) -> str:
    get_full_name = getattr(user, "get_full_name", None)
    full_name = (get_full_name() if callable(get_full_name) else "") or getattr(
        user,
        "full_name",
        "",
    )
    full_name = full_name.strip()
    return full_name or user.email


def _timezone_for_business(business):
    timezone_name = getattr(business, "timezone", "") or "UTC"
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


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
                business_memberships__role__in=(
                    BusinessUser.Role.OWNER,
                    BusinessUser.Role.ADMIN,
                    BusinessUser.Role.STAFF,
                    BusinessUser.Role.ACCOUNTANT,
                ),
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
            "country": forms.TextInput(attrs={"class": "form-control", "placeholder": "Country"}),
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
            "lead_source": "Client source",
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
            "country": forms.TextInput(attrs={"class": "form-control", "placeholder": "Country"}),
            "postal_code": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Postal code"}
            ),
            "message": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Describe the service request context...",
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
            "lead_type": "Request type",
            "status": "Status",
            "street_address": "Street Address",
            "postal_code": "Postal Code",
            "consent_to_contact": "Contact consent received",
            "is_active": "Active service request",
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
            "country",  # make sure this exists in your model
            "postal_code",
            "message",
            "consent_to_contact",
        ]

        widgets = {
            # Dropdowns
            "lead_type": forms.Select(
                attrs={
                    "class": "form-select mb-3",
                }
            ),
            "category": forms.Select(
                attrs={
                    "class": "form-select mb-3",
                }
            ),
            "district": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "company_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "SimonSays N.V.",
                }
            ),
            # Text Inputs
            "first_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "First name",
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Last name",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "name@example.com",
                }
            ),
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "+1 (721) 456-7890",
                }
            ),
            "street_address": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Street address",
                }
            ),
            "country": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Country",
                    "value": "SXM",
                }
            ),
            "postal_code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Postal code",
                }
            ),
            # Textarea
            "message": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Tell us what you need...",
                }
            ),
            # Checkbox
            "consent_to_contact": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

        labels = {
            "lead_type": "What can we help with?",
            "category": "Service category",
            "street_address": "Street Address",
            "postal_code": "Postal Code",
            "consent_to_contact": "I consent to be contacted via email and phone for service requests and updates.",
        }


class PublicBookingForm(forms.Form):
    BOOK_NOW = "book_now"
    BOOK_LATER = "book_later"
    BOOKING_INTENT_CHOICES = (
        (BOOK_NOW, "Book an appointment now"),
        (BOOK_LATER, "Contact me before booking"),
    )

    booking_intent = forms.ChoiceField(
        choices=BOOKING_INTENT_CHOICES,
        required=False,
        label="When would you like to book?",
        widget=forms.Select(attrs={"class": "form-select mb-3"}),
    )
    service = forms.ModelChoiceField(
        queryset=BusinessService.objects.none(),
        empty_label="Select a service",
        label="Service",
        widget=forms.Select(attrs={"class": "form-select mb-3"}),
    )
    staff_member = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        empty_label="Select a staff member",
        required=False,
        label="Preferred staff member",
        widget=forms.Select(attrs={"class": "form-select mb-3"}),
    )
    preferred_date = forms.DateField(
        input_formats=["%Y-%m-%d"],
        required=False,
        label="Available date",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    preferred_time = forms.TimeField(
        input_formats=["%H:%M"],
        required=False,
        label="Available time",
        widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}, format="%H:%M"),
    )
    first_name = forms.CharField(
        max_length=80,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "First name"}),
    )
    last_name = forms.CharField(
        max_length=80,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Last name"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "name@example.com"}),
    )
    phone = forms.CharField(
        max_length=40,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "+1 (721) 456-7890"}),
    )
    company_name = forms.CharField(
        max_length=120,
        label="Company or household",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Company or household"}
        ),
    )
    street_address = forms.CharField(
        max_length=255,
        label="Service location",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Street address"}),
    )
    district = forms.ChoiceField(
        choices=[("", "---------"), *Lead.DistrictChoices.choices],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    country = forms.CharField(
        max_length=100,
        required=False,
        initial="Sint Maarten",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Country"}),
    )
    postal_code = forms.CharField(
        max_length=20,
        required=False,
        initial="N/A",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Postal code"}),
    )
    message = forms.CharField(
        required=False,
        label="Message / notes",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Anything the team should know before confirming?",
            }
        ),
    )
    consent_to_contact = forms.BooleanField(
        label="I consent to be contacted about this booking request.",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(
        self,
        *args,
        business=None,
        booking_settings=None,
        selected_service_id=None,
        appointments_enabled=True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.business = business
        self.booking_settings = booking_settings
        self.appointments_enabled = appointments_enabled
        self.fields["booking_intent"].initial = (
            self.BOOK_NOW if appointments_enabled else self.BOOK_LATER
        )
        if not appointments_enabled:
            self.fields["booking_intent"].choices = (
                (self.BOOK_LATER, "Contact me before booking"),
            )
        self.fields["service"].queryset = _bookable_service_queryset(business=business)
        self.fields["service"].label_from_instance = (
            lambda service: f"{service.name} - {format_money_for_business(service.unit_price, business)}"
        )
        self.fields["staff_member"].queryset = _public_booking_staff_queryset(
            business=business,
        )
        self.fields["staff_member"].label_from_instance = _public_staff_label

        if selected_service_id:
            try:
                selected_service_pk = int(selected_service_id)
            except (TypeError, ValueError):
                selected_service_pk = None
            if (
                selected_service_pk
                and self.fields["service"]
                .queryset.filter(
                    pk=selected_service_pk,
                )
                .exists()
            ):
                self.fields["service"].initial = selected_service_pk

    def clean(self):
        cleaned_data = super().clean()

        business = self.business
        booking_settings = self.booking_settings
        booking_intent = cleaned_data.get("booking_intent") or self.BOOK_LATER
        service = cleaned_data.get("service")
        staff_member = cleaned_data.get("staff_member")
        preferred_date = cleaned_data.get("preferred_date")
        preferred_time = cleaned_data.get("preferred_time")
        wants_appointment = booking_intent == self.BOOK_NOW

        cleaned_data["booking_intent"] = booking_intent

        if business is None or booking_settings is None:
            raise forms.ValidationError("Booking requests are unavailable right now.")

        if service is not None and service.business_id != business.id:
            self.add_error("service", "Select a valid service.")

        if wants_appointment and not self.appointments_enabled:
            self.add_error(
                "booking_intent",
                "Online appointment booking is unavailable right now.",
            )

        if wants_appointment and staff_member is None:
            self.add_error("staff_member", "Select the staff member you want to book with.")

        if wants_appointment and preferred_date is None:
            self.add_error("preferred_date", "Select an available date.")

        if wants_appointment and preferred_time is None:
            self.add_error("preferred_time", "Select an available time.")

        if not (service and preferred_date and preferred_time):
            return cleaned_data

        business_tz = _timezone_for_business(business)
        preferred_start_time = datetime.combine(
            preferred_date,
            preferred_time,
            tzinfo=business_tz,
        )
        duration_minutes = (
            service.default_duration_minutes or booking_settings.default_duration_minutes
        )
        preferred_end_time = preferred_start_time + timedelta(minutes=duration_minutes)

        if preferred_end_time <= preferred_start_time:
            self.add_error("preferred_time", "Preferred end time must be after the start time.")
            return cleaned_data

        local_now = timezone.now().astimezone(business_tz)
        earliest_start_time = local_now + timedelta(
            hours=booking_settings.minimum_notice_hours,
        )
        if preferred_start_time < earliest_start_time:
            self.add_error(
                "preferred_time",
                "Choose a time with enough advance notice.",
            )

        latest_date = local_now.date() + timedelta(
            days=booking_settings.maximum_days_ahead,
        )
        if preferred_start_time.date() > latest_date:
            self.add_error(
                "preferred_date",
                "Choose a date within the booking window.",
            )

        if preferred_end_time.date() != preferred_start_time.date():
            self.add_error(
                "preferred_time",
                "Choose a time that ends within the same business day.",
            )
        else:
            availability_exists = WeeklyAvailability.objects.filter(
                business=business,
                day_of_week=preferred_start_time.weekday(),
                is_active=True,
                start_time__lte=preferred_start_time.time(),
                end_time__gte=preferred_end_time.time(),
            ).exists()
            if not availability_exists:
                self.add_error(
                    "preferred_time",
                    "Choose a time within the business's available hours.",
                )

        if staff_member is not None:
            from apps.appointments.models import Appointment

            has_conflict = Appointment.objects.filter(
                business=business,
                staff_member=staff_member,
                status=Appointment.Status.SCHEDULED,
                start_time__lt=preferred_end_time,
                end_time__gt=preferred_start_time,
            ).exists()
            if has_conflict:
                self.add_error(
                    "preferred_time",
                    "That staff member is already booked at the selected time.",
                )

        cleaned_data["preferred_start_time"] = preferred_start_time
        cleaned_data["preferred_end_time"] = preferred_end_time
        cleaned_data["duration_minutes"] = duration_minutes
        return cleaned_data


class LeadClientConversionForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = [
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
            "consent_to_contact",
        ]
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "First name"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Last name"}
            ),
            "company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Company name"}
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
            "country": forms.TextInput(attrs={"class": "form-control", "placeholder": "Country"}),
            "postal_code": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Postal code"}
            ),
            "message": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Add any extra service request context for your team...",
                }
            ),
            "consent_to_contact": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "company_name": "Company name",
            "street_address": "Street address",
            "postal_code": "Postal code",
            "consent_to_contact": "Client contact consent confirmed",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in CLIENT_REQUIRED_FIELDS_FOR_REQUEST_CONVERSION:
            self.fields[field_name].required = True

        if not self.instance.country:
            self.fields["country"].initial = "Sint Maarten"
        if not self.instance.postal_code or self.instance.postal_code == "N/A":
            self.fields["postal_code"].initial = self.instance.postal_code or "N/A"


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
            "code": "Optional. If left blank, Motionmate will generate a workspace-specific code from the name.",
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
            raise forms.ValidationError(
                "A current business is required to manage service categories."
            )

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


class BusinessServiceForm(forms.ModelForm):
    unit_price = forms.CharField(
        label="Unit price",
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "decimal"}),
    )
    tax_rate = forms.CharField(
        label="Tax rate",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "decimal"}),
    )

    class Meta:
        model = BusinessService
        fields = [
            "category",
            "name",
            "external_code",
            "description",
            "unit_price",
            "tax_rate",
            "is_active",
            "is_bookable_online",
            "default_duration_minutes",
            "booking_buffer_minutes",
            "public_description",
            "requires_manual_confirmation",
        ]
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Emergency plumbing callout"}
            ),
            "external_code": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "optional-external-code"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Describe what this service includes...",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_bookable_online": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "default_duration_minutes": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "step": 1}
            ),
            "booking_buffer_minutes": forms.NumberInput(
                attrs={"class": "form-control", "min": 0, "step": 1}
            ),
            "public_description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Describe this service for public booking requests.",
                }
            ),
            "requires_manual_confirmation": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }
        labels = {
            "is_bookable_online": "Bookable online",
            "default_duration_minutes": "Default booking duration",
            "booking_buffer_minutes": "Booking buffer",
            "public_description": "Public description",
            "requires_manual_confirmation": "Requires manual confirmation",
        }
        help_texts = {
            "external_code": "Optional. Useful for matching future CSV imports without guessing by name.",
            "is_bookable_online": "Only services marked bookable online will appear later on the public booking form.",
            "default_duration_minutes": "Optional service-specific duration in minutes. Leave blank to use workspace booking settings.",
            "booking_buffer_minutes": "Optional service-specific buffer in minutes. Leave blank to use workspace booking settings.",
            "public_description": "Optional public-facing copy for the future booking form.",
            "requires_manual_confirmation": "Manual confirmation is the current supported Motionmate booking behavior.",
        }

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        if business is not None:
            self.instance.business = business
        self.fields["category"].required = False
        self.fields["external_code"].required = False
        self.fields["tax_rate"].required = False
        self.fields["default_duration_minutes"].required = False
        self.fields["booking_buffer_minutes"].required = False
        self.fields["requires_manual_confirmation"].initial = True
        self.fields["category"].queryset = _service_category_queryset(
            business=business,
            instance=self.instance,
        )

        if business is not None and not self.instance.pk:
            self.fields["tax_rate"].initial = business.tax_rate
        if business is not None:
            price_example = localized_price_input_example(business)
            self.fields["unit_price"].help_text = (
                f"Stored as a decimal. Display uses {business.currency} and workspace locale. "
                f"Example: {price_example}."
            )
            self.fields["tax_rate"].help_text = (
                f"Leave blank to use the workspace default {business.tax_label} rate "
                f"of {business.tax_rate:.2f}% for new services. Existing services keep their "
                "current tax rate when this field is left blank."
            )

    def clean_external_code(self):
        external_code = (self.cleaned_data.get("external_code") or "").strip()
        return external_code or None

    def clean_unit_price(self):
        value = self.cleaned_data.get("unit_price")
        try:
            unit_price = parse_localized_decimal(value, self.business)
        except InvalidOperation as exc:
            raise forms.ValidationError("Enter a valid price.") from exc

        if unit_price < Decimal("0.00"):
            raise forms.ValidationError("Price cannot be negative.")

        return unit_price

    def clean_tax_rate(self):
        value = self.cleaned_data.get("tax_rate")
        if value in (None, ""):
            return None

        try:
            tax_rate = parse_localized_decimal(value, self.business)
        except InvalidOperation as exc:
            raise forms.ValidationError("Enter a valid tax rate.") from exc

        if tax_rate < Decimal("0.00") or tax_rate > Decimal("100.00"):
            raise forms.ValidationError("Tax rate must be between 0 and 100.")

        return tax_rate

    def clean(self):
        cleaned_data = super().clean()

        if not self.business:
            raise forms.ValidationError("A current business is required to manage services.")

        if cleaned_data.get("tax_rate") in (None, ""):
            if self.instance.pk:
                cleaned_data["tax_rate"] = self.instance.tax_rate
            else:
                cleaned_data["tax_rate"] = self.business.tax_rate or Decimal("0.00")

        external_code = cleaned_data.get("external_code")
        if external_code:
            queryset = BusinessService.objects.filter(
                business=self.business,
                external_code__iexact=external_code,
            )
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                self.add_error(
                    "external_code",
                    "This external code is already used in the current workspace.",
                )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.business = self.business
        instance.tax_rate = self.cleaned_data.get("tax_rate", instance.tax_rate)
        instance.external_code = self.cleaned_data.get("external_code")
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class BusinessServiceCSVImportForm(forms.Form):
    csv_file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".csv,text/csv"})
    )
