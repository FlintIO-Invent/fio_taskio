"""Refuse unowned team setup before Django/model imports."""

import os
import unittest
from unittest.mock import patch

from ui_preview.team_fixtures import verify_setup


class TeamBoundaryTests(unittest.TestCase):
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
                    {"route": "/businesses/team/", "before": {"source": "/bad"}},
                ),
            ),
            patch("ui_preview.core.verify_source", side_effect=RuntimeError("source changed")),
            patch("ui_preview.core.verify_database") as db,
        ):
            with self.assertRaisesRegex(RuntimeError, "source changed"):
                verify_setup()
            db.assert_not_called()


class InvitationSQLBoundaryTests(unittest.TestCase):
    def run_guard(self, sql):
        from ui_preview.guard import runtime_writes

        with patch("ui_preview.guard.audit"):
            return runtime_writes(lambda *args: "executed", sql, (), False, {})

    def test_subscription_read_join_in_invitation_update_is_allowed(self):
        sql = 'UPDATE "businesses_businessinvitation" SET "status" = %s WHERE "id" IN (SELECT i.id FROM "businesses_businessinvitation" i JOIN "businesses_businesssubscription" s ON s.business_id = i.business_id)'
        self.assertEqual(self.run_guard(sql), "executed")

    def test_financial_and_schema_writes_remain_blocked(self):
        from ui_preview.guard import PreviewWriteBlocked

        for sql in [
            'UPDATE "businesses_businesssubscription" SET status = %s',
            "INSERT INTO billings_invoice (id) VALUES (%s)",
            "DELETE FROM logistics_logisticscharge",
            "CREATE TABLE example (id int)",
            'UPDATE "businesses_businessinvitation" SET status = %s; UPDATE businesses_businesssubscription SET status = %s',
            'UPDATE "businesses_businessinvitation" SET status = (UPDATE businesses_businesssubscription SET status = %s)',
            'UPDATE "businesses_businessinvitation" SET status = %s /* businesses_businesssubscription */',
        ]:
            with self.subTest(sql=sql), self.assertRaises(PreviewWriteBlocked):
                self.run_guard(sql)
