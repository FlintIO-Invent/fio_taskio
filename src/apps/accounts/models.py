from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


class TaskIOUserManager(BaseUserManager):
    def create_user(
        self,
        email: str,
        first_name: str = "",
        last_name: str = "",
        password: str | None = None,
        incorporation_status: str = "CORPORATED",
        assigned_location: str = "CARIBBEAN",
        date_of_birth=None,
        company_name: str = "",
        **extra_fields,
    ):
        """
        Create and return a user with an email as the unique identifier.
        """
        if not email:
            raise ValueError("Users must have an email address")

        email = self.normalize_email(email)

        user = self.model(
            email=email,
            first_name=first_name,
            last_name=last_name,
            company_name=company_name,
            incorporation_status=incorporation_status,
            assigned_location=assigned_location,
            date_of_birth=date_of_birth,
            **extra_fields,
        )
        user.set_password(password)
        user.is_active = True
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        first_name: str = "Admin",
        last_name: str = "User",
        password: str | None = None,
        **extra_fields,
    ):
        """
        Create and return a superuser.
        """
        extra_fields.setdefault("incorporation_status", "INCORPORATED")
        extra_fields.setdefault("assigned_location", "CARIBBEAN")

        user = self.create_user(
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
            **extra_fields,
        )
        user.is_staff = True
        user.is_superuser = True  
        user.is_active = True
        user.save(using=self._db)
        return user


class TaskIOUser(AbstractBaseUser, PermissionsMixin):
    INCORPORATION_STATUS_CHOICES = (
        ("CORPORATED", "Corporated"),
        ("UNINCORPORATED", "Unincorporated"),
    )

    EMPLOYMENT_LOCATION_CHOICES = (
        ("WORLD", "World"),
        ("CARIBBEAN", "Caribbean"),
        ("ST_MAARTEN", "St. Maarten"),
        ("DOMINICA", "Dominica"),
    )

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    assigned_location = models.CharField(choices=EMPLOYMENT_LOCATION_CHOICES, max_length=20, default="CARIBBEAN")
    date_of_birth = models.DateField(null=True, blank=True)
    incoporation_date = models.DateField(null=True, blank=True)
    company_name = models.CharField(max_length=100, blank=True, null=True)
    incorporation_status = models.CharField(choices=INCORPORATION_STATUS_CHOICES, default="CORPORATED", max_length=20)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    date_operational = models.DateTimeField(blank=True, null=True)
    last_updated = models.DateTimeField(auto_now=True)
    date_joined = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = TaskIOUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "incorporation_status", "company_name", "assigned_location"]

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def initials(self) -> str:
        if self.first_name or self.last_name:
            return f"{self.first_name[:1]}{self.last_name[:1]}".upper()
        return self.email[:2].upper()


class SaaSUserProfile(models.Model):
    CURRENCY_CHOICES = (
        ("USD", "US Dollar (USD)"),
        ("XCD", "East Caribbean Dollar (XCD)"),
        ("EUR", "Euro (EUR)"),
        ("ANG", "Netherlands Antillean Guilder (ANG)"),
    )

    invoice_prefix_validator = RegexValidator(
        regex=r"^[A-Z0-9-]{2,12}$",
        message="Use 2-12 uppercase letters, numbers, or hyphens for the invoice prefix.",
    )
    hex_color_validator = RegexValidator(
        regex=r"^#[0-9A-Fa-f]{6}$",
        message="Enter a valid hex color such as #2C7BE5.",
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saas_profile",
    )
    workspace_name = models.CharField(max_length=120, blank=True)
    billing_email = models.EmailField(blank=True)
    support_email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    tax_id = models.CharField(max_length=60, blank=True)
    # TODO: These invoice-specific defaults are now legacy in the multi-business setup.
    # New invoice numbering, tax, and currency defaults should come from Business.
    # Keep these fields until the account settings UI is fully migrated off user-level invoice settings.
    currency_code = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="USD")
    invoice_prefix = models.CharField(
        max_length=12,
        default="INV",
        validators=[invoice_prefix_validator],
    )
    invoice_default_due_days = models.PositiveSmallIntegerField(
        default=14,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
    )
    invoice_accent_color = models.CharField(
        max_length=7,
        default="#2C7BE5",
        validators=[hex_color_validator],
    )
    show_company_address_on_invoice = models.BooleanField(default=True)
    show_tax_id_on_invoice = models.BooleanField(default=True)
    payment_instructions = models.TextField(blank=True)
    invoice_footer_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SaaS User Profile"
        verbose_name_plural = "SaaS User Profiles"

    def __str__(self) -> str:
        return f"{self.user.email} settings"

    @classmethod
    def get_or_create_for_user(cls, user: TaskIOUser) -> "SaaSUserProfile":
        profile, _ = cls.objects.get_or_create(
            user=user,
            defaults={
                "workspace_name": user.company_name or user.full_name or user.email.split("@")[0],
                "billing_email": user.email,
            },
        )
        return profile

    @property
    def brand_name(self) -> str:
        return self.user.company_name or self.workspace_name or self.user.full_name or self.user.email

    @property
    def invoice_preview_number(self) -> str:
        # TODO: Legacy preview helper retained for the account settings UI.
        # New invoice creation should use Business.invoice_prefix and Business.invoice_start_number instead.
        return f"{self.invoice_prefix}-{timezone.localtime():%Y%m%d}-001"
