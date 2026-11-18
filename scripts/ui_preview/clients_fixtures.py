"""Synthetic Clients review fixtures; verified new preview setup only."""

import hashlib
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

PEOPLE = [
    ("Alice", "Thompson", "Seabreeze Studio"),
    ("Ben", "Williams", "Harbour Dental"),
    ("Camille", "Laurent", "Atelier Camille"),
    ("Daniel", "James", "Island Kitchen"),
    ("Elena", "Martinez", "Blue Bay Wellness"),
    ("Farah", "Ali", "Palm House"),
    ("Gabriel", "Peters", "Peters Consulting"),
    ("Hana", "Chen", "Lotus Studio"),
    ("Isaac", "Brown", "Marina Collective"),
    ("Jade", "Richardson", "Coastal Office"),
    ("Kai", "Brooks", "Bright Ideas"),
    ("Leah", "Wilson", "Leah Wilson"),
    ("Maya", "de Vries", "Maya Design"),
]


def enabled(session):
    return session.get("route", "").startswith("/crm/staff/clients/")


def verify_setup(session):
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "ui_preview.settings"
        or os.environ.get("MOTIONMATE_PREVIEW_PHASE") != "setup"
    ):
        raise RuntimeError("Clients fixtures require verified private preview setup.")
    from ui_preview.core import load_session, verify_database

    root, owned = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
    if owned["id"] != session["id"] or not enabled(owned):
        raise RuntimeError("Clients fixture session/route identity differs.")
    verify_database(root, owned, os.environ["MOTIONMATE_PREVIEW_SIDE"])


def seed(session):
    verify_setup(session)
    from django.db import transaction

    from apps.accounts.models import TaskIOUser
    from apps.appointments.models import Appointment
    from apps.billings.models import Invoice, InvoiceLine, InvoicePayment
    from apps.billings.payment_services import record_invoice_payment
    from apps.businesses.models import (
        Business,
        BusinessSubscription,
        BusinessUser,
        ClarivoPlan,
        UserOnboardingState,
    )
    from apps.crm.models import Client

    if Business.objects.filter(slug__startswith="preview-clients-").exists():
        raise RuntimeError("Clients fixtures already exist; no reset or reseed is permitted.")
    clock = datetime.fromisoformat(session["clock"])
    accounts, contexts = [], {}
    normal_plan = ClarivoPlan.objects.get(slug="preview-services")
    fields = [
        f.name for f in Client._meta.concrete_fields if f.name not in {"created_at", "updated_at"}
    ]
    with transaction.atomic(), patch("django.utils.timezone.now", return_value=clock):
        for scenario in (
            "populated",
            "empty",
            "long",
            "partial",
            "no-history",
            "quota",
            "no-invoices",
            "no-appointments",
            "logistics",
        ):
            logistics = scenario == "logistics"
            business = Business.objects.create(
                name="Harbour Logistics · Clients Review"
                if logistics
                else "Harbour Services"
                + ("" if scenario == "populated" else " · " + scenario.title()),
                slug="preview-clients-" + scenario,
                vertical="LOGISTICS" if logistics else "SERVICE",
                timezone="America/Lower_Princes",
                country="Sint Maarten",
                currency="USD",
            )
            selected_plan = normal_plan
            if logistics:
                selected_plan = ClarivoPlan.objects.get(slug="logistics")
            if scenario in {"no-invoices", "no-appointments"}:
                selected_plan = ClarivoPlan.objects.create(
                    name="Clients review " + scenario,
                    slug="preview-clients-" + scenario,
                    max_users=10,
                    max_clients=500,
                    max_invoices_per_month=500,
                    max_appointments_per_month=500,
                    allow_public_booking=True,
                    allow_invoicing=scenario != "no-invoices",
                    allow_appointments=scenario != "no-appointments",
                )
            subscription = BusinessSubscription.objects.create(
                business=business,
                plan=selected_plan,
                status="active",
                payment_provider="local",
                billing_interval="yearly" if logistics else "monthly",
            )
            roles = (
                ["owner", "admin", "staff", "accountant", "viewer", "validation"]
                if scenario in {"populated", "logistics"}
                else ["owner"]
            )
            users = {}
            for role in roles:
                actual_role = "owner" if role == "validation" else role
                email = (
                    f"clients.{role}@preview.test"
                    if scenario == "populated"
                    else f"clients.{scenario}.{role}@preview.test"
                )
                user = TaskIOUser.objects.create_user(
                    email=email,
                    password=session["password"],
                    first_name="Alex",
                    last_name=role.title(),
                )
                BusinessUser.objects.create(business=business, user=user, role=actual_role)
                if actual_role in {"owner", "admin"}:
                    UserOnboardingState.objects.create(
                        business=business, user=user, completed_welcome=True
                    )
                users[role] = user
                accounts.append(
                    {
                        "email": email,
                        "role": actual_role,
                        "scenario": "clients-" + scenario,
                        "vertical": business.vertical,
                        "business": business.name,
                    }
                )
            clients = []
            if scenario != "empty":
                for index, (first, last, company) in enumerate(
                    PEOPLE if scenario == "populated" else PEOPLE[:2]
                ):
                    customer = Client.objects.create(
                        business=business,
                        first_name=first,
                        last_name=last,
                        company_name=company,
                        email=f"{first.lower()}@{scenario}.clients.preview.test",
                        phone=f"+1 721 555 {101 + index:04d}",
                        street_address="18 Front Street",
                        district="COLE_BAY" if index % 2 else "PHILIPSBURG",
                        country="Sint Maarten",
                        client_type="INDIVIDUAL" if index == 11 else "BUSINESS",
                        is_active=index != 5,
                        client_status="INACTIVE"
                        if index == 5
                        else "PROSPECT"
                        if index == 2
                        else "ACTIVE",
                        business_legal_name="Seabreeze Studio N.V." if index == 0 else "",
                        trade_name="Seabreeze" if index == 0 else "",
                        industry="Hospitality",
                        business_description="A small waterfront studio.",
                        website="https://example.test",
                        job_title="Operations manager",
                        department="Operations",
                        secondary_email="office@clients.preview.test",
                        secondary_phone="+1 721 555 0199",
                        whatsapp_number="+1 721 555 0198",
                        preferred_language="English",
                        preferred_contact_method="EMAIL",
                        lead_source="REFERRAL",
                        priority="MEDIUM",
                        assigned_to=users.get("staff"),
                        interested_services="Studio maintenance and seasonal deep cleaning",
                        consent_to_contact=True,
                        notes="Use the courtyard entrance. Please call before arriving."
                        if index == 0
                        else "",
                        communication_notes="Email for estimates; call for same-day changes.",
                        message="Looking for recurring studio maintenance.",
                    )
                    clients.append(customer)
                if scenario == "long":
                    target = clients[0]
                    target.first_name, target.last_name = (
                        "Alexandria-Catherine",
                        "van der Meer-Richardson",
                    )
                    target.company_name = (
                        "Caribbean Arts, Hospitality and Community Services Cooperative"
                    )
                    target.email = "alexandria.catherine.vandermeer.richardson@clients.preview.test"
                    target.notes = (
                        "Coordinate access with the facilities manager before arriving. " * 20
                    )
                    target.save()
                if scenario == "partial":
                    target = clients[0]
                    target.first_name = target.last_name = target.company_name = target.email = (
                        target.phone
                    ) = target.street_address = target.district = ""
                    target.save()
            invoices = []
            if scenario == "populated":
                for index in range(8):
                    invoice = Invoice.objects.create(
                        business=business,
                        client=clients[0],
                        invoice_number=f"CLI-{index + 1:03d}",
                        status="PAID" if index == 6 else "DRAFT" if index % 2 else "SENT",
                        subtotal=Decimal("240.00"),
                        total=Decimal("240.00"),
                    )
                    InvoiceLine.objects.create(
                        invoice=invoice,
                        description="Studio maintenance",
                        quantity=1,
                        unit_price=Decimal("240.00"),
                    )
                    if index == 0:
                        record_invoice_payment(
                            business=business,
                            actor=users["owner"],
                            invoice=invoice,
                            amount=Decimal("120.00"),
                            currency="USD",
                            method=InvoicePayment.Method.CASH,
                            reference="clients-preview-receipt",
                            idempotency_key=UUID(int=101),
                        )
                    invoices.append(invoice)
                for index, status in enumerate(("scheduled", "completed", "cancelled")):
                    start = (clock + timedelta(days=2 if index == 0 else -index)).replace(
                        hour=14, minute=0, second=0, microsecond=0
                    )
                    Appointment.objects.create(
                        business=business,
                        client=clients[0],
                        title="Studio maintenance" if index == 0 else "Seasonal deep clean",
                        start_time=start,
                        end_time=start + timedelta(hours=1),
                        status=status,
                        staff_member=users["staff"],
                        location="18 Front Street",
                    )
            if scenario == "quota":
                plan = ClarivoPlan.objects.create(
                    name="Clients at capacity",
                    slug="preview-clients-quota",
                    max_users=10,
                    max_clients=0,
                    allow_invoicing=True,
                    allow_appointments=True,
                    allow_public_booking=True,
                )
                subscription.plan = plan
                subscription.save()
            contexts[scenario] = {
                "business_id": business.pk,
                "client_ids": [c.pk for c in clients],
                "invoice_ids": [i.pk for i in invoices],
            }
        rows = [
            {
                key: (
                    str(v)
                    if isinstance(v, Decimal)
                    else v.isoformat()
                    if hasattr(v, "isoformat")
                    else v
                )
                for key, v in row.items()
            }
            for row in Client.objects.filter(business__slug__startswith="preview-clients-")
            .order_by("pk")
            .values(*fields)
        ]
    return {
        "accounts": accounts,
        "contexts": contexts,
        "client_inventory_sha256": hashlib.sha256(
            json.dumps(rows, sort_keys=True).encode()
        ).hexdigest(),
    }
