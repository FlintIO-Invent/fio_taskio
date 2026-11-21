"""Synthetic subscription states only in a freshly verified private setup environment."""

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROUTE = "/businesses/subscription/"


def verify_setup():
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "ui_preview.settings"
        or os.environ.get("MOTIONMATE_PREVIEW_PHASE") != "setup"
    ):
        raise RuntimeError("Subscription fixtures require private setup settings and phase.")
    from ui_preview.core import load_session, verify_database, verify_source

    root, state = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
    side = os.environ["MOTIONMATE_PREVIEW_SIDE"]
    if state["route"] != ROUTE:
        raise RuntimeError("Subscription fixture route differs.")
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    return root, state, side


def seed(state):
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import transaction

    from apps.accounts.models import TaskIOUser
    from apps.businesses.models import (
        Business,
        BusinessSubscription,
        BusinessUser,
        ClarivoPlan,
        UserOnboardingState,
    )
    from apps.crm.models import Client

    if Business.objects.filter(slug__startswith="preview-subscriptions-").exists():
        raise RuntimeError("Subscription fixtures already exist; reseed is forbidden.")
    clock = datetime.fromisoformat(state["clock"])
    accounts, contexts = [], {}
    with transaction.atomic(), patch("django.utils.timezone.now", return_value=clock):
        for scenario in [
            "populated",
            "empty",
            "long",
            "trial",
            "pending",
            "cancel",
            "grace",
            "readonly",
            "stale",
            "missing-period",
            "cancelled",
            "beta",
            "free-test",
            "no-subscription",
            "logistics",
        ]:
            logistics = scenario == "logistics"
            safe = ClarivoPlan.objects.get(slug="logistics" if logistics else "preview-services")
            if logistics and not safe.is_active:
                safe.is_active = True
                safe.save(update_fields=["is_active"])
            business = Business.objects.create(
                name="Harbour Services · " + scenario
                if not logistics
                else "Harbour Logistics · Subscription",
                slug="preview-subscriptions-" + scenario,
                vertical="LOGISTICS" if logistics else "SERVICE",
                country="Netherlands" if scenario == "long" else "Sint Maarten",
                currency="EUR" if scenario == "long" else "USD",
            )
            if scenario == "long":
                business.name = "Harbour Community Association for Waterfront Property Administration and Seasonal Services"
                business.save(update_fields=["name"])
            sub = (
                None
                if scenario == "no-subscription"
                else BusinessSubscription.objects.create(
                    business=business,
                    plan=safe,
                    status="active",
                    payment_provider="local",
                    billing_interval="yearly" if logistics else "monthly",
                )
            )
            for role in (
                ["owner", "admin", "staff", "accountant", "viewer"]
                if scenario in {"populated", "logistics"}
                else ["owner"]
            ):
                email = (
                    "subscriptions."
                    + ("" if scenario == "populated" else scenario + ".")
                    + role
                    + "@preview.test"
                )
                user = TaskIOUser.objects.create_user(
                    email=email, password=state["password"], first_name="Alex", last_name="Morgan"
                )
                BusinessUser.objects.create(business=business, user=user, role=role)
                UserOnboardingState.objects.create(
                    business=business,
                    user=user,
                    completed_welcome=True,
                    selected_journey="setup_business",
                )
                accounts.append(
                    {
                        "email": email,
                        "role": role,
                        "scenario": scenario,
                        "vertical": business.vertical,
                        "business": business.name,
                    }
                )
            if scenario not in {"empty", "no-subscription"}:
                for i in range(4 if scenario == "long" else 1):
                    Client.objects.create(
                        business=business,
                        first_name="Synthetic",
                        last_name="Customer " + str(i),
                        email=f"customer-{i}@{scenario}.preview.test",
                    )
            if sub:
                sub.plan = ClarivoPlan.objects.get(
                    slug="logistics" if logistics else "beta" if scenario == "beta" else "pro"
                )
                if not sub.plan.is_active:
                    sub.plan.is_active = True
                    sub.plan.save(update_fields=["is_active"])
                sub.billing_interval = "yearly" if logistics else "monthly"
                sub.billing_currency = "eur" if scenario == "long" else "usd"
                sub.current_period_start = clock - timedelta(days=15)
                sub.current_period_end = clock + timedelta(days=15)
                if scenario in {
                    "trial",
                    "pending",
                    "cancel",
                    "grace",
                    "readonly",
                    "stale",
                    "missing-period",
                    "cancelled",
                }:
                    sub.payment_provider = "stripe"
                    sub.provider_customer_id = "cus_subscription_fixture_" + scenario
                    sub.provider_subscription_id = "sub_subscription_fixture_" + scenario
                    sub.provider_price_id = "price_pro_monthly_usd"
                    sub.provider_updated_at = clock
                if scenario == "trial":
                    sub.status = "trialing"
                    sub.trial_start = clock - timedelta(days=5)
                    sub.trial_end = clock + timedelta(days=9)
                elif scenario == "pending":
                    sub.status = "pending_checkout"
                elif scenario == "cancel":
                    sub.cancel_at_period_end = True
                elif scenario in {"grace", "readonly"}:
                    sub.status = "past_due"
                    sub.past_due_since = clock - timedelta(days=8)
                    sub.grace_period_ends_at = clock + timedelta(
                        days=2 if scenario == "grace" else -1
                    )
                elif scenario == "stale":
                    sub.current_period_end = clock - timedelta(days=2)
                elif scenario == "missing-period":
                    sub.current_period_end = None
                elif scenario == "cancelled":
                    sub.status = "cancelled"
                elif scenario == "free-test":
                    sub.provisioning_source = "free_test"
                sub.save()
            contexts[scenario] = {
                "business_id": business.pk,
                "subscription_id": sub.pk if sub else None,
            }
        # Full configuration/subscription facts supplement the common domain/financial inventory.
        facts = {
            label: list(model.objects.order_by("pk").values())
            for label, model in [
                ("businesses", Business),
                ("plans", ClarivoPlan),
                ("subscriptions", BusinessSubscription),
            ]
        }
        facts = json.loads(json.dumps(facts, cls=DjangoJSONEncoder, sort_keys=True))
    return {
        "accounts": accounts,
        "contexts": contexts,
        "initial_facts": facts,
        "initial_facts_sha256": hashlib.sha256(
            json.dumps(facts, sort_keys=True).encode()
        ).hexdigest(),
    }


def canonical_facts(facts):
    """Normalize only migration-generated plan audit times for initial parity."""
    result = json.loads(json.dumps(facts))
    for plan in result["plans"]:
        plan.pop("created_at")
        plan.pop("updated_at")
    return result


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
    if "subscriptions_review" in original:
        raise RuntimeError("Subscription metadata already exists.")
    data = seed(state)
    # Existing migrations timestamp their plan rows at migration execution time.
    # Preserve the complete side-specific facts and compare configuration across
    # sides without those two non-semantic plan audit timestamps.
    write_json(
        Path(state[side]["directory"]) / "subscription-facts-initial.json", data["initial_facts"]
    )
    data["initial_facts"] = canonical_facts(data["initial_facts"])
    data["initial_facts_sha256"] = hashlib.sha256(
        json.dumps(data["initial_facts"], sort_keys=True).encode()
    ).hexdigest()
    original["accounts"].extend(data["accounts"])
    original["subscriptions_review"] = data
    original["inventory"] = inventory()
    original["sha256"] = hashlib.sha256(
        json.dumps(original["inventory"], sort_keys=True).encode()
    ).hexdigest()
    write_json(target, original)
    print("Subscription fixtures saved with complete initial facts and canonical parity metadata.")


if __name__ == "__main__":
    main()
