"""Synthetic data_import setup restricted to a fresh owned preview session."""

import hashlib
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROUTE = "/crm/staff/data-import/"


def verify_setup():
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "ui_preview.settings"
        or os.environ.get("MOTIONMATE_PREVIEW_PHASE") != "setup"
    ):
        raise RuntimeError("Data Import fixtures require private setup settings and phase.")
    from ui_preview.core import load_session, verify_database, verify_source

    root, state = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
    side = os.environ["MOTIONMATE_PREVIEW_SIDE"]
    if state["route"] != ROUTE:
        raise RuntimeError("Data Import fixture route differs.")
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    return root, state, side


def seed(state):
    from uuid import UUID

    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.db import transaction

    from apps.accounts.models import TaskIOUser
    from apps.businesses.models import (
        Business,
        BusinessSubscription,
        BusinessUser,
        ClarivoPlan,
        UserOnboardingState,
    )
    from apps.crm.importing.client_execution import execute_client_import
    from apps.crm.importing.client_preview import persist_client_preview
    from apps.crm.importing.clients import CLIENT_IMPORT_SCHEMA, validate_client_import
    from apps.crm.importing.jobs import create_import_job
    from apps.crm.importing.lead_execution import execute_lead_import
    from apps.crm.importing.lead_preview import persist_lead_preview
    from apps.crm.importing.leads import LEAD_IMPORT_SCHEMA, validate_lead_import
    from apps.crm.importing.service_execution import execute_service_import
    from apps.crm.importing.service_preview import persist_service_preview
    from apps.crm.importing.services import SERVICE_IMPORT_SCHEMA, validate_service_import
    from apps.crm.models import BusinessService, ImportJob, ServiceCategory

    if Business.objects.filter(slug__startswith="preview-data-import-").exists():
        raise RuntimeError("Data Import fixtures already exist; no reset or reseed.")
    clock = datetime.fromisoformat(state["clock"])
    accounts, contexts = [], {}
    recipes = {
        "leads": (
            validate_lead_import,
            persist_lead_preview,
            execute_lead_import,
            LEAD_IMPORT_SCHEMA,
        ),
        "services": (
            validate_service_import,
            persist_service_preview,
            execute_service_import,
            SERVICE_IMPORT_SCHEMA,
        ),
        "clients": (
            validate_client_import,
            persist_client_preview,
            execute_client_import,
            CLIENT_IMPORT_SCHEMA,
        ),
    }
    with transaction.atomic(), patch("django.utils.timezone.now", return_value=clock):
        for scenario in ["populated", "empty", "long", "readonly", "logistics"]:
            logistics = scenario == "logistics"
            plan = ClarivoPlan.objects.get(slug="logistics" if logistics else "preview-services")
            if logistics and not plan.is_active:
                plan.is_active = True
                plan.save(update_fields=["is_active"])
            business = Business.objects.create(
                name="Harbour " + ("Logistics" if logistics else "Services") + " · " + scenario,
                slug="preview-data-import-" + scenario,
                vertical="LOGISTICS" if logistics else "SERVICE",
                currency="USD",
                country="Sint Maarten",
                default_locale="en-SX",
                tax_rate=Decimal("6.00"),
            )
            sub = BusinessSubscription.objects.create(
                business=business,
                plan=plan,
                status="active",
                payment_provider="local",
                billing_interval="yearly" if logistics else "monthly",
            )
            users = {}
            for role in (
                ["owner", "admin", "staff", "accountant", "viewer", "validation"]
                if scenario in {"populated", "logistics"}
                else ["owner"]
            ):
                email = (
                    "imports."
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
                users[role] = user
                accounts.append(
                    {
                        "email": email,
                        "role": "owner" if role == "validation" else role,
                        "scenario": scenario,
                        "vertical": business.vertical,
                        "business": business.name,
                    }
                )
            category = ServiceCategory.objects.create(business=business, name="Property care")
            service = BusinessService.objects.create(
                business=business,
                category=category,
                name="Existing maintenance",
                external_code="SVC-1",
                unit_price=Decimal("125.00"),
                tax_rate=Decimal("6.00"),
            )
            jobs = {}
            index = 0
            if scenario != "empty":
                for kind in (
                    ["clients", "services"] if logistics else ["clients", "leads", "services"]
                ):
                    for case in ["ready", "blocked", "done", "expired"]:
                        index += 1
                        if kind == "services":
                            csv = (
                                "name,unit_price,category,external_code\nUpdated maintenance,160.50,Property care,SVC-1\nNew intake service,75.00,New import category,IMPORT-NEW\n"
                                if case == "ready"
                                else "name,unit_price\nInvalid amount,-10\n"
                                if case == "blocked"
                                else f"name,unit_price,external_code\n{case.title()} price list,95.00,{case.upper()}-IMPORT\n"
                            )
                        else:
                            csv = "first_name,email\n" + (
                                "Invalid,not-an-email\n"
                                if case == "blocked"
                                else f"{case.title()} intake,{kind}-{case}@{scenario}.preview.test\n"
                            )
                        validate, persist, execute, schema = recipes[kind]
                        filename = (
                            (
                                "Harbour-community-services-transfer-with-extended-record-notes-"
                                if scenario == "long"
                                else ""
                            )
                            + kind
                            + "-"
                            + case
                            + ".csv"
                        )
                        validation = validate(
                            SimpleUploadedFile(filename, csv.encode(), content_type="text/csv"),
                            business=business,
                        )
                        job = create_import_job(
                            business=business,
                            actor=users["owner"],
                            import_type=kind,
                            schema_version=schema.version,
                            parsed_file=validation.parsed_file,
                        )
                        # Set deterministic synthetic UUID before the server preview is bound.
                        fixed = UUID(int=business.pk * 100 + index)
                        ImportJob.objects.filter(pk=job.pk).update(id=fixed)
                        job.pk = fixed
                        persist(validation, job=job, business=business, actor=users["owner"])
                        job.refresh_from_db()
                        if case == "done":
                            result = execute(job_id=job.pk, business=business, actor=users["owner"])
                            if not result.completed:
                                raise RuntimeError("Synthetic " + kind + " completion failed.")
                        elif case == "expired":
                            job.transition_to(ImportJob.Status.EXPIRED)
                        jobs[kind + "-" + case] = str(job.pk)
            if scenario == "readonly":
                sub.plan = ClarivoPlan.objects.get(slug="starter")
                sub.status = "past_due"
                sub.payment_provider = "stripe"
                sub.billing_currency = "usd"
                sub.billing_interval = "monthly"
                sub.provider_customer_id = "cus_importfixture"
                sub.provider_subscription_id = "sub_importfixture"
                sub.provider_price_id = "price_importfixture"
                sub.past_due_since = clock - timedelta(days=8)
                sub.grace_period_ends_at = clock - timedelta(days=1)
                sub.save()
            contexts[scenario] = {
                "business_id": business.pk,
                "service_id": service.pk,
                "category_id": category.pk,
                "jobs": jobs,
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
    if "data_import_review" in original:
        raise RuntimeError("Data Import metadata already exists.")
    data = seed(state)
    original["accounts"].extend(data["accounts"])
    original["data_import_review"] = data
    original["inventory"] = inventory()
    original["sha256"] = hashlib.sha256(
        json.dumps(original["inventory"], sort_keys=True).encode()
    ).hexdigest()
    write_json(target, original)
    print("Data Import fixtures saved with canonical parity metadata.")


if __name__ == "__main__":
    main()
