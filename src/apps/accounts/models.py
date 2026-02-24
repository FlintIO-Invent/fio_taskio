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
        role: str = "EMPLOYEE",
        employment_status: str = "EMPLOYED",
        assigned_location: str = "WORLD",
        date_of_birth=None,
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
            role=role,
            employment_status=employment_status,
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
        extra_fields.setdefault("role", "MANAGEMENT")
        extra_fields.setdefault("employment_status", "EMPLOYED")
        extra_fields.setdefault("assigned_location", "WORLD")

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
    ROLE_CHOICES = (
        ("MANAGEMENT", "Management"),
        ("EMPLOYEE", "Employee"),
    )

    EMPLOYMENT_LOCATION_CHOICES = (
        ("WORLD", "World"),
        ("CARIBBEAN", "Caribbean"),
        ("ST_MAARTEN", "St. Maarten"),
        ("DOMINICA", "Dominica"),
    )

    EMPLOYMENT_STATUS_CHOICES = (
        ("EMPLOYED", "Employed"),
        ("UNEMPLOYED", "Unemployed"),
        ("TERMINATED", "Terminated"),
        ("RETIRED", "Retired"),
        ("LEAVE_OF_ABSENCE", "Leave of Absence"),
        ("INACTIVE", "Inactive"),
    )

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=30, blank=True)
    assigned_location = models.CharField(choices=EMPLOYMENT_LOCATION_CHOICES, max_length=20, default="CARIBBEAN")
    date_of_birth = models.DateField(null=True, blank=True)
    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default="EMPLOYEE")
    employment_status = models.CharField(choices=EMPLOYMENT_STATUS_CHOICES, default="EMPLOYED", max_length=20)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    date_hired = models.DateTimeField(blank=True, null=True)
    last_updated = models.DateTimeField(auto_now=True)
    date_joined = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = TaskIOUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self) -> str:
        return self.email

