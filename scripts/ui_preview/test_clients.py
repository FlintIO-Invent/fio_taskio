"""Offline refusal checks; no Django or database initialization."""

import os
import unittest
from unittest.mock import patch

from ui_preview.clients_fixtures import enabled, verify_setup


class ClientsBoundaryTests(unittest.TestCase):
    def test_clients_route_only(self):
        self.assertTrue(enabled({"route": "/crm/staff/clients/"}))
        self.assertFalse(enabled({"route": "/crm/agent/dashboard/"}))
        self.assertFalse(enabled({"route": "/appointments/"}))
        self.assertFalse(enabled({}))

    def test_ordinary_settings_refused_before_model_import(self):
        with patch.dict(
            os.environ,
            {"DJANGO_SETTINGS_MODULE": "taskio.settings", "MOTIONMATE_PREVIEW_PHASE": "setup"},
        ):
            with self.assertRaisesRegex(RuntimeError, "verified private preview"):
                verify_setup({"id": "irrelevant"})

    def test_runtime_serve_phase_cannot_seed(self):
        with patch.dict(
            os.environ,
            {"DJANGO_SETTINGS_MODULE": "ui_preview.settings", "MOTIONMATE_PREVIEW_PHASE": "serve"},
        ):
            with self.assertRaisesRegex(RuntimeError, "verified private preview"):
                verify_setup({"id": "irrelevant"})

    def test_changed_session_refused_before_live_database(self):
        with (
            patch.dict(
                os.environ,
                {
                    "DJANGO_SETTINGS_MODULE": "ui_preview.settings",
                    "MOTIONMATE_PREVIEW_PHASE": "setup",
                    "MOTIONMATE_PREVIEW_ROOT": "/not-accessed",
                },
            ),
            patch(
                "ui_preview.core.load_session",
                return_value=(None, {"id": "other", "route": "/crm/staff/clients/"}),
            ),
            patch("ui_preview.core.verify_database") as verify,
        ):
            with self.assertRaisesRegex(RuntimeError, "identity differs"):
                verify_setup({"id": "expected"})
            verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
