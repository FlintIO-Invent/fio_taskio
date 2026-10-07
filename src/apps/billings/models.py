from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

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
    emailed_at = models.DateTimeField(null=True, blank=True)
    emailed_to = models.EmailField(blank=True)
    email_send_count = models.PositiveIntegerField(default=0)

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

        if self.pk and self.lines.filter(logistics_charge__isnull=False).exists():
            if (
                self.lines.filter(logistics_charge__isnull=False)
                .exclude(
                    logistics_charge__business_id=self.business_id,
                    logistics_charge__client_id=self.client_id,
                )
                .exists()
            ):
                errors["client"] = "Invoice ownership must match its saved Logistics charges."
        if (
            self.pk
            and self.lines.filter(parcel__isnull=False)
            .exclude(
                parcel__business_id=self.business_id,
                parcel__client_id=self.client_id,
            )
            .exists()
        ):
            errors["client"] = "Invoice ownership must match its parcel lines."

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
    parcel = models.ForeignKey(
        "logistics.Parcel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoice_lines",
    )
    shipment = models.ForeignKey(
        "logistics.Shipment",
        on_delete=models.PROTECT,
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

    def clean(self):
        super().clean()
        if self.parcel_id and self.shipment_id:
            raise ValidationError("A line can reference a parcel or a shipment, not both.")
        if self.invoice_id:
            business_id = self.invoice.business_id
            for name in ("service", "parcel", "shipment"):
                obj = getattr(self, name)
                if obj is not None and obj.business_id != business_id:
                    raise ValidationError({name: "Reference must belong to the invoice workspace."})
            if self.parcel_id and self.parcel.client_id != self.invoice.client_id:
                raise ValidationError({"parcel": "Parcel must belong to the invoice client."})
            if self.shipment_id:
                from apps.logistics.billing_services import shipment_billing_client

                if shipment_billing_client(self.shipment).pk != self.invoice.client_id:
                    raise ValidationError(
                        {"shipment": "Shipment must belong to the invoice client."}
                    )
        if self.pk:
            from apps.logistics.models import LogisticsCharge

            charge = LogisticsCharge.objects.filter(invoice_line_id=self.pk).first()
            if charge and (
                self.invoice_id != charge.invoice_line.invoice_id
                or (
                    self.service_id,
                    self.parcel_id,
                    self.shipment_id,
                    self.description,
                    self.quantity,
                    self.unit_price,
                )
                != (
                    charge.service_id,
                    charge.parcel_id,
                    charge.shipment_id,
                    charge.invoice_description,
                    charge.quantity,
                    charge.unit_price,
                )
            ):
                raise ValidationError("Invoiced Logistics charges cannot be changed here.")

    def save(self, *args, **kwargs):
        self.clean()
        self.line_total = (self.quantity or Decimal("0.00")) * (self.unit_price or Decimal("0.00"))
        if self.parcel_id or self.shipment_id:
            self.line_total = self.line_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)
