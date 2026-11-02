from django import forms


class PaymentDecisionRadioSelect(forms.RadioSelect):
    record_available = True

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if value == "record" and not self.record_available:
            option["attrs"]["disabled"] = True
        return option


class PaymentDecisionForm(forms.Form):
    def __init__(self, *args, record_available=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decision"].widget.record_available = record_available
        # Accept already-open forms, but store an action rather than a financial claim.
        if self.is_bound and self.data.get("decision") in ("paid", "unpaid"):
            data = self.data.copy()
            data["decision"] = {"paid": "record", "unpaid": "continue"}[data["decision"]]
            self.data = data
        if self.initial.get("decision") in ("paid", "unpaid"):
            self.initial["decision"] = {"paid": "record", "unpaid": "continue"}[
                self.initial["decision"]
            ]

    decision = forms.ChoiceField(
        label="Customer payment decision",
        choices=[
            ("record", "Record payment received"),
            ("continue", "Continue without recording a payment"),
        ],
        widget=PaymentDecisionRadioSelect,
        error_messages={"required": "Choose whether to record a payment, then press Continue."},
    )
