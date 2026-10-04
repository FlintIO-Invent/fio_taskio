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
    CONVERSION_FIELDS = ("business_id", "enrolled_user_id", "converted_at", "converted_revision")
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
    business = models.OneToOneField(
        "businesses.Business",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_application",
        editable=False,
    )
    enrolled_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="logistics_applications",
        editable=False,
    )
    converted_at = models.DateTimeField(null=True, blank=True, editable=False)
    converted_revision = models.PositiveIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        business__isnull=True,
                        enrolled_user__isnull=True,
                        converted_at__isnull=True,
                        converted_revision__isnull=True,
                    )
                    | models.Q(
                        business__isnull=False,
                        enrolled_user__isnull=False,
                        converted_at__isnull=False,
                        converted_revision__isnull=False,
                    )
                ),
                name="logistics_conversion_complete_or_absent",
            )
        ]

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
            for name in self.CONVERSION_FIELDS:
                if getattr(self, name) != (getattr(previous, name) if previous else None):
                    raise ValidationError("Conversion fields must be changed through enrollment.")
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


class LogisticsEnrollmentToken(models.Model):
    """Only a digest is persisted; the bearer secret is returned once at issuance."""

    application = models.ForeignKey(
        LogisticsApplication, on_delete=models.CASCADE, related_name="enrollment_tokens"
    )
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    application_revision = models.PositiveIntegerField(editable=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="issued_logistics_enrollments",
    )

    class Meta:
        ordering = ["-created_at"]


def generate_tracking_code():
    """192 random bits, URL-safe, independent of the database identity."""
    import secrets

    return secrets.token_hex(24).upper()


class ParcelDomainQuerySet(models.QuerySet):
    """Normal ORM writes cannot bypass the parcel event services."""

    def update(self, **kwargs):
        raise ValidationError("Use the parcel services to change parcel data.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Use the parcel services to create parcel data.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Use the parcel services to change parcel data.")

    def delete(self):
        raise ValidationError("Parcel history can only be removed by the business purge workflow.")

    def _purge_delete(self):
        # Only the gated business purge calls this, after integrity checks.
        return super().delete()


class ParcelDomainModel(models.Model):
    objects = ParcelDomainQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        raise ValidationError("Use the parcel services to register parcels and append events.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Parcel history can only be removed by the business purge workflow.")

    def _validate_actor(self, field_name):
        from apps.businesses.models import BusinessUser

        actor_id = getattr(self, f"{field_name}_id")
        if (
            actor_id is not None
            and not BusinessUser.objects.filter(
                business_id=self.business_id,
                user_id=actor_id,
            ).exists()
        ):
            raise ValidationError({field_name: "Actor must belong to this workspace."})

    def _domain_save(self, **kwargs):
        self.full_clean()
        return super().save(**kwargs)


class Parcel(ParcelDomainModel):
    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Registered"
        RECEIVED = "RECEIVED", "Received"
        IN_TRANSIT = "IN_TRANSIT", "In transit"
        ARRIVED = "ARRIVED", "Arrived"
        READY = "READY", "Ready for collection / delivery"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"
        HOLD = "HOLD", "On hold"

    business = models.ForeignKey(
        "businesses.Business", on_delete=models.PROTECT, related_name="parcels"
    )
    client = models.ForeignKey("crm.Client", on_delete=models.PROTECT, related_name="parcels")
    tracking_code = models.CharField(
        max_length=48,
        unique=True,
        default=generate_tracking_code,
        editable=False,
        validators=[RegexValidator(r"\A[A-F0-9]{48}\Z")],
    )
    internal_reference = models.CharField(max_length=100, blank=True)
    origin = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    package_description = models.CharField(max_length=1000)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    dimensions = models.CharField(
        max_length=100, blank=True, help_text="Optional dimensions, including units."
    )
    declared_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    current_status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.REGISTERED, editable=False
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="registered_parcels",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["business", "current_status", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1), name="parcel_quantity_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(weight_kg__isnull=True) | models.Q(weight_kg__gte=0),
                name="parcel_weight_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(declared_value__isnull=True) | models.Q(declared_value__gte=0),
                name="parcel_value_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    current_status__in=[
                        "REGISTERED",
                        "RECEIVED",
                        "IN_TRANSIT",
                        "ARRIVED",
                        "READY",
                        "DELIVERED",
                        "CANCELLED",
                        "HOLD",
                    ]
                ),
                name="parcel_status_known",
            ),
        ]

    def __str__(self):
        return self.tracking_code

    def clean(self):
        from apps.businesses.models import Business
        from apps.crm.models import Client

        super().clean()
        if not Business.objects.filter(
            pk=self.business_id, vertical=Business.Vertical.LOGISTICS
        ).exists():
            raise ValidationError({"business": "Parcels require a Logistics workspace."})
        if (
            not self.client_id
            or not Client.objects.filter(pk=self.client_id, business_id=self.business_id).exists()
        ):
            raise ValidationError({"client": "Select a client owned by this workspace."})
        if self._state.adding:
            self._validate_actor("created_by")
        if self.pk and not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk, business_id=self.business_id).first()
            if previous is None:
                raise ValidationError("Parcel is unavailable in this workspace.")
            if (self.business_id, self.client_id, self.tracking_code) != (
                previous.business_id,
                previous.client_id,
                previous.tracking_code,
            ):
                raise ValidationError("Parcel ownership, client and tracking code are immutable.")


class ParcelEvent(ParcelDomainModel):
    class Type(models.TextChoices):
        STATUS = "STATUS", "Status change"
        NOTE = "NOTE", "Tracking update"

    business = models.ForeignKey(
        "businesses.Business", on_delete=models.PROTECT, related_name="parcel_events"
    )
    parcel = models.ForeignKey(Parcel, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=10, choices=Type.choices)
    status = models.CharField(max_length=20, choices=Parcel.Status.choices, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="parcel_events",
    )
    location = models.CharField(max_length=255, blank=True)
    public_message = models.CharField(max_length=1000, blank=True)
    internal_note = models.CharField(max_length=2000, blank=True)
    idempotency_key = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["timestamp", "pk"]
        indexes = [models.Index(fields=["business", "parcel", "timestamp"])]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "idempotency_key"], name="parcel_event_retry_unique"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(event_type="NOTE", status="")
                    | models.Q(
                        event_type="STATUS",
                        status__in=[
                            "REGISTERED",
                            "RECEIVED",
                            "IN_TRANSIT",
                            "ARRIVED",
                            "READY",
                            "DELIVERED",
                            "CANCELLED",
                            "HOLD",
                        ],
                    )
                ),
                name="parcel_event_status_consistent",
            ),
        ]

    def __str__(self):
        return f"{self.parcel_id}: {self.status or self.event_type}"

    def clean(self):
        super().clean()
        if not Parcel.objects.filter(pk=self.parcel_id, business_id=self.business_id).exists():
            raise ValidationError({"parcel": "Select a parcel owned by this workspace."})
        self._validate_actor("actor")
        if not self._state.adding:
            raise ValidationError("Parcel events are immutable.")
