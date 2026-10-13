"""Logistics finance policy layered on shared billing roles and persisted site grants.

Writes run under the existing Business lock, followed by the actor membership lock.
Accounting roles retain their financial scope independently of operational grants.
Staff clearance covers complete Parcel-only invoices, never unrelated financial rows.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef, Q

from apps.billings.models import Invoice, InvoiceLine
from apps.businesses.models import Business, BusinessSubscription, BusinessUser
from apps.businesses.utils import BILLING_MANAGE_ROLES, BILLING_VIEW_ROLES

from .location_access import (
    assignments_for,
    lock_actor_membership,
    membership_for,
    require_record_operation,
    scope_records,
)
from .models import Parcel

ACCOUNTING_ROLES = (BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN, BusinessUser.Role.ACCOUNTANT)


def require_financial_access(*, business, actor, write=False, accounting=False):
    current = Business.objects.filter(pk=business.pk, is_active=True, vertical="LOGISTICS").first()
    member = membership_for(business, actor)
    roles = (
        ACCOUNTING_ROLES if accounting else (BILLING_MANAGE_ROLES if write else BILLING_VIEW_ROLES)
    )
    if current is None or member is None or member.role not in roles:
        raise PermissionDenied(
            "Your workspace role does not permit this Logistics financial action."
        )
    subscription = (
        BusinessSubscription.objects.select_related("business", "plan")
        .filter(business=current)
        .first()
    )
    allowed = subscription and (
        subscription.can_use_module("invoicing")
        if write
        else subscription.can_view_module("invoicing")
    )
    if not allowed:
        raise PermissionDenied("Your workspace subscription does not permit Logistics billing.")
    if member.role == BusinessUser.Role.STAFF:
        if not (
            subscription.can_use_module("parcels")
            if write
            else subscription.can_view_module("parcels")
        ):
            raise PermissionDenied("Your workspace subscription does not permit Parcel clearance.")
        if not assignments_for(current, actor).exists():
            raise PermissionDenied(
                "An approved location assignment is required for financial clearance."
            )
        if write:
            from .location_access import require_work_location

            require_work_location(current, actor)
    return current


def scope_financial_targets(queryset, *, business, actor):
    require_financial_access(business=business, actor=actor)
    if membership_for(business, actor).role == BusinessUser.Role.STAFF:
        if queryset.model is not Parcel:
            return queryset.none()
        return scope_records(queryset, business=business, actor=actor)
    return queryset.filter(business=business)


def invoice_ui_permissions(*, business, actor, invoice):
    from apps.businesses.utils import business_can_modify_workspace

    member = membership_for(business, actor)
    writable = bool(
        member and member.role in BILLING_MANAGE_ROLES and business_can_modify_workspace(business)
    )
    accounting = writable
    if business.vertical == Business.Vertical.LOGISTICS:
        writable = (
            writable
            and scope_invoices(
                Invoice.objects.filter(pk=invoice.pk), business=business, actor=actor, write=True
            ).exists()
        )
        accounting = writable and member.role in ACCOUNTING_ROLES
    return {"invoice_can_clear": writable, "invoice_can_account": accounting}


def financial_parcels(*, business, actor, location_ids=None):
    return scope_records(
        Parcel.objects.filter(business=business, client__business=business),
        business=business,
        actor=actor,
        location_ids=location_ids,
    )


def scope_invoices(queryset, *, business, actor, write=False):
    """Empty, manual, Shipment and partially accessible invoices fail closed for STAFF."""
    if business.vertical != Business.Vertical.LOGISTICS:
        return queryset
    try:
        require_financial_access(business=business, actor=actor, write=write)
    except PermissionDenied:
        return queryset.none()
    queryset = queryset.filter(business=business, client__business=business)
    if membership_for(business, actor).role != BusinessUser.Role.STAFF:
        return queryset
    location_ids = None
    if write:
        from .location_access import require_work_location

        location_ids = [require_work_location(business, actor).pk]
    parcels = financial_parcels(business=business, actor=actor, location_ids=location_ids)
    lines = InvoiceLine.objects.filter(invoice_id=OuterRef("pk"))
    inaccessible = lines.filter(
        Q(parcel__isnull=True)
        | Q(shipment__isnull=False)
        | ~Q(parcel_id__in=parcels.values("pk"))
        | ~Q(parcel__client_id=OuterRef("client_id"))
    )
    return queryset.filter(Exists(lines), ~Exists(inaccessible))


def require_financial_target(*, business, actor, target, write=False):
    require_financial_access(business=business, actor=actor, write=write)
    if target.business_id != business.pk:
        raise PermissionDenied("Billing target is unavailable in this workspace.")
    if membership_for(business, actor).role == BusinessUser.Role.STAFF:
        if (
            not isinstance(target, Parcel)
            or not financial_parcels(business=business, actor=actor).filter(pk=target.pk).exists()
        ):
            raise PermissionDenied("Financial clearance requires an accessible Parcel.")
        if write:
            require_record_operation(target, business=business, actor=actor)


def require_invoice_access(*, business, actor, invoice, write=False, accounting=False):
    require_financial_access(business=business, actor=actor, write=write, accounting=accounting)
    if not scope_invoices(
        Invoice.objects.filter(pk=invoice.pk), business=business, actor=actor, write=write
    ).exists():
        raise PermissionDenied("This Invoice is unavailable for financial clearance.")


def financial_write_required(*, accounting=False):
    """Fresh authorization and serialization for shared Invoice UI mutations only."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.current_business.vertical != Business.Vertical.LOGISTICS:
                return view(request, *args, **kwargs)
            with transaction.atomic():
                business = Business.objects.select_for_update().get(pk=request.current_business.pk)
                lock_actor_membership(business, request.user)
                full_accounting = (
                    accounting or request.POST.get("status") == Invoice.Status.CANCELLED
                )
                require_financial_access(
                    business=business, actor=request.user, write=True, accounting=full_accounting
                )
                if "invoice_id" in kwargs:
                    from django.shortcuts import get_object_or_404

                    invoice = get_object_or_404(
                        Invoice.objects.filter(business=business), pk=kwargs["invoice_id"]
                    )
                    require_invoice_access(
                        business=business,
                        actor=request.user,
                        invoice=invoice,
                        write=True,
                        accounting=full_accounting,
                    )
                return view(request, *args, **kwargs)

        return wrapped

    return decorator


def project_invoice_references(*, business, actor, invoice):
    """Redact operational references in this response; never change saved billing rows."""
    from apps.logistics.location_access import scope_records
    from apps.logistics.models import Parcel, Shipment

    if business.vertical != Business.Vertical.LOGISTICS:
        return {}
    from django.db.models import prefetch_related_objects

    prefetch_related_objects([invoice], "lines")
    visibility = {
        "visible_parcel_ids": set(
            scope_records(
                Parcel.objects.filter(
                    business=business,
                    client__business=business,
                    pk__in=invoice.lines.values("parcel_id"),
                ),
                business=business,
                actor=actor,
            ).values_list("pk", flat=True)
        ),
        "visible_shipment_ids": set(
            scope_records(
                Shipment.objects.filter(
                    business=business, pk__in=invoice.lines.values("shipment_id")
                ),
                business=business,
                actor=actor,
            ).values_list("pk", flat=True)
        ),
    }
    for line in invoice.lines.all():
        if (
            line.parcel_id
            and line.parcel_id not in visibility["visible_parcel_ids"]
            or line.shipment_id
            and line.shipment_id not in visibility["visible_shipment_ids"]
        ):
            # Charge snapshots include the anonymous public tracking code. Shared
            # finance access must not disclose a restricted operational identifier.
            line.description = "Logistics charge (operational reference restricted)"
    return visibility
