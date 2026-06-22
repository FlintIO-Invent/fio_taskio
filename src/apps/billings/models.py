from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.crm.models import Client, TimeStampedModel


class Invoice(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    invoice_number = models.CharField(max_length=40)
    business = models.ForeignKey(
        "businesses.Business",
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="invoices")
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "invoice_number"],
                name="billings_invoice_unique_business_number",
            ),
        ]

    def __str__(self) -> str:
        return self.invoice_number

    @property
    def currency_code(self) -> str:
        if self.business_id and self.business:
            return self.business.currency
        return "USD"

    @property
    def tax_rate_percentage(self) -> Decimal:
        if self.business_id and self.business:
            return self.business.tax_rate
        return Decimal("0.00")

    def clean(self) -> None:
        super().clean()

        errors: dict[str, str] = {}

        if self.business_id is not None and self.client_id is not None:
            if self.client.business_id != self.business_id:
                errors["client"] = "Selected client must belong to the current workspace."

        if self.appointment_id is not None and self.business_id is not None:
            if self.appointment.business_id != self.business_id:
                errors["appointment"] = "Linked appointment must belong to the current workspace."
            elif self.client_id is not None and self.appointment.client_id != self.client_id:
                errors["appointment"] = (
                    "Linked appointment must belong to the selected client in this workspace."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class InvoiceLine(TimeStampedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    service = models.ForeignKey(
        "crm.BusinessService",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines",
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["created_at"]

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or Decimal("0.00")) * (self.unit_price or Decimal("0.00"))
        super().save(*args, **kwargs)
