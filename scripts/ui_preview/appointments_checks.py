"""Run appointment suites through the existing verified disposable test boundary."""

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
import types
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from ui_preview.core import REPO, child_env, load_session, verify_database, verify_source

BACKEND = [
    "apps.appointments.tests",
    "apps.appointments.test_workspace",
    "apps.appointments.test_services_bookings_ui",
    "apps.crm.test_services_public_booking_ui",
    "apps.crm.tests.PublicBookingTests",
    "apps.crm.tests.CRMBusinessScopingTests",
    "apps.crm.test_services_dashboard_ui",
    "apps.billings.tests.BillingBusinessScopingTests.test_invoice_create_from_appointment_prefills_context_on_get",
    "apps.billings.tests.BillingBusinessScopingTests.test_invoice_create_from_appointment_sets_business_client_and_relation",
    "apps.billings.tests.BillingBusinessScopingTests.test_invoice_create_from_appointment_blocks_other_business_appointment",
    "apps.billings.tests.BillingBusinessScopingTests.test_invoice_create_from_appointment_uses_service_snapshot_values",
    "apps.billings.tests.BillingBusinessScopingTests.test_invoice_create_from_appointment_redirects_when_linked_invoice_exists",
    "apps.billings.tests.BillingBusinessScopingTests.test_viewer_cannot_open_invoice_create_from_appointment_page",
    "apps.billings.tests.BillingBusinessScopingTests.test_accountant_can_create_invoice_from_appointment",
    "apps.billings.tests.BillingBusinessScopingTests.test_invoice_rejects_linked_appointment_from_other_business",
]
BROWSER = [
    "unified_appointments_browser_check",
    "draft_client_browser_check",
    "invoice_terminology_browser_check.ServicesTerminologyBrowserChecks",
    "invoice_terminology_browser_check.LogisticsTerminologyBrowserChecks",
]


def prepare(root, state):
    for name in ("before", "after"):
        verify_source(state[name]["source"])
    verify_database(root, state, "after")
    side = state["after"]
    marker = Path(side["directory"]) / "DISPOSABLE"
    if marker.exists() and marker.read_text().strip() != side["system_identifier"]:
        raise RuntimeError("Disposable test marker differs; nothing is replaced.")
    marker.write_text(side["system_identifier"] + "\n")
    env = child_env(root, state, "after", "test")
    env.update(
        DJANGO_SETTINGS_MODULE="taskio.services_test_settings",
        SERVICES_TEST_PG_PORT=str(side["port"]),
        SERVICES_TEST_PG_USER=state["db_user"],
        SERVICES_DASHBOARD_UI_ROOT=side["directory"],
        PYTHONPATH=os.pathsep.join([str(REPO / "scripts"), str(Path(side["source"]) / "src")]),
    )
    if os.environ.get("PWA_CHROMIUM"):
        env["PWA_CHROMIUM"] = os.environ["PWA_CHROMIUM"]
    return env


def execute(root, state, suite, browser_label=None):
    # Reuse all existing pre-Django checks, live connection identity and network guards.
    from django.test.runner import DiscoverRunner
    from ui_preview.dashboard_checks import execute as guarded_execute

    class BookingRunner(DiscoverRunner):
        def teardown_databases(self, old_config, **kwargs):
            import gc

            from django.db import connections

            connections.close_all()
            gc.collect()
            return super().teardown_databases(old_config, **kwargs)

        def run_tests(self, _labels, **kwargs):
            if suite == "browser":
                # Support scripts.* imports without adding the ordinary repo/src to PYTHONPATH.
                namespace = types.ModuleType("scripts")
                namespace.__path__ = [str(REPO / "scripts")]
                sys.modules.setdefault("scripts", namespace)
                evidence = Path(
                    tempfile.mkdtemp(prefix="bookings-regression-", dir=state["after"]["directory"])
                )
                with ExitStack() as stack:
                    for name in (
                        "unified_appointments_browser_check",
                        "draft_client_browser_check",
                    ):
                        module = importlib.import_module(name)

                        def evidence_path(value, folder=evidence / name):
                            if str(value).startswith("/tmp/taskio-"):
                                folder.mkdir(exist_ok=True)
                                return folder
                            return Path(value)

                        stack.enter_context(mock.patch.object(module, "Path", evidence_path))
                    module = importlib.import_module("invoice_terminology_browser_check")
                    stack.enter_context(
                        mock.patch.object(module, "EVIDENCE", evidence / "invoices")
                    )
                    return super().run_tests([browser_label], **kwargs)
            if suite in {"backend", "focused"}:
                labels = [
                    label
                    for label in BACKEND
                    if suite != "focused" or label != "apps.crm.tests.CRMBusinessScopingTests"
                ]
                return super().run_tests(labels, **kwargs)
            from django.conf import settings
            from django.test.utils import override_settings

            import apps.crm

            original = Path(state["before"]["source"]) / "src"
            name = "apps.crm._bookings_baseline"
            spec = importlib.util.spec_from_file_location(name, original / "apps/crm/tests.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            apps.crm._bookings_baseline = module
            spec.loader.exec_module(module)
            templates = [
                {
                    **settings.TEMPLATES[0],
                    "DIRS": [str(original / "templates"), *settings.TEMPLATES[0]["DIRS"]],
                }
            ]
            labels = [
                "apps.appointments.tests",
                "apps.appointments.test_workspace",
                name + ".PublicBookingTests",
                name + ".CRMBusinessScopingTests",
                "apps.crm.test_services_dashboard_ui",
            ]
            with override_settings(TEMPLATES=templates):
                return super().run_tests(labels, **kwargs)

    with mock.patch("django.test.utils.get_runner", return_value=BookingRunner):
        guarded_execute(root, state, "server")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument(
        "--suite", choices=["backend", "browser", "baseline", "focused"], default="backend"
    )
    parser.add_argument("--execute-tests", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--browser-label", choices=BROWSER, help=argparse.SUPPRESS)
    args = parser.parse_args()
    root, state = load_session(args.session)
    if args.execute_tests:
        execute(root, state, args.suite, args.browser_label)
        return
    labels = BROWSER if args.suite == "browser" else [None]
    for label in labels:
        # Each legacy live-server class gets a fresh test DB/process, preserving serialized fixtures.
        env = prepare(root, state)
        command = [
            state["python"],
            "-B",
            "-m",
            "ui_preview.appointments_checks",
            "--session",
            str(root),
            "--suite",
            args.suite,
            "--execute-tests",
        ]
        if label:
            command += ["--browser-label", label]
        subprocess.run(command, cwd=state["after"]["source"], env=env, check=True)


if __name__ == "__main__":
    main()
