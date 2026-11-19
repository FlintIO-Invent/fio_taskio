"""Synthetic invoice fixtures: refuse unowned settings/phase before model imports."""

import hashlib
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import UUID


def verify_setup():
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "ui_preview.settings"
        or os.environ.get("MOTIONMATE_PREVIEW_PHASE") != "setup"
    ):
        raise RuntimeError("Invoice fixtures require private setup settings and phase.")
    from ui_preview.core import load_session, verify_database, verify_source

    root, state = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
    side = os.environ["MOTIONMATE_PREVIEW_SIDE"]
    if state["route"] != "/billings/":
        raise RuntimeError("Invoice fixture route differs.")
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    return root, state, side


def seed(state):
    from django.db import transaction

    from apps.accounts.models import TaskIOUser
    from apps.billings.models import Invoice, InvoiceLine
    from apps.billings.payment_services import record_invoice_payment
    from apps.billings.services import recalculate_invoice_totals
    from apps.businesses.models import (
        Business,
        BusinessSubscription,
        BusinessUser,
        ClarivoPlan,
        UserOnboardingState,
    )
    from apps.crm.models import BusinessService, Client, ServiceCategory

    if Business.objects.filter(slug__startswith="preview-invoices-").exists():
        raise RuntimeError("Invoice fixtures already exist; reset/reseed is forbidden.")
    clock = datetime.fromisoformat(state["clock"])
    accounts, contexts = [], {}
    with transaction.atomic(), patch("django.utils.timezone.now", return_value=clock):
        for scenario in ["populated", "empty", "long", "quota", "locked", "logistics"]:
            logistics = scenario == "logistics"
            plan = ClarivoPlan.objects.get(slug="logistics" if logistics else "preview-services")
            if logistics and not plan.is_active:
                plan.is_active = True
                plan.save(update_fields=["is_active"])
            if scenario in ["quota", "locked"]:
                plan = ClarivoPlan.objects.create(
                    name="Invoice preview " + scenario,
                    slug="preview-invoices-" + scenario,
                    allow_invoicing=scenario != "locked",
                    allow_appointments=True,
                    max_users=10,
                    max_clients=100,
                    max_invoices_per_month=0 if scenario == "quota" else 100,
                )
            business = Business.objects.create(
                name="Harbour " + ("Logistics" if logistics else "Services") + " · " + scenario,
                slug="preview-invoices-" + scenario,
                vertical="LOGISTICS" if logistics else "SERVICE",
                currency="USD",
                tax_rate=Decimal("6"),
                country="Sint Maarten",
                timezone="America/Lower_Princes",
                email="hello@harbour.preview.test",
                phone="+17215550100",
                address_line_1="12 Waterfront Road",
            )
            BusinessSubscription.objects.create(
                business=business,
                plan=plan,
                status="active",
                payment_provider="local",
                billing_interval="yearly" if logistics else "monthly",
            )
            users = {}
            for role in (
                ["owner", "admin", "staff", "accountant", "viewer"]
                if scenario in ["populated", "logistics"]
                else ["owner"]
            ):
                email = (
                    f"invoices.{role}@preview.test"
                    if scenario == "populated"
                    else f"invoices.{scenario}.{role}@preview.test"
                )
                user = TaskIOUser.objects.create_user(
                    email=email,
                    password=state["password"],
                    first_name="Alex",
                    last_name=role.title(),
                )
                BusinessUser.objects.create(business=business, user=user, role=role)
                if role in ["owner", "admin"]:
                    UserOnboardingState.objects.create(
                        business=business, user=user, completed_welcome=True
                    )
                users[role] = user
                accounts.append(
                    {
                        "email": email,
                        "role": role,
                        "vertical": business.vertical,
                        "scenario": "invoices-" + scenario,
                        "business": business.name,
                    }
                )
            customer = Client.objects.create(
                business=business,
                first_name="Alice",
                last_name="Thompson",
                company_name="Seabreeze Studio",
                email=f"alice@{scenario}.invoices.preview.test",
                phone="+17215550101",
                street_address="18 Front Street",
                district="PHILIPSBURG",
                country="Sint Maarten",
            )
            if scenario == "long":
                customer.company_name = "Seabreeze Association for Community Services and Waterfront Property Administration"
                customer.save(update_fields=["company_name"])
            service = None
            if not logistics:
                category = ServiceCategory.objects.create(business=business, name="Property care")
                service = BusinessService.objects.create(
                    business=business,
                    category=category,
                    name="Studio maintenance",
                    description="Studio maintenance visit",
                    unit_price=Decimal("125"),
                )
            invoices = {}
            kinds = (
                []
                if scenario in ["empty", "locked", "quota"]
                else [
                    "partial",
                    "draft",
                    "paid",
                    "cancelled",
                    "zero-tax",
                    "zero-value",
                    "legacy",
                    "missing-email",
                    "many-lines",
                ]
                if scenario == "populated"
                else ["draft", "issued"]
            )
            for n, kind in enumerate(kinds):
                invoice = Invoice.objects.create(
                    business=business,
                    client=customer,
                    invoice_number=f"INV-{scenario.upper()}-{n + 1:04d}",
                    notes="Thank you for choosing Harbour Services.\nPlease include the invoice number with your payment."
                    + (
                        " Coordinate access with our facilities team." * 20
                        if scenario == "long"
                        else ""
                    ),
                )
                for line in range(48 if kind == "many-lines" else 2):
                    InvoiceLine.objects.create(
                        invoice=invoice,
                        description=f"Scheduled maintenance item {line + 1:02d} · Window, equipment and shared spaces"
                        if kind == "many-lines"
                        else "Studio maintenance visit"
                        if line == 0
                        else "Replacement supplies",
                        quantity=2 if line == 0 and kind != "many-lines" else 1,
                        unit_price=Decimal("0")
                        if kind == "zero-value"
                        else Decimal("25")
                        if kind == "many-lines"
                        else Decimal("125")
                        if line == 0
                        else Decimal("50"),
                    )
                recalculate_invoice_totals(invoice, actor=users["owner"])
                invoice.refresh_from_db()
                if kind == "zero-tax":
                    # Synthetic saved values demonstrate omission without changing defaults.
                    invoice.tax = Decimal("0")
                    invoice.total = invoice.subtotal
                invoice.status = (
                    "DRAFT"
                    if kind == "draft"
                    else "CANCELLED"
                    if kind == "cancelled"
                    else "PAID"
                    if kind == "legacy"
                    else "SENT"
                )
                invoice.save()
                if kind in ["partial", "paid"]:
                    record_invoice_payment(
                        business=business,
                        actor=users["owner"],
                        invoice=invoice,
                        amount=Decimal("100") if kind == "partial" else invoice.total,
                        currency="USD",
                        method="BANK_TRANSFER",
                        reference="REVIEW-" + scenario + "-" + kind,
                        idempotency_key=UUID(int=invoice.pk + 10000),
                    )
                invoices[kind] = invoice.pk
            contexts[scenario] = {
                "business_id": business.pk,
                "client_id": customer.pk,
                "service_id": service.pk if service else None,
                "invoices": invoices,
            }
    return {"accounts": accounts, "contexts": contexts}


def main():
    root, state, side = verify_setup()
    import django

    django.setup()
    from ui_preview.guard import install

    install()
    from ui_preview.core import write_json
    from ui_preview.fixtures import inventory

    target = Path(state[side]["directory"]) / "fixtures.json"
    original = json.loads(target.read_text())
    if "invoices_review" in original:
        raise RuntimeError("Invoice metadata already exists.")
    data = seed(state)
    original["accounts"].extend(data["accounts"])
    original["invoices_review"] = data
    original["inventory"] = inventory()
    original["sha256"] = hashlib.sha256(
        json.dumps(original["inventory"], sort_keys=True).encode()
    ).hexdigest()
    write_json(target, original)
    print(
        json.dumps({"fixture_sha256": original["sha256"], "contexts": data["contexts"]}, indent=2)
    )


if __name__ == "__main__":
    main()
