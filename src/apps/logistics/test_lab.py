"""Owned, portable test workspace; no provider calls or entitlement fabrication."""

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.urls import reverse
from django.views.decorators.debug import sensitive_variables

from apps.businesses.billing_policy import logistics_local_billing_bypass_enabled
from apps.businesses.business_data_purge import plan_business_purge, purge_business
from apps.businesses.business_sessions import invalidate_business_sessions
from apps.businesses.models import (
    Business,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    DemoSeedRecord,
    DemoSeedRun,
)
from apps.businesses.utils import business_limit_reached, get_business_usage_count

from .location_access_services import (
    enable_location_operations,
    review_location_access,
    select_work_location,
    set_location_assignment,
)
from .location_services import save_location
from .models import (
    LogisticsLocation,
    LogisticsLocationAssignment,
    LogisticsProfile,
    LogisticsTestLabAudit,
)

FIXTURE = "motionmate-logistics-test-lab-v2"
SLUG = "motionmate-global-cargo-test-lab"
NAME = "Motionmate Global Cargo"
DOMAIN = "globalcargo.motionmate.test"
# ADMIN is the only existing management grant. It includes billing/team access.
ACCOUNTS = (
    ("owner", BusinessUser.Role.OWNER, ()),
    ("admin", BusinessUser.Role.ADMIN, ()),
    ("manager", BusinessUser.Role.ADMIN, ()),
    ("miami", BusinessUser.Role.STAFF, ("MIA-HUB",)),
    ("sxm-port", BusinessUser.Role.STAFF, ("SXM-PORT",)),
    ("sxm-warehouse", BusinessUser.Role.STAFF, ("SXM-DC",)),
    ("dominica", BusinessUser.Role.STAFF, ("DM-HUB",)),
    ("regional", BusinessUser.Role.STAFF, ("MIA-HUB", "SXM-PORT")),
    ("unassigned", BusinessUser.Role.STAFF, ()),
)
LOCATIONS = (
    dict(
        code="MIA-HUB", name="Miami Cargo Hub", location_type="HUB", country_code="US", city="Miami"
    ),
    dict(
        code="SXM-PORT",
        name="Sint Maarten Port",
        location_type="PORT",
        country_code="SX",
        reference_code="SXPHI",
        city="Philipsburg",
    ),
    dict(
        code="SXM-DC",
        name="SXM Distribution Center",
        location_type="WAREHOUSE",
        country_code="SX",
        city="Philipsburg",
    ),
    dict(
        code="DM-HUB",
        name="Dominica Cargo Hub",
        location_type="HUB",
        country_code="DM",
        city="Roseau",
    ),
)
OWNED_MODELS = (
    Business,
    get_user_model(),
    BusinessUser,
    BusinessSubscription,
    LogisticsProfile,
    LogisticsLocation,
    LogisticsLocationAssignment,
)


def database_identity():
    """Fingerprint the connected target, without exposing connection credentials."""
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(
                "SELECT current_database(), inet_server_addr()::text, inet_server_port()"
            )
            identity = list(cursor.fetchone())
        elif connection.vendor == "sqlite":
            cursor.execute("PRAGMA database_list")
            identity = [row[2] for row in cursor.fetchall() if row[1] == "main"]
        else:
            raise CommandError("Test Lab supports SQLite locally and PostgreSQL only.")
    return hashlib.sha256(json.dumps([connection.vendor, *identity]).encode()).hexdigest()


def authorize(environment, *, execute=False, confirm_database=None, confirm_app=None):
    runtime = getattr(settings, "MOTIONMATE_ENVIRONMENT", "")
    process_environment = os.environ.get("ENV", runtime).strip().lower()
    # No CLI flag overrides runtime identity or this production rejection.
    if runtime not in {"local", "development", "staging"} or process_environment not in {
        "local",
        "development",
        "staging",
    }:
        raise CommandError("Test Lab is forbidden in production or unknown environments.")
    if environment != runtime or process_environment != runtime:
        raise CommandError("--environment must match the runtime ENV.")
    app_name = os.environ.get("HEROKU_APP_NAME", "")
    if environment == "local":
        if os.environ.get("DYNO") or app_name or not settings.DEBUG:
            raise CommandError("Local Test Lab requires DEBUG and a local process.")
    else:
        expected = (
            "mm-development-app"
            if environment == "development"
            else settings.LOGISTICS_TEST_LAB_STAGING_APP
        )
        if (
            not expected
            or expected == "mm-development-app"
            and environment == "staging"
            or re.search(r"prod|production", expected, re.I)
        ):
            raise CommandError("Configure a dedicated non-production Staging app.")
        if app_name != expected or connection.vendor != "postgresql":
            raise CommandError(
                "Shared Test Lab requires the authorized app and separate PostgreSQL database."
            )
        if execute and confirm_app != expected:
            raise CommandError("--confirm-app must match the authorized Heroku app.")
    identity = database_identity()
    if execute and (
        not settings.LOGISTICS_TEST_LAB_ENABLED
        or settings.LOGISTICS_TEST_LAB_DATABASE_ID != identity
        or confirm_database != identity
    ):
        raise CommandError(
            "Execute requires Test Lab opt-in, configured database fingerprint and matching --confirm-database."
        )
    return identity


def lab_for(environment, business_id=None, *, lock=False):
    query = Business.objects.filter(slug=SLUG)
    if lock:
        query = query.select_for_update()
    business = query.first()
    if business_id is not None and (business is None or business.pk != business_id):
        raise CommandError("Exact business ID does not identify this owned lab.")
    if business is None:
        return None, None
    seed = DemoSeedRun.objects.filter(business=business).first()
    if (
        not seed
        or seed.planned_counts.get("fixture") != FIXTURE
        or seed.planned_counts.get("environment") != environment
        or seed.planned_counts.get("database_id") != database_identity()
    ):
        raise CommandError(
            "Reserved business exists without matching lab ownership. Refusing changes."
        )
    if business.name != NAME or business.vertical != Business.Vertical.LOGISTICS:
        raise CommandError("Lab business identity changed; manual review required.")
    return business, seed


def own(seed, obj):
    DemoSeedRecord.objects.create(seed_run=seed, model_label=obj._meta.label, object_pk=str(obj.pk))
    return obj


def owned_objects(business, seed, *, lock=False, check_dependents=True):
    """Refuse changed ownership and any untracked incoming relation, even SET_NULL."""
    models = {model._meta.label: model for model in OWNED_MODELS}
    owned = {model: set() for model in OWNED_MODELS}
    dataset = {}
    if seed.planned_counts.get("dataset"):
        from .test_lab_dataset import dataset_objects

        dataset = dataset_objects(business, seed, lock=lock)
        models.update({model._meta.label: model for model in dataset})
        owned.update({model: {obj.pk for obj in items} for model, items in dataset.items()})
    for record in seed.owned_records.all():
        model = models.get(record.model_label)
        if model is None or not record.object_pk.isdecimal():
            raise CommandError("Unsupported lab ownership metadata; manual review required.")
        owned[model].add(int(record.object_pk))
    if owned[Business] != {business.pk}:
        raise CommandError("Lab business ownership is missing or changed.")
    objects = {}
    for model, pks in owned.items():
        if model in dataset:
            objects[model] = dataset[model]
            continue
        query = model.objects.filter(pk__in=pks).order_by("pk")
        if lock:
            query = query.select_for_update()
        items = list(query)
        if len(items) != len(pks):
            raise CommandError("Owned lab records are missing; manual review required.")
        for item in items:
            if model not in (Business, get_user_model()) and item.business_id != business.pk:
                raise CommandError("Owned record moved to another tenant.")
            if model == LogisticsLocationAssignment and (
                item.membership_id not in owned[BusinessUser]
                or item.location_id not in owned[LogisticsLocation]
            ):
                raise CommandError("Assignment references an unowned membership/location.")
        objects[model] = items
    if any(member.user_id not in owned[get_user_model()] for member in objects[BusinessUser]):
        raise CommandError("Owned membership references an unowned user.")
    if {member.user_id for member in objects[BusinessUser]} != owned[get_user_model()]:
        raise CommandError("Lab membership and account ownership do not match.")
    emails = {f"{name}@{DOMAIN}" for name, _, _ in ACCOUNTS}
    for user in objects[get_user_model()]:
        if (
            user.email not in emails
            or user.is_staff
            or user.is_superuser
            or user.groups.exists()
            or user.user_permissions.exists()
        ):
            raise CommandError("Lab user identity or global privileges changed.")
    for model in apps.get_models():
        if model in (DemoSeedRun, DemoSeedRecord):
            continue
        if not check_dependents and model not in OWNED_MODELS:
            continue
        conditions = Q()
        for field in model._meta.fields:
            if field.is_relation and field.related_model in owned:
                conditions |= Q(**{field.attname + "__in": owned[field.related_model]})
        if (
            conditions
            and model.objects.filter(conditions).exclude(pk__in=owned.get(model, set())).exists()
        ):
            raise CommandError(
                f"Unowned {model._meta.label} references the lab; manual review required."
            )
    for model, pks in owned.items():
        if (
            DemoSeedRecord.objects.exclude(seed_run=seed)
            .filter(model_label=model._meta.label, object_pk__in=[str(pk) for pk in pks])
            .exists()
        ):
            raise CommandError("Another seed claims lab records.")
    return objects


def seat_plan(subscription):
    if (
        subscription.plan.family != ClarivoPlan.Family.LOGISTICS
        or subscription.plan.slug != "logistics"
    ):
        raise CommandError("The configured Logistics offering is required.")
    if subscription.plan.max_users is not None and subscription.plan.max_users < len(ACCOUNTS):
        raise CommandError(
            "The normal Logistics plan must allow at least nine seats. No seat override is available."
        )


def require_entitlement(subscription, environment):
    seat_plan(subscription)
    approved_test = (
        subscription.provisioning_source == BusinessSubscription.ProvisioningSource.FREE_TEST
        and subscription.payment_provider == BusinessSubscription.PaymentProvider.LOCAL
        and subscription.status == BusinessSubscription.Status.ACTIVE
        and LogisticsTestLabAudit.objects.filter(
            fixture_version=FIXTURE,
            environment=environment,
            business_id_snapshot=subscription.business_id,
            action="test-entitlement",
        ).exists()
    )
    if environment != "local" and not approved_test:
        if (
            subscription.payment_provider != BusinessSubscription.PaymentProvider.STRIPE
            or not settings.STRIPE_ENABLED
            or not settings.STRIPE_SECRET_KEY.startswith("sk_test_")
            or not settings.STRIPE_PUBLISHABLE_KEY.startswith("pk_test_")
        ):
            raise CommandError("Shared provisioning requires configured Stripe TEST billing.")
        if (
            subscription.status != BusinessSubscription.Status.ACTIVE
            or not subscription.provider_subscription_id
            or not subscription.provider_customer_id
        ):
            raise CommandError(
                "Complete legitimate Stripe TEST checkout/activation or separately approved test entitlement before provisioning eight additional accounts."
            )
    if not subscription.can_use_module("parcels") or not subscription.can_use_module("shipments"):
        raise CommandError(
            "Normal Logistics entitlement is required (local may use the existing guarded bypass)."
        )


@sensitive_variables()
def create_account(business, seed, account, credentials):
    name, role, _ = account
    email = f"{name}@{DOMAIN}"
    if get_user_model().objects.filter(email__iexact=email).exists():
        raise CommandError(
            "A reserved test identity already exists; refusing to reuse or overwrite it."
        )
    if role != BusinessUser.Role.OWNER and business_limit_reached(
        business, "users", include_pending_invitations=True
    ):
        raise CommandError("Normal seat allowance reached.")
    password = secrets.token_urlsafe(32)
    user = get_user_model()(email=email, first_name=name.replace("-", " ").title(), is_active=True)
    validate_password(password, user)
    user.set_password(password)
    user.full_clean()
    user.save()
    own(seed, user)
    member = own(seed, BusinessUser.objects.create(business=business, user=user, role=role))
    credentials.append({"email": email, "password": password})
    return member


def credential_target(path, recipient):
    if (
        not path
        or not recipient
        or not re.fullmatch(r"age1[0-9a-z]{58}", recipient)
        or not shutil.which("age")
    ):
        raise CommandError(
            "Credential writes require age, an age public recipient and --credential-file."
        )
    target = Path(path).absolute()
    # Ciphertext only, exclusive creation, private existing parent, no symlinks.
    parent = target.parent
    if (
        any(part.is_symlink() for part in (target, *target.parents))
        or not parent.is_dir()
        or parent.stat().st_uid != os.getuid()
        or stat.S_IMODE(parent.stat().st_mode) & 0o077
    ):
        raise CommandError(
            "Credential target requires an existing operator-owned 0700 directory without symlinks."
        )
    if target.exists():
        raise CommandError("Credential artifact already exists; select a new path.")
    return target


@sensitive_variables()
def encrypted_handoff(path, recipient, payload):
    try:
        encrypted = subprocess.run(
            ["age", "--armor", "--recipient", recipient],
            input=json.dumps(payload).encode(),
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    except (OSError, subprocess.SubprocessError):
        raise CommandError("Encrypted handoff failed; database transaction rolled back.") from None


def login_url():
    base = settings.MOTIONMATE_PUBLIC_BASE_URL.rstrip("/")
    if settings.MOTIONMATE_ENVIRONMENT == "local":
        parsed = urlsplit(base)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.scheme not in {
            "http",
            "https",
        }:
            base = "http://127.0.0.1:8000"
    return base + reverse("business_login")


def inspect_lab(business, seed):
    result = {
        "fixture": FIXTURE,
        "business_id": business.pk if business else None,
        "name": NAME,
        "login_url": login_url(),
        "manager_limitation": "manager uses existing ADMIN: business-wide Logistics, billing and team management; no narrower manager permission exists.",
    }
    if seed:
        result["metadata"] = seed.planned_counts
        result["subscription_access"] = business.subscription.effective_access_status
        result["seat_limit"] = business.subscription.plan.max_users
        result["locations"] = list(
            business.logistics_locations.values(
                "code", "name", "country_code", "reference_code", "location_type"
            )
        )
        result["accounts"] = [
            {
                "email": member.user.email,
                "role": member.role,
                "active": member.is_active and member.user.is_active,
                "locations": list(
                    member.logistics_location_assignments.values(
                        "location__code", "is_current", "can_operate", "is_work_context"
                    )
                ),
                "business_wide": member.role in (BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN),
            }
            for member in business.memberships.select_related("user")
        ]
    else:
        result["accounts"] = [
            {"email": f"{name}@{DOMAIN}", "role": role, "locations": sites}
            for name, role, sites in ACCOUNTS
        ]
        result["locations"] = LOCATIONS
    return result


def entitlement_plan(business, approval_reference):
    if business is None:
        raise CommandError("Initialize an owned lab before approving test entitlement.")
    configured = settings.LOGISTICS_TEST_LAB_ENTITLEMENT_APPROVAL
    if (
        not configured
        or not approval_reference
        or configured != approval_reference
        or len(configured) > 120
    ):
        raise CommandError(
            "A separately configured approval reference must match --test-entitlement-approval."
        )
    subscription = business.subscription
    seat_plan(subscription)
    if not subscription.plan.is_active:
        raise CommandError(
            "The normal Logistics offering must be active; no plan activation override is available."
        )
    if (
        subscription.status != BusinessSubscription.Status.PENDING_CHECKOUT
        or any(
            getattr(subscription, name)
            for name in (
                "provider_customer_id",
                "provider_subscription_id",
                "provider_checkout_session_id",
                "provider_price_id",
            )
        )
        or subscription.logistics_approval_review_required
    ):
        raise CommandError(
            "Only a pending lab without Stripe references or approval holds can receive test entitlement."
        )
    return {
        "business_id": business.pk,
        "plan": subscription.plan.slug,
        "seat_limit": subscription.plan.max_users,
        "approval_reference": configured,
    }


def audit_operation(business_id, environment, action, reason, approval=""):
    return LogisticsTestLabAudit.objects.create(
        fixture_version=FIXTURE,
        environment=environment,
        business_id_snapshot=business_id,
        action=action,
        reason_reference=reason,
        approval_reference=approval,
    )


@sensitive_variables()
def execute_lab(
    *,
    environment,
    action,
    credential_file=None,
    recipient=None,
    business_id=None,
    reason_reference=None,
    identity=None,
    approval_reference=None,
):
    authorize(
        environment,
        execute=True,
        confirm_database=identity,
        confirm_app=os.environ.get("HEROKU_APP_NAME"),
    )
    target = (
        credential_target(credential_file, recipient)
        if action not in ("cleanup", "test-entitlement")
        else None
    )
    artifact_written = False
    try:
        with transaction.atomic():
            business, seed = lab_for(environment, business_id, lock=True)
            credentials = []
            if business:
                objects = owned_objects(
                    business, seed, lock=True, check_dependents=action != "rotate"
                )
            if action == "test-entitlement":
                result = entitlement_plan(business, approval_reference)
                subscription = BusinessSubscription.objects.select_for_update().get(
                    business=business
                )
                subscription.status = BusinessSubscription.Status.ACTIVE
                subscription.payment_provider = BusinessSubscription.PaymentProvider.LOCAL
                subscription.provisioning_source = BusinessSubscription.ProvisioningSource.FREE_TEST
                subscription.save()
                audit_operation(
                    business.pk, environment, action, reason_reference, approval_reference
                )
                return result
            if action == "cleanup":
                cleanup_plan(business, seed)
                # Deactivate only after ownership and existing financial gates pass.
                business.is_active = False
                business.save(update_fields=["is_active", "updated_at"])
                purge_business(
                    business_id=business.pk,
                    reason_reference=reason_reference,
                    delete_eligible_users=True,
                )
                audit_operation(business_id, environment, action, reason_reference)
                return {"cleaned_business_id": business_id}
            if action == "rotate":
                for user in objects[get_user_model()]:
                    password = secrets.token_urlsafe(32)
                    validate_password(password, user)
                    user.set_password(password)
                    user.save(update_fields=["password"])
                    credentials.append({"email": user.email, "password": password})
                invalidate_business_sessions(business.pk)
                seed.planned_counts["rotations"] = seed.planned_counts.get("rotations", 0) + 1
                seed.planned_counts["last_rotation_reason"] = reason_reference
            else:
                if business and (
                    action == "initialize" or seed.planned_counts.get("phase") == "ready"
                ):
                    raise CommandError(
                        "Lab already exists. Inspect it or use guarded cleanup before rebuilding."
                    )
                if business is None:
                    if any(
                        get_user_model().objects.filter(email__iexact=f"{a[0]}@{DOMAIN}").exists()
                        for a in ACCOUNTS
                    ):
                        raise CommandError(
                            "Reserved account identities exist; refusing to overwrite users."
                        )
                    plan = ClarivoPlan.objects.select_for_update().get(slug="logistics")
                    prospective = BusinessSubscription(plan=plan)
                    seat_plan(prospective)
                    if action == "provision" and not logistics_local_billing_bypass_enabled():
                        raise CommandError(
                            "Initialize owner first, then activate legitimate entitlement before full provisioning."
                        )
                    business = Business.objects.create(
                        name=NAME,
                        slug=SLUG,
                        vertical=Business.Vertical.LOGISTICS,
                        business_type="Fictional Logistics Test Lab",
                        country="Sint Maarten",
                        timezone="America/Lower_Princes",
                    )
                    seed = DemoSeedRun.objects.create(
                        business=business,
                        planned_counts={
                            "fixture": FIXTURE,
                            "environment": environment,
                            "database_id": identity,
                            "phase": "initialized",
                            "reason_reference": reason_reference,
                        },
                    )
                    own(seed, business)
                    subscription = own(
                        seed,
                        BusinessSubscription.objects.create(
                            business=business,
                            plan=plan,
                            status=BusinessSubscription.Status.PENDING_CHECKOUT,
                            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
                            billing_interval="yearly",
                            billing_currency="usd",
                        ),
                    )
                    owner = create_account(business, seed, ACCOUNTS[0], credentials)
                    own(
                        seed,
                        LogisticsProfile.objects.create(
                            business=business,
                            operating_areas=["TRANSPORTATION"],
                            transportation_modes=["SEA", "AIR", "ROAD"],
                        ),
                    )
                else:
                    subscription = (
                        BusinessSubscription.objects.select_for_update()
                        .select_related("plan", "business")
                        .get(business=business)
                    )
                    owner = business.memberships.get(role=BusinessUser.Role.OWNER)
                if action == "provision":
                    require_entitlement(subscription, environment)
                    if (
                        get_business_usage_count(
                            business, "users", include_pending_invitations=True
                        )
                        != 1
                    ):
                        raise CommandError("Initialized lab must have exactly one owner seat.")
                    sites = {
                        fields["code"]: own(
                            seed, save_location(business=business, actor=owner.user, **fields)
                        )
                        for fields in LOCATIONS
                    }
                    for account in ACCOUNTS[1:]:
                        member = create_account(business, seed, account, credentials)
                        for code in account[2]:
                            own(
                                seed,
                                set_location_assignment(
                                    business=business,
                                    actor=owner.user,
                                    membership=member,
                                    location=sites[code],
                                    can_operate=True,
                                ),
                            )
                    review_location_access(business=business, actor=owner.user)
                    # Administrator work context supports strict facility operations.
                    for member in business.memberships.filter(
                        role__in=("owner", "admin")
                    ).select_related("user"):
                        select_work_location(
                            business=business, actor=member.user, location=sites["MIA-HUB"]
                        )
                        own(seed, member.logistics_location_assignments.get(is_current=True))
                    enable_location_operations(business=business, actor=owner.user)
                    seed.planned_counts["phase"] = "ready"
            seed.save(update_fields=["planned_counts", "updated_at"])
            result = inspect_lab(business, seed)
            audit_operation(business.pk, environment, action, reason_reference)
            encrypted_handoff(
                target,
                recipient,
                {
                    "fixture": FIXTURE,
                    "environment": environment,
                    "business_id": business.pk,
                    "login_url": login_url(),
                    "accounts": credentials,
                },
            )
            artifact_written = True
        return result
    except BaseException:
        if artifact_written:
            target.unlink(missing_ok=True)
        raise


def cleanup_plan(business, seed):
    if business is None:
        raise CommandError("No owned lab exists.")
    owned_objects(business, seed)
    plan = plan_business_purge(business.pk, delete_eligible_users=True)
    blockers = set(plan.blocking_error_codes) - {"business_active"}
    if blockers or any(not decision.delete for decision in plan.user_decisions):
        raise CommandError(
            "Existing purge safeguards block lab cleanup: "
            + ", ".join(sorted(blockers or {"ineligible_users"}))
        )
    return {
        "business_id": business.pk,
        "owned_counts": {
            model._meta.label: len(items) for model, items in owned_objects(business, seed).items()
        },
        "sessions": plan.session_summary.sessions_to_invalidate,
    }
