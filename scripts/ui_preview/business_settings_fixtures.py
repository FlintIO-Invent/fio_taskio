"""Synthetic team records only inside newly owned, verified setup resources."""

import hashlib
import json
import os
from pathlib import Path

ROUTE = "/businesses/settings/"


def verify_setup():
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "ui_preview.settings"
        or os.environ.get("MOTIONMATE_PREVIEW_PHASE") != "setup"
    ):
        raise RuntimeError("Settings fixtures require private setup settings and phase.")
    from ui_preview.core import load_session, verify_database, verify_source

    root, state = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
    side = os.environ["MOTIONMATE_PREVIEW_SIDE"]
    if state["route"] != ROUTE:
        raise RuntimeError("Settings fixture route differs.")
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    return root, state, side


def seed(state):
    from io import BytesIO

    from django.db import transaction
    from PIL import Image

    from apps.accounts.models import TaskIOUser
    from apps.businesses.models import (
        Business,
        BusinessInvoiceLogo,
        BusinessSubscription,
        BusinessUser,
        ClarivoPlan,
        UserOnboardingState,
    )

    accounts, contexts = [], {}
    with transaction.atomic():
        for scenario in ["populated", "empty", "long", "restricted", "locked", "eur"]:
            business = Business.objects.get(slug="preview-" + scenario)
            contexts[scenario] = {"business_id": business.pk}
        current = Business.objects.get(pk=contexts["populated"]["business_id"])
        current.email = "hello@harbour.preview.test"
        current.address_line_1 = "Front Street 12"
        current.city = "Philipsburg"
        current.business_type = "Property services"
        current.save()
        png = BytesIO()
        Image.new("RGBA", (180, 60), (57, 73, 219, 255)).save(png, format="PNG")
        BusinessInvoiceLogo.objects.create(business=current, png_data=png.getvalue())
        BusinessInvoiceLogo.objects.create(
            business_id=contexts["long"]["business_id"], png_data=b"synthetic unreadable logo"
        )
        plan = ClarivoPlan.objects.get(slug="logistics")
        if not plan.is_active:
            plan.is_active = True
            plan.save(update_fields=["is_active"])
        business = Business.objects.create(
            name="Harbour Logistics review",
            slug="settings-review-logistics",
            vertical="LOGISTICS",
            country="SX",
        )
        BusinessSubscription.objects.create(
            business=business,
            plan=plan,
            status="active",
            payment_provider="local",
            billing_interval="yearly",
        )
        user = TaskIOUser.objects.create_user(
            email="settings.logistics.owner@preview.test",
            password=state["password"],
            first_name="Logistics",
            last_name="Owner",
        )
        BusinessUser.objects.create(business=business, user=user, role="owner")
        UserOnboardingState.objects.create(
            business=business, user=user, completed_welcome=True, selected_journey="setup_business"
        )
        accounts.append(
            {
                "email": user.email,
                "role": "owner",
                "scenario": "settings-logistics",
                "vertical": "LOGISTICS",
                "business": business.name,
            }
        )
        contexts["logistics"] = {"business_id": business.pk}
        user = TaskIOUser.objects.create_user(
            email="settings.no-business@preview.test",
            password=state["password"],
            first_name="Personal",
            last_name="Account",
        )
        accounts.append(
            {
                "email": user.email,
                "role": "personal",
                "scenario": "no-business",
                "vertical": "SERVICE",
                "business": "No workspace",
            }
        )
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
    data = json.loads(target.read_text())
    if "settings_review" in data:
        raise RuntimeError("Settings fixture metadata already exists; refusing reseed.")
    review = seed(state)
    data["accounts"].extend(review["accounts"])
    from apps.businesses.models import Business, BusinessInvoiceLogo

    review["canonical"] = {
        "businesses": list(
            Business.objects.order_by("pk").values(
                "id",
                "name",
                "email",
                "currency",
                "country",
                "timezone",
                "default_locale",
                "invoice_prefix",
            )
        ),
        "logos": [
            {
                "business_id": logo.business_id,
                "sha256": hashlib.sha256(bytes(logo.png_data)).hexdigest(),
            }
            for logo in BusinessInvoiceLogo.objects.order_by("business_id")
        ],
    }
    review["sha256"] = hashlib.sha256(
        json.dumps(review["canonical"], sort_keys=True).encode()
    ).hexdigest()
    data["settings_review"] = review
    data["inventory"] = inventory()
    data["sha256"] = hashlib.sha256(
        json.dumps(data["inventory"], sort_keys=True).encode()
    ).hexdigest()
    write_json(target, data)
    print("Settings fixtures saved with canonical parity metadata.")


if __name__ == "__main__":
    main()
