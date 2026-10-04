import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.utils import timezone

from .policy import normalized_identity


class LogisticsApplication(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        DECLINED = "DECLINED", "Declined"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    class OperationType(models.TextChoices):
        COURIER = "COURIER", "Courier / local parcel delivery"
        FORWARDER = "FORWARDER", "Parcel / freight forwarding"
        COLLECTION = "COLLECTION", "Parcel collection / distribution"
        OTHER = "OTHER", "Other"

    class ProcessMethod(models.TextChoices):
        PAPER = "PAPER", "Paper / manual records"
        SPREADSHEETS = "SPREADSHEETS", "Spreadsheets"
        MESSAGING = "MESSAGING", "WhatsApp / messaging"
        SOFTWARE = "SOFTWARE", "Tracking software"
        OTHER = "OTHER", "Other"

    class Currency(models.TextChoices):
        USD = "USD", "US dollar (USD)"
        EUR = "EUR", "Euro (EUR)"

    MATERIAL_FIELDS = (
        "business_name",
        "trading_name",
        "contact_first_name",
        "contact_last_name",
        "email",
        "phone",
        "whatsapp",
        "country",
        "business_address",
        "registration_number",
        "website",
        "preferred_currency",
        "timezone",
        "operation_type",
        "routes",
        "monthly_parcel_estimate",
        "expected_staff_count",
        "location_count",
        "current_process_method",
        "current_process_details",
        "customer_tracking_needed",
        "manifest_needed",
        "api_integration_needed",
        "custom_workflow",
        "custom_workflow_details",
        "multi_jurisdiction",
        "custom_pricing_requested",
        "operational_notes",
    )
    DECISION_FIELDS = (
        "status",
        "revision",
        "approved_revision",
        "decision_result",
        "reason_codes",
        "evaluated_at",
        "evaluated_revision",
        "rule_version",
        "threshold_snapshot",
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_name = models.CharField("Legal / business name", max_length=120)
    trading_name = models.CharField(max_length=120, blank=True)
    contact_first_name = models.CharField(max_length=100)
    contact_last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(
        max_length=30, validators=[RegexValidator(r"^[+()\d .-]+$", "Enter a valid phone number.")]
    )
    whatsapp = models.CharField(
        "WhatsApp number",
        max_length=30,
        blank=True,
        validators=[RegexValidator(r"^[+()\d .-]+$", "Enter a valid phone number.")],
    )
    country = models.CharField("Country / territory", max_length=100)
    business_address = models.TextField(max_length=1000, validators=[MaxLengthValidator(1000)])
    registration_number = models.CharField(
        "Registration / company number", max_length=100, blank=True
    )
    website = models.URLField(blank=True)
    preferred_currency = models.CharField(max_length=3, choices=Currency.choices)
    timezone = models.CharField(max_length=100, default="UTC")
    operation_type = models.CharField(max_length=30, choices=OperationType.choices)
    routes = models.TextField(
        "Origins, destinations and routes", max_length=3000, validators=[MaxLengthValidator(3000)]
    )
    monthly_parcel_estimate = models.PositiveIntegerField(validators=[MinValueValidator(0)])
    expected_staff_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    location_count = models.PositiveIntegerField(
        "Location / branch count", validators=[MinValueValidator(1)]
    )
    current_process_method = models.CharField(max_length=30, choices=ProcessMethod.choices)
    current_process_details = models.TextField(
        blank=True, max_length=3000, validators=[MaxLengthValidator(3000)]
    )
    customer_tracking_needed = models.BooleanField(default=False)
    manifest_needed = models.BooleanField(default=False)
    api_integration_needed = models.BooleanField(default=False)
    custom_workflow = models.BooleanField(default=False)
    custom_workflow_details = models.TextField(
        blank=True, max_length=3000, validators=[MaxLengthValidator(3000)]
    )
    multi_jurisdiction = models.BooleanField(default=False)
    custom_pricing_requested = models.BooleanField(
        "Enterprise / custom pricing requested", default=False
    )
    operational_notes = models.TextField(
        blank=True, max_length=5000, validators=[MaxLengthValidator(5000)]
    )

    normalized_email = models.CharField(max_length=254, editable=False, db_index=True)
    normalized_business_name = models.CharField(max_length=120, editable=False, db_index=True)
    normalized_registration_number = models.CharField(
        max_length=100, blank=True, editable=False, db_index=True
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SUBMITTED, db_index=True
    )
    revision = models.PositiveIntegerField(default=1, editable=False)
    approved_revision = models.PositiveIntegerField(null=True, blank=True, editable=False)
    decision_result = models.CharField(max_length=20, blank=True, editable=False)
    reason_codes = models.JSONField(default=list, blank=True, editable=False)
    evaluated_at = models.DateTimeField(null=True, blank=True, editable=False)
    evaluated_revision = models.PositiveIntegerField(null=True, blank=True, editable=False)
    rule_version = models.CharField(max_length=100, blank=True, editable=False)
    threshold_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.business_name

    def material_inputs(self):
        return {name: getattr(self, name) for name in self.MATERIAL_FIELDS}

    def clean(self):
        super().clean()
        for name in self.MATERIAL_FIELDS:
            value = getattr(self, name)
            if isinstance(value, str):
                setattr(self, name, value.strip())
        self.email = self.email.casefold()
        errors = {}
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            errors["timezone"] = (
                "Enter a valid IANA timezone, such as America/Curacao or Europe/Amsterdam."
            )
        if self.custom_workflow and not self.custom_workflow_details:
            errors["custom_workflow_details"] = "Describe the custom workflow."
        if (
            self.current_process_method == self.ProcessMethod.OTHER
            and not self.current_process_details
        ):
            errors["current_process_details"] = "Describe your current process."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        from .services import reevaluate_application

        update_fields = kwargs.get("update_fields")
        if update_fields is not None and not update_fields:
            return
        with transaction.atomic():
            previous = (
                None
                if self._state.adding
                else type(self).objects.select_for_update().get(pk=self.pk)
            )
            for name in self.DECISION_FIELDS:
                expected = (
                    getattr(previous, name)
                    if previous
                    else self._meta.get_field(name).get_default()
                )
                if getattr(self, name) != expected:
                    raise ValidationError(
                        "Decision fields must be changed through the Logistics review workflow."
                    )
            if previous is not None and update_fields is not None:
                for name in self.MATERIAL_FIELDS:
                    if name not in update_fields:
                        setattr(self, name, getattr(previous, name))
            self.clean()
            self.normalized_email = self.email.casefold()
            self.normalized_business_name = normalized_identity(self.business_name)
            self.normalized_registration_number = normalized_identity(self.registration_number)
            self.full_clean()
            material_fields = (
                set(self.MATERIAL_FIELDS)
                if update_fields is None
                else set(update_fields) & set(self.MATERIAL_FIELDS)
            )
            changed = previous is None or any(
                getattr(self, name) != getattr(previous, name) for name in material_fields
            )
            if changed and previous is not None and previous.status == self.Status.WITHDRAWN:
                raise ValidationError("Withdrawn application details cannot be changed.")
            if changed and previous is not None:
                self.revision = previous.revision + 1
                self.status = self.Status.SUBMITTED
                self.approved_revision = None
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {
                    "normalized_email",
                    "normalized_business_name",
                    "normalized_registration_number",
                    "updated_at",
                }
                if changed:
                    kwargs["update_fields"] |= {"revision", "status", "approved_revision"}
            super().save(*args, **kwargs)
            if changed:
                reevaluate_application(self.pk)
                self.refresh_from_db()


class LogisticsApplicationDecision(models.Model):
    class Source(models.TextChoices):
        AUTOMATIC = "AUTOMATIC", "Automatic evaluation"
        MANUAL = "MANUAL", "Manual review"

    application = models.ForeignKey(
        LogisticsApplication, on_delete=models.PROTECT, related_name="decisions"
    )
    application_revision = models.PositiveIntegerField()
    result = models.CharField(max_length=20, choices=LogisticsApplication.Status.choices)
    evaluated_result = models.CharField(max_length=20)
    reason_codes = models.JSONField(default=list)
    evaluated_at = models.DateTimeField(default=timezone.now)
    rule_version = models.CharField(max_length=100)
    threshold_snapshot = models.JSONField()
    evaluated_inputs = models.JSONField()
    relationship_snapshot = models.JSONField()
    resource_classification = models.CharField(max_length=30)
    source = models.CharField(max_length=20, choices=Source.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="logistics_application_decisions",
    )
    actor_identifier = models.PositiveBigIntegerField(null=True, blank=True)
    override_reason = models.TextField(blank=True, max_length=3000)

    class Meta:
        ordering = ["-evaluated_at", "-pk"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Application decision history is immutable.")
        return super().save(*args, **kwargs)
