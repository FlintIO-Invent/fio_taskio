import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.businesses.localization import format_decimal_for_business
from apps.businesses.utils import (
    BILLING_MANAGE_ROLES,
    business_module_required,
    business_role_required,
)
from apps.crm.models import BusinessService

from .billing_forms import ChargeInvoiceForm, LogisticsChargeForm
from .billing_services import (
    add_charge,
    invoice_charges,
    require_billing_access,
    shipment_billing_client,
)
from .models import Parcel, Shipment


def billing_context(request, target):
    kind = "parcel" if isinstance(target, Parcel) else "shipment"
    try:
        require_billing_access(
            business=request.current_business, actor=request.user, target_kind=kind
        )
    except PermissionDenied:
        return {}
    charges = list(
        target.charges.filter(business=request.current_business).select_related(
            "service", "client", "invoice_line__invoice"
        )
    )
    try:
        client = target.client if kind == "parcel" else shipment_billing_client(target)
        error = ""
    except ValidationError as exc:
        client, error = None, "; ".join(exc.messages)
    try:
        require_billing_access(
            business=request.current_business, actor=request.user, target_kind=kind, write=True
        )
        writable = client is not None
    except PermissionDenied:
        writable = False
    return {
        "billing": {
            "charges": charges,
            "total": sum((charge.total for charge in charges), Decimal("0.00")),
            "client": client,
            "error": error,
            "can_manage": writable,
            "kind": kind,
            "add_url": reverse(f"logistics_{kind}_charge", args=[target.pk]),
            "invoice_url": reverse(f"logistics_{kind}_invoice", args=[target.pk]),
            "pending": any(charge.invoice_line_id is None for charge in charges),
        }
    }


@never_cache
@business_module_required("invoicing")
@business_role_required(*BILLING_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def charge_create(request, parcel_id=None, shipment_id=None):
    kind, model, pk = (
        ("parcel", Parcel, parcel_id)
        if parcel_id is not None
        else ("shipment", Shipment, shipment_id)
    )
    require_billing_access(
        business=request.current_business, actor=request.user, write=True, target_kind=kind
    )
    target = get_object_or_404(model, business=request.current_business, pk=pk)
    form = LogisticsChargeForm(
        request.POST if request.method == "POST" else None,
        business=request.current_business,
        initial={"idempotency_key": uuid.uuid4(), "charge_type": "service"},
    )
    if request.method == "POST" and form.is_valid():
        fields = dict(form.cleaned_data)
        fields.pop("charge_type")
        try:
            add_charge(
                business=request.current_business, actor=request.user, **{kind: target}, **fields
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect(f"logistics_{kind}_detail", **{f"{kind}_id": pk})
    prices = {
        str(service.pk): format_decimal_for_business(service.unit_price, request.current_business)
        for service in BusinessService.for_business(request.current_business)
    }
    return render(
        request,
        "logistics/billing_form.html",
        {
            "form": form,
            "target": target,
            "kind": kind,
            "title": "Add charge",
            "prices": prices,
            "back_url": reverse(f"logistics_{kind}_detail", args=[pk]),
        },
    )


@never_cache
@business_module_required("invoicing")
@business_role_required(*BILLING_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def charge_invoice(request, parcel_id=None, shipment_id=None):
    kind, model, pk = (
        ("parcel", Parcel, parcel_id)
        if parcel_id is not None
        else ("shipment", Shipment, shipment_id)
    )
    require_billing_access(
        business=request.current_business, actor=request.user, write=True, target_kind=kind
    )
    target = get_object_or_404(model, business=request.current_business, pk=pk)
    try:
        client = target.client if kind == "parcel" else shipment_billing_client(target)
    except ValidationError:
        return redirect(f"logistics_{kind}_detail", **{f"{kind}_id": pk})
    form = ChargeInvoiceForm(
        request.POST if request.method == "POST" else None,
        business=request.current_business,
        target=target,
        client=client,
        initial={
            "charges": list(
                target.charges.filter(invoice_line__isnull=True).values_list("pk", flat=True)
            )
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            invoice = invoice_charges(
                business=request.current_business,
                actor=request.user,
                charge_ids=list(form.cleaned_data["charges"].values_list("pk", flat=True)),
                invoice=form.cleaned_data["invoice"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
        else:
            return redirect("invoice_detail", invoice_id=invoice.pk)
    return render(
        request,
        "logistics/billing_form.html",
        {
            "form": form,
            "target": target,
            "kind": kind,
            "title": "Create invoice / Add to existing invoice",
            "back_url": reverse(f"logistics_{kind}_detail", args=[pk]),
        },
    )
