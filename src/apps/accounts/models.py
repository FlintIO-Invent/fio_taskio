from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager


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

