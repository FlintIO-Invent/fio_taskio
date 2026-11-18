"""One synthetic scenario adapter, run identically inside each real application."""

import hashlib
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import transaction

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice, InvoiceLine
from apps.businesses.models import (
    Business,
    BusinessBookingSettings,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    UserOnboardingState,
    WeeklyAvailability,
)
from apps.crm.models import BusinessService, Client, Lead

PEOPLE = [
    ("Jamie", "Rivera", "Harbour View Apartments"),
    ("Taylor", "Bennett", "Island Property Services"),
    ("Casey", "Laurent", "Household"),
    ("Jordan", "Ellis", "Seaview Guesthouse"),
    ("Riley", "James", "Market Street Studio"),
]


@transaction.atomic
def seed(session):
    if Business.objects.exists() or TaskIOUser.objects.exists():
        raise RuntimeError("Fixture seeding requires a fresh database with no users or businesses.")
    now = datetime.fromisoformat(session["clock"])
    accounts = []
    with patch("django.utils.timezone.now", return_value=now):
        plan = ClarivoPlan.objects.create(
            name="Preview Services",
            slug="preview-services",
            max_users=10,
            max_clients=500,
            max_invoices_per_month=500,
            max_appointments_per_month=750,
            allow_invoicing=True,
            allow_appointments=True,
            allow_public_booking=True,
        )
        locked = ClarivoPlan.objects.create(
            name="Preview locked modules",
            slug="preview-locked",
            max_users=10,
            max_clients=500,
            allow_invoicing=False,
            allow_appointments=False,
            allow_public_booking=False,
        )
        for scenario in (
            "populated",
            "empty",
            "locked",
            "grace",
            "restricted",
            "welcome",
            "long",
            "eur",
            "validation",
        ):
            business = Business.objects.create(
                name="Harbour Services · " + scenario.title(),
                slug="preview-" + scenario,
                timezone="America/Lower_Princes",
                currency="EUR" if scenario == "eur" else "USD",
                country="Netherlands" if scenario == "eur" else "Sint Maarten",
                default_locale="nl-NL" if scenario == "eur" else "en-SX",
                invoice_prefix="INV",
            )
            if scenario == "long":
                business.name = (
                    "Harbour Association for Community Services and Property Administration"
                )
                business.save()
            subscription = BusinessSubscription.objects.create(
                business=business, plan=plan, status="active", payment_provider="local"
            )
            for role in (
                ("owner", "admin", "staff", "accountant", "viewer")
                if scenario == "populated"
                else ("owner",)
            ):
                email = (
                    f"{role}@preview.test"
                    if scenario == "populated"
                    else f"{scenario}.{role}@preview.test"
                )
                user = TaskIOUser.objects.create_user(
                    email=email, password=session["password"], first_name="Alex", last_name="Morgan"
                )
                BusinessUser.objects.create(business=business, user=user, role=role)
                if role in {"owner", "admin"}:
                    UserOnboardingState.objects.create(
                        business=business,
                        user=user,
                        completed_welcome=scenario not in {"welcome", "validation"},
                        selected_journey=""
                        if scenario in {"welcome", "validation"}
                        else "setup_business",
                    )
                accounts.append(
                    {
                        "email": email,
                        "role": role,
                        "scenario": scenario,
                        "vertical": "SERVICE",
                        "business": business.name,
                    }
                )
            if scenario != "empty":
                service = BusinessService.objects.create(
                    business=business,
                    name="Property maintenance consultation",
                    unit_price=Decimal("125"),
                    is_bookable_online=True,
                    default_duration_minutes=60,
                )
                BusinessBookingSettings.objects.create(
                    business=business,
                    booking_enabled=True,
                    minimum_notice_hours=0,
                    maximum_days_ahead=365,
                )
                for day in range(7):
                    WeeklyAvailability.objects.create(
                        business=business,
                        day_of_week=day,
                        start_time=time(0),
                        end_time=time(23, 59),
                        is_active=True,
                    )
                for i, (first, last, company) in enumerate(PEOPLE):
                    customer = Client.objects.create(
                        business=business,
                        first_name=first,
                        last_name=last,
                        email=f"client-{i}@{scenario}.preview.test",
                        phone="+17215550101",
                        company_name=company
                        + (
                            " · Community services and waterfront property administration"
                            if scenario == "long"
                            else ""
                        ),
                    )
                    start = now + timedelta(hours=1 + 2 * i)
                    Appointment.objects.create(
                        business=business,
                        client=customer,
                        service=service,
                        service_name=service.name,
                        title="Initial site visit",
                        start_time=start,
                        end_time=start + timedelta(hours=1),
                    )
                    Lead.objects.create(
                        business=business,
                        lead_type="REQUEST",
                        requested_service=service,
                        first_name=first,
                        last_name=last,
                        company_name=company,
                        email=f"request-{i}@{scenario}.preview.test",
                        phone="+17215550102",
                        status="NEW" if i < 3 else "CONTACTED",
                        request_source="public_booking" if i < 2 else "staff",
                        preferred_start_time=start + timedelta(days=1),
                    )
                    if i < 3:
                        amount = Decimal(125 * (i + 1))
                        invoice = Invoice.objects.create(
                            business=business,
                            client=customer,
                            invoice_number=f"PRE-{1001 + i}",
                            status="SENT",
                            subtotal=amount,
                            total=amount,
                        )
                        InvoiceLine.objects.create(
                            invoice=invoice, description="Consultation", unit_price=amount
                        )
            if scenario == "locked":
                subscription.plan = locked
                subscription.save()
            if scenario in {"grace", "restricted"}:
                subscription.plan = ClarivoPlan.objects.get(slug="pro")
                subscription.status, subscription.payment_provider = "past_due", "stripe"
                subscription.provider_customer_id = "cus_preview_synthetic_" + scenario
                subscription.provider_subscription_id = "sub_preview_synthetic_" + scenario
                subscription.provider_price_id = "price_preview_synthetic_" + scenario
                subscription.billing_interval, subscription.billing_currency = "monthly", "usd"
                subscription.current_period_start, subscription.current_period_end = (
                    now - timedelta(days=15),
                    now + timedelta(days=15),
                )
                subscription.past_due_since = now - timedelta(days=10)
                subscription.grace_period_ends_at = now + timedelta(
                    days=2 if scenario == "grace" else -1
                )
                subscription.save()
        logistics = Business.objects.create(
            name="Harbour Logistics · Preview", slug="preview-logistics", vertical="LOGISTICS"
        )
        BusinessSubscription.objects.create(
            business=logistics,
            plan=ClarivoPlan.objects.get(slug="logistics"),
            status="pending_checkout",
            payment_provider="stripe",
            billing_interval="yearly",
            billing_currency="eur",
        )
        for role in ("owner", "staff"):
            email = f"logistics.{role}@preview.test"
            user = TaskIOUser.objects.create_user(
                email=email, password=session["password"], first_name="Alex", last_name="Morgan"
            )
            BusinessUser.objects.create(business=logistics, user=user, role=role)
            UserOnboardingState.objects.create(
                business=logistics, user=user, completed_welcome=True
            )
            accounts.append(
                {
                    "email": email,
                    "role": role,
                    "scenario": "logistics",
                    "vertical": "LOGISTICS",
                    "business": logistics.name,
                }
            )
    from ui_preview.appointments_fixtures import seed as seed_appointments

    appointments_review = seed_appointments(session)
    from ui_preview.clients_fixtures import enabled
    from ui_preview.clients_fixtures import seed as seed_clients

    clients_review = seed_clients(session) if enabled(session) else None
    if clients_review:
        accounts.extend(clients_review["accounts"])
    data = inventory()
    result = {
        "clock": session["clock"],
        "accounts": accounts,
        "appointments_review": appointments_review,
        "inventory": data,
        "sha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
    }
    if clients_review is not None:
        result["clients_review"] = clients_review
    return result


def inventory():
    """Compare meaningful fixture fields, excluding randomized password salts."""
    specs = [
        (Business, ["id", "name", "slug", "vertical", "currency", "timezone"]),
        (TaskIOUser, ["id", "email", "is_active"]),
        (BusinessUser, ["business_id", "user_id", "role", "is_active"]),
        (Client, ["id", "business_id", "first_name", "last_name", "company_name", "email"]),
        (
            BusinessService,
            [
                "id",
                "business_id",
                "name",
                "unit_price",
                "is_bookable_online",
                "default_duration_minutes",
            ],
        ),
        (
            BusinessBookingSettings,
            ["business_id", "booking_enabled", "minimum_notice_hours", "maximum_days_ahead"],
        ),
        (WeeklyAvailability, ["business_id", "day_of_week", "start_time", "end_time", "is_active"]),
        (UserOnboardingState, ["business_id", "user_id", "selected_journey", "completed_welcome"]),
        (
            ClarivoPlan,
            [
                "id",
                "slug",
                "allow_appointments",
                "allow_invoicing",
                "allow_public_booking",
                "max_users",
                "max_clients",
                "max_appointments_per_month",
                "max_invoices_per_month",
            ],
        ),
        (
            Appointment,
            ["id", "business_id", "client_id", "title", "start_time", "end_time", "status"],
        ),
        (
            Lead,
            [
                "id",
                "business_id",
                "first_name",
                "last_name",
                "status",
                "lead_type",
                "request_source",
                "preferred_start_time",
            ],
        ),
        (Invoice, ["id", "business_id", "client_id", "invoice_number", "status", "total"]),
        (InvoiceLine, ["invoice_id", "description", "unit_price", "quantity"]),
        (
            BusinessSubscription,
            [
                "business_id",
                "plan_id",
                "status",
                "payment_provider",
                "billing_currency",
                "billing_interval",
                "current_period_start",
                "current_period_end",
                "past_due_since",
                "grace_period_ends_at",
            ],
        ),
    ]
    return {
        model._meta.label: [
            {
                key: (
                    value.isoformat()
                    if isinstance(value, (datetime, time))
                    else str(value)
                    if isinstance(value, Decimal)
                    else value
                )
                for key, value in row.items()
            }
            for row in model.objects.order_by("pk").values(*fields)
        ]
        for model, fields in specs
    }
