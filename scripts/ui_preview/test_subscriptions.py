"""Refuse unowned subscriptions setup before Django/model imports."""

import os
import unittest
from unittest.mock import patch

from ui_preview.subscriptions_fixtures import canonical_facts, verify_setup


class SubscriptionsBoundaryTests(unittest.TestCase):
    def test_parity_normalizes_only_plan_audit_times_and_keeps_source_facts(self):
        facts = {
            "plans": [
                {"created_at": "before", "updated_at": "before", "price_monthly": "39.00", "id": 1}
            ],
            "subscriptions": [{"current_period_end": "unchanged"}],
        }
        normalized = canonical_facts(facts)
        self.assertEqual(normalized["plans"], [{"price_monthly": "39.00", "id": 1}])
        self.assertEqual(normalized["subscriptions"], facts["subscriptions"])
        self.assertEqual(facts["plans"][0]["created_at"], "before")

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
                return_value=(None, {"route": "/appointments/"}),
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
                    {"route": "/businesses/subscription/", "before": {"source": "/bad"}},
                ),
            ),
            patch("ui_preview.core.verify_source", side_effect=RuntimeError("source changed")),
            patch("ui_preview.core.verify_database") as db,
        ):
            with self.assertRaisesRegex(RuntimeError, "source changed"):
                verify_setup()
            db.assert_not_called()
