from __future__ import annotations

from copy import copy
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.businesses.service_limits import ServiceCapacityQuerySet
from apps.businesses.usage_limits import capacity_guard
from apps.crm.models import Client, TimeStampedModel


class InvoiceQuerySet(ServiceCapacityQuerySet):
    def delete(self):
        if self.filter(payments__isnull=False).exists():
            raise ProtectedError("Customer payment history must be retained.", list(self))
        protected = self.filter(business__vertical="LOGISTICS").filter(
            Q(lines__charge_source__isnull=False) | Q(lines__logistics_charge__isnull=False)
        )
        if protected.exists():
            raise ProtectedError(
                "Linked Logistics invoice history must be retained.", list(protected)
            )
        return super().delete()


class Invoice(TimeStampedModel):
    objects = InvoiceQuerySet.as_manager()

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

    currency_snapshot = models.CharField(max_length=3, null=True, blank=True, editable=False)
    tax_rate_snapshot = models.DecimalField(
        max_digits=9, decimal_places=4, null=True, blank=True, editable=False
    )
    financial_snapshot_at = models.DateTimeField(null=True, blank=True, editable=False)
    snapshot_is_legacy = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["business", "created_at"], name="billings_invoice_usage_idx")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "invoice_number"],
                name="billings_invoice_unique_business_number",
            ),
        ]

    def __str__(self) -> str:
        return self.invoice_number

    def delete(self, *args, **kwargs):
        if self.payments.exists():
            raise ProtectedError("Customer payment history must be retained.", [self])
        if (
            self.business.vertical == "LOGISTICS"
            and self.lines.filter(
                Q(charge_source__isnull=False) | Q(logistics_charge__isnull=False)
            ).exists()
        ):
            raise ProtectedError("Linked Logistics invoice history must be retained.", [self])
        return super().delete(*args, **kwargs)

    @property
    def currency_code(self) -> str:
        if self.business_id and self.business.vertical == "LOGISTICS" and self.currency_snapshot:
            return self.currency_snapshot
        if self.business_id and self.business:
            return self.business.currency
        return "USD"

    @property
    def tax_rate_percentage(self) -> Decimal:
        if (
            self.business_id
            and self.business.vertical == "LOGISTICS"
            and self.tax_rate_snapshot is not None
        ):
            return self.tax_rate_snapshot
        if self.business_id and self.business:
            return self.business.tax_rate
        return Decimal("0.00")

    @property
    def billing_business(self):
        if self.business.vertical != "LOGISTICS":
            return self.business
        result = copy(self.business)
        result.currency = self.currency_code
        result.tax_rate = self.tax_rate_percentage
        return result

    def clean(self) -> None:
        super().clean()

        errors: dict[str, str] = {}

        if self.pk and self.payments.exists():
            previous = type(self).objects.get(pk=self.pk)
            if any(
                getattr(self, field) != getattr(previous, field)
                for field in ("business_id", "client_id", "subtotal", "tax", "total")
            ):
                raise ValidationError(
                    "Invoices with customer payments retain their monetary basis."
                )

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

        if self.pk and self.business.vertical == "LOGISTICS":
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and previous.financial_snapshot_at:
                frozen = (
                    "business_id",
                    "client_id",
                    "currency_snapshot",
                    "tax_rate_snapshot",
                    "subtotal",
                    "tax",
                    "total",
                    "financial_snapshot_at",
                )
                if any(getattr(self, field) != getattr(previous, field) for field in frozen):
                    raise ValidationError("Issued Logistics monetary snapshots are immutable.")

        if (
            self.pk
            and self.lines.filter(charge_source__isnull=False)
            .exclude(
                charge_source__business_id=self.business_id, charge_source__client_id=self.client_id
            )
            .exists()
        ):
            errors["client"] = "Invoice ownership must match its source charges."
        if (
            self.pk
            and self.business.vertical == "LOGISTICS"
            and self.lines.filter(charge_source__isnull=False)
            .exclude(charge_source__currency_snapshot=self.currency_code)
            .exists()
        ):
            errors["currency_snapshot"] = (
                "Invoice currency must match its saved charge obligations."
            )
        if errors:
            raise ValidationError(errors)

    @capacity_guard
    def save(self, *args, **kwargs):
        if self.business_id and self.business.vertical == "LOGISTICS":
            from django.utils import timezone

            if self.currency_snapshot is None:
                self.currency_snapshot = self.business.currency
            if self.tax_rate_snapshot is None:
                self.tax_rate_snapshot = self.business.tax_rate
            rate = Decimal(str(self.tax_rate_snapshot))
            normalized_rate = rate.quantize(Decimal("0.0001"))
            if rate != normalized_rate:
                raise ValidationError("Invoice tax snapshots support at most four decimal places.")
            self.tax_rate_snapshot = normalized_rate
            if self.status != self.Status.DRAFT and self.financial_snapshot_at is None:
                self.financial_snapshot_at = timezone.now()
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                        "currency_snapshot",
                        "tax_rate_snapshot",
                        "financial_snapshot_at",
                    }
        self.full_clean()
        super().save(*args, **kwargs)


class InvoiceLineQuerySet(models.QuerySet):
    def delete(self):
        if self.filter(invoice__payments__isnull=False).exists():
            raise ProtectedError("Receipted Invoice lines must be retained.", list(self))
        protected = self.filter(charge_source__isnull=False)
        if protected.exists():
            raise ProtectedError("Linked Logistics lines must be retained.", list(protected))
        return super().delete()


class InvoiceLine(TimeStampedModel):
    objects = InvoiceLineQuerySet.as_manager()

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
    charge_source = models.ForeignKey(
        "logistics.LogisticsCharge",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines",
        editable=False,
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["created_at"]

    def delete(self, *args, **kwargs):
        if self.invoice.payments.exists():
            raise ProtectedError("Receipted Invoice lines must be retained.", [self])
        if self.pk and type(self).objects.filter(pk=self.pk, charge_source__isnull=False).exists():
            raise ProtectedError("Linked Logistics lines must be retained.", [self])
        return super().delete(*args, **kwargs)

    def clean(self):
        super().clean()
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if self.invoice_id and (
            self.invoice.payments.exists() or (previous and previous.invoice.payments.exists())
        ):
            if previous is None or any(
                getattr(self, field) != getattr(previous, field)
                for field in (
                    "invoice_id",
                    "service_id",
                    "parcel_id",
                    "shipment_id",
                    "charge_source_id",
                    "description",
                    "quantity",
                    "unit_price",
                    "line_total",
                )
            ):
                raise ValidationError("Receipted Invoice lines are immutable.")
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
        if (
            self.invoice_id
            and self.invoice.business.vertical == "LOGISTICS"
            and self.invoice.financial_snapshot_at
        ):
            old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            fields = (
                "invoice_id",
                "parcel_id",
                "shipment_id",
                "service_id",
                "charge_source_id",
                "description",
                "quantity",
                "unit_price",
                "line_total",
            )
            if old is None or any(getattr(self, field) != getattr(old, field) for field in fields):
                raise ValidationError("Issued Logistics invoice lines are immutable.")
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if previous.charge_source_id and previous.charge_source_id != self.charge_source_id:
                raise ValidationError("Saved charge source links are immutable.")
        if self.charge_source_id:
            charge = self.charge_source
            if charge.currency_snapshot and self.invoice.currency_code != charge.currency_snapshot:
                raise ValidationError("Invoice currency must match its source charge.")
            if (
                self.invoice.business_id,
                self.invoice.client_id,
                self.parcel_id,
                self.shipment_id,
                self.service_id,
                self.description,
                self.quantity,
                self.unit_price,
            ) != (
                charge.business_id,
                charge.client_id,
                charge.parcel_id,
                charge.shipment_id,
                charge.service_id,
                charge.invoice_description,
                charge.quantity,
                charge.unit_price,
            ):
                raise ValidationError("Invoice line must preserve its source charge snapshot.")
        if self.pk:
            from apps.logistics.models import LogisticsCharge

            charge = (
                self.charge_source
                or LogisticsCharge.objects.filter(invoice_line_id=self.pk).first()
            )
            if charge and (
                self.invoice_id != type(self).objects.get(pk=self.pk).invoice_id
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


class InvoicePaymentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Customer payment history is append-only.")

    def delete(self):
        raise ProtectedError("Customer payment history must be retained.", list(self))

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use the shared customer payment services.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Customer payment history is append-only.")


class InvoicePayment(models.Model):
    """Append-only customer receipts and linked reductions, independent of SaaS billing."""

    class Kind(models.TextChoices):
        RECEIPT = "RECEIPT", "Receipt"
        REVERSAL = "REVERSAL", "Reversal"
        REFUND = "REFUND", "Refund"

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        ONLINE = "ONLINE", "Online payment"
        VERIFIED_ONLINE = "VERIFIED_ONLINE", "Externally verified online"

    objects = InvoicePaymentQuerySet.as_manager()
    business = models.ForeignKey(
        "businesses.Business", on_delete=models.PROTECT, related_name="customer_payments"
    )
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    original = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="adjustments"
    )
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.RECEIPT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    invoice_total_snapshot = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    method = models.CharField(max_length=16, choices=Method.choices)
    reference = models.CharField(max_length=160)
    verification_reference = models.CharField(max_length=160, blank=True)
    reason_reference = models.CharField(max_length=160, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_payment_entries"
    )
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    idempotency_key = models.UUIDField(editable=False)

    class Meta:
        ordering = ["recorded_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "idempotency_key"], name="billings_payment_retry_unique"
            ),
            models.UniqueConstraint(
                fields=["business", "reference"],
                condition=Q(kind="RECEIPT", original__isnull=True),
                name="billings_payment_root_reference_unique",
            ),
            models.UniqueConstraint(
                fields=["original"],
                condition=Q(kind="RECEIPT", original__isnull=False),
                name="billings_payment_correction_unique",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="billings_payment_positive"),
            models.CheckConstraint(
                condition=Q(kind="RECEIPT") | Q(original__isnull=False),
                name="billings_payment_adjustment_original",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=["RECEIPT", "REVERSAL", "REFUND"]),
                name="billings_payment_known_kind",
            ),
        ]

    def clean(self):
        super().clean()
        if self.business_id != self.invoice.business_id:
            raise ValidationError("Payment and Invoice must share a workspace.")
        if self.invoice.client.business_id != self.business_id:
            raise ValidationError("Payment Invoice has an invalid Client relationship.")
        if self.amount is None or not self.amount.is_finite() or self.amount <= 0:
            raise ValidationError("Payment entries require a finite positive amount.")
        if not self.reference.strip():
            raise ValidationError("A stable receipt/transaction reference is required.")
        if self.method == self.Method.VERIFIED_ONLINE and not self.verification_reference.strip():
            raise ValidationError("Externally verified payments require an evidence reference.")
        if self.original_id:
            original = self.original
            if original.kind != self.Kind.RECEIPT or (
                original.business_id,
                original.invoice_id,
                original.currency,
                original.invoice_total_snapshot,
            ) != (
                self.business_id,
                self.invoice_id,
                self.currency,
                self.invoice_total_snapshot,
            ):
                raise ValidationError(
                    "Adjustments must reference a receipt on the same Invoice basis."
                )
            if not self.reason_reference.strip():
                raise ValidationError("Payment adjustments require an audit reason reference.")
        elif self.kind != self.Kind.RECEIPT:
            raise ValidationError("Payment reductions require an original receipt.")

    def save(self, *args, **kwargs):
        raise ValidationError("Use the shared customer payment services.")

    def delete(self, *args, **kwargs):
        raise ProtectedError("Customer payment history must be retained.", [self])

    def _append(self):
        if not self._state.adding:
            raise ValidationError("Customer payment history is append-only.")
        self.full_clean()
        super().save(force_insert=True)
        return self


# Register additive settlement models after the original billing models exist.
from .cancellation_models import (  # noqa: E402,F401
    InvoiceCancellationCredit,
    InvoiceObligationShare,
    InvoiceReceiptShare,
    InvoiceRefundAllocation,
    ParcelCancellationSettlement,
)
