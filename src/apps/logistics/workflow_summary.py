"""Request-scoped, read-only Parcel journeys from the existing domain records.

Capabilities are advisory snapshots, never reusable authorization tokens. Consumers
must resolve again under the existing Business/member locks before a mutation.
"""

import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Prefetch, Q, TextField, prefetch_related_objects
from django.db.models.functions import Cast
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.billings.models import Invoice, InvoiceLine, InvoicePayment
from apps.billings.payment_services import _invoice_settlement
from apps.businesses.models import BusinessUser
from apps.businesses.utils import can_use_module
from apps.crm.models import ActivityLog

from .financial_access import require_financial_access, scope_invoices
from .financial_coverage import (
    validate_charge_coverage,
    validate_invoice_money,
    validate_location_integrity,
)
from .location_access import membership_for, scope_records
from .location_operations import (
    current_site,
    next_site,
    operation_location,
    operations_enabled,
    validate_transition_location,
)
from .models import (
    LogisticsCharge,
    LogisticsChargeParcel,
    LogisticsCreditApproval,
    LogisticsLocation,
    Parcel,
    ParcelEvent,
    Shipment,
)
from .parcel_policy import ALLOWED_TRANSITIONS
from .parcel_services import parcels_for_business, require_parcel_access
from .shipment_services import shipments_for_business

MAX_BATCH_SIZE = 100
ZERO = Decimal("0.00")


class FinancialState(StrEnum):
    PAID = "PAID"
    PARTIAL = "PARTIAL"
    UNPAID = "UNPAID"
    UNINVOICED = "UNINVOICED"
    CREDIT_APPROVED = "CREDIT_APPROVED"  # Reserved for an authoritative Block 06 approval.
    REFUND_DUE = "REFUND_DUE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ParcelWorkflowSummary:
    parcel_id: int
    tracking_code: str
    internal_reference: str
    operational: dict
    shipment: dict | None
    financial: dict
    completed_steps: tuple[dict, ...]
    outstanding_tasks: tuple[dict, ...]
    candidate_actions: tuple[dict, ...]
    executable_actions: tuple[dict, ...]
    history: tuple[dict, ...]
    issues: tuple[str, ...]
    as_of: datetime

    def to_dict(self):
        """Native Decimal/datetime contract; serialize explicitly at an API boundary."""
        return asdict(self)


@dataclass(frozen=True)
class ParcelWorkflowBatch:
    summaries: tuple[ParcelWorkflowSummary, ...]
    financial_totals: dict
    as_of: datetime
    contract_version: int = 1

    @property
    def by_parcel_id(self):
        return {summary.parcel_id: summary for summary in self.summaries}


@dataclass(frozen=True)
class _ReadPolicy:
    work_location: object
    wide_access: bool
    operations_enabled: bool


@contextmanager
def _read_snapshot():
    outer = connection.in_atomic_block
    with transaction.atomic():
        if connection.vendor == "postgresql" and not outer:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield


def _actor(user):
    return {"id": user.pk, "label": str(user)} if user else {"id": None, "label": "Unknown actor"}


def _location(site, business_id):
    if site is None or site.business_id != business_id:
        return None
    return {"id": site.pk, "code": site.code, "name": site.name}


def _add(totals, currency, amount):
    totals[currency] = totals.get(currency, ZERO) + amount


def _totals(charges, invoices):
    result = {
        key: {} for key in ("charges", "billed", "unbilled", "verified_net_paid", "outstanding")
    }
    for charge in charges:
        if charge["voided"]:
            continue
        _add(result["charges"], charge["currency"], charge["amount"])
        _add(
            result["billed"] if charge["billed"] else result["unbilled"],
            charge["currency"],
            charge["amount"],
        )
    for invoice in invoices:
        if (
            invoice["lifecycle_status"] == Invoice.Status.CANCELLED
            or not invoice["evidence_verified"]
        ):
            continue
        _add(result["verified_net_paid"], invoice["currency"], invoice["net_paid"])
        _add(result["outstanding"], invoice["currency"], invoice["outstanding"])
    return result


class _Graph:
    def __init__(self, business, actor, ids, include_history):
        self.business, self.actor, self.include_history = business, actor, include_history
        queryset = parcels_for_business(business=business, actor=actor)
        self.parcels = list(
            queryset.filter(pk__in=ids)
            .select_related(
                "client",
                "created_by",
                "origin_location",
                "destination_location",
                "shipment__origin_location",
                "shipment__destination_location",
            )
            .prefetch_related(
                Prefetch(
                    "events",
                    queryset=ParcelEvent.objects.filter(business=business)
                    .select_related("actor", "operational_location")
                    .order_by("timestamp", "pk"),
                )
            )
        )
        if len(self.parcels) != len(ids):
            raise PermissionDenied("Workflow summaries require accessible workspace Parcels.")
        self.member = membership_for(business, actor)
        self.credit_approvals, self.credit_references = {}, {}
        self.private_finance = False
        try:
            require_financial_access(business=business, actor=actor)
            self.finance_available = True
            self.private_finance = self.member.role != BusinessUser.Role.STAFF
        except PermissionDenied:
            self.finance_available = False
        if self.finance_available:
            for approval in (
                LogisticsCreditApproval.objects.filter(business=business, parcel_id__in=ids)
                .select_related("approved_by", "location", "revocation__revoked_by")
                .order_by("-approved_at", "-pk")
            ):
                self.credit_approvals.setdefault(approval.parcel_id, []).append(approval)
        self.finance_write = False
        if self.private_finance:
            try:
                require_financial_access(
                    business=business, actor=actor, write=True, accounting=True
                )
                self.finance_write = True
            except PermissionDenied:
                pass
        self.finance_parcel_write = self.finance_write and can_use_module(business, "parcels")
        self.shipment_write = self.finance_write and can_use_module(business, "shipments")
        self.policy = _ReadPolicy(
            None, self.member.role in ("owner", "admin"), operations_enabled(business)
        )
        self.operable = set()
        try:
            require_parcel_access(business=business, actor=actor, write=True)
            site = operation_location(business, actor)
            self.policy = _ReadPolicy(site, self.policy.wide_access, self.policy.operations_enabled)
            self.operable = set(
                ids
                if self.policy.wide_access
                else scope_records(
                    Parcel.objects.filter(business=business, pk__in=ids),
                    business=business,
                    actor=actor,
                    location_ids=[site.pk],
                ).values_list("pk", flat=True)
            )
        except PermissionDenied:
            pass
        self.staff_finance_write = False
        if self.finance_available and self.member.role == BusinessUser.Role.STAFF:
            try:
                require_financial_access(business=business, actor=actor, write=True)
                self.staff_finance_write = True
            except PermissionDenied:
                pass
        self.charges, self.invoices, self.balances = [], {}, {}
        self.evidence_charges = {}
        self.unlinked = []
        if self.finance_available and ids:
            client_ids = {parcel.client_id for parcel in self.parcels}
            self.charges = list(
                LogisticsCharge.objects.filter(business=business)
                .filter(
                    Q(parcel_id__in=ids)
                    | Q(parcel_coverage__parcel_id__in=ids)
                    | Q(
                        shipment__isnull=False,
                        coverage_recorded_at__isnull=True,
                        client_id__in=client_ids,
                    )
                )
                .distinct()
                .select_related(
                    "client",
                    "service",
                    "created_by",
                    "parcel__client",
                    "parcel__origin_location",
                    "parcel__destination_location",
                    "parcel__shipment__origin_location",
                    "parcel__shipment__destination_location",
                    "shipment__origin_location",
                    "shipment__destination_location",
                )
                .prefetch_related(
                    Prefetch(
                        "parcel_coverage",
                        queryset=LogisticsChargeParcel.objects.select_related(
                            "parcel__client",
                            "parcel__origin_location",
                            "parcel__destination_location",
                            "parcel__shipment__origin_location",
                            "parcel__shipment__destination_location",
                        ),
                    ),
                    Prefetch("invoice_lines", queryset=InvoiceLine.objects.order_by("pk")),
                )
            )
            self.unlinked = list(
                InvoiceLine.objects.filter(invoice__business=business, charge_source__isnull=True)
                .filter(
                    Q(parcel_id__in=ids)
                    | Q(shipment__isnull=False, invoice__client_id__in=client_ids)
                )
                .values(
                    "parcel_id",
                    "shipment_id",
                    "invoice__client_id",
                    "invoice_id",
                    "invoice__status",
                )
            )
            invoice_ids = {
                line.invoice_id for charge in self.charges for line in charge.invoice_lines.all()
            }
            invoice_ids.update(
                row["invoice_id"] for row in self.unlinked if row["parcel_id"] in ids
            )
            self.invoices = {
                invoice.pk: invoice
                for invoice in Invoice.objects.filter(
                    business=business, client__business=business, pk__in=invoice_ids
                )
                .select_related("business", "client")
                .prefetch_related(
                    Prefetch(
                        "lines",
                        queryset=InvoiceLine.objects.select_related(
                            "service",
                            "parcel__client",
                            "shipment",
                            "charge_source__client",
                            "charge_source__service",
                            "charge_source__parcel__client",
                            "charge_source__parcel__origin_location",
                            "charge_source__parcel__destination_location",
                            "charge_source__parcel__shipment__origin_location",
                            "charge_source__parcel__shipment__destination_location",
                            "charge_source__shipment__origin_location",
                            "charge_source__shipment__destination_location",
                        ),
                    ),
                    Prefetch(
                        "payments",
                        queryset=InvoicePayment.objects.select_related("recorded_by").order_by(
                            "pk"
                        ),
                    ),
                )
            }
            self.readable_invoices = (
                set(
                    scope_invoices(
                        Invoice.objects.filter(pk__in=invoice_ids), business=business, actor=actor
                    ).values_list("pk", flat=True)
                )
                if self.private_finance
                else set()
            )
            self.evidence_charges = {charge.pk: charge for charge in self.charges}
            extra_sources = []
            for invoice in self.invoices.values():
                for line in invoice.lines.all():
                    if line.charge_source_id:
                        if line.charge_source_id not in self.evidence_charges:
                            self.evidence_charges[line.charge_source_id] = line.charge_source
                            extra_sources.append(line.charge_source)
                        line._state.fields_cache["charge_source"] = self.evidence_charges[
                            line.charge_source_id
                        ]
            prefetch_related_objects(
                extra_sources,
                Prefetch(
                    "parcel_coverage",
                    queryset=LogisticsChargeParcel.objects.select_related(
                        "parcel__client",
                        "parcel__origin_location",
                        "parcel__destination_location",
                        "parcel__shipment__origin_location",
                        "parcel__shipment__destination_location",
                    ),
                ),
                Prefetch(
                    "invoice_lines",
                    queryset=InvoiceLine.objects.select_related("invoice__business").order_by("pk"),
                ),
            )
            for charge in self.evidence_charges.values():
                for line in charge.invoice_lines.all():
                    if line.invoice_id in self.invoices:
                        line._state.fields_cache["invoice"] = self.invoices[line.invoice_id]
        self._load_locations_and_shipments(ids)
        self.charge_members, self.charge_issues = {}, {}
        root_charge_ids = {charge.pk for charge in self.charges}
        for charge in self.evidence_charges.values():
            try:
                if charge.pk in root_charge_ids and any(
                    line.invoice_id not in self.invoices for line in charge.invoice_lines.all()
                ):
                    raise ValidationError("Unowned Invoice relationship.")
                members = validate_charge_coverage(charge)
                self.charge_members[charge.pk] = {parcel.pk for parcel in members}
            except ValidationError:
                self.charge_issues[charge.pk] = (
                    "Unproven or inconsistent financial coverage requires accounting review."
                )
        for invoice in self.invoices.values():
            balance = _invoice_settlement(invoice)
            self.balances[invoice.pk] = balance
            issues = list(balance.issues)
            try:
                validate_invoice_money(invoice)
                for line in invoice.lines.all():
                    if (
                        (
                            line.parcel_id
                            and (
                                line.parcel.business_id != business.pk
                                or line.parcel.client_id != invoice.client_id
                            )
                        )
                        or (line.shipment_id and line.shipment.business_id != business.pk)
                        or (line.service_id and line.service.business_id != business.pk)
                    ):
                        raise ValidationError("Invalid Invoice references.")
                    source = line.charge_source
                    if source is None and (line.parcel_id or line.shipment_id):
                        raise ValidationError(
                            "Unlinked Logistics Invoice evidence requires review."
                        )
                    if source and (
                        source.pk in self.charge_issues
                        or (source.voided_at and invoice.status != "CANCELLED")
                        or (
                            invoice.status != "CANCELLED"
                            and sum(
                                line.invoice.status != "CANCELLED"
                                for line in source.invoice_lines.all()
                            )
                            != 1
                        )
                    ):
                        raise ValidationError("Invoice charge coverage requires accounting review.")
                    if source and (
                        (
                            source.business_id,
                            source.client_id,
                            source.parcel_id,
                            source.shipment_id,
                            source.service_id,
                            source.invoice_description,
                            source.quantity,
                            source.unit_price,
                            source.total,
                            source.currency_snapshot,
                        )
                        != (
                            business.pk,
                            invoice.client_id,
                            line.parcel_id,
                            line.shipment_id,
                            line.service_id,
                            line.description,
                            line.quantity,
                            line.unit_price,
                            line.line_total,
                            invoice.currency_code,
                        )
                        or source.currency_is_legacy
                        or not source.coverage_recorded_at
                        or not source.logical_key
                    ):
                        raise ValidationError("Invalid or unconfirmed Invoice charge snapshots.")
            except ValidationError:
                issues.append("Invoice evidence requires accounting review.")
            if invoice.snapshot_is_legacy or balance.legacy_paid_unverified:
                issues.append("Legacy Invoice status/currency/tax is unverified.")
            self.invoice_issues[invoice.pk] = tuple(dict.fromkeys(issues))
        self.logs = []
        if include_history and self.private_finance and (self.invoices or self.charges):
            self.logs = list(
                ActivityLog.objects.filter(business=business)
                .filter(
                    Q(payload__invoice_id__in=list(self.invoices))
                    | Q(
                        action_type="INVOICE_CREATED",
                        payload__invoice_number__in=[
                            item.invoice_number for item in self.invoices.values()
                        ],
                    )
                    | Q(payload__charge_id__in=[item.pk for item in self.charges])
                )
                .select_related("actor")
                .order_by("created_at", "pk")
            )

    def _load_locations_and_shipments(self, ids):
        parcels = list(self.parcels)
        for charge in self.evidence_charges.values():
            parcels.extend(entry.parcel for entry in charge.parcel_coverage.all())
            if charge.parcel_id:
                parcels.append(charge.parcel)
        prefetch_related_objects(
            parcels, "handling_sites__location", "shipment__handling_sites__location"
        )
        ship_ids = {parcel.shipment_id for parcel in parcels if parcel.shipment_id}
        ship_ids.update(
            charge.shipment_id for charge in self.evidence_charges.values() if charge.shipment_id
        )
        query = Shipment.objects.filter(business=self.business)
        if self.include_history and ids:
            pattern = (
                r'"parcel_id"\s*:\s*"?('
                + "|".join(re.escape(str(pk)) for pk in ids)
                + r')("|\s*[,}])'
            )
            query = query.annotate(history_text=Cast("operation_history", TextField())).filter(
                Q(pk__in=ship_ids) | Q(history_text__regex=pattern)
            )
        else:
            query = query.filter(pk__in=ship_ids)
        self.shipments = {
            ship.pk: ship
            for ship in query.select_related(
                "origin_location", "destination_location"
            ).prefetch_related("handling_sites__location")
        }
        history_site_ids = {
            entry["location_id"]
            for ship in self.shipments.values()
            if isinstance(ship.operation_history, list)
            for entry in ship.operation_history
            if isinstance(entry, dict) and isinstance(entry.get("location_id"), int)
        }
        self.history_sites = (
            {
                site.pk: site
                for site in LogisticsLocation.objects.filter(
                    business=self.business, pk__in=history_site_ids
                )
            }
            if history_site_ids
            else {}
        )
        try:
            self.visible_shipments = set(
                shipments_for_business(business=self.business, actor=self.actor)
                .filter(pk__in=self.shipments)
                .values_list("pk", flat=True)
            )
        except PermissionDenied:
            self.visible_shipments = set()
        for parcel in parcels:
            if parcel.shipment_id in self.shipments:
                parcel._state.fields_cache["shipment"] = self.shipments[parcel.shipment_id]
        for charge in self.evidence_charges.values():
            if charge.shipment_id in self.shipments:
                charge._state.fields_cache["shipment"] = self.shipments[charge.shipment_id]
        self.invoice_issues = {}

    def invoice_projection(self, invoice):
        balance = self.balances[invoice.pk]
        return {
            "id": invoice.pk,
            "number": invoice.invoice_number,
            "lifecycle_status": invoice.status,
            "currency": balance.currency,
            "total": balance.total,
            "net_paid": balance.net_paid,
            "outstanding": balance.outstanding,
            "adjusted_total": balance.adjusted_total,
            "credits": balance.credits,
            "refund_due": balance.refund_due,
            "settled": balance.settled and not self.invoice_issues[invoice.pk],
            "evidence_verified": not self.invoice_issues[invoice.pk],
            "shared": any(item.shipment_id for item in invoice.lines.all())
            or len({item.parcel_id for item in invoice.lines.all() if item.parcel_id}) > 1,
            "allocation": "FULL_INVOICE_BALANCE_NO_PARCEL_ALLOCATION",
        }

    def financial(self, parcel, require_credit_evidence):
        visibility = (
            "DETAILED"
            if self.private_finance
            else "CLEARANCE_ONLY" if self.finance_available else "UNAVAILABLE"
        )
        issues, rows, invoices = [], [], {}
        selected = []
        for charge in self.charges:
            members = self.charge_members.get(charge.pk, set())
            if (
                parcel.pk in members
                or charge.parcel_id == parcel.pk
                or (
                    charge.coverage_recorded_at is None
                    and charge.shipment_id
                    and charge.client_id == parcel.client_id
                )
            ):
                selected.append(charge)
        if not self.finance_available:
            issues.append("Financial clearance is unavailable with your current access.")
        elif any(
            item["invoice__status"] != "CANCELLED"
            and (
                item["parcel_id"] == parcel.pk
                or (item["shipment_id"] and item["invoice__client_id"] == parcel.client_id)
            )
            for item in self.unlinked
        ):
            issues.append("Unlinked financial history requires accounting review.")
        related_invoice_ids = {
            row["invoice_id"] for row in self.unlinked if row["parcel_id"] == parcel.pk
        }
        related_invoice_ids.update(
            line.invoice_id
            for charge in selected
            if charge.parcel_id == parcel.pk
            or parcel.pk in self.charge_members.get(charge.pk, set())
            for line in charge.invoice_lines.all()
        )
        invoices = (
            {
                pk: self.invoice_projection(self.invoices[pk])
                for pk in related_invoice_ids
                if pk in self.readable_invoices and self.invoices[pk].client_id == parcel.client_id
            }
            if self.private_finance
            else {}
        )
        for charge in selected:
            if charge.pk in self.charge_issues:
                if not charge.voided_at:
                    issues.append(self.charge_issues[charge.pk])
                continue
            lines = list(charge.invoice_lines.all())
            active = [line for line in lines if line.invoice.status != "CANCELLED"]
            if len(active) > 1 or (charge.voided_at and active):
                issues.append("Ambiguous active Invoice bindings require accounting review.")
            if not charge.voided_at and (
                charge.currency_is_legacy or not charge.currency_snapshot or not charge.logical_key
            ):
                issues.append("Legacy financial snapshots require accounting confirmation.")
            state = FinancialState.UNINVOICED
            if len(active) == 1:
                invoice, balance = active[0].invoice, self.balances[active[0].invoice_id]
                if self.invoice_issues[invoice.pk]:
                    issues.extend(self.invoice_issues[invoice.pk])
                    state = FinancialState.UNKNOWN
                else:
                    from apps.billings.cancellation_services import parcel_invoice_settled

                    own_settled = parcel_invoice_settled(invoice, parcel.pk)
                    effective_settled = balance.settled if own_settled is None else own_settled
                    state = (
                        FinancialState.PAID
                        if effective_settled
                        else (
                            FinancialState.PARTIAL
                            if balance.net_paid > 0
                            else FinancialState.UNPAID
                        )
                    )
            own_invoice_ids = tuple(
                dict.fromkeys(
                    line.invoice_id for line in lines if line.invoice_id in self.readable_invoices
                )
            )
            rows.append(
                {
                    "id": charge.pk,
                    "description": charge.description,
                    "target_kind": "SHIPMENT" if charge.shipment_id else "PARCEL",
                    "amount": charge.total,
                    "currency": charge.currency_snapshot or "UNKNOWN",
                    "shared": len(self.charge_members[charge.pk]) > 1,
                    "covered_requested_parcel_ids": tuple(
                        sorted(self.charge_members[charge.pk] & {item.pk for item in self.parcels})
                    ),
                    "billed": len(active) == 1,
                    "state": state.value,
                    "voided": bool(charge.voided_at),
                    "invoice_ids": own_invoice_ids,
                }
            )
            for line in lines:
                invoice = line.invoice
                if invoice.pk in self.readable_invoices:
                    invoices[invoice.pk] = self.invoice_projection(invoice)
        active_rows = [row for row in rows if not row["voided"]]
        if not active_rows:
            issues.append("No proven active financial obligations; clearance cannot be inferred.")
        states = {row["state"] for row in active_rows}
        state = (
            FinancialState.UNKNOWN
            if issues
            else (
                FinancialState.UNINVOICED
                if "UNINVOICED" in states
                else (
                    FinancialState.PAID
                    if states == {"PAID"}
                    else (
                        FinancialState.PARTIAL
                        if "PARTIAL" in states or "PAID" in states
                        else FinancialState.UNPAID
                    )
                )
            )
        )
        complete = not issues
        from .credit_services import CREDIT_MOVEMENTS, obligation_snapshot, valid_approvals

        approved = (
            valid_approvals(self, parcel, obligation_snapshot(self, parcel), at=timezone.now())
            if complete
            else {}
        )
        relevant_movement = (
            "IN_TRANSIT"
            if parcel.current_status in ("REGISTERED", "RECEIVED", "HOLD")
            else "DELIVERED"
        )
        if require_credit_evidence and relevant_movement not in approved:
            issues.append("Required authoritative credit approval evidence is unavailable.")
            complete, state = False, FinancialState.UNKNOWN
        settled = complete and state == FinancialState.PAID
        movements = {
            status: complete and (settled or status in approved) for status in CREDIT_MOVEMENTS
        }
        self.credit_references[parcel.pk] = (
            {status: approval.pk for status, approval in approved.items()} if not settled else {}
        )
        cleared = movements[relevant_movement]
        settlement_state = state
        if cleared and not settled:
            state = FinancialState.CREDIT_APPROVED
        detailed = visibility == "DETAILED"
        safe_issues = (
            tuple(dict.fromkeys(issues))
            if detailed
            else (("Accounting clearance requires review.",) if issues else ())
        )
        return {
            "visibility": visibility,
            "state": state.value if detailed else None,
            "state_label": (
                {
                    "PAID": "Paid",
                    "PARTIAL": "Partially paid",
                    "UNPAID": "Unpaid",
                    "UNINVOICED": "Not invoiced",
                    "UNKNOWN": "Unknown — review required",
                    "CREDIT_APPROVED": "Approved credit",
                    "REFUND_DUE": "Refund due",
                }[state.value]
                if detailed
                else None
            ),
            "clearance": {
                "complete": complete,
                "cleared": cleared,
                "issues": safe_issues,
                "movements": movements,
                "via_credit": cleared and not settled,
            },
            "settlement_state": settlement_state.value if detailed else None,
            "credit": (
                tuple(
                    {
                        "id": approval.pk,
                        "status": approval.status,
                        "approved_by": _actor(approval.approved_by),
                        "reason_reference": approval.reason_reference,
                        "expires_at": approval.expires_at,
                    }
                    for approval in approved.values()
                )
                if detailed
                else ()
            ),
            "charges": tuple(rows) if detailed else (),
            "invoices": tuple(invoices.values()) if detailed else (),
            "totals_by_currency": _totals(rows, invoices.values()) if detailed else {},
            "balance_scope": "RELATED_INVOICE_FULL_BALANCES" if detailed else None,
            "shared_allocation": "UNALLOCATED" if detailed else None,
        }


def _history(graph, parcel, financial):
    result, issues = [], []

    def add(timestamp, kind, source, source_id, label, actor=None, location=None, revision=0):
        result.append(
            {
                "timestamp": timestamp,
                "kind": kind,
                "source": source,
                "source_id": source_id,
                "revision": revision,
                "label": label,
                "actor": actor or {"id": None, "label": "Unknown actor"},
                "location": location,
            }
        )

    add(
        parcel.created_at,
        "PARCEL_CREATED",
        "logistics.Parcel",
        parcel.pk,
        "Parcel record created",
        _actor(parcel.created_by),
    )
    for event in parcel.events.all():
        site = _location(event.operational_location, graph.business.pk)
        if event.operational_location_id and site is None:
            issues.append("Historical location attribution requires review.")
        add(
            event.timestamp,
            "PARCEL_EVENT",
            "logistics.ParcelEvent",
            event.pk,
            event.get_status_display() if event.status else "Parcel details/tracking update",
            _actor(event.actor),
            site,
        )
    for ship in graph.shipments.values():
        if ship.pk not in graph.visible_shipments:
            continue
        if not isinstance(ship.operation_history, list):
            if ship.pk == parcel.shipment_id:
                issues.append("Shipment history requires review.")
            continue
        relevant = ship.pk == parcel.shipment_id or any(
            isinstance(entry, dict) and str(entry.get("parcel_id")) == str(parcel.pk)
            for entry in ship.operation_history
        )
        if not relevant:
            continue
        assigned = False
        for entry in ship.operation_history:
            if not isinstance(entry, dict) or entry.get("business_id") != graph.business.pk:
                issues.append("Shipment history requires ownership review.")
                continue
            applies = str(entry.get("parcel_id")) == str(parcel.pk)
            if applies and entry.get("action") == "assign":
                assigned = True
            if applies or (assigned and entry.get("action") == "status"):
                try:
                    stamp = parse_datetime(entry.get("timestamp", ""))
                    if stamp is None or timezone.is_naive(stamp):
                        raise ValueError
                except (ValueError, TypeError):
                    issues.append("Shipment history has missing/ambiguous timestamps.")
                else:
                    site_id = entry.get("location_id")
                    site = (
                        _location(graph.history_sites.get(site_id), graph.business.pk)
                        if isinstance(site_id, int)
                        else None
                    )
                    if site_id and site is None:
                        issues.append("Historical Shipment location attribution requires review.")
                    elif site:
                        site = {**site, "code": entry.get("location_code") or site["code"]}
                    add(
                        stamp,
                        "SHIPMENT_EVENT",
                        "logistics.Shipment",
                        ship.pk,
                        f"Shipment {entry.get('action')} · {entry.get('new_state')}",
                        {
                            "id": entry.get("actor_id"),
                            "label": entry.get("actor_name") or "Unknown actor",
                        },
                        site,
                        entry.get("revision", 0),
                    )
            if applies and entry.get("action") == "remove":
                assigned = False
    if financial["visibility"] == "DETAILED":
        charge_ids = {row["id"] for row in financial["charges"]}
        invoice_ids = {row["id"] for row in financial["invoices"]}
        for charge in graph.charges:
            if charge.pk not in charge_ids:
                continue
            add(
                charge.created_at,
                "CHARGE_CREATED",
                "logistics.LogisticsCharge",
                charge.pk,
                "Charge recorded",
                _actor(charge.created_by),
            )
            if charge.voided_at:
                audit = next(
                    (
                        log
                        for log in graph.logs
                        if isinstance(log.payload, dict)
                        and log.payload.get("charge_id") == charge.pk
                        and log.summary == "Logistics charge voided"
                    ),
                    None,
                )
                add(
                    charge.voided_at,
                    "CHARGE_VOIDED",
                    "logistics.LogisticsCharge",
                    charge.pk,
                    "Charge voided; history retained",
                    _actor(audit.actor) if audit else None,
                )
            for line in charge.invoice_lines.all():
                if line.invoice_id in invoice_ids:
                    add(
                        line.created_at,
                        "INVOICE_BINDING",
                        "billings.InvoiceLine",
                        line.pk,
                        "Charge linked to Invoice",
                    )
        for invoice_id in invoice_ids:
            invoice = graph.invoices[invoice_id]
            creator = next(
                (
                    log
                    for log in graph.logs
                    if log.action_type == "INVOICE_CREATED"
                    and isinstance(log.payload, dict)
                    and log.payload.get("invoice_number") == invoice.invoice_number
                ),
                None,
            )
            add(
                invoice.created_at,
                "INVOICE_CREATED",
                "billings.Invoice",
                invoice.pk,
                f"Invoice {invoice.invoice_number} created",
                _actor(creator.actor) if creator else None,
            )
            for payment in invoice.payments.all():
                if payment.business_id == graph.business.pk:
                    add(
                        payment.recorded_at,
                        f"PAYMENT_{payment.kind}",
                        "billings.InvoicePayment",
                        payment.pk,
                        f"{payment.get_kind_display()} · {payment.currency} {payment.amount}",
                        _actor(payment.recorded_by),
                    )
        for log in graph.logs:
            payload = log.payload if isinstance(log.payload, dict) else {}
            if (
                payload.get("invoice_id") in invoice_ids
                or payload.get("charge_id") in charge_ids
                or (
                    log.action_type == "INVOICE_CREATED"
                    and any(
                        graph.invoices[pk].invoice_number == payload.get("invoice_number")
                        for pk in invoice_ids
                    )
                )
            ):
                add(
                    log.created_at,
                    "ACCOUNTING_EVENT",
                    "crm.ActivityLog",
                    log.pk,
                    log.summary,
                    _actor(log.actor),
                )
    priority = {
        source: index
        for index, source in enumerate(
            (
                "logistics.Parcel",
                "logistics.ParcelEvent",
                "logistics.Shipment",
                "logistics.LogisticsCharge",
                "billings.Invoice",
                "billings.InvoiceLine",
                "billings.InvoicePayment",
                "crm.ActivityLog",
                "logistics.LogisticsCreditApproval",
                "logistics.LogisticsCreditRevocation",
            )
        )
    }
    if graph.private_finance:
        for approval in graph.credit_approvals.get(parcel.pk, ()):
            add(
                approval.approved_at,
                "CREDIT_APPROVED",
                "logistics.LogisticsCreditApproval",
                approval.pk,
                "Scoped credit approved",
                _actor(approval.approved_by),
                _location(approval.location, graph.business.pk),
            )
            if hasattr(approval, "revocation"):
                revoked = approval.revocation
                add(
                    revoked.revoked_at,
                    "CREDIT_REVOKED",
                    "logistics.LogisticsCreditRevocation",
                    revoked.pk,
                    "Scoped credit revoked",
                    _actor(revoked.revoked_by),
                )
    return (
        tuple(
            sorted(
                result,
                key=lambda item: (
                    item["timestamp"],
                    priority[item["source"]],
                    item["source_id"],
                    item["revision"],
                ),
            )
        ),
        issues,
    )


def _summary(graph, parcel, as_of, require_credit_evidence):
    events = list(parcel.events.all())
    status_events = [event for event in events if event.event_type == "STATUS" and event.status]
    issues = []
    complete = bool(
        status_events
        and any(event.status == "REGISTERED" for event in status_events)
        and status_events[-1].status == parcel.current_status
    )
    if not complete:
        issues.append("Registration/status evidence is incomplete or inconsistent.")
    site_ids, sites = {}, {}
    try:
        validate_location_integrity(parcel)
        site_ids = {"current": current_site(parcel), "next": next_site(parcel)}
    except (ValidationError, TypeError, KeyError, AttributeError):
        complete = False
        issues.append("Operational route/location evidence requires review.")
    related = [parcel] + ([parcel.shipment] if parcel.shipment_id else [])
    for record in related:
        for site in (record.origin_location, record.destination_location):
            if site and site.business_id == graph.business.pk:
                sites[site.pk] = site
        for edge in record.handling_sites.all():
            if edge.location.business_id == graph.business.pk:
                sites[edge.location_id] = edge.location
    financial = graph.financial(parcel, require_credit_evidence)
    ship = graph.shipments.get(parcel.shipment_id)
    shipment = (
        {
            "id": ship.pk,
            "reference": ship.reference,
            "state": ship.status,
            "transport_mode": ship.transport_mode,
        }
        if ship and ship.pk in graph.visible_shipments
        else None
    )
    # Compact projection still validates the history already in its graph. Only
    # former Shipment discovery and accounting audit loading are omitted.
    history, history_issues = _history(graph, parcel, financial)
    issues.extend(history_issues)
    steps = [
        {
            "code": event.status,
            "label": event.get_status_display(),
            "source": "logistics.ParcelEvent",
            "source_id": event.pk,
            "timestamp": event.timestamp,
        }
        for event in status_events
    ]
    steps = list({step["code"]: step for step in steps}.values())
    assignment = next(
        (
            entry
            for entry in reversed(history)
            if entry["kind"] == "SHIPMENT_EVENT" and entry["label"].startswith("Shipment assign")
        ),
        None,
    )
    if assignment:
        steps.append(
            {
                "code": "SHIPMENT_ASSIGNED",
                "label": "Shipment assigned",
                "source": assignment["source"],
                "source_id": assignment["source_id"],
                "timestamp": assignment["timestamp"],
            }
        )
    if financial["visibility"] == "DETAILED":
        charge_ids = {row["id"] for row in financial["charges"]}
        invoice_ids = {row["id"] for row in financial["invoices"]}
        proven_charges = [charge for charge in graph.charges if charge.pk in charge_ids]
        records = (
            (
                "CHARGES_RECORDED",
                "Charges recorded",
                "logistics.LogisticsCharge",
                proven_charges,
                "created_at",
            ),
            (
                "INVOICED",
                "Charges invoiced",
                "billings.InvoiceLine",
                [
                    line
                    for charge in proven_charges
                    for line in charge.invoice_lines.all()
                    if line.invoice_id in invoice_ids
                ],
                "created_at",
            ),
            (
                "PAYMENT_RECORDED",
                "Customer payment recorded",
                "billings.InvoicePayment",
                [
                    payment
                    for pk in invoice_ids
                    for payment in graph.invoices[pk].payments.all()
                    if payment.kind == "RECEIPT" and payment.business_id == graph.business.pk
                ],
                "recorded_at",
            ),
        )
        for code, label, source, items, time_field in records:
            record = min(items, key=lambda item: (getattr(item, time_field), item.pk), default=None)
            if record:
                steps.append(
                    {
                        "code": code,
                        "label": label,
                        "source": source,
                        "source_id": record.pk,
                        "timestamp": getattr(record, time_field),
                    }
                )
    if financial["clearance"]["cleared"]:
        steps.append(
            {
                "code": "FINANCIALLY_CLEARED",
                "label": (
                    "Credit clearance approved"
                    if financial["clearance"]["via_credit"]
                    else "Financially settled"
                ),
                "source": (
                    "logistics.LogisticsCreditApproval"
                    if financial["clearance"]["via_credit"]
                    else "billings.InvoicePayment/Invoice"
                ),
                "source_id": None,
                "timestamp": None,
            }
        )
    tasks = []
    next_tasks = {
        "REGISTERED": ("RECEIVE_PARCEL", "Receive the Parcel"),
        "RECEIVED": ("DEPARTURE", "Arrange departure"),
        "IN_TRANSIT": ("ARRIVAL", "Record arrival at the approved next site"),
        "ARRIVED": ("PREPARE_DELIVERY", "Prepare the Parcel for delivery"),
        "READY": ("DELIVERY", "Complete delivery after clearance"),
        "HOLD": ("REVIEW_HOLD", "Review the hold and approved resumption stage"),
    }
    if parcel.current_status in next_tasks:
        code, label = next_tasks[parcel.current_status]
        tasks.append({"code": code, "label": label})
    if issues:
        tasks.append(
            {
                "code": "REVIEW_OPERATIONAL_EVIDENCE",
                "label": "Review registration, route and history evidence",
            }
        )
    if not parcel.shipment_id and parcel.current_status in ("REGISTERED", "RECEIVED"):
        tasks.append({"code": "ARRANGE_TRANSPORT", "label": "Arrange Shipment transport if needed"})
    if not financial["clearance"]["cleared"]:
        label = (
            "Obtain accounting clearance"
            if financial["visibility"] != "DETAILED"
            else {
                "UNKNOWN": "Review missing or ambiguous financial evidence",
                "UNINVOICED": "Invoice outstanding charges",
                "PARTIAL": "Collect the remaining Invoice balance",
                "UNPAID": "Issue the draft Invoice or record customer payment",
            }.get(financial["state"], "Obtain accounting clearance")
        )
        tasks.append({"code": "FINANCIAL_CLEARANCE", "label": label})
    candidates, executable = [], []
    for status, label in Parcel.Status.choices:
        if status not in ALLOWED_TRANSITIONS.get(parcel.current_status, ()):
            continue
        action = {
            "code": f"MARK_{status}",
            "label": f"Mark {label}",
            "kind": "OPERATIONAL",
            "status": status,
            "requires_financial_clearance": status in ("IN_TRANSIT", "DELIVERED"),
        }
        candidates.append(action)
        allowed = parcel.pk in graph.operable and complete and not history_issues
        if (
            action["requires_financial_clearance"]
            and not financial["clearance"]["movements"][status]
        ):
            allowed = False
        if allowed:
            try:
                validate_transition_location(
                    parcel,
                    business=graph.business,
                    actor=graph.actor,
                    status=status,
                    _read_context=graph.policy,
                )
            except (PermissionDenied, ValidationError):
                continue
            executable.append(action)
    if financial["visibility"] in ("DETAILED", "CLEARANCE_ONLY"):
        parcel_finance_write = graph.finance_parcel_write or (
            graph.staff_finance_write and parcel.pk in graph.operable
        )
        action = {
            "code": "ADD_CHARGE",
            "label": "Add charge",
            "kind": "FINANCIAL",
            "url": reverse("logistics_parcel_charge", args=[parcel.pk]),
        }
        candidates.append(action)
        if parcel_finance_write and complete:
            executable.append(action)
        if any(
            charge.parcel_id == parcel.pk
            and not charge.voided_at
            and parcel.pk in graph.charge_members.get(charge.pk, set())
            and not any(line.invoice.status != "CANCELLED" for line in charge.invoice_lines.all())
            for charge in graph.charges
        ):
            action = {
                "code": "GENERATE_INVOICE",
                "label": "Create invoice / Add to existing invoice",
                "kind": "FINANCIAL",
                "url": reverse("logistics_parcel_invoice", args=[parcel.pk]),
            }
            candidates.append(action)
            if parcel_finance_write and financial["clearance"]["complete"]:
                executable.append(action)
    if financial["visibility"] == "DETAILED":
        unbilled_shipments = {
            charge.shipment_id
            for charge in graph.charges
            if charge.shipment_id in graph.visible_shipments
            and any(
                row["id"] == charge.pk and not row["voided"] and not row["billed"]
                for row in financial["charges"]
            )
        }
        for shipment_id in sorted(unbilled_shipments):
            action = {
                "code": f"GENERATE_SHIPMENT_INVOICE_{shipment_id}",
                "label": "Invoice Shipment charges",
                "kind": "FINANCIAL",
                "url": reverse("logistics_shipment_invoice", args=[shipment_id]),
            }
            candidates.append(action)
            if graph.finance_write and graph.shipment_write and financial["clearance"]["complete"]:
                executable.append(action)
        for invoice in financial["invoices"]:
            if invoice["lifecycle_status"] == "DRAFT":
                action = {
                    "code": f"ISSUE_INVOICE_{invoice['id']}",
                    "label": "Review and issue Invoice",
                    "kind": "FINANCIAL",
                    "url": reverse("invoice_detail", args=[invoice["id"]]),
                }
                candidates.append(action)
                if graph.finance_write and financial["clearance"]["complete"]:
                    executable.append(action)
            if invoice["lifecycle_status"] in ("SENT", "PAID") and invoice["outstanding"] > 0:
                action = {
                    "code": f"RECORD_PAYMENT_{invoice['id']}",
                    "label": "Record verified customer payment",
                    "kind": "FINANCIAL",
                    "url": reverse("invoice_payment_record", args=[invoice["id"]]),
                }
                candidates.append(action)
                if graph.finance_write and financial["clearance"]["complete"]:
                    executable.append(action)
    return ParcelWorkflowSummary(
        parcel.pk,
        parcel.tracking_code,
        parcel.internal_reference,
        {
            "state": parcel.current_status,
            "label": parcel.get_current_status_display(),
            "evidence_complete": complete and not history_issues,
            "origin": _location(parcel.origin_location, graph.business.pk),
            "destination": _location(parcel.destination_location, graph.business.pk),
            "current": _location(sites.get(site_ids.get("current")), graph.business.pk),
            "next": _location(sites.get(site_ids.get("next")), graph.business.pk),
            "work_location": _location(graph.policy.work_location, graph.business.pk),
            "shipment_restricted": bool(parcel.shipment_id and not shipment),
        },
        shipment,
        financial,
        tuple(steps),
        tuple(tasks),
        tuple(candidates),
        tuple(executable),
        history if graph.include_history else (),
        tuple(dict.fromkeys(issues)),
        as_of,
    )


def resolve_parcel_workflows(
    *, business, actor, parcel_ids, include_history=True, require_credit_evidence=False
):
    """Resolve at most 100 accessible Parcels with a bounded number of SQL queries."""
    try:
        ids = {int(getattr(value, "pk", value)) for value in parcel_ids}
    except (TypeError, ValueError) as exc:
        raise ValidationError("Supply persisted Parcel IDs.") from exc
    if len(ids) > MAX_BATCH_SIZE or any(value <= 0 for value in ids):
        raise ValidationError("Use positive Parcel IDs in batches of at most 100.")
    with _read_snapshot():
        current = require_parcel_access(business=business, actor=actor)
        stamp = timezone.now()
        graph = _Graph(current, actor, ids, include_history)
        summaries = tuple(
            _summary(graph, parcel, stamp, require_credit_evidence)
            for parcel in sorted(graph.parcels, key=lambda item: item.pk)
        )
        charges, invoices = {}, {}
        for summary in summaries:
            charges.update({charge["id"]: charge for charge in summary.financial["charges"]})
            invoices.update({invoice["id"]: invoice for invoice in summary.financial["invoices"]})
        totals = _totals(charges.values(), invoices.values()) if graph.private_finance else {}
        return ParcelWorkflowBatch(summaries, totals, stamp)


def resolve_parcel_workflow(
    *, business, actor, parcel, include_history=True, require_credit_evidence=False
):
    return resolve_parcel_workflows(
        business=business,
        actor=actor,
        parcel_ids=[parcel],
        include_history=include_history,
        require_credit_evidence=require_credit_evidence,
    ).summaries[0]
