from decimal import Decimal

from django import forms

from apps.billings.models import Invoice
from apps.businesses.localization import format_money_for_business, parse_localized_decimal
from apps.crm.models import BusinessService

from .models import LogisticsCharge


class ChargeServiceChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} — {format_money_for_business(obj.unit_price, obj.business)}"


class LogisticsChargeForm(forms.Form):
    charge_type = forms.ChoiceField(
        choices=[("service", "Existing service"), ("custom", "Custom charge")],
        widget=forms.RadioSelect,
    )
    service = ChargeServiceChoice(queryset=BusinessService.objects.none(), required=False)
    description = forms.CharField(
        max_length=160,
        required=False,
        help_text="Required for custom charges; optional description override for saved services.",
    )
    quantity = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), initial=1
    )
    unit_price = forms.CharField(
        required=False,
        label="Unit price",
        help_text="Leave blank to use the saved Service price. You may enter today's agreed price.",
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.fields["service"].queryset = BusinessService.for_business(business)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.RadioSelect, forms.HiddenInput)):
                field.widget.attrs["class"] = (
                    "form-select" if isinstance(field.widget, forms.Select) else "form-control"
                )
        self.fields["unit_price"].widget.attrs["inputmode"] = "decimal"

    def clean(self):
        cleaned = super().clean()
        service = cleaned.get("service")
        if cleaned.get("charge_type") == "service" and not service:
            self.add_error("service", "Choose an active saved service.")
        if cleaned.get("charge_type") == "custom":
            cleaned["service"] = None
            if not cleaned.get("description"):
                self.add_error("description", "Enter a description for this charge.")
        value = cleaned.get("unit_price")
        if not value:
            cleaned["unit_price"] = None
            if cleaned.get("charge_type") == "custom":
                self.add_error("unit_price", "Enter the custom unit price.")
        else:
            try:
                price = parse_localized_decimal(value, self.business)
                forms.DecimalField(max_digits=12, decimal_places=2, min_value=0).clean(price)
                cleaned["unit_price"] = price
            except (ArithmeticError, forms.ValidationError):
                self.add_error(
                    "unit_price", "Enter a valid nonnegative price with up to two decimal places."
                )
        return cleaned


class ChargeInvoiceForm(forms.Form):
    charges = forms.ModelMultipleChoiceField(
        queryset=LogisticsCharge.objects.none(), widget=forms.CheckboxSelectMultiple
    )
    invoice = forms.ModelChoiceField(
        queryset=Invoice.objects.none(),
        required=False,
        empty_label="Create a new draft invoice",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, business, target, client, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["charges"].queryset = target.charges.filter(
            business=business, client=client, invoice_line__isnull=True
        )
        self.fields["invoice"].queryset = Invoice.objects.filter(
            business=business, client=client, status=Invoice.Status.DRAFT
        )
        self.fields["charges"].label_from_instance = (
            lambda obj: f"{obj.description} — {format_money_for_business(obj.total, business)}"
        )
