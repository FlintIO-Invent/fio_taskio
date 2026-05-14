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
