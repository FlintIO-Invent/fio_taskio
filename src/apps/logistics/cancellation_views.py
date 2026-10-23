"""Accounting review/confirmation of customer service cancellation settlement."""

import uuid
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.billings.cancellation_services import (
    confirm_cancellation,
    refund_choices,
    review_cancellation,
    settlement_options,
)
from apps.billings.models import (
    InvoiceObligationShare,
    InvoiceReceiptShare,
    ParcelCancellationSettlement,
)
from apps.businesses.utils import business_module_required, business_role_required

from .financial_access import require_financial_access
from .models import Parcel

SALT = "logistics-cancellation-settlement"


class CancellationReviewForm(forms.Form):
    reason_reference = forms.CharField(max_length=1000, label="Cancellation reason / reference")
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, charges, invoices, parcel, **kwargs):
        super().__init__(*args, **kwargs)
        self.shares, self.receipts = {}, {}
        for invoice, options in invoices:
            obligations = [(o["line"], p) for o in options for p in o["members"]]
            saved = InvoiceObligationShare.objects.filter(line__invoice=invoice).exists()
            for option in options:
                if len(option["members"]) > 1 and not saved:
                    for member in option["members"]:
                        key = f"{option['line'].pk}:{member.pk}"
                        name = f"share_{invoice.pk}_{option['line'].pk}_{member.pk}"
                        self.shares[name] = (str(invoice.pk), key)
                        self.fields[name] = forms.DecimalField(
                            min_value=0,
                            max_digits=12,
                            decimal_places=2,
                            label=f"{invoice.invoice_number} · {option['line'].description} · {member.tracking_code}",
                            help_text=f"Explicit original freight share before tax ({invoice.currency_code}). All shares must total the original line amount.",
                        )
            if len(obligations) > 1:
                for receipt in invoice.payments.filter(kind="RECEIPT"):
                    if InvoiceReceiptShare.objects.filter(receipt=receipt).exists():
                        continue
                    for line, member in obligations:
                        key = f"{line.pk}:{member.pk}"
                        name = f"receipt_{receipt.pk}_{line.pk}_{member.pk}"
                        self.receipts[name] = (str(invoice.pk), str(receipt.pk), key)
                        self.fields[name] = forms.DecimalField(
                            min_value=0,
                            max_digits=12,
                            decimal_places=2,
                            required=False,
                            label=f"Receipt {receipt.reference} → {member.tracking_code} · {line.description}",
                            help_text=f"Amount including tax ({invoice.currency_code}). Allocate the whole receipt; use 0 where none belongs.",
                        )
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def choices(self):
        choices = {"invoices": {}}
        for name, (invoice, key) in self.shares.items():
            choices["invoices"].setdefault(invoice, {}).setdefault("obligations", {})[key] = str(
                self.cleaned_data[name]
            )
        for name, (invoice, receipt, key) in self.receipts.items():
            choices["invoices"].setdefault(invoice, {}).setdefault("receipts", {}).setdefault(
                receipt, {}
            )[key] = str(self.cleaned_data[name] or Decimal("0"))
        return choices


@never_cache
@business_module_required("invoicing")
@business_role_required("owner", "admin", "accountant")
@require_http_methods(["GET", "POST"])
def parcel_cancellation_settlement(request, parcel_id):
    business, actor = request.current_business, request.user
    require_financial_access(business=business, actor=actor, write=True, accounting=True)
    parcel = get_object_or_404(Parcel, business=business, client__business=business, pk=parcel_id)
    form, preview, token, error = None, None, None, None
    if request.method == "POST" and request.POST.get("confirmation"):
        try:
            payload = signing.loads(request.POST["confirmation"], salt=SALT, max_age=900)
            if (
                payload["parcel"] != parcel.pk
                or payload["business"] != business.pk
                or payload["actor"] != actor.pk
            ):
                raise ValidationError(
                    "This preview belongs to a different Parcel or accounting session."
                )
            confirm_cancellation(
                business=business,
                actor=actor,
                parcel=parcel,
                choices=payload["choices"],
                fingerprint=payload["fingerprint"],
                idempotency_key=payload["key"],
                reason_reference=payload["reason"],
            )
        except (signing.BadSignature, KeyError, TypeError, ValidationError) as exc:
            error = (
                "; ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "This preview expired or is invalid. Review again."
            )
        else:
            messages.success(
                request,
                "Cancellation settlement recorded. Any refund due still needs a completed manual refund.",
            )
            return redirect("logistics_parcel_cancellation_settlement", parcel_id=parcel.pk)
    case = (
        ParcelCancellationSettlement.objects.filter(business=business, parcel=parcel)
        .select_related("recorded_by")
        .first()
    )
    if case is None:
        try:
            _, charges, invoices = settlement_options(business=business, actor=actor, parcel=parcel)
            form = CancellationReviewForm(
                (
                    request.POST
                    if request.method == "POST" and not request.POST.get("confirmation")
                    else None
                ),
                charges=charges,
                invoices=invoices,
                parcel=parcel,
                initial={"idempotency_key": uuid.uuid4()},
            )
            if not form.is_bound and not form.shares and not form.receipts:
                preview = review_cancellation(
                    business=business, actor=actor, parcel=parcel, choices={}
                )
            if form.is_bound and form.is_valid():
                preview = review_cancellation(
                    business=business, actor=actor, parcel=parcel, choices=form.choices()
                )
                token = signing.dumps(
                    {
                        "parcel": parcel.pk,
                        "business": business.pk,
                        "actor": actor.pk,
                        "choices": form.choices(),
                        "fingerprint": preview["fingerprint"],
                        "key": str(form.cleaned_data["idempotency_key"]),
                        "reason": form.cleaned_data["reason_reference"],
                    },
                    salt=SALT,
                )
        except ValidationError as exc:
            error = "; ".join(exc.messages)
    credits, refunds = [], []
    if case:
        from apps.billings.payment_services import invoice_settlement

        for credit in case.credits.select_related(
            "obligation__line__invoice__business",
            "obligation__line__invoice__client",
            "obligation__parcel",
        ):
            invoice = credit.obligation.line.invoice
            balance = invoice_settlement(business=business, actor=actor, invoice=invoice)
            credits.append(
                {
                    "credit": credit,
                    "invoice": invoice,
                    "balance": balance,
                    "retained": credit.obligation.total - credit.total,
                    "retained_tax": credit.obligation.tax - credit.tax,
                    "service_charge": credit.obligation.subtotal - credit.subtotal,
                }
            )
            for receipt in invoice.payments.filter(kind="RECEIPT"):
                for available, due in refund_choices(invoice, receipt):
                    if available.pk == credit.pk:
                        refunds.append(
                            {
                                "reference": receipt.reference,
                                "due": due,
                                "currency": invoice.currency_code,
                                "url": reverse(
                                    "invoice_payment_adjust", args=[invoice.pk, receipt.pk]
                                )
                                + f"?cancellation_credit={credit.pk}",
                            }
                        )
    return render(
        request,
        "logistics/cancellation_settlement.html",
        {
            "parcel": parcel,
            "form": form,
            "preview": preview,
            "confirmation": token,
            "settlement_error": error,
            "settlement": case,
            "credits": credits,
            "refunds": refunds,
            "configured_service_charge": business.cancellation_service_charge,
            "service_charge_currency": business.currency,
        },
    )
