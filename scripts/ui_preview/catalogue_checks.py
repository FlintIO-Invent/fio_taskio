"""Catalogue review adapters confined to independently verified disposable resources."""

import argparse
import os
import subprocess
from pathlib import Path
from unittest import mock

from ui_preview.core import REPO, child_env, load_session, verify_database, verify_source

BACKEND = [
    "apps.crm.test_services_catalogue_ui",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_category_management_is_scoped_and_archives_instead_of_deleting",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_management_is_scoped_and_archives_instead_of_deleting",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_rejects_category_from_another_business",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_booking_fields_have_safe_defaults",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_booking_duration_must_be_positive_if_provided",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_booking_buffer_cannot_be_negative",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_create_can_create_category_inline",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_create_requires_existing_or_new_category_choice",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_price_display_and_input_follow_business_locale",
    "apps.crm.tests.CRMBusinessScopingTests.test_business_service_tax_defaults_apply_to_new_services_only",
    "apps.crm.tests.CRMBusinessScopingTests.test_admin_can_set_service_as_bookable_online",
    "apps.crm.tests.CRMBusinessScopingTests.test_service_management_roles_cannot_edit_bookable_service_settings",
    "apps.crm.tests.CRMBusinessScopingTests.test_accountant_cannot_open_service_management",
    "apps.businesses.test_capabilities",
    "apps.crm.test_combined_service_import",
    "apps.crm.tests.PublicBookingTests.test_public_booking_only_shows_active_bookable_current_business_services",
    "services_catalogue_browser_check.CatalogueFormBrowserChecks",
]


def verify_review(root, state):
    if state["route"] != "/crm/settings/services/":
        raise RuntimeError("This adapter requires a fresh invoice review session.")
    for side in ["before", "after"]:
        verify_source(state[side]["source"])
    verify_database(root, state, "after")


def backend(root, state, labels, baseline=False):
    from django.test.runner import DiscoverRunner
    from ui_preview.dashboard_checks import execute

    class CatalogueRunner(DiscoverRunner):
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

    os.environ["SERVICES_CATALOGUE_BEFORE"] = state["before"]["source"]
    os.environ["SERVICES_CATALOGUE_EVIDENCE"] = str(Path(state["after"]["directory"]) / "evidence")
    with mock.patch("django.test.utils.get_runner", return_value=CatalogueRunner):
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
        special = ["services_catalogue_browser_check.CatalogueFormBrowserChecks"]
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
                    "ui_preview.catalogue_checks",
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
            str(REPO / "scripts/services_catalogue_browser_check.py"),
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
