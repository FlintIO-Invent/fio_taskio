import uuid

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
from .financial_access import require_financial_target, scope_financial_targets, scope_invoices
from .models import LogisticsCharge, Parcel, Shipment


def billing_context(request, target):
    kind = "parcel" if isinstance(target, Parcel) else "shipment"
    try:
        require_billing_access(
            business=request.current_business, actor=request.user, target_kind=kind
        )
        require_financial_target(
            business=request.current_business, actor=request.user, target=target
        )
    except PermissionDenied:
        return {}
    from .financial_coverage import coverage_for_parcel, coverage_for_shipment

    try:
        coverage = (coverage_for_parcel if kind == "parcel" else coverage_for_shipment)(
            business=request.current_business, actor=request.user, **{kind: target}
        )
    except ValidationError as exc:
        return {"billing": {"error": "; ".join(exc.messages), "kind": kind, "can_manage": False}}
    charges = list(
        LogisticsCharge.objects.filter(
            business=request.current_business, pk__in=[row.charge_id for row in coverage.charges]
        ).select_related("service", "client", "business")
    )
    from apps.billings.models import Invoice

    readable = scope_invoices(
        Invoice.objects.filter(business=request.current_business),
        business=request.current_business,
        actor=request.user,
    )
    for charge in charges:
        charge.display_invoice_line = (
            charge.invoice_lines.exclude(invoice__status="CANCELLED")
            .select_related("invoice")
            .first()
            or charge.invoice_lines.select_related("invoice").order_by("-pk").first()
        )
        charge.invoice_accessible = bool(
            charge.display_invoice_line
            and readable.filter(pk=charge.display_invoice_line.invoice_id).exists()
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
        require_financial_target(
            business=request.current_business, actor=request.user, target=target, write=True
        )
        writable = client is not None
    except PermissionDenied:
        writable = False
    return {
        "billing": {
            "charges": charges,
            "totals_by_currency": coverage.totals_by_currency,
            "coverage_issues": coverage.issues,
            "restricted_invoices": any("Restricted" in issue for issue in coverage.issues),
            "client": client,
            "error": error,
            "can_manage": writable,
            "kind": kind,
            "add_url": reverse(f"logistics_{kind}_charge", args=[target.pk]),
            "invoice_url": reverse(f"logistics_{kind}_invoice", args=[target.pk]),
            "pending": any(
                row.state == "UNINVOICED" for row in coverage.charges if row.target_kind == kind
            ),
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
    target = get_object_or_404(
        scope_financial_targets(
            model.objects.filter(business=request.current_business),
            business=request.current_business,
            actor=request.user,
        ),
        pk=pk,
    )
    require_financial_target(
        business=request.current_business, actor=request.user, target=target, write=True
    )
    guided = kind == "parcel" and request.GET.get("registration") == "1"
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
            if guided:
                return redirect("logistics_parcel_registration", parcel_id=pk)
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
            "charge_currency": request.current_business.currency,
            "back_url": reverse(
                "logistics_parcel_registration" if guided else f"logistics_{kind}_detail", args=[pk]
            ),
            "registration": guided,
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
    target = get_object_or_404(
        scope_financial_targets(
            model.objects.filter(business=request.current_business),
            business=request.current_business,
            actor=request.user,
        ),
        pk=pk,
    )
    require_financial_target(
        business=request.current_business, actor=request.user, target=target, write=True
    )
    guided = kind == "parcel" and request.GET.get("registration") == "1"
    try:
        client = target.client if kind == "parcel" else shipment_billing_client(target)
    except ValidationError:
        return redirect(f"logistics_{kind}_detail", **{f"{kind}_id": pk})
    form = ChargeInvoiceForm(
        request.POST if request.method == "POST" else None,
        business=request.current_business,
        target=target,
        client=client,
        actor=request.user,
        registration=guided,
        initial={
            "charges": list(
                target.charges.filter(voided_at__isnull=True)
                .exclude(invoice_lines__invoice__status__in=["DRAFT", "SENT", "PAID"])
                .values_list("pk", flat=True)
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
            if guided:
                return redirect("logistics_parcel_registration", parcel_id=pk)
            return redirect("invoice_detail", invoice_id=invoice.pk)
    return render(
        request,
        "logistics/billing_form.html",
        {
            "form": form,
            "target": target,
            "kind": kind,
            "title": "Create invoice / Add to existing invoice",
            "back_url": reverse(
                "logistics_parcel_registration" if guided else f"logistics_{kind}_detail", args=[pk]
            ),
            "registration": guided,
        },
    )
