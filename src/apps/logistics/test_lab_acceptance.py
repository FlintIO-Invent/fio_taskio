"""Non-production acceptance evidence. Missing/manual evidence never becomes a pass."""

import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client as HTTPClient
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .location_access import locations_for
from .models import Parcel, Shipment
from .parcel_services import parcels_for_business
from .shipment_services import shipments_for_business
from .test_lab import ACCOUNTS, DOMAIN, FIXTURE, authorize, lab_for, login_url
from .test_lab_dataset import context, dataset_objects, inspect_dataset, reset_plan
from .test_lab_scenarios import EXPECTED_COUNTS, VERSION

SCHEMA = "motionmate-logistics-acceptance-v2"
# These are evidence requirements, not a list of automatically successful checks.
LOCAL_GATES = (
    "migrations",
    "foundation",
    "dataset",
    "location_querysets",
    "login_http",
    "automated_suite",
    "service_regression",
    "workflow",
    "security",
    "fixture_reset",
    "browser",
    "pwa",
    "reviewed_release",
    "promotion_approval",
)
STAGING_GATES = LOCAL_GATES + (
    "postgresql_concurrency",
    "dedicated_database",
    "https",
    "stripe_test",
    "tracking_cache_proxy",
    "deployed_browser",
)
PILOT_GATES = STAGING_GATES + (
    "physical_android",
    "physical_iphone",
    "physical_qr_code128",
    "label_print_4x6",
)
EVIDENCE_KINDS = {
    "automated_suite": "automated",
    "service_regression": "automated",
    "workflow": "automated",
    "security": "automated",
    "fixture_reset": "automated",
    "browser": "browser-emulation",
    "pwa": "browser-emulation",
    "postgresql_concurrency": "postgresql",
    "dedicated_database": "operator",
    "https": "operator",
    "stripe_test": "provider",
    "tracking_cache_proxy": "operator",
    "deployed_browser": "operator",
    "physical_android": "physical-device",
    "physical_iphone": "physical-device",
    "physical_qr_code128": "physical-device",
    "label_print_4x6": "physical-print",
    "promotion_approval": "approval",
}


def release_identity():
    """Heroku identifies the deployed commit; local identity includes all tracked/new code."""
    sha = os.environ.get("HEROKU_SLUG_COMMIT") or os.environ.get("SOURCE_VERSION", "")
    root = Path(settings.BASE_DIR).parent
    dirty = None
    tree_digest = None
    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        paths = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout.split(b"\0")
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, check=True
        ).stdout
        dirty = bool(status)
        digest = hashlib.sha256()
        for raw in sorted(set(paths)):
            if not raw:
                continue
            # Acceptance prose/results do not alter executable or deployment inputs.
            if raw.startswith(b"docs/") or raw.endswith(b".md"):
                continue
            path = root / os.fsdecode(raw)
            digest.update(raw + b"\0")
            digest.update(path.read_bytes() if path.is_file() else b"<deleted>")
        tree_digest = digest.hexdigest()
        if not sha:
            sha = git_sha
    except (OSError, subprocess.CalledProcessError):
        pass
    return {
        "commit_sha": sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None,
        "release": os.environ.get("HEROKU_RELEASE_VERSION")
        or ("local-working-tree" if settings.MOTIONMATE_ENVIRONMENT == "local" else None),
        "dirty": dirty,
        "tree_digest": tree_digest,
    }


def binding(report):
    return {
        key: report[key]
        for key in (
            "schema",
            "environment",
            "database_id",
            "business_id",
            "foundation_version",
            "dataset_version",
            "commit_sha",
            "tree_digest",
            "configuration_digest",
        )
    }


def apply_evidence(report, evidence):
    if not isinstance(evidence, dict) or evidence.get("binding") != binding(report):
        raise CommandError(
            "Evidence must match this environment, database, lab, versions and code/configuration."
        )
    timestamp = parse_datetime(str(evidence.get("recorded_at", "")))
    now = timezone.now()
    if (
        not timestamp
        or timezone.is_naive(timestamp)
        or not now - timedelta(days=7) <= timestamp <= now
    ):
        raise CommandError("Evidence requires an aware timestamp within the past seven days.")
    checks = evidence.get("checks")
    if not isinstance(checks, dict) or set(checks) - EVIDENCE_KINDS.keys():
        raise CommandError(
            "Evidence contains unsupported checks; inspection/login results cannot be overridden."
        )
    for name, entry in checks.items():
        if (
            not isinstance(entry, dict)
            or entry.get("kind") != EVIDENCE_KINDS[name]
            or entry.get("status") not in {"PASS", "FAIL", "PENDING"}
            or not isinstance(entry.get("reference"), str)
            or not entry["reference"].strip()
            or len(entry["reference"]) > 240
            or not isinstance(entry.get("operator"), str)
            or not entry["operator"].strip()
        ):
            raise CommandError(
                f"Invalid evidence for {name}; supply status, required kind, operator and reference."
            )
        if (
            entry.get("kind") in {"automated", "postgresql", "browser-emulation"}
            and entry.get("status") == "PASS"
        ):
            # A skipped suite, no executed tests, or a failed process is not a pass.
            if (
                entry.get("exit_code") != 0
                or type(entry.get("tests")) is not int
                or entry["tests"] <= 0
                or entry.get("failures") != 0
                or entry.get("errors") != 0
                or entry.get("skipped") != 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("log_sha256", "")))
            ):
                raise CommandError(
                    f"{name} requires complete, zero-skip results and a raw-log digest."
                )
        report["checks"][name] = {
            key: entry[key]
            for key in (
                "status",
                "kind",
                "operator",
                "reference",
                "exit_code",
                "tests",
                "failures",
                "errors",
                "skipped",
                "log_sha256",
            )
            if key in entry
        }
    # Report evidence is operator attestation; it never grants database/application permissions.


def finalize(report, target):
    permitted = {"local": {"development"}, "development": {"staging"}, "staging": {"pilot"}}
    if target not in permitted[report["environment"]]:
        raise CommandError("Promotion must follow Local -> Development -> Staging -> Pilot.")
    gates = (
        LOCAL_GATES
        if target == "development"
        else STAGING_GATES if target == "staging" else PILOT_GATES
    )
    report["promotion_target"] = target
    report["blockers"] = [name for name in gates if report["checks"][name]["status"] != "PASS"]
    # Any reported failure, including an optional check, prevents promotion.
    report["blockers"] += [
        name
        for name, value in report["checks"].items()
        if value["status"] == "FAIL" and name not in report["blockers"]
    ]
    report["verdict"] = "BLOCKED" if report["blockers"] else "READY FOR NEXT ENVIRONMENT"
    report["promotion_approval"] = report["checks"]["promotion_approval"]["status"]
    if report["environment"] == "staging":
        report["pilot_verdict"] = (
            "NOT READY FOR SUPERVISED PILOT" if report["blockers"] else "READY FOR SUPERVISED PILOT"
        )
    return report


def build_report(*, environment, business_id, target, evidence=None):
    database_id = authorize(environment)
    if business_id <= 0 or business_id == 133:
        raise CommandError("Only the exact owned lab business is permitted; 133 is excluded.")
    business, seed = lab_for(environment, business_id)
    if business is None:
        raise CommandError("Provision the owned Block 06A lab first.")
    report = {
        "schema": SCHEMA,
        "environment": environment,
        "application": os.environ.get("HEROKU_APP_NAME") or "local-isolated-test-lab",
        "database_vendor": connection.vendor,
        "database_id": database_id,
        "database_name": Path(connection.settings_dict["NAME"]).name,
        **release_identity(),
        "business_id": business.pk,
        "foundation_version": FIXTURE,
        "dataset_version": VERSION,
        "recorded_at": timezone.now().isoformat(),
        "login_url": login_url(),
        "checks": {
            name: {"status": "PENDING", "kind": kind}
            for name, kind in {**dict.fromkeys(PILOT_GATES, "inspection"), **EVIDENCE_KINDS}.items()
        },
        "accounts": [
            {
                "email": f"{name}@{DOMAIN}",
                "role": role,
                "locations": list(codes),
                "business_wide": role in {"owner", "admin"},
                "login": "PENDING",
            }
            for name, role, codes in ACCOUNTS
        ],
        "manager_limitation": "Existing ADMIN: business-wide Logistics, billing and team management; no narrower management permission.",
        "verification_limits": [
            "HTTP client checks run inside Django, not across HTTPS/proxy.",
            "Browser emulation does not verify a physical Android/iPhone or printer.",
            "Operator evidence is an attestation, not provider or device execution.",
        ],
    }
    configuration = {
        "environment": environment,
        "application": report["application"],
        "database_id": database_id,
        "debug": settings.DEBUG,
        "local_billing_bypass": settings.LOGISTICS_LOCAL_BILLING_BYPASS,
        "lab_enabled": settings.LOGISTICS_TEST_LAB_ENABLED,
        "public_base_url": getattr(settings, "MOTIONMATE_PUBLIC_BASE_URL", ""),
        "cache_backend": settings.CACHES["default"]["BACKEND"],
        "modes": business.logistics_profile.transportation_modes,
        "tracking_shared_cache": settings.LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE,
        "tracking_ip_mode": settings.LOGISTICS_TRACKING_CLIENT_IP_MODE,
        "staging_app": settings.LOGISTICS_TEST_LAB_STAGING_APP,
        "stripe_test_configuration": bool(
            settings.STRIPE_ENABLED
            and settings.STRIPE_SECRET_KEY.startswith("sk_test_")
            and settings.STRIPE_PUBLISHABLE_KEY.startswith("pk_test_")
        ),
    }
    report["configuration"] = configuration
    report["configuration_digest"] = hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode()
    ).hexdigest()
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    report["migrations"] = {
        "unapplied": [f"{migration.app_label}.{migration.name}" for migration, _ in plan]
    }
    report["checks"]["migrations"] = {"status": "FAIL" if plan else "PASS", "kind": "inspection"}
    report["checks"]["reviewed_release"] = {
        "status": (
            "PASS"
            if report["commit_sha"] and report["dirty"] is False
            else (
                "PASS"
                if environment != "local" and report["commit_sha"] and report["dirty"] is None
                else "FAIL"
            )
        ),
        "kind": "inspection",
    }
    if environment != "local" and not report["release"]:
        report["checks"]["reviewed_release"]["status"] = "FAIL"
    try:
        users, sites, _ = context(business, seed, environment=environment)
        report["checks"]["foundation"] = {"status": "PASS", "kind": "inspection"}
        report["subscription"] = {
            "status": business.subscription.effective_access_status,
            "local_bypass": bool(
                environment == "local" and settings.LOGISTICS_LOCAL_BILLING_BYPASS
            ),
        }
        dataset = inspect_dataset(environment=environment, business_id=business_id)
        report["dataset"] = {key: value for key, value in dataset.items() if key != "records"}
        objects = dataset_objects(business, seed, verify=True)
        reset_plan(business, seed)
        report["checks"]["dataset"] = {
            "status": "PASS" if dataset.get("counts") == EXPECTED_COUNTS else "FAIL",
            "kind": "inspection",
        }
        rows = []
        for name, role, codes in ACCOUNTS:
            actor = users[name]
            visible = set(locations_for(business, actor).values_list("code", flat=True))
            expected = set(sites) if role in {"owner", "admin"} else set(codes)
            parcel_ids = set(
                parcels_for_business(business=business, actor=actor).values_list("pk", flat=True)
            )
            shipment_ids = set(
                shipments_for_business(business=business, actor=actor).values_list("pk", flat=True)
            )

            def expected_ids(model, role=role, expected=expected):
                result = set()
                for obj in objects[model]:
                    route = {
                        getattr(obj.origin_location, "code", None),
                        getattr(obj.destination_location, "code", None),
                    }
                    route |= set(obj.handling_sites.values_list("location__code", flat=True))
                    if model == Parcel and obj.shipment_id:
                        shipment = obj.shipment
                        route |= {
                            getattr(shipment.origin_location, "code", None),
                            getattr(shipment.destination_location, "code", None),
                        }
                        route |= set(
                            shipment.handling_sites.values_list("location__code", flat=True)
                        )
                    if role in {"owner", "admin"} or route & expected:
                        result.add(obj.pk)
                return result

            # Additional unowned records may exist after operator workflows; compare the fixture subset only.
            passed = (
                visible == expected
                and (parcel_ids & {p.pk for p in objects[Parcel]}) == expected_ids(Parcel)
                and (shipment_ids & {s.pk for s in objects[Shipment]}) == expected_ids(Shipment)
            )
            rows.append(
                {
                    "email": actor.email,
                    "status": "PASS" if passed else "FAIL",
                    "visible_parcels": len(parcel_ids),
                    "visible_shipments": len(shipment_ids),
                }
            )
        report["location_results"] = rows
        report["checks"]["location_querysets"] = {
            "status": "PASS" if all(r["status"] == "PASS" for r in rows) else "FAIL",
            "kind": "inspection",
        }
    except (CommandError, PermissionDenied) as exc:
        report["checks"]["foundation"] = {
            "status": "FAIL",
            "kind": "inspection",
            "reason": str(exc),
        }
    if evidence is not None:
        apply_evidence(report, evidence)
    return finalize(report, target)


def read_credentials(*, credential_file, credential_identity, report):
    """Decrypt only into RAM. Never put a password in exceptions, output or artifacts."""
    authorize(report["environment"])
    files = [credential_file] if isinstance(credential_file, (str, Path)) else credential_file
    for name in (*files, credential_identity):
        path = Path(name)
        try:
            info = path.lstat()
            parent = path.parent.stat()
        except OSError as exc:
            raise CommandError("Credential file/identity is unavailable.") from exc
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or parent.st_uid != os.getuid()
            or parent.st_mode & 0o077
        ):
            raise CommandError(
                "Credential files must be operator-owned 0600 files inside a private 0700 directory."
            )
    expected = {account["email"] for account in report["accounts"]}
    combined = {}
    for path in files:
        try:
            process = subprocess.run(
                ["age", "--decrypt", "-i", str(credential_identity), str(path)],
                capture_output=True,
                check=True,
                timeout=30,
            )
            payload = json.loads(process.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise CommandError("Secured credential decryption failed.") from None
        accounts = payload.get("accounts", []) if isinstance(payload, dict) else []
        if (
            not isinstance(payload, dict)
            or payload.get("fixture") != FIXTURE
            or payload.get("environment") != report["environment"]
            or payload.get("business_id") != report["business_id"]
            or not isinstance(accounts, list)
            or not accounts
            or any(
                not isinstance(a, dict)
                or not isinstance(a.get("password"), str)
                or a.get("email") not in expected
                or a.get("email") in combined
                for a in accounts
            )
            or len({a["email"] for a in accounts}) != len(accounts)
        ):
            raise CommandError(
                "Credential handoff does not match this environment and nine-account lab."
            )
        combined.update({account["email"]: account["password"] for account in accounts})
    if set(combined) != expected:
        raise CommandError(
            "Provide the owner bootstrap and eight-account handoffs, or one full nine-account handoff."
        )
    return combined


def verify_logins(report, credentials):
    """Normal CSRF-protected HTTP authentication; deliberately no force_login/bypass."""
    authorize(report["environment"])
    origin = urlsplit(report["login_url"])
    for account in report["accounts"]:
        client = HTTPClient(
            enforce_csrf_checks=True,
            SERVER_NAME=origin.hostname,
            SERVER_PORT=str(origin.port or (443 if origin.scheme == "https" else 80)),
        )
        secure = origin.scheme == "https"
        try:
            client.get(reverse("business_login"), secure=secure)
            token = client.cookies.get(settings.CSRF_COOKIE_NAME)
            if token is None:
                account["login"] = "FAIL"
                continue
            response = client.post(
                reverse("business_login"),
                {
                    "email": account["email"],
                    "password": credentials[account["email"]],
                    "csrfmiddlewaretoken": token.value,
                },
                secure=secure,
                HTTP_REFERER=report["login_url"],
            )
            passed = (
                response.status_code == 302
                and "_auth_user_id" in client.session
                and client.session.get(CURRENT_BUSINESS_SESSION_KEY) == report["business_id"]
            )
            account["login"] = "PASS" if passed else "FAIL"
            # Logout destroys the created session; normal login updates last_login.
        finally:
            client.get(reverse("logout"), secure=secure)
    report["checks"]["login_http"] = {
        "status": "PASS" if all(a["login"] == "PASS" for a in report["accounts"]) else "FAIL",
        "kind": "http-authentication",
    }
