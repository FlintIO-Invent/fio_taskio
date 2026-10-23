import uuid
from decimal import Decimal

from django import forms

from .models import InvoicePayment


class PaymentReceiptForm(forms.Form):
    amount = forms.DecimalField(max_digits=18, decimal_places=6, min_value=Decimal("0.000001"))
    currency = forms.CharField(disabled=True)
    method = forms.ChoiceField(choices=InvoicePayment.Method.choices)
    reference = forms.CharField(
        max_length=160,
        help_text="Stable cash receipt or bank transaction reference; reuse it on retries.",
    )
    verification_reference = forms.CharField(
        max_length=160,
        required=False,
        help_text="For online receipts, reference evidence checked outside Motionmate. Recording does not charge the customer.",
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, currency, accounting, manual_receipts=False, invoice=None, **kwargs):
        initial = {
            "currency": currency,
            "idempotency_key": uuid.uuid4(),
            **kwargs.pop("initial", {}),
        }
        super().__init__(*args, initial=initial, **kwargs)
        # Logistics operators record receipts without an external evidence workflow.
        # Keep older open forms usable while storing the ordinary online method.
        if manual_receipts:
            if self.is_bound and self.data.get(self.add_prefix("method")) == "VERIFIED_ONLINE":
                data = self.data.copy()
                data[self.add_prefix("method")] = InvoicePayment.Method.ONLINE
                self.data = data
            self.fields["method"].choices = [
                item for item in InvoicePayment.Method.choices if item[0] != "VERIFIED_ONLINE"
            ]
            self.fields["reference"].required = False
            self.fields["reference"].help_text = (
                "Optional receipt or transaction reference. Leave blank to generate a receipt ID."
            )
            self.fields.pop("verification_reference")
        else:
            self.fields["method"].choices = [
                item for item in InvoicePayment.Method.choices if item[0] != "ONLINE"
            ]
        if not accounting and not manual_receipts:
            self.fields["method"].choices = [
                item for item in self.fields["method"].choices if item[0] != "VERIFIED_ONLINE"
            ]
        self.allocation_names = []
        if invoice is not None:
            from .cancellation_services import receipt_allocation_fields

            allocations = receipt_allocation_fields(invoice)
            if len(allocations) > 1:
                for share, debt in allocations:
                    name = f"allocation_{share.pk}"
                    self.allocation_names.append(name)
                    self.fields[name] = forms.DecimalField(
                        min_value=0,
                        max_digits=12,
                        decimal_places=2,
                        required=False,
                        label=f"Payment for {share.parcel.tracking_code} · {share.line.description}",
                        help_text=f"Outstanding {currency} {debt}. Allocate this receipt in full.",
                    )
        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs["class"] = (
                    "form-select" if isinstance(field.widget, forms.Select) else "form-control"
                )

    def clean(self):
        cleaned = super().clean()
        if self.allocation_names:
            cleaned["receipt_allocations"] = {
                name.removeprefix("allocation_"): cleaned.pop(name, None) or Decimal("0")
                for name in self.allocation_names
            }
        return cleaned


class PaymentAdjustmentForm(PaymentReceiptForm):
    action = forms.ChoiceField(
        choices=[
            ("REVERSAL", "Reverse erroneous receipt"),
            ("REFUND", "Record completed refund"),
            ("CORRECTION", "Reverse remaining receipt and record correction"),
        ]
    )
    reason_reference = forms.CharField(
        max_length=160, help_text="Audit case/evidence reference explaining this adjustment."
    )
