from django import forms


class PaymentDecisionRadioSelect(forms.RadioSelect):
    paid_available = True

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if value == "paid" and not self.paid_available:
            option["attrs"]["disabled"] = True
        return option


class PaymentDecisionForm(forms.Form):
    def __init__(self, *args, paid_available=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decision"].widget.paid_available = paid_available

    decision = forms.ChoiceField(
        label="Customer payment decision",
        choices=[
            ("paid", "Paid · record money received"),
            ("unpaid", "Unpaid · keep outstanding balance"),
        ],
        widget=PaymentDecisionRadioSelect,
        error_messages={"required": "Select paid or unpaid, then press Continue."},
    )
