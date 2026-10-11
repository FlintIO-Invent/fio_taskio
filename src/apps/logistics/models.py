import uuid
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.utils import timezone

from .classification import (
    ClassificationHelpers,
    TransportationMode,
    default_operating_areas,
    normalize_classification,
    validate_classification,
    validate_operating_areas,
    validate_transportation_modes,
)
from .location_reference import (
    country_choices,
    exact_country_code,
    location_references,
    reference_choices,
    validate_country_code,
    validate_reference_code,
    validate_route_locations,
)
from .policy import normalized_identity
from .tracking_codes import (
    TRACKING_CODE_ALPHABET,
    TRACKING_CODE_PREFIX,
    TRACKING_CODE_REGEX,
    TRACKING_CODE_SUFFIX_LENGTH,
)


class LogisticsTestLabAudit(models.Model):
    """Non-secret operation references retained even after guarded lab cleanup."""

    fixture_version = models.CharField(max_length=80)
    environment = models.CharField(max_length=20)
    business_id_snapshot = models.PositiveBigIntegerField()
    action = models.CharField(max_length=30)
    reason_reference = models.CharField(max_length=120)
    approval_reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class LogisticsProfile(ClassificationHelpers, models.Model):
    business = models.OneToOneField(
        "businesses.Business", on_delete=models.CASCADE, related_name="logistics_profile"
    )
    operating_areas = models.JSONField(
        default=default_operating_areas, validators=[validate_operating_areas], blank=True
    )
    transportation_modes = models.JSONField(
        default=list, validators=[validate_transportation_modes], blank=True
    )
    location_access_reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    location_operations_enabled_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Logistics profile for {self.business}"

    def clean(self):
        super().clean()
        from apps.businesses.models import Business

        if self.business_id and self.business.vertical != Business.Vertical.LOGISTICS:
            raise ValidationError(
                {"business": "Only LOGISTICS businesses have a Logistics profile."}
            )
        validate_classification(self.operating_areas, self.transportation_modes)
        normalize_classification(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class LogisticsApplication(ClassificationHelpers, models.Model):
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
        "operating_areas",
        "transportation_modes",
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
    CONVERSION_FIELDS = (
        "business_id",
        "business_id_snapshot",
        "enrolled_user_id",
        "converted_at",
        "converted_revision",
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
    country_code = models.CharField(
        max_length=2, null=True, blank=True, editable=False, validators=[validate_country_code]
    )
    location_review_required = models.BooleanField(default=False, editable=False)
    business_address = models.TextField(max_length=1000, validators=[MaxLengthValidator(1000)])
    registration_number = models.CharField(
        "Registration / company number", max_length=100, blank=True
    )
    website = models.URLField(blank=True)
    preferred_currency = models.CharField(max_length=3, choices=Currency.choices)
    timezone = models.CharField(max_length=100, default="UTC")
    operating_areas = models.JSONField(
        default=list, validators=[validate_operating_areas], blank=True
    )
    transportation_modes = models.JSONField(
        default=list, validators=[validate_transportation_modes], blank=True
    )
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
    business_id_snapshot = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

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
                        business_id_snapshot__isnull=True,
                    )
                    | (
                        models.Q(
                            enrolled_user__isnull=False,
                            converted_at__isnull=False,
                            converted_revision__isnull=False,
                        )
                        & (
                            models.Q(business__isnull=False)
                            | models.Q(business_id_snapshot__isnull=False)
                        )
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
        self.country_code = exact_country_code(self.country)
        self.location_review_required = bool(self.country and not self.country_code)
        # Historical applications did not collect classification. Preserve their
        # unrecorded values on unrelated edits; all new/classification edits validate.
        legacy = (
            not self._state.adding
            and not self.operating_areas
            and not self.transportation_modes
            and type(self)
            .objects.filter(pk=self.pk, operating_areas=[], transportation_modes=[])
            .exists()
        )
        validate_classification(
            self.operating_areas,
            self.transportation_modes,
            require_areas=not legacy,
            require_modes=not legacy,
        )
        normalize_classification(self)
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
                    "country_code",
                    "location_review_required",
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
    """Readable V2 bearer secret with at least the legacy 192 bits of entropy."""
    import secrets

    return TRACKING_CODE_PREFIX + "".join(
        secrets.choice(TRACKING_CODE_ALPHABET) for _ in range(TRACKING_CODE_SUFFIX_LENGTH)
    )


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
        # Controlled tenant purge or ownership-validated demo reset only.
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


class LogisticsLocation(models.Model):
    """A company's facility, distinct from geography and public port references."""

    class Type(models.TextChoices):
        PORT = "PORT", "Port"
        AIRPORT = "AIRPORT", "Airport"
        WAREHOUSE = "WAREHOUSE", "Warehouse"
        BRANCH = "BRANCH", "Branch"
        HUB = "HUB", "Hub"
        PICKUP_POINT = "PICKUP_POINT", "Pickup point"
        OTHER = "OTHER", "Other"

    business = models.ForeignKey(
        "businesses.Business", on_delete=models.PROTECT, related_name="logistics_locations"
    )
    name = models.CharField("Canonical name", max_length=160)
    code = models.CharField(
        "Stable short code",
        max_length=20,
        validators=[
            RegexValidator(
                r"\A[A-Za-z][A-Za-z0-9-]{1,19}\Z",
                "Use 2–20 letters, numbers or hyphens, starting with a letter.",
            )
        ],
    )
    location_type = models.CharField(max_length=12, choices=Type.choices)
    country_code = models.CharField(
        "Country / territory",
        max_length=2,
        choices=country_choices,
        validators=[validate_country_code],
    )
    reference_code = models.CharField(
        "Verified port / airport reference",
        max_length=5,
        blank=True,
        choices=reference_choices,
        validators=[validate_reference_code],
    )
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("code"), "business", name="logistics_location_code_unique"
            ),
            models.UniqueConstraint(
                models.functions.Lower("name"), "business", name="logistics_location_name_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    location_type__in=[
                        "PORT",
                        "AIRPORT",
                        "WAREHOUSE",
                        "BRANCH",
                        "HUB",
                        "PICKUP_POINT",
                        "OTHER",
                    ]
                ),
                name="logistics_location_type_known",
            ),
        ]

    def __str__(self):
        return f"{self.code} · {self.name} · {self.country_code}" + (
            " (inactive)" if not self.is_active else ""
        )

    def clean(self):
        from apps.businesses.models import Business

        super().clean()
        self.name = self.name.strip()
        self.code = self.code.strip().upper()
        if not self.name:
            raise ValidationError({"name": "Enter a canonical name."})
        if not Business.objects.filter(
            pk=self.business_id, vertical=Business.Vertical.LOGISTICS
        ).exists():
            raise ValidationError({"business": "Locations require a Logistics workspace."})
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and (self.business_id, self.code, self.country_code) != (
                previous.business_id,
                previous.code,
                previous.country_code,
            ):
                raise ValidationError("Location ownership, short code and country are immutable.")
        reference = location_references().get(self.reference_code)
        if reference and (
            reference["country_code"] != self.country_code
            or self.location_type not in reference["types"]
        ):
            raise ValidationError(
                {"reference_code": "Select a reference matching this location's country and type."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class LogisticsRouteFields(models.Model):
    origin_country_code = models.CharField(
        "Origin country / territory",
        max_length=2,
        null=True,
        blank=True,
        choices=country_choices,
        validators=[validate_country_code],
    )
    destination_country_code = models.CharField(
        "Destination country / territory",
        max_length=2,
        null=True,
        blank=True,
        choices=country_choices,
        validators=[validate_country_code],
    )
    origin_location = models.ForeignKey(
        LogisticsLocation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="%(class)s_origins",
        verbose_name="Origin company facility",
    )
    destination_location = models.ForeignKey(
        LogisticsLocation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="%(class)s_destinations",
        verbose_name="Destination company facility",
    )
    origin_reference_code = models.CharField(
        "Origin port / airport reference",
        max_length=5,
        blank=True,
        choices=reference_choices,
        validators=[validate_reference_code],
    )
    destination_reference_code = models.CharField(
        "Destination port / airport reference",
        max_length=5,
        blank=True,
        choices=reference_choices,
        validators=[validate_reference_code],
    )
    location_review_required = models.BooleanField(default=False, editable=False)

    class Meta:
        abstract = True


class Parcel(ParcelDomainModel, LogisticsRouteFields):
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
    shipment = models.ForeignKey(
        "Shipment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="parcels",
        editable=False,
    )
    tracking_code = models.CharField(
        max_length=48,
        unique=True,
        default=generate_tracking_code,
        editable=False,
        validators=[RegexValidator(TRACKING_CODE_REGEX)],
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
    hs_code = models.CharField("HS code", max_length=100, blank=True)
    marks_numbers = models.CharField("Marks and numbers", max_length=100, blank=True)
    length_cm = models.DecimalField(
        "Length (cm)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    width_cm = models.DecimalField(
        "Width (cm)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    height_cm = models.DecimalField(
        "Height (cm)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    volume_m3 = models.DecimalField(
        "Volume (m³)",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    sender_name = models.CharField(max_length=255, blank=True)
    sender_contact = models.CharField(max_length=100, blank=True)
    sender_address = models.CharField(max_length=1000, blank=True)
    sender_address_line_1 = models.CharField(
        "Sender address line 1", max_length=255, null=True, blank=True
    )
    sender_address_line_2 = models.CharField(
        "Sender address line 2", max_length=255, null=True, blank=True
    )
    sender_city = models.CharField(max_length=100, null=True, blank=True)
    sender_region = models.CharField(max_length=100, null=True, blank=True)
    sender_postal_code = models.CharField(max_length=32, null=True, blank=True)
    sender_country_code = models.CharField(
        "Sender country code",
        max_length=3,
        blank=True,
        validators=[
            RegexValidator(r"\A[A-Za-z]{2,3}\Z", "Use a two or three letter country code.")
        ],
    )
    sender_tax_id = models.CharField("Sender tax ID", max_length=100, blank=True)
    recipient_name = models.CharField(max_length=255, blank=True)
    recipient_contact = models.CharField(max_length=100, blank=True)
    recipient_address = models.CharField(max_length=1000, blank=True)
    recipient_address_line_1 = models.CharField(
        "Recipient address line 1", max_length=255, null=True, blank=True
    )
    recipient_address_line_2 = models.CharField(
        "Recipient address line 2", max_length=255, null=True, blank=True
    )
    recipient_city = models.CharField(max_length=100, null=True, blank=True)
    recipient_region = models.CharField(max_length=100, null=True, blank=True)
    recipient_postal_code = models.CharField(max_length=32, null=True, blank=True)
    recipient_country_code = models.CharField(
        "Recipient country / territory", max_length=2, null=True, blank=True
    )
    mode_of_transport = models.CharField(max_length=100, blank=True)
    vessel_name = models.CharField("Vessel / carrier name", max_length=255, blank=True)
    voyage_no = models.CharField("Voyage number", max_length=100, blank=True)
    imo_no = models.CharField("IMO number", max_length=100, blank=True)
    port_load_unlocode = models.CharField("Loading port (UN/LOCODE)", max_length=100, blank=True)
    port_discharge_unlocode = models.CharField(
        "Discharge port (UN/LOCODE)", max_length=100, blank=True
    )
    master_bl_no = models.CharField("Master bill of lading", max_length=100, blank=True)
    house_bl_no = models.CharField("House bill of lading", max_length=100, blank=True)
    issue_date = models.DateField("Document issue date", null=True, blank=True)
    incoterms = models.CharField("Incoterms", max_length=100, blank=True)
    fragile_goods = models.BooleanField("Fragile goods", default=False)
    biodegradable_goods = models.BooleanField("Biodegradable goods", default=False)
    expiry_date = models.DateField(null=True, blank=True)
    internal_notes = models.CharField("Internal notes", max_length=2000, blank=True)
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
        validate_route_locations(self)
        if self.sender_country_code:
            self.sender_country_code = self.sender_country_code.upper()
            if not exact_country_code(self.sender_country_code):
                previous_country = (
                    type(self)
                    .objects.filter(pk=self.pk)
                    .values_list("sender_country_code", flat=True)
                    .first()
                    if not self._state.adding
                    else None
                )
                if self.sender_country_code != previous_country:
                    raise ValidationError(
                        {"sender_country_code": "Select a valid ISO country or territory."}
                    )
        self.recipient_country_code = self.recipient_country_code or None
        if self.recipient_country_code:
            self.recipient_country_code = self.recipient_country_code.upper()
            validate_country_code(self.recipient_country_code)
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
        if (
            self.shipment_id
            and not Shipment.objects.filter(
                pk=self.shipment_id, business_id=self.business_id
            ).exists()
        ):
            raise ValidationError({"shipment": "Select a shipment owned by this workspace."})
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
    operational_location = models.ForeignKey(
        LogisticsLocation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="parcel_events",
        editable=False,
    )
    previous_status = models.CharField(
        max_length=20, choices=Parcel.Status.choices, null=True, blank=True, editable=False
    )
    resulting_status = models.CharField(
        max_length=20, choices=Parcel.Status.choices, null=True, blank=True, editable=False
    )
    location_override_reason = models.CharField(max_length=1000, blank=True, editable=False)
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
        if (
            self.operational_location_id
            and not LogisticsLocation.objects.filter(
                pk=self.operational_location_id, business_id=self.business_id
            ).exists()
        ):
            raise ValidationError("Operational location must belong to this workspace.")
        if self.operational_location_id and not self.actor_id:
            raise ValidationError("Verified operational events require an authenticated actor.")
        if self.resulting_status and self.status and self.resulting_status != self.status:
            raise ValidationError("Event resulting state must match its transition status.")
        if not self._state.adding:
            raise ValidationError("Parcel events are immutable.")


def generate_shipment_reference():
    return f"SHP-{uuid.uuid4().hex.upper()}"


class Shipment(ParcelDomainModel, LogisticsRouteFields):
    """One operational grouping; all writes go through shipment_services."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        READY = "READY", "Ready"
        IN_TRANSIT = "IN_TRANSIT", "In transit"
        ARRIVED = "ARRIVED", "Arrived"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    business = models.ForeignKey(
        "businesses.Business", on_delete=models.PROTECT, related_name="shipments"
    )
    reference = models.CharField(
        max_length=36, unique=True, default=generate_shipment_reference, editable=False
    )
    origin = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    transport_mode = models.CharField(
        "Transportation mode",
        max_length=4,
        choices=TransportationMode.choices,
        null=True,
        blank=True,
    )
    carrier_name = models.CharField("Carrier", max_length=160, null=True, blank=True)
    vessel_name = models.CharField("Vessel", max_length=160, null=True, blank=True)
    voyage_reference = models.CharField("Voyage", max_length=100, null=True, blank=True)
    container_reference = models.CharField("Container", max_length=100, null=True, blank=True)
    bill_of_lading_reference = models.CharField(
        "Bill of Lading", max_length=100, null=True, blank=True
    )
    vehicle_reference = models.CharField("Vehicle", max_length=100, null=True, blank=True)
    driver_name = models.CharField("Driver", max_length=160, null=True, blank=True)
    dispatch_reference = models.CharField(
        "Dispatch Reference", max_length=100, null=True, blank=True
    )
    departure_at = models.DateTimeField(null=True, blank=True)
    estimated_arrival_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, editable=False
    )
    notes = models.TextField(blank=True, max_length=2000, validators=[MaxLengthValidator(2000)])
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_shipments",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    idempotency_key = models.UUIDField(null=True, blank=True, editable=False)
    revision = models.PositiveBigIntegerField(default=1, editable=False)
    write_receipts = models.JSONField(default=dict, blank=True, editable=False)
    operation_history = models.JSONField(default=list, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["business", "status", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["DRAFT", "READY", "IN_TRANSIT", "ARRIVED", "COMPLETED", "CANCELLED"]
                ),
                name="shipment_status_known",
            ),
            models.UniqueConstraint(
                fields=["business", "idempotency_key"], name="shipment_creation_retry_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(transport_mode__isnull=True)
                | models.Q(transport_mode__in=TransportationMode.values),
                name="shipment_transport_mode_known",
            ),
        ]

    def __str__(self):
        return self.reference

    @property
    def transportation_details(self):
        from .shipment_references import populated_transport_references

        return populated_transport_references(self, include_historical=True)

    def clean(self):
        from apps.businesses.models import Business

        super().clean()
        if not Business.objects.filter(
            pk=self.business_id, vertical=Business.Vertical.LOGISTICS
        ).exists():
            raise ValidationError({"business": "Shipments require a Logistics workspace."})
        validate_route_locations(self)
        if self._state.adding:
            self._validate_actor("created_by")
        else:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous is None or (
                self.business_id,
                self.reference,
                self.created_by_id,
                self.idempotency_key,
            ) != (
                previous.business_id,
                previous.reference,
                previous.created_by_id,
                previous.idempotency_key,
            ):
                raise ValidationError(
                    "Shipment ownership, reference, creator and creation retry key are immutable."
                )
        if self.departure_at and self.estimated_arrival_at:
            if self.estimated_arrival_at < self.departure_at:
                raise ValidationError({"estimated_arrival_at": "ETA cannot precede departure."})

    def save(self, *args, **kwargs):
        raise ValidationError("Use the shipment services to change shipments.")


class LogisticsCharge(ParcelDomainModel):
    """A saved charge snapshot awaiting attachment to the existing invoice system."""

    business = models.ForeignKey(
        "businesses.Business", on_delete=models.PROTECT, related_name="logistics_charges"
    )
    client = models.ForeignKey(
        "crm.Client", on_delete=models.PROTECT, related_name="logistics_charges"
    )
    parcel = models.ForeignKey(
        Parcel, on_delete=models.PROTECT, null=True, blank=True, related_name="charges"
    )
    shipment = models.ForeignKey(
        Shipment, on_delete=models.PROTECT, null=True, blank=True, related_name="charges"
    )
    service = models.ForeignKey(
        "crm.BusinessService",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="logistics_charges",
    )
    target_reference = models.CharField(max_length=100)
    description = models.CharField(max_length=160)
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=1, validators=[MinValueValidator(Decimal("0.01"))]
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)]
    )
    invoice_line = models.OneToOneField(
        "billings.InvoiceLine",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="logistics_charge",
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="logistics_charges",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(parcel__isnull=False, shipment__isnull=True)
                    | models.Q(parcel__isnull=True, shipment__isnull=False)
                ),
                name="logistics_charge_one_target",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0, unit_price__gte=0),
                name="logistics_charge_positive_amounts",
            ),
            models.UniqueConstraint(
                fields=["business", "idempotency_key"], name="logistics_charge_retry_unique"
            ),
        ]

    @property
    def total(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def invoice_description(self):
        target = f"{'Parcel' if self.parcel_id else 'Shipment'} {self.target_reference}"
        return f"{self.description[: 255 - len(target) - 3]} — {target}"

    def clean(self):
        super().clean()
        if bool(self.parcel_id) == bool(self.shipment_id):
            raise ValidationError("Select exactly one parcel or shipment.")
        for name in ("client", "parcel", "shipment", "service"):
            obj = getattr(self, name)
            if obj is not None and obj.business_id != self.business_id:
                raise ValidationError({name: "Reference must belong to the charge workspace."})
        if self.parcel_id and self.parcel.client_id != self.client_id:
            raise ValidationError({"client": "Parcel must belong to the charge client."})
        if self.shipment_id:
            from .billing_services import shipment_billing_client

            if shipment_billing_client(self.shipment).pk != self.client_id:
                raise ValidationError({"client": "Shipment must belong to the charge client."})
        if self.invoice_line_id:
            line = self.invoice_line
            if (
                line.invoice.business_id,
                line.invoice.client_id,
                line.parcel_id,
                line.shipment_id,
                line.service_id,
                line.description,
                line.quantity,
                line.unit_price,
            ) != (
                self.business_id,
                self.client_id,
                self.parcel_id,
                self.shipment_id,
                self.service_id,
                self.invoice_description,
                self.quantity,
                self.unit_price,
            ):
                raise ValidationError("Invoice line must match the saved charge.")
        if self.quantity is not None and self.unit_price is not None:
            from apps.billings.models import InvoiceLine

            InvoiceLine._meta.get_field("line_total").clean(self.total, None)
        if self._state.adding:
            self._validate_actor("created_by")
        else:
            previous = type(self).objects.get(pk=self.pk)
            fields = (
                "business_id",
                "client_id",
                "parcel_id",
                "shipment_id",
                "service_id",
                "description",
                "target_reference",
                "quantity",
                "unit_price",
                "idempotency_key",
                "created_by_id",
            )
            if any(getattr(self, field) != getattr(previous, field) for field in fields) or (
                previous.invoice_line_id and previous.invoice_line_id != self.invoice_line_id
            ):
                raise ValidationError("Saved charge snapshots and invoice links are immutable.")


class LogisticsLocationAssignment(models.Model):
    """Owner-approved access for an existing workspace membership."""

    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="logistics_location_assignments",
    )
    membership = models.ForeignKey(
        "businesses.BusinessUser",
        on_delete=models.CASCADE,
        related_name="logistics_location_assignments",
    )
    location = models.ForeignKey(
        LogisticsLocation, on_delete=models.PROTECT, related_name="worker_assignments"
    )
    can_operate = models.BooleanField(default=False)
    is_work_context = models.BooleanField(default=False, editable=False)
    is_current = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "location"], name="logistics_worker_location_unique"
            ),
            models.UniqueConstraint(
                fields=["membership"],
                condition=models.Q(is_current=True),
                name="logistics_worker_current_unique",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.business_id or not self.membership_id or not self.location_id:
            return
        if (
            self.membership.business_id != self.business_id
            or self.location.business_id != self.business_id
        ):
            raise ValidationError("Membership and location must belong to this workspace.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class LogisticsHandlingSite(models.Model):
    """An explicit site association; no scheduling or transport planning."""

    class Kind(models.TextChoices):
        EXPECTED = "EXPECTED", "Expected at site"
        CURRENT = "CURRENT", "Currently handled at site"
        STOP = "STOP", "Operational stop"

    business = models.ForeignKey(
        "businesses.Business", on_delete=models.PROTECT, related_name="logistics_handling_sites"
    )
    location = models.ForeignKey(
        LogisticsLocation, on_delete=models.PROTECT, related_name="handling_sites"
    )
    parcel = models.ForeignKey(
        Parcel, null=True, blank=True, on_delete=models.CASCADE, related_name="handling_sites"
    )
    shipment = models.ForeignKey(
        Shipment, null=True, blank=True, on_delete=models.CASCADE, related_name="handling_sites"
    )
    kind = models.CharField(max_length=8, choices=Kind.choices)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(parcel__isnull=False, shipment__isnull=True)
                    | models.Q(parcel__isnull=True, shipment__isnull=False)
                ),
                name="logistics_handling_one_target",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=["EXPECTED", "CURRENT", "STOP"]),
                name="logistics_handling_kind_known",
            ),
            models.UniqueConstraint(
                fields=["parcel", "location", "kind"], name="logistics_parcel_site_unique"
            ),
            models.UniqueConstraint(
                fields=["shipment", "location", "kind"], name="logistics_shipment_site_unique"
            ),
        ]

    def clean(self):
        super().clean()
        target = self.parcel if self.parcel_id else self.shipment if self.shipment_id else None
        if bool(self.parcel_id) == bool(self.shipment_id):
            raise ValidationError("Select exactly one parcel or shipment.")
        if (
            target
            and self.location_id
            and (
                target.business_id != self.business_id
                or self.location.business_id != self.business_id
            )
        ):
            raise ValidationError("Target and handling site must belong to this workspace.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
