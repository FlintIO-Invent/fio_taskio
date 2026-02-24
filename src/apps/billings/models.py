from __future__ import annotations

from decimal import Decimal
from django.db import models

from apps.crm.models import TimeStampedModel, Client, Lead


class Invoice(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    invoice_number = models.CharField(max_length=40, unique=True)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="invoices")
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.invoice_number


class InvoiceLine(TimeStampedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["created_at"]

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or Decimal("0.00")) * (self.unit_price or Decimal("0.00"))
        super().save(*args, **kwargs)