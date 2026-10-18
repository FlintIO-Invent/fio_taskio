"""Reusable, read-only financial applicability for later payment/scanner integrations.

Shipment amounts are shared obligations, never invented per-Parcel allocations.
A bulk result counts each charge once. Settlement requires authoritative shared
customer receipts; manual Invoice PAID status alone cannot clear cargo.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.billings.models import Invoice, InvoiceLine
from apps.businesses.models import Business, BusinessUser
from apps.crm.models import ActivityLog
from apps.crm.services import log_activity

from .financial_access import (
    financial_parcels,
    require_financial_access,
    require_financial_target,
    scope_invoices,
)
from .location_access import lock_actor_membership, membership_for
from .models import LogisticsCharge, LogisticsChargeParcel, Parcel, Shipment


@dataclass(frozen=True)
class ChargeCoverage:
    charge_id: int
    parcel_ids: tuple[int, ...]
    target_kind: str
    amount: Decimal
    currency: str
    state: str
    invoice_ids: tuple[int, ...]
    shared: bool
    financially_settled: bool = False


@dataclass(frozen=True)
class FinancialCoverage:
    parcel_ids: tuple[int, ...]
    charges: tuple[ChargeCoverage, ...]
    totals_by_currency: dict[str, Decimal]
    uncovered_parcel_ids: tuple[int, ...]
    issues: tuple[str, ...]
    complete: bool
    cleared: bool


@dataclass(frozen=True)
class FinancialClearance:
    parcel_id: int
    complete: bool
    cleared: bool
    issues: tuple[str, ...]


def validate_location_integrity(record):
    for name in ("origin_location", "destination_location"):
        location = getattr(record, name)
        if location is not None and location.business_id != record.business_id:
            raise ValidationError("Financial targets have cross-tenant operating locations.")
    sites = getattr(record, "_prefetched_objects_cache", {}).get("handling_sites")
    invalid_sites = (
        any(
            site.business_id != record.business_id
            or site.location.business_id != record.business_id
            for site in sites
        )
        if sites is not None
        else record.handling_sites.exclude(
            business_id=record.business_id, location__business_id=record.business_id
        ).exists()
    )
    if invalid_sites:
        raise ValidationError("Financial targets have inconsistent handling-site relationships.")
    if isinstance(record, Parcel) and record.shipment_id:
        if record.shipment.business_id != record.business_id:
            raise ValidationError("Parcel and Shipment must share a tenant.")
        validate_location_integrity(record.shipment)


def validate_invoice_money(invoice):
    from apps.billings.services import calculate_tax_amount

    lines = getattr(invoice, "_prefetched_objects_cache", {}).get("lines")
    subtotal = (
        sum((line.line_total for line in lines), Decimal("0.00"))
        if lines is not None
        else invoice.lines.aggregate(value=Sum("line_total"))["value"] or Decimal("0.00")
    )
    if (
        subtotal != invoice.subtotal
        or invoice.total != invoice.subtotal + invoice.tax
        or calculate_tax_amount(subtotal=invoice.subtotal, tax_rate=invoice.tax_rate_percentage)
        != invoice.tax
    ):
        raise ValidationError("Invoice monetary totals require integrity review.")


def validate_charge_coverage(charge):
    for name in ("client", "parcel", "shipment", "service"):
        reference = getattr(charge, name)
        if reference is not None and reference.business_id != charge.business_id:
            raise ValidationError("Charge has a cross-tenant financial reference.")
    entries = list(
        charge.parcel_coverage.all()
        if "parcel_coverage" in getattr(charge, "_prefetched_objects_cache", {})
        else charge.parcel_coverage.select_related("parcel")
    )
    if not charge.coverage_recorded_at or not entries:
        raise ValidationError(
            "Historical Shipment charge membership requires explicit accounting review."
        )
    parcels = tuple(entry.parcel for entry in entries)
    for parcel in parcels:
        validate_location_integrity(parcel)
    if any(
        (item.business_id, item.client_id) != (charge.business_id, charge.client_id)
        or item.client.business_id != charge.business_id
        for item in parcels
    ):
        raise ValidationError("Charge coverage has an invalid tenant/client relationship.")
    if charge.parcel_id and {item.pk for item in parcels} != {charge.parcel_id}:
        raise ValidationError("Direct charge membership does not match its Parcel.")
    lines = list(
        charge.invoice_lines.all()
        if "invoice_lines" in getattr(charge, "_prefetched_objects_cache", {})
        else charge.invoice_lines.select_related("invoice")
    )
    for line in lines:
        if (
            line.invoice.business_id,
            line.invoice.client_id,
            line.parcel_id,
            line.shipment_id,
            line.service_id,
            line.quantity,
            line.unit_price,
            line.description,
        ) != (
            charge.business_id,
            charge.client_id,
            charge.parcel_id,
            charge.shipment_id,
            charge.service_id,
            charge.quantity,
            charge.unit_price,
            charge.invoice_description,
        ):
            raise ValidationError("Invoice history does not match its saved charge.")
        if line.invoice.status != Invoice.Status.DRAFT:
            validate_invoice_money(line.invoice)
        if line.line_total != charge.total:
            raise ValidationError("Invoice line amount does not match its saved charge.")
        if line.invoice.status != Invoice.Status.DRAFT and not line.invoice.financial_snapshot_at:
            raise ValidationError("Issued Invoice lacks its monetary snapshot seal.")
        if line.invoice.currency_code != charge.currency_snapshot:
            raise ValidationError("Invoice and charge currencies do not match.")
    if charge.invoice_line_id and not any(line.pk == charge.invoice_line_id for line in lines):
        raise ValidationError("The original charge binding requires accounting review.")
    return parcels


def _result(*, business, actor, parcels, charges, clearance_only=False):
    rows, issues, totals, covered = [], [], {}, set()
    if (
        InvoiceLine.objects.filter(invoice__business=business, charge_source__isnull=True)
        .exclude(invoice__status=Invoice.Status.CANCELLED)
        .filter(
            Q(parcel_id__in=[item.pk for item in parcels])
            | Q(
                shipment__isnull=False,
                invoice__client_id__in=[item.client_id for item in parcels],
            )
        )
        .exists()
    ):
        issues.append("Unlinked financial history requires accounting coverage review.")
    staff = membership_for(business, actor).role == BusinessUser.Role.STAFF
    readable_invoices = scope_invoices(
        Invoice.objects.filter(business=business), business=business, actor=actor
    )
    for charge in charges:
        try:
            members = validate_charge_coverage(charge)
        except ValidationError:
            if charge.voided_at:
                continue
            issues.append(
                "Unproven or inconsistent historical financial coverage requires accounting review."
            )
            continue
        if (
            staff
            and not clearance_only
            and (
                charge.shipment_id
                or not financial_parcels(business=business, actor=actor)
                .filter(pk__in=[item.pk for item in members])
                .count()
                == len(members)
            )
        ):
            issues.append("Restricted financial relationships require accounting clearance.")
            continue
        lines = list(charge.invoice_lines.select_related("invoice").order_by("pk"))
        if (
            staff
            and not clearance_only
            and any(not readable_invoices.filter(pk=line.invoice_id).exists() for line in lines)
        ):
            issues.append("Restricted financial relationships require accounting clearance.")
            continue
        active = [line for line in lines if line.invoice.status != Invoice.Status.CANCELLED]
        if charge.voided_at and active:
            issues.append("Voided charges still have active Invoice bindings; review is required.")
        if len(active) > 1:
            issues.append("A charge has multiple active Invoice bindings; review is required.")
        state = (
            "VOIDED"
            if charge.voided_at
            else (active[0].invoice.status if len(active) == 1 else "UNINVOICED")
        )
        financially_settled = False
        if not charge.voided_at and len(active) == 1:
            from apps.billings.payment_services import _invoice_settlement

            balance = _invoice_settlement(active[0].invoice)
            financially_settled = balance.settled
            from apps.billings.cancellation_services import parcel_invoice_settled

            allocated = [
                parcel_invoice_settled(active[0].invoice, item.pk)
                for item in members
                if item.pk in {p.pk for p in parcels}
            ]
            if allocated and all(value is not None for value in allocated):
                financially_settled = all(allocated)
            if balance.issues or balance.legacy_paid_unverified:
                issues.append("Invoice receipt history requires accounting settlement review.")
        if not charge.voided_at and (
            charge.currency_is_legacy
            or not charge.currency_snapshot
            or charge.logical_key is None
            or any(line.invoice.snapshot_is_legacy for line in active)
        ):
            issues.append("Legacy currency, tax or duplicate-charge history requires confirmation.")
        if not charge.voided_at:
            covered.update(item.pk for item in members)
            if charge.currency_snapshot:
                totals[charge.currency_snapshot] = (
                    totals.get(charge.currency_snapshot, Decimal("0.00")) + charge.total
                )
        rows.append(
            ChargeCoverage(
                charge.pk,
                tuple(sorted(item.pk for item in members)),
                "parcel" if charge.parcel_id else "shipment",
                charge.total,
                charge.currency_snapshot or "UNKNOWN",
                state,
                tuple(dict.fromkeys(line.invoice_id for line in lines)),
                len(members) > 1,
                financially_settled,
            )
        )
    ids = tuple(sorted(item.pk for item in parcels))
    uncovered = tuple(pk for pk in ids if pk not in covered)
    if uncovered:
        issues.append(
            "Some Parcels have no recorded active financial obligations; clearance cannot be inferred."
        )
    issues = tuple(dict.fromkeys(issues))
    active_rows = [row for row in rows if row.state != "VOIDED"]
    complete = bool(ids) and not issues
    return FinancialCoverage(
        ids,
        tuple(rows),
        totals,
        uncovered,
        issues,
        complete,
        complete and bool(active_rows) and all(row.financially_settled for row in active_rows),
    )


def _parcels(*, business, actor, parcel_ids):
    require_financial_access(business=business, actor=actor)
    ids = set(parcel_ids)
    queryset = Parcel.objects.filter(business=business, client__business=business, pk__in=ids)
    if membership_for(business, actor).role == BusinessUser.Role.STAFF:
        queryset = financial_parcels(business=business, actor=actor).filter(pk__in=ids)
    parcels = list(
        queryset.select_related(
            "origin_location",
            "destination_location",
            "shipment__origin_location",
            "shipment__destination_location",
        )
        .prefetch_related("handling_sites__location", "shipment__handling_sites__location")
        .order_by("pk")
    )
    if len(parcels) != len(ids):
        raise PermissionDenied("Financial coverage requires accessible workspace Parcels.")
    for parcel in parcels:
        validate_location_integrity(parcel)
    return parcels


def coverage_for_parcels(*, business, actor, parcel_ids):
    parcels = _parcels(business=business, actor=actor, parcel_ids=parcel_ids)
    ids = [item.pk for item in parcels]
    charges = (
        LogisticsCharge.objects.filter(business=business)
        .filter(
            Q(parcel_id__in=ids)
            | Q(parcel_coverage__parcel_id__in=ids)
            | Q(
                shipment__isnull=False,
                coverage_recorded_at__isnull=True,
                client_id__in=[item.client_id for item in parcels],
            )
        )
        .distinct()
        .order_by("pk")
    )
    return _result(business=business, actor=actor, parcels=parcels, charges=charges)


def clearance_for_parcel(*, business, actor, parcel):
    """Bounded status-only clearance for an accessible Parcel, including shared freight.

    Does not grant Invoice visibility, expose amounts/other cargo, authorize payment,
    or permit an operational release. Recheck inside the Business write transaction.
    """
    parcels = _parcels(business=business, actor=actor, parcel_ids=[getattr(parcel, "pk", parcel)])
    ids = [item.pk for item in parcels]
    charges = (
        LogisticsCharge.objects.filter(business=business)
        .filter(
            Q(parcel_id__in=ids)
            | Q(parcel_coverage__parcel_id__in=ids)
            | Q(
                shipment__isnull=False,
                coverage_recorded_at__isnull=True,
                voided_at__isnull=True,
                client_id=parcels[0].client_id,
            )
        )
        .distinct()
        .order_by("pk")
    )
    result = _result(
        business=business, actor=actor, parcels=parcels, charges=charges, clearance_only=True
    )
    return FinancialClearance(parcels[0].pk, result.complete, result.cleared, result.issues)


def coverage_for_parcel(*, business, actor, parcel):
    return coverage_for_parcels(
        business=business, actor=actor, parcel_ids=[getattr(parcel, "pk", parcel)]
    )


def coverage_for_shipment(*, business, actor, shipment):
    selected = Shipment.objects.filter(
        business=business, pk=getattr(shipment, "pk", shipment)
    ).first()
    if selected is None:
        raise PermissionDenied("Shipment is unavailable in this workspace.")
    require_financial_target(business=business, actor=actor, target=selected)
    from .billing_services import shipment_billing_client

    shipment_billing_client(selected)  # Mixed-client and corrupt cargo fail closed.
    parcels = _parcels(
        business=business, actor=actor, parcel_ids=selected.parcels.values_list("pk", flat=True)
    )
    ids = [item.pk for item in parcels]
    charges = (
        LogisticsCharge.objects.filter(business=business)
        .filter(Q(shipment=selected) | Q(parcel_id__in=ids) | Q(parcel_coverage__parcel_id__in=ids))
        .distinct()
        .order_by("pk")
    )
    return _result(business=business, actor=actor, parcels=parcels, charges=charges)


@transaction.atomic
def record_legacy_charge_coverage(*, business, actor, charge, parcel_ids, reason_reference):
    current = Business.objects.select_for_update().get(pk=business.pk)
    lock_actor_membership(current, actor)
    require_financial_access(business=current, actor=actor, write=True, accounting=True)
    selected = LogisticsCharge.objects.select_for_update().get(
        business=current, pk=getattr(charge, "pk", charge)
    )
    if not reason_reference.strip():
        raise ValidationError("Documentary evidence/reason reference is required.")
    ids = set(parcel_ids)
    parcels = list(
        Parcel.objects.filter(business=current, client_id=selected.client_id, pk__in=ids).order_by(
            "pk"
        )
    )
    if not ids or len(parcels) != len(ids) or (selected.parcel_id and ids != {selected.parcel_id}):
        raise ValidationError(
            "Coverage must contain the charge's same-tenant, same-client Parcels."
        )
    if selected.coverage_recorded_at:
        if ids != set(selected.parcel_coverage.values_list("parcel_id", flat=True)):
            raise ValidationError("Recorded coverage is immutable.")
        return selected
    if selected.parcel_coverage.exists():
        raise ValidationError("Partial historical coverage requires manual integrity review.")
    for item in parcels:
        LogisticsChargeParcel(charge=selected, parcel=item)._domain_save(force_insert=True)
    selected.coverage_recorded_at = timezone.now()
    selected._domain_save(update_fields=["coverage_recorded_at"])
    log_activity(
        actor=actor,
        business=current,
        client=selected.client,
        action_type=ActivityLog.ActionType.STATUS_CHANGED,
        summary="Historical Logistics charge coverage recorded",
        payload={
            "charge_id": selected.pk,
            "parcel_ids": sorted(ids),
            "reason_reference": reason_reference.strip(),
        },
    )
    return selected


def validate_invoice_charge_bindings(invoice):
    """Validate every existing line before append, recalculation or issuance."""
    for line in invoice.lines.select_related("charge_source", "parcel", "shipment"):
        for target in (line.parcel, line.shipment):
            if target is not None:
                if target.business_id != invoice.business_id:
                    raise ValidationError("Invoice references a cross-tenant financial target.")
                validate_location_integrity(target)
        if (
            not line.charge_source_id
            and LogisticsCharge.objects.filter(invoice_line_id=line.pk).exists()
        ):
            raise ValidationError("Original charge source links require integrity review.")
        if line.charge_source_id:
            charge = line.charge_source
            if charge.voided_at:
                raise ValidationError("An active Invoice cannot contain a voided charge.")
            validate_charge_coverage(charge)
            if charge.invoice_lines.exclude(invoice__status=Invoice.Status.CANCELLED).count() != 1:
                raise ValidationError("A charge must have exactly one active Invoice binding.")
