from django import forms


class PaymentDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        label="Customer payment decision",
        choices=[
            ("paid", "Paid · record money received"),
            ("unpaid", "Unpaid · keep outstanding balance"),
        ],
        widget=forms.RadioSelect,
        error_messages={"required": "Select paid or unpaid, then press Continue."},
    )
