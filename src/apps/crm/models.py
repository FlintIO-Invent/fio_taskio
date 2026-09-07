from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from apps.businesses.localization import format_crm_address, format_crm_address_lines


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def default_import_job_expiry():
    return timezone.now() + timedelta(hours=24)


class ImportJob(TimeStampedModel):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        VALIDATED = "validated", "Validated"
        READY = "ready", "Ready"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    class ImportType(models.TextChoices):
        CLIENTS = "clients", "Clients"
        LEADS = "leads", "Leads"
        SERVICES = "services", "Services"

    ALLOWED_STATUS_TRANSITIONS = {
        Status.UPLOADED: frozenset({Status.VALIDATED, Status.FAILED, Status.EXPIRED}),
        Status.VALIDATED: frozenset({Status.READY, Status.FAILED, Status.EXPIRED}),
        Status.READY: frozenset({Status.COMPLETED, Status.FAILED, Status.EXPIRED}),
        Status.COMPLETED: frozenset(),
        Status.FAILED: frozenset(),
        Status.EXPIRED: frozenset(),
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.CASCADE,
        related_name="import_jobs",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="crm_import_jobs",
    )
    import_type = models.CharField(max_length=20, choices=ImportType.choices)
    schema_version = models.CharField(max_length=20)
    original_filename = models.CharField(max_length=255)
    file_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    rows_detected = models.PositiveIntegerField(default=0)
    rows_valid = models.PositiveIntegerField(default=0)
    rows_warning = models.PositiveIntegerField(default=0)
    rows_error = models.PositiveIntegerField(default=0)
    rows_created = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(default=default_import_job_expiry)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["business", "import_type", "status"]),
            models.Index(fields=["created_by", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_import_type_display()} import {self.pk} ({self.status})"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    def validate_transition(self, new_status: str) -> str:
        try:
            current_status = self.Status(self.status)
            normalized_status = self.Status(new_status)
        except ValueError as exc:
            raise ValidationError({"status": "Unknown import job status."}) from exc
        if normalized_status not in self.ALLOWED_STATUS_TRANSITIONS[current_status]:
            raise ValidationError(
                {"status": f"Import job cannot move from {self.status} to {normalized_status}."}
            )
        return normalized_status

    def transition_to(self, new_status: str, *, at=None) -> None:
        normalized_status = self.validate_transition(new_status)
        transition_time = at or timezone.now()
        self.status = normalized_status
        update_fields = ["status", "updated_at"]
        if normalized_status == self.Status.COMPLETED:
            self.completed_at = transition_time
            update_fields.append("completed_at")
        self.save(update_fields=update_fields)

    def assert_usable(self, *, at=None) -> None:
        checked_at = at or timezone.now()
        if self.expires_at <= checked_at or self.status == self.Status.EXPIRED:
            raise ValidationError("This import preview has expired.", code="import_job_expired")
        if self.status in {self.Status.COMPLETED, self.Status.FAILED}:
            raise ValidationError(
                "This import preview can no longer be used.", code="import_job_unusable"
            )

    def assert_confirmable(self, *, at=None) -> None:
        self.assert_usable(at=at)
        if self.status != self.Status.READY:
            raise ValidationError(
                "This import preview is not ready for confirmation.",
                code="import_job_not_ready",
            )


class ServiceCategory(TimeStampedModel):
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_categories",
    )
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "code"],
                name="crm_service_category_unique_business_code",
            ),
        ]
        indexes = [
            models.Index(fields=["business", "is_active", "name"]),
        ]

    @classmethod
    def for_business(
        cls,
        business,
        *,
        include_inactive: bool = False,
    ) -> models.QuerySet[ServiceCategory]:
        if business is None:
            return cls.objects.none()

        queryset = cls.objects.filter(business=business)
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        return queryset.order_by("name", "pk")

    def _normalized_code(self) -> str:
        base_value = self.code or self.name
        return slugify(base_value).replace("-", "_") or "service_category"

    def _generate_unique_code(self) -> str:
        base_code = self._normalized_code()
        candidate = base_code
        suffix = 2

        existing_categories = self.__class__.objects.filter(
            business=self.business,
            code=candidate,
        )
        if self.pk:
            existing_categories = existing_categories.exclude(pk=self.pk)

        while existing_categories.exists():
            candidate = f"{base_code}_{suffix}"
            existing_categories = self.__class__.objects.filter(
                business=self.business,
                code=candidate,
            )
            if self.pk:
                existing_categories = existing_categories.exclude(pk=self.pk)
            suffix += 1

        return candidate

    def save(self, *args, **kwargs):
        self.code = self._generate_unique_code()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"code"}
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        if self.business_id is None:
            return self.name
        return f"{self.name} ({self.business})"


class BusinessService(TimeStampedModel):
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.CASCADE,
        related_name="business_services",
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="services",
    )
    name = models.CharField(max_length=160)
    external_code = models.CharField(max_length=80, null=True, blank=True)
    description = models.TextField(blank=True)
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    is_active = models.BooleanField(default=True)
    is_bookable_online = models.BooleanField(default=False)
    default_duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
    )
    booking_buffer_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    public_description = models.TextField(blank=True)
    requires_manual_confirmation = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "pk"]
        indexes = [
            models.Index(fields=["business", "is_active", "name"]),
            models.Index(fields=["business", "category", "is_active"]),
            models.Index(fields=["business", "is_bookable_online", "is_active"]),
        ]

    @classmethod
    def for_business(
        cls,
        business,
        *,
        include_inactive: bool = False,
    ) -> models.QuerySet[BusinessService]:
        if business is None:
            return cls.objects.none()

        queryset = cls.objects.filter(business=business)
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        return queryset.order_by("name", "pk")

    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        if self.category_id is None:
            category_is_valid = True
        else:
            category_is_valid = self.category.business_id == self.business_id

        if not category_is_valid:
            errors["category"] = "Selected service category must belong to the current workspace."

        if self.default_duration_minutes is not None and self.default_duration_minutes <= 0:
            errors["default_duration_minutes"] = "Default booking duration must be greater than zero."

        if self.booking_buffer_minutes is not None and self.booking_buffer_minutes < 0:
            errors["booking_buffer_minutes"] = "Booking buffer cannot be negative."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Lead(TimeStampedModel):
    class LeadType(models.TextChoices):
        REQUEST = "REQUEST", "Service Request"
        INTEREST = "INTEREST", "Interested (no request yet)"

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        CONTACTED = "CONTACTED", "Contacted"
        INVOICED = "INVOICED", "Invoiced"
        CLOSED = "CLOSED", "Closed"

    class RequestSource(models.TextChoices):
        PUBLIC_REQUEST = "public_request", "Public booking"
        PUBLIC_BOOKING = "public_booking", "Public booking"
        STAFF = "staff", "Staff-entered"
        OTHER = "other", "Other"

    class DistrictChoices(models.TextChoices):
        MIDDLE_REGION = "MIDDLEREGION", "Middle Region"
        DUTCH_QUARTER = "DUTCH_QUARTER", "Dutch Quarter"
        MADAME_ESTATE = "MADAMEESTATE", "Madame Estate"
        UNION_FARM = "UNIONFARM", "Union Farm"
        OYSTER_POND = "OYSTERPOND", "Oyster Pond"
        DEFIANCE = "DEFIANCE", "Defiance"
        SUCKERGARDEN = "SUCKERGARDEN", "Sucker Garden"
        HOPE_ESTATE = "HOPE_ESTATE", "Hope Estate"
        POINT_BLANCHE = "POINT_BLANCHE", "Point Blanche"
        GUANA_BAY = "GUANA_BAY", "Guana Bay"
        ST_PETERS = "ST_PETERS", "St. Peters"
        SOUTH_REWARD = "SOUTH_REWARD", "South Reward"
        ST_JOHN = "ST_JOHN", "St. John"
        EBENEZER = "EBENEZER", "Ebenezer"
        SAUNDERS = "SAUNDERS", "Saunders"
        MARYS_FANCY = "MARYS_FANCY", "Mary's Fancy"
        PHILIPSBURG = "PHILIPSBURG", "Philipsburg"
        BELAIR = "BELAIR", "Belair"
        INDIGO_BAY = "INDIGO_BAY", "Indigo Bay"
        COLE_BAY = "COLE_BAY", "Cole Bay"
        PELICAN_KEY = "PELICAN_KEY", "Pelican Key"
        SIMPSON_BAY = "SIMPSON_BAY", "Simpson Bay"
        MAHO = "MAHO", "Maho"

    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    lead_type           = models.CharField(max_length=20, choices=LeadType.choices, db_index=True)
    status              = models.CharField(max_length=20,choices=Status.choices,default=Status.NEW, db_index=True)
    category            = models.ForeignKey(ServiceCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads",)
    requested_service   = models.ForeignKey(BusinessService, on_delete=models.SET_NULL, null=True, blank=True, related_name="requested_leads")
    preferred_start_time = models.DateTimeField(null=True, blank=True)
    preferred_end_time  = models.DateTimeField(null=True, blank=True)
    request_source      = models.CharField(max_length=40, choices=RequestSource.choices, blank=True, default="")
    first_name          = models.CharField(max_length=80)
    last_name           = models.CharField(max_length=80)
    email               = models.EmailField()
    phone               = models.CharField(max_length=40)
    company_name        = models.CharField(max_length=120)
    message             = models.TextField(blank=True)
    street_address      = models.CharField(max_length=255, blank=True)
    district            = models.CharField(max_length=100, blank=True)
    country             = models.CharField(max_length=100, blank=True, default="Sint Maarten")
    postal_code         = models.CharField(max_length=20, blank=True, default="N/A")
    notes               = models.TextField(blank=True)
    consent_to_contact  = models.BooleanField(default=True)
    is_active           = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email

    @property
    def is_public_booking_request(self) -> bool:
        return self.request_source in {
            self.RequestSource.PUBLIC_BOOKING,
            self.RequestSource.PUBLIC_REQUEST,
        }

    @property
    def has_valid_requested_service(self) -> bool:
        return (
            self.requested_service_id is not None
            and self.requested_service is not None
            and self.business_id is not None
            and self.requested_service.business_id == self.business_id
            and self.requested_service.is_active
        )

    @property
    def requested_duration_minutes(self) -> int | None:
        if not self.preferred_start_time or not self.preferred_end_time:
            return None

        duration_seconds = (
            self.preferred_end_time - self.preferred_start_time
        ).total_seconds()
        if duration_seconds <= 0:
            return None
        return int(duration_seconds // 60)

    def get_district_display(self) -> str:
        return dict(self.DistrictChoices.choices).get(self.district, self.district)

    @property
    def formatted_address_lines(self) -> list[str]:
        return format_crm_address_lines(
            street_address=self.street_address,
            locality=self.get_district_display(),
            country=self.country,
            postal_code=self.postal_code,
        )

    @property
    def formatted_address(self) -> str:
        return format_crm_address(
            street_address=self.street_address,
            locality=self.get_district_display(),
            country=self.country,
            postal_code=self.postal_code,
        )


class Client(TimeStampedModel):

    class DistrictChoices(models.TextChoices):
        MIDDLE_REGION = "MIDDLEREGION", "Middle Region"
        DUTCH_QUARTER = "DUTCH_QUARTER", "Dutch Quarter"
        MADAME_ESTATE = "MADAMEESTATE", "Madame Estate"
        UNION_FARM = "UNIONFARM", "Union Farm"
        OYSTER_POND = "OYSTERPOND", "Oyster Pond"
        DEFIANCE = "DEFIANCE", "Defiance"
        SUCKERGARDEN = "SUCKERGARDEN", "Sucker Garden"
        HOPE_ESTATE = "HOPE_ESTATE", "Hope Estate"
        POINT_BLANCHE = "POINT_BLANCHE", "Point Blanche"
        GUANA_BAY = "GUANA_BAY", "Guana Bay"
        ST_PETERS = "ST_PETERS", "St. Peters"
        SOUTH_REWARD = "SOUTH_REWARD", "South Reward"
        ST_JOHN = "ST_JOHN", "St. John"
        EBENEZER = "EBENEZER", "Ebenezer"
        SAUNDERS = "SAUNDERS", "Saunders"
        MARYS_FANCY = "MARYS_FANCY", "Mary's Fancy"
        PHILIPSBURG = "PHILIPSBURG", "Philipsburg"
        BELAIR = "BELAIR", "Belair"
        INDIGO_BAY = "INDIGO_BAY", "Indigo Bay"
        COLE_BAY = "COLE_BAY", "Cole Bay"
        PELICAN_KEY = "PELICAN_KEY", "Pelican Key"
        SIMPSON_BAY = "SIMPSON_BAY", "Simpson Bay"
        MAHO = "MAHO", "Maho"

    class ClientType(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        BUSINESS = "BUSINESS", "Business"

    class ClientStatus(models.TextChoices):
        LEAD = "LEAD", "Lead"
        PROSPECT = "PROSPECT", "Prospect"
        ACTIVE = "ACTIVE", "Active Client"
        INACTIVE = "INACTIVE", "Inactive"
        ARCHIVED = "ARCHIVED", "Archived"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    class PreferredContactMethod(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        PHONE = "PHONE", "Phone"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    class LeadSource(models.TextChoices):
        WEBSITE = "WEBSITE", "Website"
        REFERRAL = "REFERRAL", "Referral"
        WALK_IN = "WALK_IN", "Walk-in"
        INSTAGRAM = "INSTAGRAM", "Instagram"
        FACEBOOK = "FACEBOOK", "Facebook"
        LINKEDIN = "LINKEDIN", "LinkedIn"
        PHONE = "PHONE", "Phone Inquiry"
        OTHER = "OTHER", "Other"

    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clients",
    )
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    email = models.EmailField()
    phone = models.CharField(max_length=40)

    # CRM business identity
    client_type = models.CharField(
        max_length=20,
        choices=ClientType.choices,
        default=ClientType.BUSINESS,
    )
    company_name = models.CharField(max_length=120)
    business_legal_name = models.CharField(max_length=160, blank=True)
    trade_name = models.CharField(max_length=160, blank=True)
    industry = models.CharField(max_length=100, blank=True)
    business_description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    registration_number = models.CharField(max_length=60, blank=True)

    # CRM contact context
    job_title = models.CharField(max_length=100, blank=True)
    department = models.CharField(max_length=100, blank=True)
    secondary_email = models.EmailField(blank=True)
    secondary_phone = models.CharField(max_length=40, blank=True)
    whatsapp_number = models.CharField(max_length=40, blank=True)
    preferred_contact_method = models.CharField(
        max_length=20,
        choices=PreferredContactMethod.choices,
        default=PreferredContactMethod.EMAIL,
    )
    preferred_language = models.CharField(max_length=50, blank=True)

    # CRM relationship / sales context
    client_status = models.CharField(
        max_length=20,
        choices=ClientStatus.choices,
        default=ClientStatus.LEAD,
    )
    lead_source = models.CharField(
        max_length=20,
        choices=LeadSource.choices,
        blank=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    interested_services = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_clients",
    )
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    next_follow_up_at = models.DateTimeField(null=True, blank=True)

    # Address / location
    street_address = models.CharField(max_length=255)
    district = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True, default="Sint Maarten")
    postal_code = models.CharField(max_length=20, blank=True, default="N/A")

    # Notes / communication
    message = models.TextField(blank=True)
    communication_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    consent_to_contact = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["first_name", "last_name"]

    def __str__(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        if self.company_name:
            return f"{name} - {self.company_name}"
        return name

    def get_district_display(self) -> str:
        return dict(self.DistrictChoices.choices).get(self.district, self.district)

    @property
    def formatted_address_lines(self) -> list[str]:
        return format_crm_address_lines(
            street_address=self.street_address,
            locality=self.get_district_display(),
            country=self.country,
            postal_code=self.postal_code,
        )

    @property
    def formatted_address(self) -> str:
        return format_crm_address(
            street_address=self.street_address,
            locality=self.get_district_display(),
            country=self.country,
            postal_code=self.postal_code,
        )


class ActivityLog(TimeStampedModel):
    class ActionType(models.TextChoices):
        EMAIL_SENT = "EMAIL_SENT", "Email Sent"
        INVOICE_CREATED = "INVOICE_CREATED", "Invoice Created"
        STATUS_CHANGED = "STATUS_CHANGED", "Status Changed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs"
    )
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs")

    action_type = models.CharField(max_length=40, choices=ActionType.choices)
    summary = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action_type} {self.created_at:%Y-%m-%d %H:%M}"
    

    
