"""Preserve history; do not invent historical Shipment cargo or erase duplicates."""

import hashlib
import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    alias = schema_editor.connection.alias
    Invoice = apps.get_model("billings", "Invoice")
    Line = apps.get_model("billings", "InvoiceLine")
    Charge = apps.get_model("logistics", "LogisticsCharge")
    Coverage = apps.get_model("logistics", "LogisticsChargeParcel")
    recorded = timezone.now()
    for invoice in (
        Invoice.objects.using(alias)
        .filter(business__vertical="LOGISTICS", currency_snapshot__isnull=True)
        .select_related("business")
        .iterator()
    ):
        rate = invoice.business.tax_rate
        if invoice.status != "DRAFT" and invoice.subtotal:
            rate = (invoice.tax * Decimal("100") / invoice.subtotal).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        if abs(rate) > Decimal("99999.9999"):
            rate = (
                invoice.business.tax_rate
            )  # Preserve pathological legacy totals without inventing a statutory rate.
        Invoice.objects.using(alias).filter(pk=invoice.pk).update(
            currency_snapshot=invoice.business.currency,
            tax_rate_snapshot=rate,
            snapshot_is_legacy=True,
            financial_snapshot_at=recorded if invoice.status != "DRAFT" else None,
        )
    charges = list(
        Charge.objects.using(alias).select_related("business", "parcel", "invoice_line__invoice")
    )

    def key(charge):
        purpose = (
            ["service", charge.service_id]
            if charge.service_id
            else ["custom", " ".join(charge.description.split()).casefold()]
        )
        value = [
            "parcel" if charge.parcel_id else "shipment",
            charge.parcel_id or charge.shipment_id,
            purpose,
            "",
        ]
        return hashlib.sha256(
            json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()

    counts = Counter((charge.business_id, key(charge)) for charge in charges)
    for charge in charges:
        if charge.currency_snapshot is not None:
            continue
        currency = charge.business.currency
        if charge.invoice_line_id:
            line = charge.invoice_line
            if (
                line.invoice.business_id == charge.business_id
                and line.invoice.client_id == charge.client_id
            ):
                Line.objects.using(alias).filter(pk=line.pk).update(charge_source_id=charge.pk)
                currency = line.invoice.currency_snapshot or currency
        fields = dict(currency_snapshot=currency, currency_is_legacy=True)
        if counts[charge.business_id, key(charge)] == 1:
            fields["logical_key"] = key(charge)
        if charge.parcel_id and (charge.parcel.business_id, charge.parcel.client_id) == (
            charge.business_id,
            charge.client_id,
        ):
            Coverage.objects.using(alias).get_or_create(
                charge_id=charge.pk, parcel_id=charge.parcel_id
            )
            fields["coverage_recorded_at"] = recorded
        Charge.objects.using(alias).filter(pk=charge.pk).update(**fields)


class Migration(migrations.Migration):
    dependencies = [("logistics", "0020_financial_coverage_snapshots")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
