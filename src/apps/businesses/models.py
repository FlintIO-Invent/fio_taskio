from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Business(TimeStampedModel):
    class Currency(models.TextChoices):
        USD = "USD", "US Dollar (USD)"
        XCD = "XCD", "East Caribbean Dollar (XCD)"
        EUR = "EUR", "Euro (EUR)"
        ANG = "ANG", "Netherlands Antillean Guilder (ANG)"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=150, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    country = models.CharField(max_length=100, blank=True)
    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.USD,
    )
    timezone = models.CharField(max_length=100, default="UTC")
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    invoice_prefix = models.CharField(max_length=12, default="INV")
    invoice_start_number = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def has_active_subscription(self) -> bool:
        try:
            subscription = self.subscription
        except BusinessSubscription.DoesNotExist:
            return False
        return subscription.has_access

    @property
    def is_trialing(self) -> bool:
        try:
            subscription = self.subscription
        except BusinessSubscription.DoesNotExist:
            return False
        return subscription.is_trialing

    def can_use_module(self, module_name: str) -> bool:
        try:
            subscription = self.subscription
        except BusinessSubscription.DoesNotExist:
            return False
        return subscription.can_use_module(module_name)


class ClarivoPlan(TimeStampedModel):
    MODULE_FLAG_MAP = {
        "invoicing": "allow_invoicing",
        "appointments": "allow_appointments",
        "memberships": "allow_memberships",
        "public_booking": "allow_public_booking",
        "public_request_form": "allow_public_request_form",
        "public_request": "allow_public_request_form",
    }
    CORE_MODULES = {
        "workspace",
        "crm",
        "clients",
        "service_requests",
    }

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    price_monthly = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    price_yearly = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    is_active = models.BooleanField(default=True)
    max_users = models.PositiveIntegerField(null=True, blank=True)
    max_clients = models.PositiveIntegerField(null=True, blank=True)
    max_invoices_per_month = models.PositiveIntegerField(null=True, blank=True)
    allow_invoicing = models.BooleanField(default=False)
    allow_appointments = models.BooleanField(default=False)
    allow_memberships = models.BooleanField(default=False)
    allow_public_booking = models.BooleanField(default=False)
    allow_public_request_form = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def allows_module(self, module_name: str) -> bool:
        normalized_name = module_name.strip().lower().replace("-", "_")
        if normalized_name in self.CORE_MODULES:
            return True

        flag_name = self.MODULE_FLAG_MAP.get(normalized_name)
        if flag_name is None:
            return False

        return bool(getattr(self, flag_name))


class BusinessSubscription(TimeStampedModel):
    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past Due"
        CANCELLED = "cancelled", "Cancelled"
        SUSPENDED = "suspended", "Suspended"

    ACCESS_STATUSES = {
        Status.TRIALING,
        Status.ACTIVE,
    }

    business = models.OneToOneField(
        Business,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(
        ClarivoPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TRIALING,
    )
    trial_start = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)

    class Meta:
        ordering = ["business__name"]

    def __str__(self) -> str:
        return f"{self.business} - {self.plan} ({self.get_status_display()})"

    @property
    def has_access(self) -> bool:
        return (
            self.business.is_active
            and self.plan.is_active
            and self.status in self.ACCESS_STATUSES
        )

    @property
    def is_trialing(self) -> bool:
        return self.status == self.Status.TRIALING

    def can_use_module(self, module_name: str) -> bool:
        return self.has_access and self.plan.allows_module(module_name)


class BusinessUser(TimeStampedModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"
        ACCOUNTANT = "accountant", "Accountant"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="business_memberships",
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STAFF,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["business__name", "user__email"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "business"],
                name="businesses_membership_unique_user_business",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.business} ({self.get_role_display()})"
