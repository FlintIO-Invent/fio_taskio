from decimal import Decimal

from django import forms
from django.db.models import Q

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
    occurrence_reference = forms.CharField(
        max_length=80,
        required=False,
        help_text="Use a stable job/leg/occurrence reference only for a separate charge occurrence. A new retry token never creates a new obligation.",
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

    def __init__(self, *args, business, target, client, actor, registration=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.registration_target = target if registration else None
        charges = target.charges
        if registration:
            from .financial_access import scope_financial_targets
            from .models import Parcel

            parcels = scope_financial_targets(
                Parcel.objects.filter(business=business, client=client),
                business=business,
                actor=actor,
            )
            from .location_access import membership_for, require_work_location, scope_records

            if membership_for(business, actor).role == "staff":
                site = require_work_location(business, actor)
                parcels = scope_records(
                    parcels, business=business, actor=actor, location_ids=[site.pk]
                )
            charges = LogisticsCharge.objects.filter(parcel__in=parcels)
        self.fields["charges"].queryset = charges.filter(
            business=business, client=client, voided_at__isnull=True
        )
        pending = self.fields["charges"].queryset.exclude(
            invoice_lines__invoice__status__in=[
                Invoice.Status.DRAFT,
                Invoice.Status.SENT,
                Invoice.Status.PAID,
            ]
        )
        # Accept original selected rows on a bound guided retry. The service verifies
        # the complete payload and existing binding under lock; GET offers pending only.
        if registration and self.is_bound:
            values = (
                self.data.getlist("charges")
                if hasattr(self.data, "getlist")
                else self.data.get("charges", [])
            )
            submitted = [value for value in values if str(value).isdigit()]
            self.fields["charges"].queryset = self.fields["charges"].queryset.filter(
                Q(pk__in=pending.values("pk")) | Q(pk__in=submitted)
            )
        else:
            self.fields["charges"].queryset = pending
        from .financial_access import scope_invoices

        drafts = Invoice.objects.filter(business=business, client=client)
        if registration and self.is_bound and str(self.data.get("invoice", "")).isdigit():
            drafts = drafts.filter(Q(status="DRAFT") | Q(pk=self.data["invoice"]))
        else:
            drafts = drafts.filter(status="DRAFT")
        self.fields["invoice"].queryset = scope_invoices(
            drafts,
            business=business,
            actor=actor,
            write=True,
        )
        self.fields["charges"].label_from_instance = (
            lambda obj: f"{obj.parcel.tracking_code + ' · ' if registration else ''}{obj.description} — {format_money_for_business(obj.total, obj.billing_business)}"
        )
        if registration:
            self.fields["charges"].queryset = self.fields["charges"].queryset.select_related(
                "parcel", "business"
            )
            self.fields["charges"].help_text = (
                "Select this Parcel's charges and any other same-Client Parcels to combine. Previously billed charges are not offered."
            )

    def clean(self):
        cleaned = super().clean()
        charges = cleaned.get("charges")
        if (
            self.registration_target
            and charges is not None
            and not charges.filter(parcel=self.registration_target).exists()
        ):
            self.add_error(
                "charges", "Include at least one charge for the Parcel being registered."
            )
        return cleaned
