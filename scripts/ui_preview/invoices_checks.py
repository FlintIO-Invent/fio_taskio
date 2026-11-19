"""Invoice review adapters confined to independently verified disposable resources."""

import argparse
import os
import subprocess
from pathlib import Path
from unittest import mock

from ui_preview.core import REPO, child_env, load_session, verify_database, verify_source

BACKEND = [
    "apps.billings.test_services_invoices_ui",
    "apps.billings.test_services_invoice_documents",
    "apps.billings.tests",
    "apps.billings.test_presentation",
    "apps.billings.test_pdf_layout",
    "apps.billings.test_invoice_logos",
    "apps.billings.test_payments",
    "apps.billings.test_invoice_payment_filter",
    "apps.billings.test_invoice_refund_filter",
    "apps.billings.test_payment_concurrency",
    "apps.logistics.test_financial_access",
    "apps.logistics.test_financial_coverage",
    "apps.logistics.test_cancellation_settlement",
    "apps.crm.test_services_clients_ui",
    "apps.appointments.test_services_bookings_ui",
    "services_invoices_browser_check.InvoiceBrowserChecks",
]


def verify_review(root, state):
    if state["route"] != "/billings/":
        raise RuntimeError("This adapter requires a fresh invoice review session.")
    for side in ["before", "after"]:
        verify_source(state[side]["source"])
    verify_database(root, state, "after")


def backend(root, state, labels, baseline=False):
    from django.test.runner import DiscoverRunner
    from ui_preview.dashboard_checks import execute

    class InvoiceRunner(DiscoverRunner):
        def run_tests(self, _labels, **kwargs):
            if baseline:
                from django.conf import settings
                from django.test.utils import override_settings

                templates = [
                    {
                        **settings.TEMPLATES[0],
                        "DIRS": [
                            str(Path(state["before"]["source"]) / "src/templates"),
                            *settings.TEMPLATES[0]["DIRS"],
                        ],
                    }
                ]
                with override_settings(TEMPLATES=templates):
                    return super().run_tests(labels, **kwargs)
            return super().run_tests(labels, **kwargs)

    os.environ["SERVICES_INVOICES_BEFORE"] = state["before"]["source"]
    os.environ["SERVICES_INVOICES_EVIDENCE"] = str(Path(state["after"]["directory"]) / "evidence")
    with mock.patch("django.test.utils.get_runner", return_value=InvoiceRunner):
        execute(root, state, "server")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument(
        "--suite", choices=["backend", "capture-before", "capture-after"], default="backend"
    )
    parser.add_argument("--labels", nargs="*", choices=BACKEND)
    parser.add_argument("--execute-tests", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    root, state = load_session(args.session)
    verify_review(root, state)
    if args.execute_tests:
        backend(root, state, args.labels or BACKEND, args.baseline)
        return
    if args.suite == "backend":
        from ui_preview.appointments_checks import prepare

        # Transaction suites with serialized rollback and browser workers need their
        # own fresh test processes/databases. Never mix their fixture restoration.
        special = [
            "apps.billings.test_payment_concurrency",
            "apps.logistics.test_cancellation_settlement",
            "services_invoices_browser_check.InvoiceBrowserChecks",
        ]
        requested = args.labels or BACKEND
        ordinary = [label for label in requested if label not in special]
        batches = ([ordinary] if ordinary else []) + [
            [label] for label in special if label in requested
        ]
        for labels in batches:
            env = prepare(root, state)
            subprocess.run(
                [
                    state["python"],
                    "-B",
                    "-m",
                    "ui_preview.invoices_checks",
                    "--session",
                    str(root),
                    "--execute-tests",
                    "--labels",
                    *labels,
                    *(["--baseline"] if args.baseline else []),
                ],
                cwd=state["after"]["source"],
                env=env,
                check=True,
            )
        return
    side = "before" if args.suite == "capture-before" else "after"
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
            str(REPO / "scripts/services_invoices_browser_check.py"),
            "--session",
            str(root),
            "--side",
            side,
        ],
        cwd=state[side]["source"],
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
