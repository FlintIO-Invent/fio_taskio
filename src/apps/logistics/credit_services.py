"""Scoped credit authority and shared clearance checks; no money/status fabrication."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid5

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.businesses.models import Business
from apps.crm.models import ActivityLog
from apps.crm.services import log_activity

from .financial_access import require_financial_access
from .location_access import lock_actor_membership, membership_for
from .models import LogisticsCreditApproval, LogisticsCreditRevocation, LogisticsLocationAssignment
from .parcel_services import _key

CREDIT_MOVEMENTS = ("IN_TRANSIT", "DELIVERED")


def obligation_snapshot(graph, parcel):
    """Exact charge membership/bindings and full shared Invoice limits, once per ID."""
    charges, invoices = [], {}
    for charge in graph.charges:
        if charge.voided_at or parcel.pk not in graph.charge_members.get(charge.pk, set()):
            continue
        if charge.pk in graph.charge_issues:
            return None
        lines = [line for line in charge.invoice_lines.all() if line.invoice.status != "CANCELLED"]
        if len(lines) != 1:
            return None
        line = lines[0]
        invoice = graph.invoices[line.invoice_id]
        if graph.invoice_issues[invoice.pk] or invoice.status not in ("SENT", "PAID"):
            return None
        charges.append(
            {
                "id": charge.pk,
                "logical_key": charge.logical_key,
                "currency": charge.currency_snapshot,
                "total": str(charge.total),
                "parcel_ids": sorted(graph.charge_members[charge.pk]),
                "line_id": line.pk,
                "invoice_id": invoice.pk,
            }
        )
        balance = graph.balances[invoice.pk]
        invoices[invoice.pk] = {
            "id": invoice.pk,
            "currency": invoice.currency_code,
            "tax_rate": str(invoice.tax_rate_percentage),
            "total": str(invoice.total),
            "subtotal": str(invoice.subtotal),
            "tax": str(invoice.tax),
            "lines": sorted(
                [
                    [
                        item.pk,
                        item.charge_source_id,
                        str(item.quantity),
                        str(item.unit_price),
                        str(item.line_total),
                    ]
                    for item in invoice.lines.all()
                ]
            ),
            "outstanding_limit": str(balance.outstanding),
            **({"cancellation_credits": str(balance.credits)} if balance.credits else {}),
        }
    if not charges:
        return None
    return {
        "version": 1,
        "parcel_id": parcel.pk,
        "client_id": parcel.client_id,
        "charges": sorted(charges, key=lambda row: row["id"]),
        "invoices": [invoices[pk] for pk in sorted(invoices)],
    }


def fingerprint(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def valid_approvals(graph, parcel, snapshot, *, at):
    """Read-only comparison; refunds may never exceed the approved balance caps."""
    valid = {}
    if snapshot is None:
        return valid
    for approval in graph.credit_approvals.get(parcel.pk, ()):
        if (
            approval.business_id != graph.business.pk
            or approval.client_id != parcel.client_id
            or approval.approved_role not in ("owner", "admin")
            or approval.approved_at > at
            or approval.expires_at <= at
            or hasattr(approval, "revocation")
            or approval.status not in CREDIT_MOVEMENTS
        ):
            continue
        saved = approval.obligations_snapshot
        if not isinstance(saved, dict) or fingerprint(saved) != approval.obligation_fingerprint:
            continue
        try:
            limits = {row["id"]: row["outstanding_limit"] for row in saved["invoices"]}
            compared = {**snapshot, "invoices": []}
            for row in snapshot["invoices"]:
                cap = Decimal(limits[row["id"]])
                if not cap.is_finite() or cap < 0 or Decimal(row["outstanding_limit"]) > cap:
                    raise ValueError("Credit limit exceeded")
                compared["invoices"].append({**row, "outstanding_limit": limits[row["id"]]})
            if saved == compared:
                valid.setdefault(approval.status, approval)
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
    return valid


def _authority(business, actor, *, lock=False):
    if lock:
        business = Business.objects.select_for_update().get(pk=business.pk)
        lock_actor_membership(business, actor)
    require_financial_access(business=business, actor=actor, write=True, accounting=True)
    member = membership_for(business, actor)
    if member.role not in ("owner", "admin"):
        raise PermissionDenied("Only owners and administrators may approve or revoke credit.")
    return business, member


def credit_review(*, business, actor, parcel):
    from .workflow_summary import _Graph, _read_snapshot

    _authority(business, actor)
    with _read_snapshot():
        graph = _Graph(business, actor, [parcel.pk], False)
        selected = graph.parcels[0]
        financial = graph.financial(selected, False)
        snapshot = obligation_snapshot(graph, selected)
        if not financial["clearance"]["complete"] or snapshot is None:
            raise ValidationError(
                "Credit requires complete, verified issued Invoice obligations. Resolve missing or ambiguous evidence first."
            )
        if not any(Decimal(row["outstanding_limit"]) > 0 for row in snapshot["invoices"]):
            raise ValidationError("These obligations are already settled; credit is unnecessary.")
        return snapshot


@transaction.atomic
def approve_credit(
    *,
    business,
    actor,
    parcel,
    status,
    expires_at,
    reason_reference,
    obligation_fingerprint,
    idempotency_key,
):
    current, member = _authority(business, actor, lock=True)
    key = _key(idempotency_key)
    if not key or status not in CREDIT_MOVEMENTS or not reason_reference.strip():
        raise ValidationError("Movement, reason and retry token are required.")
    existing = LogisticsCreditApproval.objects.filter(business=current, idempotency_key=key).first()
    fields = {
        "parcel_id": parcel.pk,
        "approved_by_id": actor.pk,
        "status": status,
        "expires_at": expires_at,
        "reason_reference": reason_reference.strip(),
        "obligation_fingerprint": obligation_fingerprint,
    }
    if existing:
        if any(getattr(existing, name) != value for name, value in fields.items()):
            raise ValidationError("Credit retry token belongs to another approval.")
        return existing
    if (
        not isinstance(expires_at, datetime)
        or timezone.is_naive(expires_at)
        or expires_at <= timezone.now()
    ):
        raise ValidationError("Set a future, timezone-aware credit expiry.")
    snapshot = credit_review(business=current, actor=actor, parcel=parcel)
    if fingerprint(snapshot) != obligation_fingerprint:
        raise ValidationError(
            "Financial obligations changed since review. Reload before approving credit."
        )
    same = LogisticsCreditApproval.objects.filter(
        business=current, revocation__isnull=True, **fields
    ).first()
    if same:
        return same
    location = LogisticsLocationAssignment.objects.filter(
        business=current,
        membership=member,
        is_current=True,
        location__business=current,
        location__is_active=True,
    ).first()
    approval = LogisticsCreditApproval(
        business=current,
        client_id=snapshot["client_id"],
        approved_role=member.role,
        obligations_snapshot=snapshot,
        location_id=location.location_id if location else None,
        idempotency_key=key,
        **fields,
    )
    approval._domain_save(force_insert=True)
    # Renewing/correcting the same movement scope must not leave an older, wider
    # limit available as fallback after this approval expires or is revoked.
    for previous in LogisticsCreditApproval.objects.filter(
        business=current, parcel=parcel, status=status, revocation__isnull=True
    ).exclude(pk=approval.pk):
        revoke_credit(
            business=current,
            actor=actor,
            approval=previous,
            reason_reference=f"Superseded by credit approval {approval.pk}",
            idempotency_key=uuid5(key, f"supersede/{previous.pk}"),
        )
    log_activity(
        business=current,
        actor=actor,
        client=approval.client,
        action_type=ActivityLog.ActionType.STATUS_CHANGED,
        summary="Scoped Logistics credit approved",
        payload={
            "credit_approval_id": approval.pk,
            "parcel_id": approval.parcel_id,
            "movement": status,
            "reason_reference": approval.reason_reference,
            "expires_at": expires_at.isoformat(),
            "obligation_fingerprint": obligation_fingerprint,
        },
    )
    return approval


@transaction.atomic
def revoke_credit(*, business, actor, approval, reason_reference, idempotency_key):
    current, _ = _authority(business, actor, lock=True)
    approval = (
        LogisticsCreditApproval.objects.select_for_update()
        .filter(business=current, pk=approval.pk)
        .first()
    )
    key = _key(idempotency_key)
    if approval is None or not key or not reason_reference.strip():
        raise ValidationError("Same-tenant approval, reason and retry token are required.")
    fields = {
        "approval": approval,
        "revoked_by": actor,
        "reason_reference": reason_reference.strip(),
    }
    existing = LogisticsCreditRevocation.objects.filter(
        business=current, idempotency_key=key
    ).first()
    existing = existing or LogisticsCreditRevocation.objects.filter(approval=approval).first()
    if existing:
        if any(getattr(existing, name) != value for name, value in fields.items()):
            raise ValidationError("Revoked credit retains its original revocation audit.")
        return existing
    result = LogisticsCreditRevocation(business=current, idempotency_key=key, **fields)
    result._domain_save(force_insert=True)
    log_activity(
        business=current,
        actor=actor,
        client=approval.client,
        action_type=ActivityLog.ActionType.STATUS_CHANGED,
        summary="Scoped Logistics credit revoked",
        payload={
            "credit_approval_id": approval.pk,
            "parcel_id": approval.parcel_id,
            "reason_reference": result.reason_reference,
        },
    )
    return result


def require_movement_clearance(*, business, actor, parcel, status):
    """Call under the shared Business/member lock, immediately before new movement."""
    if status not in CREDIT_MOVEMENTS:
        return None
    if not connection.in_atomic_block:
        raise ValidationError("Movement clearance requires a locked transaction.")
    business = Business.objects.select_for_update().get(pk=business.pk)
    lock_actor_membership(business, actor)
    from .workflow_summary import _Graph

    graph = _Graph(business, actor, [parcel.pk], False)
    financial = graph.financial(graph.parcels[0], False)
    if not financial["clearance"]["movements"].get(status):
        raise ValidationError(
            "Verified settlement or valid scoped credit is required before departure or delivery."
        )
    return graph.credit_references[parcel.pk].get(status)
