from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .localization import format_business_address_lines, uses_netherlands_address_format
from .plan_catalog import PUBLIC_PAID_PLAN_ORDERING, PUBLIC_PAID_PLAN_SLUGS


def default_business_invitation_expiry():
    return timezone.now() + timedelta(days=7)


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
    business_type = models.CharField(max_length=120, blank=True, default="")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address_line_1 = models.CharField(max_length=255, blank=True, default="")
    address_line_2 = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=120, blank=True, default="")
    region = models.CharField(max_length=120, blank=True, default="")
    postal_code = models.CharField(max_length=40, blank=True, default="")
    address = models.TextField(blank=True)
    country = models.CharField(max_length=100, blank=True)
    currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.USD,
    )
    timezone = models.CharField(max_length=100, default="UTC")
    default_locale = models.CharField(max_length=35, blank=True, default="")
    tax_label = models.CharField(max_length=40, blank=True, default="Tax")
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
    def formatted_address_lines(self) -> list[str]:
        return format_business_address_lines(
            address_line_1=self.address_line_1,
            address_line_2=self.address_line_2,
            city=self.city,
            region=self.region,
            postal_code=self.postal_code,
            country=self.country,
            legacy_address=self.address,
        )

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


class BusinessBookingSettings(TimeStampedModel):
    class ConfirmationMode(models.TextChoices):
        REQUEST_ONLY = "request_only", "Request first / manual confirmation"
        AUTO_CONFIRM_LATER = "auto_confirm_later", "Auto-confirm later"

    business = models.OneToOneField(
        Business,
        on_delete=models.CASCADE,
        related_name="booking_settings",
    )
    booking_enabled = models.BooleanField(default=False)
    default_duration_minutes = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1)],
    )
    minimum_notice_hours = models.PositiveIntegerField(
        default=24,
        validators=[MinValueValidator(0)],
    )
    maximum_days_ahead = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1)],
    )
    buffer_minutes = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    confirmation_mode = models.CharField(
        max_length=30,
        choices=ConfirmationMode.choices,
        default=ConfirmationMode.REQUEST_ONLY,
    )
    public_booking_instructions = models.TextField(blank=True)
    cancellation_policy_text = models.TextField(blank=True)
    reschedule_policy_text = models.TextField(blank=True)

    class Meta:
        ordering = ["business__name"]
        verbose_name = "business booking settings"
        verbose_name_plural = "business booking settings"

    def __str__(self) -> str:
        return f"Booking settings for {self.business}"

    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        if self.business_id is None:
            errors["business"] = "Booking settings must belong to a workspace."

        if self.default_duration_minutes is not None and self.default_duration_minutes <= 0:
            errors["default_duration_minutes"] = "Default duration must be greater than zero."

        if self.minimum_notice_hours is not None and self.minimum_notice_hours < 0:
            errors["minimum_notice_hours"] = "Minimum notice cannot be negative."

        if self.maximum_days_ahead is not None and self.maximum_days_ahead <= 0:
            errors["maximum_days_ahead"] = "Maximum days ahead must be greater than zero."

        if self.buffer_minutes is not None and self.buffer_minutes < 0:
            errors["buffer_minutes"] = "Buffer time cannot be negative."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class WeeklyAvailability(TimeStampedModel):
    class DayOfWeek(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="weekly_availability",
    )
    staff_member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="availability_blocks",
    )
    day_of_week = models.PositiveSmallIntegerField(choices=DayOfWeek.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["day_of_week", "start_time", "pk"]
        indexes = [
            models.Index(fields=["business", "day_of_week", "is_active"]),
            models.Index(fields=["business", "staff_member", "day_of_week", "is_active"]),
        ]
        verbose_name = "weekly availability"
        verbose_name_plural = "weekly availability"

    def __str__(self) -> str:
        staff_label = "Business-wide"
        if self.staff_member_id:
            get_full_name = getattr(self.staff_member, "get_full_name", None)
            full_name = (get_full_name() if callable(get_full_name) else "") or getattr(
                self.staff_member, "full_name", ""
            )
            staff_label = full_name.strip() or self.staff_member.email
        return (
            f"{self.business} - {staff_label} - {self.get_day_of_week_display()} "
            f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"
        )

    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        if self.business_id is None:
            errors["business"] = "Availability must belong to a workspace."

        valid_days = {choice.value for choice in self.DayOfWeek}
        if self.day_of_week is not None and self.day_of_week not in valid_days:
            errors["day_of_week"] = "Select a valid day of the week."

        if self.start_time and self.end_time and self.end_time <= self.start_time:
            errors["end_time"] = "End time must be after the start time."

        if self.business_id is not None and self.staff_member_id is not None:
            has_membership = BusinessUser.objects.filter(
                user=self.staff_member,
                business_id=self.business_id,
                is_active=True,
                business__is_active=True,
                role__in=(
                    BusinessUser.Role.OWNER,
                    BusinessUser.Role.ADMIN,
                    BusinessUser.Role.STAFF,
                ),
            ).exists()
            if not has_membership:
                errors["staff_member"] = (
                    "Selected staff member must have an active bookable membership "
                    "in this workspace."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class ClarivoPlan(TimeStampedModel):
    MOTIONMATE_PLAN_SLUGS = PUBLIC_PAID_PLAN_SLUGS
    USD_PRICING_REGION = "usd"
    EUR_PRICING_REGION = "eur"
    DEFAULT_PRICING_REGION = USD_PRICING_REGION
    CARIBBEAN_INTERNATIONAL_PRICING_REGION = "caribbean_international"
    NETHERLANDS_PRICING_REGION = "netherlands"
    PRICING_REGION_LABELS = {
        USD_PRICING_REGION: "USD",
        EUR_PRICING_REGION: "EUR",
        CARIBBEAN_INTERNATIONAL_PRICING_REGION: "Caribbean / International",
        NETHERLANDS_PRICING_REGION: "Netherlands",
    }
    MODULE_FLAG_MAP = {
        "invoicing": "allow_invoicing",
        "appointments": "allow_appointments",
        "public_booking": "allow_public_booking",
        "public_booking_requests": "allow_public_booking",
        "public_request_form": "allow_public_booking",
        "public_request": "allow_public_booking",
    }
    CORE_MODULES = {
        "workspace",
        "crm",
        "clients",
        "client_management",
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
    regional_prices = models.JSONField(default=dict, blank=True)
    is_recommended = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    max_users = models.PositiveIntegerField(null=True, blank=True)
    max_clients = models.PositiveIntegerField(null=True, blank=True)
    max_invoices_per_month = models.PositiveIntegerField(null=True, blank=True)
    max_appointments_per_month = models.PositiveIntegerField(null=True, blank=True)
    max_public_bookings_per_month = models.PositiveIntegerField(null=True, blank=True)
    allow_invoicing = models.BooleanField(default=False)
    allow_appointments = models.BooleanField(default=False)
    allow_memberships = models.BooleanField(default=False)
    allow_public_booking = models.BooleanField(default=False)
    allow_public_request_form = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def motionmate_plan_ordering(cls):
        return models.Case(
            *[
                models.When(slug=slug, then=models.Value(position))
                for position, slug in enumerate(PUBLIC_PAID_PLAN_ORDERING)
            ],
            default=models.Value(len(PUBLIC_PAID_PLAN_ORDERING)),
            output_field=models.IntegerField(),
        )

    @classmethod
    def motionmate_plans(cls):
        return cls.objects.filter(
            is_active=True,
            slug__in=PUBLIC_PAID_PLAN_SLUGS,
        ).order_by(cls.motionmate_plan_ordering(), "pk")

    @classmethod
    def attach_display_pricing(
        cls,
        plans,
        *,
        business: Business | None = None,
        region: str | None = None,
    ):
        for plan in plans:
            plan.display_pricing = plan.get_display_pricing(business=business, region=region)
            plan.usd_display_pricing = plan.get_display_pricing(region=cls.USD_PRICING_REGION)
            plan.eur_display_pricing = plan.get_display_pricing(region=cls.EUR_PRICING_REGION)
        return plans

    @classmethod
    def pricing_region_for_business(cls, business: Business | None = None) -> str:
        if business is not None and uses_netherlands_address_format(business.country):
            return cls.EUR_PRICING_REGION
        return cls.DEFAULT_PRICING_REGION

    @staticmethod
    def _decimal_from_price(value, fallback: Decimal) -> Decimal:
        if value in (None, ""):
            return fallback
        return Decimal(str(value))

    @staticmethod
    def _format_plan_price(value: Decimal, currency: str = "EUR") -> str:
        amount = Decimal(value or "0.00")
        decimal_places = 0 if amount == amount.to_integral_value() else 2
        formatted_amount = f"{amount:,.{decimal_places}f}"
        currency_symbol = {
            "EUR": "€",
            "USD": "$",
            "XCD": "$",
            "ANG": "ƒ",
        }.get(currency.upper(), f"{currency.upper()} ")
        return f"{currency_symbol}{formatted_amount}"

    def get_pricing_data(
        self,
        *,
        business: Business | None = None,
        region: str | None = None,
    ) -> dict:
        pricing_region = region or self.pricing_region_for_business(business)
        regional_prices = self.regional_prices or {}
        fallback_regions = [pricing_region]
        if pricing_region == self.USD_PRICING_REGION:
            fallback_regions.append(self.CARIBBEAN_INTERNATIONAL_PRICING_REGION)
        if pricing_region == self.EUR_PRICING_REGION:
            fallback_regions.append(self.NETHERLANDS_PRICING_REGION)
        fallback_regions.extend(
            [
                self.DEFAULT_PRICING_REGION,
                self.CARIBBEAN_INTERNATIONAL_PRICING_REGION,
            ]
        )
        region_data = {}
        for fallback_region in fallback_regions:
            region_data = regional_prices.get(fallback_region) or {}
            if region_data:
                break

        return {
            "region": pricing_region,
            "region_label": self.PRICING_REGION_LABELS.get(pricing_region, "Default"),
            "currency": region_data.get("currency", "EUR"),
            "monthly": self._decimal_from_price(
                region_data.get("monthly"),
                self.price_monthly,
            ),
            "yearly": self._decimal_from_price(
                region_data.get("yearly"),
                self.price_yearly,
            ),
            "tax_note": region_data.get("tax_note", ""),
        }

    def get_display_pricing(
        self,
        *,
        business: Business | None = None,
        region: str | None = None,
    ) -> dict:
        pricing_data = self.get_pricing_data(business=business, region=region)
        monthly = pricing_data["monthly"]
        yearly = pricing_data["yearly"]
        currency = pricing_data["currency"]

        return {
            **pricing_data,
            "monthly_display": self._format_plan_price(monthly, currency),
            "yearly_display": self._format_plan_price(yearly, currency),
        }

    @property
    def staff_account_limit(self) -> int | None:
        if self.max_users is None:
            return None
        return max(self.max_users - 1, 0)

    @property
    def user_limit_summary(self) -> str:
        if self.max_users is None:
            return "Unlimited total users"

        staff_limit = self.staff_account_limit or 0
        staff_label = "staff account" if staff_limit == 1 else "staff accounts"
        return f"{self.max_users} total users: owner + {staff_limit} {staff_label}"

    @property
    def staff_capacity_summary(self) -> str:
        if self.staff_account_limit is None:
            return "Unlimited staff accounts"

        staff_label = "staff account" if self.staff_account_limit == 1 else "staff accounts"
        return f"{self.staff_account_limit} {staff_label}"

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
            self.business.is_active and self.plan.is_active and self.status in self.ACCESS_STATUSES
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
    # Motionmate MVP keeps exactly one role per user inside a workspace.
    # Use Admin when someone needs both operational and billing permissions.
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


class UserOnboardingState(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="onboarding_states",
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="onboarding_states",
    )
    selected_journey = models.CharField(max_length=80, null=True, blank=True)
    completed_welcome = models.BooleanField(default=False)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    skipped_steps = models.JSONField(default=list, blank=True)
    last_step_key = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        ordering = ["business__name", "user__email"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "business"],
                name="businesses_onboarding_unique_user_business",
            ),
        ]
        indexes = [
            models.Index(fields=["business", "user"]),
            models.Index(fields=["business", "selected_journey"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} onboarding @ {self.business}"


class BusinessInvitation(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=20,
        choices=BusinessUser.Role.choices,
        default=BusinessUser.Role.STAFF,
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_business_invitations",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    expires_at = models.DateTimeField(default=default_business_invitation_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accepted_business_invitations",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.email} -> {self.business} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return self.status == self.Status.PENDING and self.expires_at <= timezone.now()
