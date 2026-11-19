"""Offline refusal checks; never load Django or open a database."""

import os
from unittest import TestCase, main, mock

from ui_preview.invoices_checks import verify_review
from ui_preview.invoices_fixtures import verify_setup


class InvoiceBoundaryTests(TestCase):
    def test_ordinary_settings_refused_before_resource_or_model_access(self):
        with (
            mock.patch.dict(
                os.environ,
                {"DJANGO_SETTINGS_MODULE": "taskio.settings", "MOTIONMATE_PREVIEW_PHASE": "setup"},
                clear=True,
            ),
            self.assertRaises(RuntimeError),
        ):
            verify_setup()

    def test_serve_phase_cannot_seed(self):
        with (
            mock.patch.dict(
                os.environ,
                {
                    "DJANGO_SETTINGS_MODULE": "ui_preview.settings",
                    "MOTIONMATE_PREVIEW_PHASE": "serve",
                },
                clear=True,
            ),
            self.assertRaises(RuntimeError),
        ):
            verify_setup()

    def test_another_route_cannot_run_invoice_adapter(self):
        with (
            mock.patch("ui_preview.invoices_checks.verify_database") as database,
            self.assertRaises(RuntimeError),
        ):
            verify_review(None, {"route": "/crm/staff/clients/"})
        database.assert_not_called()

    def test_source_refusal_precedes_live_database(self):
        with (
            mock.patch(
                "ui_preview.invoices_checks.verify_source",
                side_effect=RuntimeError("source changed"),
            ),
            mock.patch("ui_preview.invoices_checks.verify_database") as database,
            self.assertRaises(RuntimeError),
        ):
            verify_review(
                None,
                {
                    "route": "/billings/",
                    "before": {"source": "invalid"},
                    "after": {"source": "invalid"},
                },
            )
        database.assert_not_called()


if __name__ == "__main__":
    main()
