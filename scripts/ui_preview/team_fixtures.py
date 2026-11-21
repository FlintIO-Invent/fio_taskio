"""Synthetic team records only inside newly owned, verified setup resources."""

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROUTE = "/businesses/team/"


def verify_setup():
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "ui_preview.settings"
        or os.environ.get("MOTIONMATE_PREVIEW_PHASE") != "setup"
    ):
        raise RuntimeError("Team fixtures require private setup settings and phase.")
    from ui_preview.core import load_session, verify_database, verify_source

    root, state = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
    side = os.environ["MOTIONMATE_PREVIEW_SIDE"]
    if state["route"] != ROUTE:
        raise RuntimeError("Team fixture route differs.")
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    return root, state, side


def seed(state):
    from django.db import transaction

    from apps.accounts.models import TaskIOUser
    from apps.businesses.models import (
        Business,
        BusinessInvitation,
        BusinessSubscription,
        BusinessUser,
        ClarivoPlan,
        UserOnboardingState,
    )

    clock = datetime.fromisoformat(state["clock"])
    accounts, contexts = [], {}
    with transaction.atomic(), patch("django.utils.timezone.now", return_value=clock):
        plan = ClarivoPlan.objects.create(
            name="Team review",
            slug="team-review",
            max_users=50,
            allow_invoicing=True,
            allow_appointments=True,
            allow_public_booking=True,
        )
        for scenario in ["populated", "empty", "long", "readonly", "starter", "logistics"]:
            logistics = scenario == "logistics"
            selected = (
                ClarivoPlan.objects.get(slug="logistics" if logistics else "starter")
                if logistics or scenario == "starter"
                else plan
            )
            if logistics and not selected.is_active:
                selected.is_active = True
                selected.save(update_fields=["is_active"])
            business = Business.objects.create(
                name=(
                    "Harbour Community Services"
                    if scenario != "long"
                    else "Harbour Association for Community Services and Property Administration"
                ),
                slug="team-review-" + scenario,
                vertical="LOGISTICS" if logistics else "SERVICE",
                country="Sint Maarten",
                timezone="America/Lower_Princes",
            )
            sub = BusinessSubscription.objects.create(
                business=business,
                plan=selected,
                status="active",
                payment_provider="local",
                billing_interval="yearly" if logistics else "monthly",
            )
            memberships = {}
            for role in (
                ["owner", "admin", "staff", "accountant", "viewer"]
                if scenario == "populated"
                else ["owner"]
            ):
                email = (
                    "team."
                    + ("" if scenario == "populated" else scenario + ".")
                    + role
                    + "@preview.test"
                )
                user = TaskIOUser.objects.create_user(
                    email=email,
                    password=state["password"],
                    first_name="Alexandria" if scenario == "long" else role.title(),
                    last_name="Community Coordination" if scenario == "long" else "Rivera",
                )
                member = BusinessUser.objects.create(business=business, user=user, role=role)
                memberships[role] = member.pk
                if role in {"owner", "admin"}:
                    UserOnboardingState.objects.create(
                        user=user,
                        business=business,
                        completed_welcome=True,
                        selected_journey="setup_business",
                    )
                accounts.append(
                    dict(
                        email=email,
                        role=role,
                        scenario=scenario,
                        vertical=business.vertical,
                        business=business.name,
                    )
                )
            owner = business.memberships.get(role="owner").user
            if scenario not in {"empty", "starter"}:
                user = TaskIOUser.objects.create_user(
                    email="team.inactive." + scenario + "@preview.test",
                    password=state["password"],
                    first_name="Jordan",
                    last_name="Inactive",
                )
                BusinessUser.objects.create(
                    user=user, business=business, role="staff", is_active=False
                )
                for n in range(2):
                    BusinessInvitation.objects.create(
                        business=business,
                        email=(
                            "a.very.long.employee.address.for.community.services"
                            if scenario == "long"
                            else "new.teammate"
                        )
                        + str(n)
                        + "@"
                        + scenario
                        + ".preview.test",
                        role="staff",
                        token="synthetic-team-" + scenario + "-" + str(n),
                        invited_by=owner,
                        expires_at=clock + timedelta(days=7 if n == 0 else -1),
                    )
            if scenario == "readonly":
                sub.status = "past_due"
                sub.payment_provider = "stripe"
                sub.provider_customer_id = "cus_team_synthetic"
                sub.provider_subscription_id = "sub_team_synthetic"
                sub.billing_interval = "monthly"
                sub.past_due_since = clock - timedelta(days=10)
                sub.grace_period_ends_at = clock - timedelta(days=1)
                sub.save()
            contexts[scenario] = dict(business_id=business.pk, memberships=memberships)
    return dict(accounts=accounts, contexts=contexts)


def main():
    root, state, side = verify_setup()
    import django

    django.setup()
    from ui_preview.guard import install

    install()
    from ui_preview.core import write_json
    from ui_preview.fixtures import inventory

    from apps.businesses.models import BusinessInvitation, BusinessUser

    target = Path(state[side]["directory"]) / "fixtures.json"
    data = json.loads(target.read_text())
    if "team_review" in data:
        raise RuntimeError("Team fixture metadata already exists; refusing reseed.")
    review = seed(state)
    data["accounts"].extend(review["accounts"])
    review["canonical"] = dict(
        memberships=list(
            BusinessUser.objects.order_by("pk").values(
                "id", "business_id", "user_id", "role", "is_active"
            )
        ),
        invitations=list(
            BusinessInvitation.objects.order_by("pk").values(
                "business_id", "email", "role", "token", "status"
            )
        ),
    )
    review["sha256"] = hashlib.sha256(
        json.dumps(review["canonical"], sort_keys=True).encode()
    ).hexdigest()
    data["team_review"] = review
    data["inventory"] = inventory()
    data["sha256"] = hashlib.sha256(
        json.dumps(data["inventory"], sort_keys=True).encode()
    ).hexdigest()
    write_json(target, data)
    print("Team fixtures saved with canonical parity metadata.")


if __name__ == "__main__":
    main()
