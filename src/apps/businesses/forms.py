from django import forms

from .models import Business, ClarivoPlan


class BusinessSettingsForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = [
            "name",
            "email",
            "phone",
            "address",
            "country",
            "currency",
            "timezone",
            "tax_rate",
            "invoice_prefix",
            "invoice_start_number",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Acme Freight"}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "hello@example.com"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "+1 721 555 0100"}
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Business address",
                }
            ),
            "country": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Sint Maarten"}
            ),
            "currency": forms.Select(attrs={"class": "form-select"}),
            "timezone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "UTC"}
            ),
            "tax_rate": forms.NumberInput(
                attrs={"class": "form-control", "min": 0, "max": 100, "step": "0.01"}
            ),
            "invoice_prefix": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "INV"}
            ),
            "invoice_start_number": forms.NumberInput(
                attrs={"class": "form-control", "min": 1}
            ),
        }


class BusinessSubscriptionPlanForm(forms.Form):
    plan = forms.ModelChoiceField(
        queryset=ClarivoPlan.objects.none(),
        empty_label=None,
        widget=forms.HiddenInput(),
    )

    def __init__(self, *args, plans=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = plans if plans is not None else ClarivoPlan.objects.filter(is_active=True)
        self.fields["plan"].queryset = queryset
