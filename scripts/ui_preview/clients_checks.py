"""Clients review checks through independently verified disposable resources."""

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from ui_preview.core import REPO, child_env, load_session, verify_database, verify_source

BACKEND = [
    "apps.crm.test_services_clients_ui",
    "apps.crm.tests.CRMBusinessScopingTests",
    "apps.crm.test_quick_client",
    "apps.crm.test_client_invoices",
    "apps.crm.test_client_importing",
    "apps.crm.test_client_preview",
    "apps.crm.test_client_execution",
    "apps.crm.test_logistics_client_capacity.LogisticsClientCapacityTests",
    "apps.logistics.test_financial_access.LogisticsFinancialAccessTests.test_client_invoice_history_keeps_existing_location_financial_scope",
    "apps.billings.test_presentation",
    "apps.appointments.test_services_bookings_ui",
    "services_clients_browser_check.LogisticsClientsBrowserChecks",
    "draft_client_browser_check.DraftClientBrowserChecks",
]


def prepare(session_path):
    root, state = load_session(session_path)
    for side in ("before", "after"):
        verify_source(state[side]["source"])
    verify_database(root, state, "after")
    from ui_preview.appointments_checks import prepare as guarded_prepare

    env = guarded_prepare(root, state)
    return root, state, env


def execute_backend(root, state, labels, baseline=False):
    from django.test.runner import DiscoverRunner
    from ui_preview.dashboard_checks import execute as guarded_execute

    class ClientsRunner(DiscoverRunner):
        def teardown_databases(self, old_config, **kwargs):
            import gc

            from django.db import connections

            connections.close_all()
            gc.collect()
            return super().teardown_databases(old_config, **kwargs)

        def run_tests(self, _labels, **kwargs):
            if baseline:
                from django.conf import settings
                from django.test.utils import override_settings

                import apps.crm

                name = "apps.crm._clients_original_tests"
                original = Path(state["before"]["source"]) / "src"
                spec = importlib.util.spec_from_file_location(name, original / "apps/crm/tests.py")
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                apps.crm._clients_original_tests = module
                spec.loader.exec_module(module)
                templates = [
                    {
                        **settings.TEMPLATES[0],
                        "DIRS": [str(original / "templates"), *settings.TEMPLATES[0]["DIRS"]],
                    }
                ]
                with override_settings(TEMPLATES=templates):
                    return super().run_tests(
                        [
                            name
                            + ".CRMBusinessScopingTests.test_business_service_import_page_displays_examples_in_browser"
                        ],
                        **kwargs,
                    )
            if "draft_client_browser_check.DraftClientBrowserChecks" in labels:
                import time
                from concurrent.futures import ThreadPoolExecutor
                from importlib import import_module

                from django.db import connections

                module = import_module("draft_client_browser_check")
                evidence = (
                    Path(state["after"]["directory"])
                    / "evidence"
                    / f"clients-existing-draft-{time.time_ns()}"
                )
                evidence.mkdir(parents=True, exist_ok=False)

                def evidence_path(value):
                    return (
                        evidence
                        if str(value).startswith("/tmp/taskio-draft-client-browser")
                        else Path(value)
                    )

                class ClosingExecutor(ThreadPoolExecutor):
                    def submit(self, fn, /, *args, **kw):
                        def closed():
                            try:
                                return fn(*args, **kw)
                            finally:
                                connections.close_all()

                        return super().submit(closed)

                with (
                    mock.patch.object(module, "Path", evidence_path),
                    mock.patch.object(module, "ThreadPoolExecutor", ClosingExecutor),
                    mock.patch.object(module.DraftClientBrowserChecks, "port", 8768),
                ):
                    return super().run_tests(labels, **kwargs)
            return super().run_tests(labels, **kwargs)

    with mock.patch("django.test.utils.get_runner", return_value=ClientsRunner):
        guarded_execute(root, state, "server")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument(
        "--suite",
        choices=["backend", "baseline", "capture-before", "capture-after", "browser"],
        default="backend",
    )
    parser.add_argument("--labels", nargs="*", choices=BACKEND)
    parser.add_argument("--execute-tests", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root, state = load_session(args.session)
    if args.execute_tests:
        execute_backend(root, state, args.labels or BACKEND, baseline=args.suite == "baseline")
        return
    if args.suite in {"backend", "baseline"}:
        root, state, env = prepare(root)
        subprocess.run(
            [
                state["python"],
                "-B",
                "-m",
                "ui_preview.clients_checks",
                "--session",
                str(root),
                "--execute-tests",
                "--suite",
                args.suite,
                *(["--labels", *args.labels] if args.labels else []),
            ],
            cwd=state["after"]["source"],
            env=env,
            check=True,
        )
        return
    side = "before" if args.suite == "capture-before" else "after"
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    env = child_env(root, state, side, "serve")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO / "scripts"), str(Path(state[side]["source"]) / "src")]
    )
    if os.environ.get("PWA_CHROMIUM"):
        env["PWA_CHROMIUM"] = os.environ["PWA_CHROMIUM"]
    subprocess.run(
        [
            state["python"],
            "-B",
            str(REPO / "scripts/services_clients_browser_check.py"),
            "--session",
            str(root),
            "--side",
            side,
            "--mode",
            "journey" if args.suite == "browser" else "capture",
        ],
        cwd=state[side]["source"],
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
