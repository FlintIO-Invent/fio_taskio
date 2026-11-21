"""Synthetic catalogue setup restricted to a fresh owned preview session."""

import hashlib
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROUTE = "/crm/settings/services/"


def verify_setup():
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "ui_preview.settings"
        or os.environ.get("MOTIONMATE_PREVIEW_PHASE") != "setup"
    ):
        raise RuntimeError("Catalogue fixtures require private setup settings and phase.")
    from ui_preview.core import load_session, verify_database, verify_source

    root, state = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
    side = os.environ["MOTIONMATE_PREVIEW_SIDE"]
    if state["route"] != ROUTE:
        raise RuntimeError("Catalogue fixture route differs.")
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    return root, state, side


def seed(state):
    from django.db import transaction

    from apps.accounts.models import TaskIOUser
    from apps.businesses.models import (
        Business,
        BusinessSubscription,
        BusinessUser,
        ClarivoPlan,
        UserOnboardingState,
    )
    from apps.crm.models import BusinessService, ServiceCategory

    if Business.objects.filter(slug__startswith="preview-catalogue-").exists():
        raise RuntimeError("Catalogue fixtures already exist; reseed is forbidden.")
    clock = datetime.fromisoformat(state["clock"])
    accounts, contexts = [], {}
    with transaction.atomic(), patch("django.utils.timezone.now", return_value=clock):
        for scenario in [
            "populated",
            "empty",
            "long",
            "archived",
            "no-booking",
            "readonly",
            "logistics",
        ]:
            logistics = scenario == "logistics"
            plan = ClarivoPlan.objects.get(slug="logistics" if logistics else "preview-services")
            if logistics and not plan.is_active:
                plan.is_active = True
                plan.save(update_fields=["is_active"])
            if scenario == "no-booking":
                plan = ClarivoPlan.objects.create(
                    name="Internal services",
                    slug="preview-catalogue-internal",
                    max_users=10,
                    allow_invoicing=True,
                    allow_appointments=True,
                    allow_public_booking=False,
                )
            business = Business.objects.create(
                name="Harbour " + ("Logistics" if logistics else "Services") + " · " + scenario,
                slug="preview-catalogue-" + scenario,
                vertical="LOGISTICS" if logistics else "SERVICE",
                currency="EUR" if scenario == "long" else "USD",
                country="Netherlands" if scenario == "long" else "Sint Maarten",
                default_locale="nl-NL" if scenario == "long" else "en-SX",
                tax_rate=Decimal("6.00"),
                timezone="America/Lower_Princes",
            )
            sub = BusinessSubscription.objects.create(
                business=business,
                plan=plan,
                status="active",
                payment_provider="local",
                billing_interval="yearly" if logistics else "monthly",
            )
            for role in (
                ["owner", "admin", "staff", "accountant", "viewer", "validation"]
                if scenario in {"populated", "logistics"}
                else ["owner"]
            ):
                email = (
                    "catalogue."
                    + ("" if scenario == "populated" else scenario + ".")
                    + role
                    + "@preview.test"
                )
                user = TaskIOUser.objects.create_user(
                    email=email, password=state["password"], first_name="Alex", last_name="Morgan"
                )
                BusinessUser.objects.create(
                    business=business, user=user, role="owner" if role == "validation" else role
                )
                UserOnboardingState.objects.create(
                    business=business,
                    user=user,
                    completed_welcome=True,
                    selected_journey="setup_business",
                )
                accounts.append(
                    {
                        "email": email,
                        "role": "owner" if role == "validation" else role,
                        "scenario": scenario,
                        "vertical": business.vertical,
                        "business": business.name,
                    }
                )
            services, categories = [], []
            if scenario != "empty":
                for index in range(3 if scenario != "long" else 6):
                    category = ServiceCategory.objects.create(
                        business=business,
                        name=["Property care", "Consultations", "Seasonal work"][index % 3]
                        + (
                            " and comprehensive waterfront community administration"
                            if scenario == "long"
                            else ""
                        )
                        + str(index + 1),
                        is_active=index != 2,
                    )
                    categories.append(category.pk)
                    service = BusinessService.objects.create(
                        business=business,
                        category=category,
                        name=[
                            "Property maintenance consultation",
                            "Garden and courtyard care",
                            "Archived seasonal service",
                        ][index % 3]
                        + (
                            " — extended assessment and coordinated maintenance for community properties"
                            if scenario == "long"
                            else ""
                        ),
                        external_code="SVC-" + str(index + 1),
                        description="Existing scope and pricing are preserved.",
                        unit_price=Decimal("1234.56")
                        if scenario == "long"
                        else Decimal("125.00") + index * 25,
                        tax_rate=Decimal("6.00"),
                        is_active=scenario != "archived" and index != 2,
                        is_bookable_online=not logistics and index == 0,
                        default_duration_minutes=60,
                        booking_buffer_minutes=15,
                        public_description="Property consultation",
                        requires_manual_confirmation=True,
                    )
                    services.append(service.pk)
            if scenario == "readonly":
                sub.plan = ClarivoPlan.objects.get(slug="starter")
                sub.status = "past_due"
                sub.payment_provider = "stripe"
                sub.billing_currency = "usd"
                sub.billing_interval = "monthly"
                sub.provider_customer_id = "cus_catalogue_fixture"
                sub.provider_subscription_id = "sub_catalogue_fixture"
                sub.past_due_since = clock - timedelta(days=8)
                sub.grace_period_ends_at = clock - timedelta(days=1)
                sub.current_period_start = clock - timedelta(days=35)
                sub.current_period_end = clock - timedelta(days=5)
                sub.provider_updated_at = clock
                sub.save()
            contexts[scenario] = {
                "business_id": business.pk,
                "service_ids": services,
                "category_ids": categories,
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
    if "catalogue_review" in original:
        raise RuntimeError("Catalogue metadata already exists.")
    data = seed(state)
    original["accounts"].extend(data["accounts"])
    original["catalogue_review"] = data
    original["inventory"] = inventory()
    original["sha256"] = hashlib.sha256(
        json.dumps(original["inventory"], sort_keys=True).encode()
    ).hexdigest()
    write_json(target, original)
    print("Catalogue fixtures saved with canonical parity metadata.")


if __name__ == "__main__":
    main()
