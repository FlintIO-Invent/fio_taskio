"""Explicit zero-value billing evidence for operational-only test fixtures."""

import uuid

from apps.billings.services import change_invoice_status

from .billing_services import add_charge, invoice_charges


def clear_test_parcel(*, business, actor, parcel):
    """A stated no-charge fixture, never a payment fabrication or policy bypass.

    Financial-policy tests must build their own obligations and never use this helper.
    """
    charge = parcel.charges.filter(
        description="Explicit zero-value operational test fixture"
    ).first()
    if charge is None:
        charge = add_charge(
            business=business,
            actor=actor,
            parcel=parcel,
            description="Explicit zero-value operational test fixture",
            unit_price=0,
            idempotency_key=uuid.uuid4(),
        )
    invoice = invoice_charges(business=business, actor=actor, charge_ids=[charge.pk])
    change_invoice_status(business=business, actor=actor, invoice=invoice, status="SENT")
