from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.businesses.models import BusinessUser
from apps.crm.models import BusinessService, Client, TimeStampedModel


class Appointment(TimeStampedModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No Show"

    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.CASCADE,
        related_name="appointments",
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    service = models.ForeignKey(
        BusinessService,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    service_name = models.CharField(max_length=160, blank=True, default="")
    staff_member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    title = models.CharField(max_length=160)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
        db_index=True,
    )
    location = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["start_time", "pk"]
        indexes = [
            models.Index(fields=["business", "start_time"]),
            models.Index(fields=["business", "status", "start_time"]),
            models.Index(fields=["business", "staff_member", "start_time"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} - {self.client} ({self.start_time:%Y-%m-%d %H:%M})"

    @property
    def status_badge_class(self) -> str:
        badge_classes = {
            self.Status.SCHEDULED: "badge-phoenix-primary",
            self.Status.COMPLETED: "badge-phoenix-success",
            self.Status.CANCELLED: "badge-phoenix-danger",
            self.Status.NO_SHOW: "badge-phoenix-warning",
        }
        return badge_classes.get(self.status, "badge-phoenix-secondary")

    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        if self.start_time and self.end_time and self.end_time <= self.start_time:
            errors["end_time"] = "End time must be after the start time."

        if self.business_id is None:
            if errors:
                raise ValidationError(errors)
            return

        if self.client_id is not None:
            if self.client.business_id is None:
                errors["client"] = "Appointments require a client from the current workspace."
            elif self.client.business_id != self.business_id:
                errors["client"] = "Selected client must belong to the current workspace."

        if self.service_id is not None and self.service.business_id != self.business_id:
            errors["service"] = "Selected service must belong to the current workspace."

        if self.staff_member_id is not None:
            has_membership = BusinessUser.objects.filter(
                user=self.staff_member,
                business_id=self.business_id,
                is_active=True,
                business__is_active=True,
            ).exists()
            if not has_membership:
                errors["staff_member"] = (
                    "Selected staff member must have an active membership in the current workspace."
                )

        if errors:
            raise ValidationError(errors)

    def _apply_service_snapshot(self) -> None:
        if self.service_id is None:
            return

        previous_service_id = None
        if self.pk:
            previous_service_id = (
                self.__class__.objects.filter(pk=self.pk)
                .values_list("service_id", flat=True)
                .first()
            )

        if not self.service_name or previous_service_id != self.service_id:
            self.service_name = self.service.name

    def save(self, *args, **kwargs):
        self._apply_service_snapshot()
        self.full_clean()
        super().save(*args, **kwargs)
