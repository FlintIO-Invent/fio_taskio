"""DataImport review adapters confined to independently verified disposable resources."""

import argparse
import os
import subprocess
from pathlib import Path
from unittest import mock

from ui_preview.core import REPO, child_env, load_session, verify_database, verify_source

BACKEND = [
    "apps.crm.test_services_data_import_ui",
    "apps.crm.test_importing",
    "apps.crm.test_client_importing",
    "apps.crm.test_client_preview",
    "apps.crm.test_client_execution",
    "apps.crm.test_lead_importing",
    "apps.crm.test_lead_execution",
    "apps.crm.test_service_importing",
    "apps.crm.test_service_execution",
    "apps.crm.test_combined_service_import",
    "apps.crm.test_import_history.ImportHistoryViewTests",
    "apps.businesses.test_logistics_usage_limits.LogisticsQuotaClientImportTests",
    "apps.businesses.test_logistics_usage_limits.LogisticsQuotaServiceImportTests",
    "apps.crm.test_import_ux.ImportUXTests.test_template_downloads_use_current_schema_and_fictional_examples",
    "apps.crm.test_import_ux.ImportUXTests.test_client_preview_uses_accessible_states_and_confirmation_counts",
    "apps.crm.test_import_ux.ImportUXTests.test_missing_client_values_are_ready_to_confirm",
    "apps.crm.test_import_ux.ImportUXTests.test_missing_trailing_cells_are_treated_as_blank",
    "apps.crm.test_import_ux.ImportUXTests.test_invalid_client_status_names_the_field",
    "apps.crm.test_import_ux.ImportUXTests.test_wrong_csv_type_explains_the_matching_import",
    "apps.crm.test_import_ux.ImportUXTests.test_partial_contact_csvs_preview_confirm_and_replay_without_blank_duplicates",
    "apps.crm.test_import_ux.ImportUXTests.test_partial_new_service_csv_imports_inactive_and_replays_safely",
    "apps.crm.test_import_ux.ImportUXTests.test_partial_service_update_preserves_omitted_values_and_blank_name_price",
    "apps.crm.test_import_ux.ImportUXTests.test_every_downloaded_csv_template_can_preview_confirm_and_replay",
    "apps.crm.test_import_ux.ImportUXTests.test_lead_preview_uses_accessible_states_and_confirmation_counts",
    "apps.crm.test_import_ux.ImportUXTests.test_service_preview_shows_create_update_and_confirmation_counts",
    "apps.crm.test_import_ux.ImportUXTests.test_blocking_file_error_explains_how_to_recover_without_writes",
    "apps.crm.test_import_ux.ImportUXTests.test_completed_results_offer_consistent_next_actions",
    "apps.crm.test_import_ux.ImportUXTests.test_expired_result_gives_safe_recovery_action",
    "apps.crm.test_import_ux.ImportUXTests.test_navigation_links_follow_existing_import_role_matrix",
    "apps.crm.test_import_ux.ImportUXTests.test_every_import_route_requires_authentication_and_active_membership",
    "services_data_import_browser_check.DataImportFormBrowserChecks",
]


BASELINE_ONLY = [
    "apps.crm.test_import_ux.ImportUXTests.test_landing_explains_process_migration_and_role_appropriate_cards",
    "apps.crm.test_import_ux.ImportUXTests.test_upload_pages_show_shared_limits_templates_and_no_save_guidance",
]


def verify_review(root, state):
    if state["route"] != "/crm/staff/data-import/":
        raise RuntimeError("This adapter requires a fresh invoice review session.")
    for side in ["before", "after"]:
        verify_source(state[side]["source"])
    verify_database(root, state, "after")


def backend(root, state, labels, baseline=False):
    from django.test.runner import DiscoverRunner
    from ui_preview.dashboard_checks import execute

    class DataImportRunner(DiscoverRunner):
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

    os.environ["SERVICES_DATA_IMPORT_BEFORE"] = state["before"]["source"]
    os.environ["SERVICES_DATA_IMPORT_EVIDENCE"] = str(
        Path(state["after"]["directory"]) / "evidence"
    )
    with mock.patch("django.test.utils.get_runner", return_value=DataImportRunner):
        execute(root, state, "server")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument(
        "--suite", choices=["backend", "capture-before", "capture-after"], default="backend"
    )
    parser.add_argument("--labels", nargs="*", choices=BACKEND + BASELINE_ONLY)
    parser.add_argument("--execute-tests", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    if args.labels and any(label in BASELINE_ONLY for label in args.labels) and not args.baseline:
        raise RuntimeError(
            "Superseded copy assertions are BEFORE-only; use current design/domain tests on AFTER."
        )
    root, state = load_session(args.session)
    verify_review(root, state)
    if args.execute_tests:
        backend(root, state, args.labels or BACKEND, args.baseline)
        return
    if args.suite == "backend":
        from ui_preview.appointments_checks import prepare

        # Transaction suites with serialized rollback and browser workers need their
        # own fresh test processes/databases. Never mix their fixture restoration.
        special = ["services_data_import_browser_check.DataImportFormBrowserChecks"]
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
                    "ui_preview.data_import_checks",
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
            str(REPO / "scripts/services_data_import_browser_check.py"),
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
