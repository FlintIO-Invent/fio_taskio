"""Read-only customer invoice vocabulary. Never changes accounting or lifecycle state.

Callers must apply their existing tenant/financial read scope before presenting invoices.
Settlement remains authoritative; payment, refund liability and movement clearance are
deliberately independent. In particular, credit clearance is never payment evidence.
"""

from copy import copy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.businesses.models import Business

from .models import Invoice
from .payment_services import InvoiceSettlement, _invoice_settlement

ZERO = Decimal("0.00")
PAYMENT_LABELS = {"UNPAID": "Unpaid", "PARTIAL": "Partially paid", "PAID": "Paid"}
LIFECYCLE_LABELS = {"DRAFT": "Draft", "ISSUED": "Issued", "CANCELLED": "Cancelled"}


def payment_classification(*, issued, review, adjusted_total, outstanding):
    """Classify authoritative obligation balances, including allocated cancellation debt.

    adjusted_total - outstanding represents satisfied obligations, excluding excess
    receipts owed back on a different allocation. Never net refund liability off debt.
    """
    if not issued or review:
        return "", False
    if adjusted_total == ZERO and outstanding == ZERO:
        return "", True
    if outstanding == ZERO:
        return "PAID", False
    return ("PARTIAL" if adjusted_total > outstanding else "UNPAID"), False


@dataclass(frozen=True)
class InvoicePresentation:
    lifecycle: str
    lifecycle_label: str
    payment_status: str
    payment_label: str
    no_payment_required: bool
    review_required: bool
    legacy_unverified: bool
    issues: tuple[str, ...]
    balance: InvoiceSettlement
    original_total: Decimal
    billing_business: Business
    email_submitted_at: datetime | None
    email_recipient: str
    email_submission_count: int

    @property
    def currency(self):
        return self.balance.currency

    @property
    def email_note(self):
        if not self.email_submitted_at:
            return "No email submission recorded."
        submitted_at = timezone.localtime(
            self.email_submitted_at, ZoneInfo(self.billing_business.timezone)
        )
        return (
            f"Sent by email {submitted_at:%Y-%m-%d %H:%M %Z} to {self.email_recipient}. "
            "Delivery to the recipient is unconfirmed."
        )

    @property
    def collectible(self):
        return self.lifecycle == "ISSUED" and not self.review_required and self.balance_due > ZERO

    @property
    def balance_due(self):
        if self.review_required:
            return None
        return self.balance.outstanding if self.lifecycle == "ISSUED" else ZERO

    @property
    def unverified_balance(self):
        return self.balance.outstanding if self.review_required else ZERO

    @property
    def verified_paid(self):
        return self.payment_status == "PAID" and self.balance.net_paid > ZERO

    @property
    def indicators(self):
        labels = [self.payment_label] if self.payment_label else []
        if self.no_payment_required:
            labels.append("No payment required")
        if self.balance.credits:
            labels.append("Cancellation credit")
        if self.balance.refund_due:
            labels.append("Refund due")
        if self.review_required:
            labels.append(
                "Manually marked paid — unverified"
                if self.legacy_unverified
                else "Accounting review required"
            )
        return tuple(labels)

    @property
    def refund_note(self):
        if not self.balance.refund_due:
            return ""
        return (
            "Refund due is separate from the balance due. Money has not been recorded as returned. "
            "Payments allocated to one obligation do not offset debt on another."
        )

    @property
    def summary(self):
        """Bounded native-value projection for Logistics' Decimal/datetime contract.

        Never embed model instances or receipt/tenant details in workflow summaries.
        """
        return {
            "lifecycle_label": self.lifecycle_label,
            "payment_label": self.payment_label,
            "verified_paid": self.verified_paid,
            "no_payment_required": self.no_payment_required,
            "review_required": self.review_required,
            "legacy_unverified": self.legacy_unverified,
            "indicators": self.indicators,
            "balance_due": self.balance_due,
            "balance": {"credits": self.balance.credits, "refund_due": self.balance.refund_due},
        }

    @property
    def note(self):
        if self.legacy_unverified:
            return (
                "Manually marked paid — unverified. No receipt evidence; "
                "review before requesting payment."
            )
        if self.review_required:
            return (
                "Accounting review required. These amounts are not included in collectible totals."
            )
        if self.no_payment_required:
            return (
                "Fully credited. No payment required."
                if self.balance.credits
                else "Zero-value invoice. No payment required."
            )
        if self.lifecycle == "DRAFT":
            return "Draft — not collectible."
        if self.lifecycle == "CANCELLED":
            return "Cancelled — no collectible balance. Payment history is retained."
        return ""

    @property
    def amount_rows(self):
        """One set of labels and saved-currency amounts for HTML, email and both PDFs."""
        balance = self.balance
        rows = [("Original invoice total", self.original_total)]
        if balance.credits:
            rows += [
                ("Cancellation credits", balance.credits),
                ("Adjusted invoice amount", balance.adjusted_total),
            ]
        rows += [
            ("Net payments received", balance.net_paid if not self.issues else None),
            ("Balance due", self.balance_due),
            ("Refund due", balance.refund_due if not self.issues else None),
        ]
        if self.review_required:
            rows.append(("Unverified balance — review only", self.unverified_balance))
        return tuple(
            {
                "label": label,
                "amount": amount,
                "text": (
                    f"{self.currency} {amount:.2f}"
                    if amount is not None
                    else "Accounting review required"
                ),
            }
            for label, amount in rows
        )


def present_invoice(invoice, *, balance=None, issues=()):
    balance = balance if balance is not None else _invoice_settlement(invoice)
    lifecycle = (
        "DRAFT"
        if invoice.status == Invoice.Status.DRAFT
        else "CANCELLED" if invoice.status == Invoice.Status.CANCELLED else "ISSUED"
    )
    issues = tuple(dict.fromkeys((*balance.issues, *issues)))
    if invoice.business.vertical == "LOGISTICS" and invoice.snapshot_is_legacy:
        issues += ("Legacy currency/tax snapshots require accounting confirmation.",)
    review = bool(issues or balance.legacy_paid_unverified)
    status, no_payment = payment_classification(
        issued=lifecycle == "ISSUED",
        review=review,
        adjusted_total=balance.adjusted_total,
        outstanding=balance.outstanding,
    )
    # A zero balance is not evidence when the ledger has no receipts for a
    # positive adjusted obligation. Keep unexpected projections out of Paid.
    if status == "PAID" and balance.net_paid <= ZERO:
        status, review = "", True
        issues += ("Payment evidence requires accounting review.",)
    business = copy(invoice.business)
    business.currency = balance.currency
    return InvoicePresentation(
        lifecycle=lifecycle,
        lifecycle_label=LIFECYCLE_LABELS[lifecycle],
        payment_status=status,
        payment_label=PAYMENT_LABELS.get(status, ""),
        no_payment_required=no_payment,
        review_required=review,
        legacy_unverified=balance.legacy_paid_unverified,
        issues=issues,
        balance=balance,
        original_total=invoice.total,
        billing_business=business,
        email_submitted_at=invoice.emailed_at,
        email_recipient=invoice.emailed_to,
        email_submission_count=invoice.email_send_count,
    )


def invoice_finance_totals(invoices, *, business, month_start, month_end):
    """Currency-separated invoice/receipt totals for already-authorized querysets."""
    buckets = {}
    for invoice in invoices:
        if invoice.business_id != business.pk:
            raise ValueError("Invoice totals must remain within the authorized workspace.")
        financial = present_invoice(invoice)
        values = buckets.setdefault(
            financial.currency,
            {
                "currency": financial.currency,
                "billing_business": financial.billing_business,
                "outstanding_invoice_total": ZERO,
                "paid_invoice_total": ZERO,
                "invoiced_this_month_total": ZERO,
                "draft_invoice_total": ZERO,
                "review_invoice_total": ZERO,
                "review_invoice_count": 0,
                "open_invoice_count": 0,
                "paid_invoice_count": 0,
            },
        )
        if financial.review_required:
            values["review_invoice_total"] += financial.unverified_balance
            values["review_invoice_count"] += 1
            continue
        if financial.lifecycle == "DRAFT":
            values["draft_invoice_total"] += financial.original_total
            continue
        if financial.lifecycle != "ISSUED":
            continue
        if month_start <= invoice.created_at < month_end:
            values["invoiced_this_month_total"] += financial.balance.adjusted_total
        values["outstanding_invoice_total"] += financial.balance_due
        values["paid_invoice_total"] += financial.balance.net_paid
        values["open_invoice_count"] += int(financial.collectible)
        values["paid_invoice_count"] += int(financial.verified_paid)
    return list(sorted(buckets.values(), key=lambda value: value["currency"]))
