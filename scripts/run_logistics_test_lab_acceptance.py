"""Run isolated suites and preserve machine-readable results plus private raw logs.

Example: ENV=local DEBUG=True LOGISTICS_LOCAL_BILLING_BYPASS=False \
  python scripts/run_logistics_test_lab_acceptance.py --suite logistics --output-dir /private/qa
DATABASE_URL must name an empty, disposable test base database, never a customer DB.
Django creates its own test database. No deployment database is copied.
"""

import argparse
import hashlib
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def labels_for(suite):
    if suite == "service":
        return [
            f"apps.{name}" for name in ("accounts", "businesses", "crm", "billings", "appointments")
        ]
    if suite == "postgresql":
        labels = [
            f"apps.logistics.{path.stem}"
            for path in sorted((ROOT / "src/apps/logistics").glob("test*concurrency.py"))
        ]
        # Some existing race classes live beside their ordinary workflow tests.
        labels.extend(
            f"apps.logistics.{name}"
            for name in (
                "test_enrollment.EnrollmentConcurrencyTests",
                "test_transport_details.TransportDetailsConcurrencyTests",
                "test_transportation.TransportationConcurrencyTests",
                "test_checkout_approval.LogisticsCheckoutApprovalConcurrencyTests",
                "test_shipment_write_safety.ShipmentWriteSafetyConcurrencyTests",
            )
        )
        return labels
    if suite == "pwa":
        return ["taskio.test_pwa", "scripts.pwa_browser_check"]
    if suite == "browser":
        return [
            f"scripts.{name}"
            for name in (
                "logistics_test_lab_browser_check",
                "logistics_scan_browser_check",
                "logistics_camera_browser_check",
                "logistics_shipping_label_browser_check",
                "logistics_location_browser_check",
                "logistics_location_access_browser_check",
                "logistics_location_operations_browser_check",
            )
        ]
    return [
        f"apps.logistics.{path.stem}"
        for path in sorted((ROOT / "src/apps/logistics").glob("test*.py"))
        if "concurrency" not in path.stem and path.stem != "test_tracking_shared_cache"
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite", required=True, choices=("logistics", "service", "postgresql", "browser", "pwa")
    )
    parser.add_argument(
        "--output-dir", required=True, help="New private directory; existing paths are refused."
    )
    args = parser.parse_args()
    if os.environ.get("ENV") != "local":
        parser.error(
            "Run isolated automated suites with ENV=local; deployment smoke uses accept_logistics_test_lab."
        )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskio.settings")
    import django

    django.setup()
    from django.conf import settings
    from django.db import connection
    from django.test.runner import DiscoverRunner, iter_test_cases

    from apps.logistics.test_lab_acceptance import release_identity

    if settings.MOTIONMATE_ENVIRONMENT != "local":
        parser.error("Runtime settings must also identify Local.")
    if args.suite == "postgresql" and connection.vendor != "postgresql":
        parser.error("PostgreSQL concurrency evidence requires actual PostgreSQL.")
    # Speed only inside Django's isolated test runner; never change a lab's password hashes.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    directory = Path(args.output_dir)
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    log_path = directory / "tests.log"
    fd = os.open(log_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    results = {}

    class EvidenceRunner(DiscoverRunner):
        def build_suite(self, *args, **kwargs):
            suite = super().build_suite(*args, **kwargs)
            if args_suite in {"browser", "postgresql"}:
                # Every transactional class must restore data migrations consistently.
                # Mixing serialized/nonserialized classes loses plans and duplicates
                # post_migrate content types when a later class restores its snapshot.
                for test in iter_test_cases(suite):
                    type(test).serialized_rollback = True
            return suite

        def run_suite(self, suite, **kwargs):
            results["planned_tests"] = suite.countTestCases()
            result = super().run_suite(suite, **kwargs)
            results.update(
                tests=result.testsRun,
                failures=len(result.failures),
                errors=len(result.errors),
                skipped=len(result.skipped),
                interrupted=bool(result.shouldStop),
            )
            return result

    args_suite = args.suite
    labels = labels_for(args.suite)
    release_before = release_identity()
    with os.fdopen(fd, "w") as log, redirect_stdout(log), redirect_stderr(log):
        try:
            exit_code = EvidenceRunner(verbosity=1, interactive=False).run_tests(labels)
        except Exception:
            import traceback

            traceback.print_exc()
            exit_code = 1
    release_after = release_identity()
    results.update(
        suite=args.suite,
        labels=labels,
        database_vendor=connection.vendor,
        exit_code=int(bool(exit_code)),
        log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest(),
        **release_before,
        code_changed_during_run=any(
            release_before[key] != release_after[key] for key in ("commit_sha", "tree_digest")
        ),
    )
    results["status"] = (
        "PASS"
        if results.get("tests", 0) > 0
        and exit_code == 0
        and results.get("skipped") == 0
        and not results["code_changed_during_run"]
        and not results.get("interrupted", True)
        and results.get("tests") == results.get("planned_tests")
        else "FAIL"
    )
    with os.fdopen(
        os.open(directory / "results.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
    ) as artifact:
        json.dump(results, artifact, indent=2, sort_keys=True)
        artifact.write("\n")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if results["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
