"""Refuse unowned business_settings setup before Django/model imports."""

import os
import unittest
from unittest.mock import patch

from ui_preview.business_settings_fixtures import verify_setup


class SettingsBoundaryTests(unittest.TestCase):
    def test_wrong_settings_and_serve_phase_refused(self):
        for settings, phase in [("taskio.settings", "setup"), ("ui_preview.settings", "serve")]:
            with (
                self.subTest(settings=settings, phase=phase),
                patch.dict(
                    os.environ,
                    {"DJANGO_SETTINGS_MODULE": settings, "MOTIONMATE_PREVIEW_PHASE": phase},
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "private setup"):
                    verify_setup()

    def test_wrong_route_refused_before_connection(self):
        with (
            patch.dict(
                os.environ,
                {
                    "DJANGO_SETTINGS_MODULE": "ui_preview.settings",
                    "MOTIONMATE_PREVIEW_PHASE": "setup",
                    "MOTIONMATE_PREVIEW_ROOT": "/unused",
                    "MOTIONMATE_PREVIEW_SIDE": "before",
                },
            ),
            patch(
                "ui_preview.core.load_session",
                return_value=(None, {"route": "/businesses/subscription/"}),
            ),
            patch("ui_preview.core.verify_database") as db,
        ):
            with self.assertRaisesRegex(RuntimeError, "route differs"):
                verify_setup()
            db.assert_not_called()

    def test_source_failure_precedes_database_access(self):
        with (
            patch.dict(
                os.environ,
                {
                    "DJANGO_SETTINGS_MODULE": "ui_preview.settings",
                    "MOTIONMATE_PREVIEW_PHASE": "setup",
                    "MOTIONMATE_PREVIEW_ROOT": "/unused",
                    "MOTIONMATE_PREVIEW_SIDE": "before",
                },
            ),
            patch(
                "ui_preview.core.load_session",
                return_value=(
                    None,
                    {"route": "/businesses/settings/", "before": {"source": "/bad"}},
                ),
            ),
            patch("ui_preview.core.verify_source", side_effect=RuntimeError("source changed")),
            patch("ui_preview.core.verify_database") as db,
        ):
            with self.assertRaisesRegex(RuntimeError, "source changed"):
                verify_setup()
            db.assert_not_called()
