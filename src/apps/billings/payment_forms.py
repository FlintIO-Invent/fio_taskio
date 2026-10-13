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

    def __init__(self, *args, currency, accounting, **kwargs):
        initial = {
            "currency": currency,
            "idempotency_key": uuid.uuid4(),
            **kwargs.pop("initial", {}),
        }
        super().__init__(*args, initial=initial, **kwargs)
        if not accounting:
            self.fields["method"].choices = [
                item for item in InvoicePayment.Method.choices if item[0] != "VERIFIED_ONLINE"
            ]
        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs["class"] = (
                    "form-select" if isinstance(field.widget, forms.Select) else "form-control"
                )


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
