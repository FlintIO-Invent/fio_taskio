"""Append-only cancellation credits and explicit monetary allocation of receipts."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .models import InvoicePaymentQuerySet


class SettlementRecord(models.Model):
    objects = InvoicePaymentQuerySet.as_manager()
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        raise ValidationError("Use the cancellation settlement services.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Cancellation settlement history must be retained.")

    def _append(self):
        if not self._state.adding:
            raise ValidationError("Settlement records are append-only.")
        self.full_clean()
        super().save(force_insert=True)
        return self


class InvoiceObligationShare(SettlementRecord):
    line = models.ForeignKey(
        "billings.InvoiceLine", on_delete=models.PROTECT, related_name="obligation_shares"
    )
    parcel = models.ForeignKey(
        "logistics.Parcel", on_delete=models.PROTECT, related_name="obligation_shares"
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)

    @property
    def total(self):
        return self.subtotal + self.tax

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["line", "parcel"], name="billing_obligation_line_parcel"
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0, tax__gte=0),
                name="billing_obligation_nonnegative",
            ),
        ]

    def clean(self):
        if (self.line.invoice.business_id, self.parcel.business_id, self.parcel.client_id) != (
            self.business_id,
            self.business_id,
            self.line.invoice.client_id,
        ):
            raise ValidationError("Obligation shares require the Invoice tenant and Client.")
        if self.currency != self.line.invoice.currency_code:
            raise ValidationError("Obligation currency must match the Invoice.")


class InvoiceReceiptShare(SettlementRecord):
    receipt = models.ForeignKey(
        "billings.InvoicePayment", on_delete=models.PROTECT, related_name="obligation_shares"
    )
    obligation = models.ForeignKey(
        InvoiceObligationShare, on_delete=models.PROTECT, related_name="receipt_shares"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "obligation"], name="billing_receipt_obligation_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="billing_receipt_share_positive"
            ),
        ]

    def clean(self):
        if self.receipt.kind != "RECEIPT" or (
            self.receipt.business_id,
            self.obligation.business_id,
            self.receipt.invoice_id,
        ) != (self.business_id, self.business_id, self.obligation.line.invoice_id):
            raise ValidationError("Receipt allocation requires the same Invoice and tenant.")


class ParcelCancellationSettlement(SettlementRecord):
    parcel = models.OneToOneField(
        "logistics.Parcel", on_delete=models.PROTECT, related_name="cancellation_settlement"
    )
    idempotency_key = models.UUIDField()
    reason_reference = models.CharField(max_length=1000)
    request_snapshot = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business", "idempotency_key"], name="billing_cancellation_retry_unique"
            )
        ]

    def clean(self):
        if self.parcel.business_id != self.business_id or self.parcel.current_status != "CANCELLED":
            raise ValidationError("Settlement requires a cancelled Parcel in this tenant.")


class InvoiceCancellationCredit(SettlementRecord):
    settlement = models.ForeignKey(
        ParcelCancellationSettlement, on_delete=models.PROTECT, related_name="credits"
    )
    obligation = models.OneToOneField(
        InvoiceObligationShare, on_delete=models.PROTECT, related_name="cancellation_credit"
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def total(self):
        return self.subtotal + self.tax

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0, tax__gte=0),
                name="billing_cancellation_credit_nonnegative",
            )
        ]

    def clean(self):
        if (
            self.settlement.business_id,
            self.obligation.business_id,
            self.settlement.parcel_id,
        ) != (self.business_id, self.business_id, self.obligation.parcel_id):
            raise ValidationError("Credit must match the cancelled Parcel obligation.")
        if self.subtotal > self.obligation.subtotal or self.tax > self.obligation.tax:
            raise ValidationError("Credit cannot exceed the original obligation.")


class InvoiceRefundAllocation(SettlementRecord):
    refund = models.OneToOneField(
        "billings.InvoicePayment", on_delete=models.PROTECT, related_name="cancellation_allocation"
    )
    credit = models.ForeignKey(
        InvoiceCancellationCredit, on_delete=models.PROTECT, related_name="refund_allocations"
    )

    def clean(self):
        if self.refund.kind != "REFUND" or (
            self.refund.business_id,
            self.credit.business_id,
            self.refund.invoice_id,
        ) != (self.business_id, self.business_id, self.credit.obligation.line.invoice_id):
            raise ValidationError("Refund allocation must match the credited Invoice and tenant.")
