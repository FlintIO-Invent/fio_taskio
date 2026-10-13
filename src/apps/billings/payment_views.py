from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.businesses.models import BusinessUser
from apps.businesses.utils import (
    BILLING_MANAGE_ROLES,
    business_module_required,
    business_role_required,
)
from apps.logistics.financial_access import scope_invoices

from .models import Invoice, InvoicePayment
from .payment_forms import PaymentAdjustmentForm, PaymentReceiptForm
from .payment_services import (
    ACCOUNTING_ROLES,
    _remaining,
    adjust_invoice_payment,
    correct_invoice_payment,
    invoice_settlement,
    record_invoice_payment,
    require_payment_access,
)


def _invoice(request, invoice_id):
    return get_object_or_404(
        scope_invoices(
            Invoice.objects.filter(
                business=request.current_business, client__business=request.current_business
            ),
            business=request.current_business,
            actor=request.user,
        ),
        pk=invoice_id,
    )


def payment_context(*, business, actor, invoice):
    balance = invoice_settlement(business=business, actor=actor, invoice=invoice)
    writable, accounting = False, False
    try:
        require_payment_access(business=business, actor=actor, invoice=invoice, write=True)
        writable = True
        require_payment_access(
            business=business, actor=actor, invoice=invoice, write=True, accounting=True
        )
        accounting = True
    except PermissionDenied:
        pass
    entries = (
        list(
            invoice.payments.filter(business=business).select_related("recorded_by").order_by("pk")
        )
        if not balance.issues
        else []
    )
    reductions = {}
    for entry in entries:
        if entry.kind != "RECEIPT":
            reductions[entry.original_id] = reductions.get(entry.original_id, 0) + entry.amount
    for entry in entries:
        entry.can_adjust = (
            accounting
            and not balance.issues
            and entry.kind == "RECEIPT"
            and entry.amount > reductions.get(entry.pk, 0)
        )
    return {
        "payment_balance": balance,
        "has_customer_payments": invoice.payments.exists(),
        "payment_entries": entries,
        "payment_currency_differs": balance.currency != invoice.currency_code,
        "can_record_payment": (
            writable
            and not balance.issues
            and balance.outstanding > 0
            and invoice.status in (Invoice.Status.SENT, Invoice.Status.PAID)
            and not (business.vertical == "LOGISTICS" and invoice.snapshot_is_legacy)
        ),
    }


@never_cache
@business_role_required(*BILLING_MANAGE_ROLES)
@business_module_required("invoicing")
@require_http_methods(["GET", "POST"])
def invoice_payment_record(request, invoice_id):
    invoice = _invoice(request, invoice_id)
    require_payment_access(
        business=request.current_business, actor=request.user, invoice=invoice, write=True
    )
    balance = invoice_settlement(
        business=request.current_business, actor=request.user, invoice=invoice
    )
    member = BusinessUser.objects.get(business=request.current_business, user=request.user)
    form = PaymentReceiptForm(
        request.POST if request.method == "POST" else None,
        currency=balance.currency,
        accounting=member.role in ACCOUNTING_ROLES,
        initial={"method": "CASH", "amount": balance.outstanding},
    )
    if request.method == "POST" and form.is_valid():
        try:
            record_invoice_payment(
                business=request.current_business,
                actor=request.user,
                invoice=invoice,
                **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(request, "Customer receipt recorded. Invoice status is unchanged.")
            return redirect("invoice_detail", invoice_id=invoice.pk)
    return render(
        request,
        "billings/payment_form.html",
        {
            "invoice": invoice,
            "form": form,
            "payment_balance": balance,
            "title": "Record customer payment",
        },
    )


@never_cache
@business_role_required(*ACCOUNTING_ROLES)
@business_module_required("invoicing")
@require_http_methods(["GET", "POST"])
def invoice_payment_adjust(request, invoice_id, payment_id):
    invoice = _invoice(request, invoice_id)
    require_payment_access(
        business=request.current_business,
        actor=request.user,
        invoice=invoice,
        write=True,
        accounting=True,
    )
    original = get_object_or_404(
        InvoicePayment,
        business=request.current_business,
        invoice=invoice,
        pk=payment_id,
        kind="RECEIPT",
    )
    form = PaymentAdjustmentForm(
        request.POST if request.method == "POST" else None,
        currency=original.currency,
        accounting=True,
        initial={"amount": _remaining(original), "method": original.method},
    )
    if request.method == "POST" and form.is_valid():
        fields = dict(form.cleaned_data)
        action = fields.pop("action")
        fields.pop("currency")
        try:
            if action == "CORRECTION":
                correct_invoice_payment(
                    business=request.current_business,
                    actor=request.user,
                    invoice=invoice,
                    payment=original,
                    **fields,
                )
            else:
                fields.pop("method")
                fields.pop("verification_reference")
                adjust_invoice_payment(
                    business=request.current_business,
                    actor=request.user,
                    invoice=invoice,
                    payment=original,
                    kind=action,
                    **fields,
                )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            messages.success(request, "Payment adjustment recorded; original history retained.")
            return redirect("invoice_detail", invoice_id=invoice.pk)
    return render(
        request,
        "billings/payment_form.html",
        {
            "invoice": invoice,
            "form": form,
            "original_payment": original,
            "title": "Adjust customer receipt",
        },
    )
