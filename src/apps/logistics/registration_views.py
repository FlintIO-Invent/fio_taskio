"""A resumable handoff between existing forms/services, with no wizard state ledger."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.billings.models import Invoice
from apps.billings.payment_forms import PaymentReceiptForm
from apps.billings.payment_services import (
    ACCOUNTING_ROLES,
    invoice_settlement,
    record_invoice_payment,
)
from apps.billings.services import change_invoice_status
from apps.businesses.models import Business
from apps.businesses.utils import business_module_required, business_role_required, can_use_module

from .financial_access import scope_invoices
from .location_access import (
    lock_actor_membership,
    membership_for,
    require_record_operation,
    require_work_location,
    scope_records,
)
from .parcel_policy import PARCEL_VIEW_ROLES
from .parcel_services import parcels_for_business
from .shipment_forms import ShipmentWriteForm
from .shipment_policy import ASSIGNABLE_PARCEL_STATUSES, ASSIGNABLE_SHIPMENT_STATUSES
from .shipment_services import assign_parcel, require_shipment_access, shipments_for_business
from .workflow_summary import resolve_parcel_workflow


def registration_url(parcel):
    return reverse("logistics_parcel_registration", args=[parcel.pk])


def registration_parcel(request):
    """Only a fixed, scoped Parcel continuation; never accept arbitrary return URLs."""
    value = request.GET.get("registration_parcel")
    if not value:
        return None
    return get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user), pk=_id(value)
    )


def _id(value):
    try:
        result = int(value)
        if result > 0:
            return result
    except (TypeError, ValueError):
        pass
    raise Http404("Registration record is unavailable.")


def _parcel(request, parcel_id):
    return get_object_or_404(
        parcels_for_business(business=request.current_business, actor=request.user).select_related(
            "client"
        ),
        pk=parcel_id,
    )


def _related_invoice(request, summary, invoice_id):
    # The resolver already checks frozen membership and all sibling sources.
    ids = [row["id"] for row in summary.financial["invoices"]]
    related = Invoice.objects.filter(business=request.current_business, pk__in=ids)
    if summary.financial["visibility"] == "CLEARANCE_ONLY":
        # An operating worker may explicitly issue a complete authorized Parcel
        # Invoice. This does not broaden their read-only clearance summary.
        related = Invoice.objects.filter(
            business=request.current_business, lines__parcel_id=summary.parcel_id
        ).distinct()
    return get_object_or_404(
        scope_invoices(
            related,
            business=request.current_business,
            actor=request.user,
            write=True,
        ),
        pk=_id(invoice_id),
    )


def _shipment_choices(request, parcel):
    if parcel.shipment_id or parcel.current_status not in ASSIGNABLE_PARCEL_STATUSES:
        return [], False
    try:
        require_shipment_access(business=request.current_business, actor=request.user, write=True)
        require_record_operation(parcel, business=request.current_business, actor=request.user)
        site = require_work_location(request.current_business, request.user)
    except PermissionDenied:
        return [], False
    if not all(can_use_module(request.current_business, name) for name in ("parcels", "tracking")):
        return [], False
    choices = shipments_for_business(business=request.current_business, actor=request.user).filter(
        status__in=ASSIGNABLE_SHIPMENT_STATUSES
    )
    # Use the same billed-Shipment Client restriction as assign_parcel.
    from .models import LogisticsCharge

    choices = choices.exclude(
        pk__in=LogisticsCharge.objects.filter(
            business=request.current_business, shipment__isnull=False
        )
        .exclude(client=parcel.client)
        .values("shipment_id")
    )
    if site:
        choices = scope_records(
            choices, business=request.current_business, actor=request.user, location_ids=[site.pk]
        )
    # Route selection is explicit; it does not grant operating access.
    for name in ("origin", "destination"):
        site_id = getattr(parcel, name + "_location_id")
        choices = (
            choices.filter(**{name + "_location_id": site_id})
            if site_id
            else choices.filter(**{name + "__iexact": getattr(parcel, name)})
        )
    rows = list(choices.order_by("-created_at", "-pk")[:25])
    for shipment in rows:
        shipment.registration_form = ShipmentWriteForm(
            shipment=shipment, auto_id=f"id_shipment_{shipment.pk}_%s"
        )
    return rows, True


def _post(request, parcel, summary):
    action = request.POST.get("action")
    if action in ("issue", "payment"):
        invoice = _related_invoice(request, summary, request.POST.get("invoice"))
        if action == "issue":
            if invoice.status not in ("DRAFT", "SENT", "PAID"):
                raise ValidationError("This Invoice cannot be issued. Review its current state.")
            change_invoice_status(
                business=request.current_business,
                actor=request.user,
                invoice=invoice,
                status="SENT",
            )
            messages.success(request, "Invoice issued. Customer payment is optional at this step.")
        else:
            balance = invoice_settlement(
                business=request.current_business, actor=request.user, invoice=invoice
            )
            form = PaymentReceiptForm(
                request.POST,
                invoice=invoice,
                manual_receipts=True,
                currency=balance.currency,
                accounting=membership_for(request.current_business, request.user).role
                in ACCOUNTING_ROLES,
            )
            if not form.is_valid():
                return form, invoice
            try:
                record_invoice_payment(
                    business=request.current_business,
                    actor=request.user,
                    invoice=invoice,
                    **form.cleaned_data,
                )
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))
                return form, invoice
            messages.success(request, "Customer receipt recorded.")
    elif action == "assign":
        shipment = get_object_or_404(
            shipments_for_business(business=request.current_business, actor=request.user),
            pk=_id(request.POST.get("shipment")),
        )
        form = ShipmentWriteForm(request.POST, shipment=shipment)
        if not form.is_valid():
            raise ValidationError("The Shipment form is incomplete. Reload before assigning.")
        assign_parcel(
            business=request.current_business,
            actor=request.user,
            parcel=parcel,
            shipment=shipment,
            **form.cleaned_data,
        )
        messages.success(request, "Parcel assigned to Shipment.")
    elif action == "later":
        # Deferral is a navigation choice, not a saved assignment/clearance flag.
        return redirect(registration_url(parcel) + "?summary=1")
    else:
        raise ValidationError("Choose an available registration action.")
    return redirect(registration_url(parcel))


@never_cache
@business_module_required("parcels", access="read")
@business_module_required("tracking", access="read")
@business_role_required(*PARCEL_VIEW_ROLES)
@require_http_methods(["GET", "POST"])
def parcel_registration(request, parcel_id):
    error, payment_form, payment_invoice = None, None, None
    if request.method == "POST":
        # Fresh source/permissions and writes share the existing lock order.
        with transaction.atomic():
            request.current_business = Business.objects.select_for_update().get(
                pk=request.current_business.pk
            )
            lock_actor_membership(request.current_business, request.user)
            parcel = _parcel(request, parcel_id)
            summary = resolve_parcel_workflow(
                business=request.current_business, actor=request.user, parcel=parcel
            )
            try:
                result = _post(request, parcel, summary)
                if isinstance(result, tuple):
                    payment_form, payment_invoice = result
                else:
                    return result
            except ValidationError as exc:
                error = "; ".join(exc.messages)
    parcel = _parcel(request, parcel_id)
    summary = resolve_parcel_workflow(
        business=request.current_business, actor=request.user, parcel=parcel
    )
    actions = {action["code"]: action for action in summary.executable_actions}
    invoices = []
    if summary.financial["visibility"] == "DETAILED":
        for row in summary.financial["invoices"]:
            invoices.append(
                {
                    **row,
                    "can_issue": f"ISSUE_INVOICE_{row['id']}" in actions,
                    "can_pay": f"RECORD_PAYMENT_{row['id']}" in actions,
                }
            )
    elif summary.financial["visibility"] == "CLEARANCE_ONLY":
        for invoice in scope_invoices(
            Invoice.objects.filter(
                business=request.current_business, lines__parcel=parcel
            ).distinct(),
            business=request.current_business,
            actor=request.user,
            write=True,
        ):
            balance = invoice_settlement(
                business=request.current_business, actor=request.user, invoice=invoice
            )
            invoices.append(
                {
                    "id": invoice.pk,
                    "number": "Parcel Invoice",
                    "lifecycle_status": invoice.status,
                    "restricted": True,
                    "can_issue": invoice.status == "DRAFT",
                    "can_pay": invoice.status in ("SENT", "PAID")
                    and not balance.issues
                    and balance.outstanding > 0
                    and not invoice.snapshot_is_legacy,
                }
            )
    selected_payment = request.GET.get("payment")
    if payment_form is None and selected_payment:
        if not any(str(row["id"]) == selected_payment and row["can_pay"] for row in invoices):
            raise PermissionDenied("Payment entry is unavailable for this Parcel/Invoice.")
        payment_invoice = _related_invoice(request, summary, selected_payment)
        balance = invoice_settlement(
            business=request.current_business, actor=request.user, invoice=payment_invoice
        )
        payment_form = PaymentReceiptForm(
            invoice=payment_invoice,
            manual_receipts=True,
            currency=balance.currency,
            accounting=membership_for(request.current_business, request.user).role
            in ACCOUNTING_ROLES,
            initial={"method": "CASH", "amount": balance.outstanding},
        )
    shipments, can_assign = _shipment_choices(request, parcel)
    financial_actions = []
    for action in actions.values():
        if action["code"] in ("ADD_CHARGE", "GENERATE_INVOICE"):
            financial_actions.append({**action, "url": action["url"] + "?registration=1"})
        elif action["code"].startswith("GENERATE_SHIPMENT_INVOICE_"):
            financial_actions.append(action)
    tasks = []
    if summary.financial["visibility"] == "DETAILED":
        active = [row for row in summary.financial["charges"] if not row["voided"]]
        if not active:
            tasks.append("Needs charges or accounting review")
        elif any(not row["billed"] for row in active):
            tasks.append("Needs Invoice")
        if any(row["lifecycle_status"] == "DRAFT" for row in invoices):
            tasks.append("Needs Invoice issuance")
        if not summary.financial["clearance"]["cleared"]:
            tasks.append("Needs payment or accounting review")
    elif not summary.financial["clearance"]["cleared"]:
        tasks.append("Needs accounting clearance")
    if not parcel.shipment_id:
        tasks.append("Needs Shipment · assignment may be deferred")
    resume_step = "registration-shipment"
    resume_label = "Continue to Shipment"
    if any(action["code"] == "GENERATE_INVOICE" for action in financial_actions) or not invoices:
        resume_step, resume_label = "registration-billing", "Continue to charges & Invoice"
    elif any(row["can_issue"] for row in invoices):
        resume_step, resume_label = "registration-payment", "Continue to Invoice issuance"
    elif parcel.shipment_id or request.GET.get("summary") == "1":
        resume_step, resume_label = "registration-summary", "View completion summary"
    return render(
        request,
        "logistics/parcel_registration.html",
        {
            "parcel": parcel,
            "workflow_summary": summary,
            "financial_actions": financial_actions,
            "invoices": invoices,
            "shipments": shipments,
            "can_assign": can_assign,
            "payment_form": payment_form,
            "payment_invoice": payment_invoice,
            "error": error,
            "show_completion": request.GET.get("summary") == "1" or bool(parcel.shipment_id),
            "registration_tasks": tasks,
            "resume_step": resume_step,
            "cancellation_can_manage": membership_for(request.current_business, request.user).role
            in ("owner", "admin", "accountant"),
            "resume_label": resume_label,
        },
    )
