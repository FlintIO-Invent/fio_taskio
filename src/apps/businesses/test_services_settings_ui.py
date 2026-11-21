"""Settings payload/access and accessible DOM contracts on owned PostgreSQL."""

import os
import re
from pathlib import Path

from django.conf import settings
from django.forms.models import model_to_dict
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.crm.test_services_dashboard_ui import assert_disposable

from .models import ClarivoPlan
from .test_service_allowances import ServicesFixture


class SettingsPresentationTests(ServicesFixture, TestCase):
    def setUp(self):
        assert_disposable()
        super().setUp()
        self.login()

    def test_personal_save_is_separate_from_business_and_keeps_draft_errors(self):
        original = model_to_dict(self.business)
        data = {
            "section": "account",
            "account-first_name": "Native",
            "account-last_name": "Personal",
            "account-email": self.owner.email,
            "account-phone": "12345",
            "account-address": "Personal street",
            "account-date_of_birth": "1990-02-03",
        }
        response = self.client.post(reverse("business_settings"), data)
        self.assertRedirects(response, reverse("business_settings") + "#my-account")
        self.business.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertEqual(original, model_to_dict(self.business))
        self.assertEqual(self.owner.first_name, "Native")
        response = self.client.post(
            reverse("business_settings"), {**data, "account-email": "invalid"}
        )
        self.assertContains(response, "Enter a valid email address.")
        self.assertContains(response, 'value="Native"')
        self.assertContains(response, 'aria-invalid="true"')

    def test_role_scopes_remain_distinct(self):
        for role in ["owner", "admin", "staff", "accountant", "viewer"]:
            self.member.role = role
            self.member.save(update_fields=["role"])
            response = self.client.get(reverse("business_settings"))
            self.assertContains(response, 'name="account-email"')
            self.assertEqual(
                'name="currency"' in response.content.decode(), role in ["owner", "admin"]
            )
            if role not in ["owner", "admin"]:
                self.assertEqual(
                    self.client.post(
                        reverse("business_settings"), {"section": "business", "name": "Forbidden"}
                    ).status_code,
                    403,
                )
        self.business.refresh_from_db()
        self.assertNotEqual(self.business.name, "Forbidden")

    def test_bulk_ids_are_unique_without_changing_payload_or_tab_hooks(self):
        response = self.client.get(reverse("business_booking_settings"))
        html = response.content.decode()
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        for field in ["staff_member", "start_time", "end_time", "is_active"]:
            self.assertIn('id="id_' + field + '"', html)
            self.assertIn('id="id_bulk_' + field + '"', html)
        for value in ["availability", "bulk_availability", "settings"]:
            self.assertIn('name="form_kind" value="' + value + '"', html)
        for hook in [
            "availability-entry-tabs",
            "availability-single-tab",
            "availability-single-panel",
            "availability-bulk-tab",
            "availability-bulk-panel",
        ]:
            self.assertIn('id="' + hook + '"', html)
        response = self.client.post(
            reverse("business_booking_settings"),
            {
                "form_kind": "bulk_availability",
                "days": ["0", "1"],
                "start_time": "17:00",
                "end_time": "09:00",
                "is_active": "on",
            },
        )
        self.assertContains(response, "End time must be after the start time.")
        self.assertContains(response, 'id="id_bulk_end_time"')
        self.assertContains(response, 'id="availability-bulk-panel"')

    def test_legacy_redirects_and_no_business_fallback(self):
        self.assertRedirects(
            self.client.get(reverse("saas_profile") + "?section=invoice"),
            reverse("business_settings") + "#invoice-defaults",
        )
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        response = self.client.get(reverse("business_settings"))
        self.assertContains(response, "My account")
        self.assertNotContains(response, "services-settings.css")

    def test_logistics_settings_render_matches_frozen_before(self):
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        self.business.vertical = "LOGISTICS"
        self.business.country = "SX"
        self.business.save(update_fields=["vertical", "country"])
        self.subscription.plan = plan
        self.subscription.billing_interval = "yearly"
        self.subscription.save()
        before = Path(os.environ["SERVICES_SETTINGS_BEFORE"]) / "src/templates"
        templates = [
            {**settings.TEMPLATES[0], "DIRS": [str(before), *settings.TEMPLATES[0]["DIRS"]]}
        ]
        current = self.client.get(reverse("business_settings"))
        with override_settings(TEMPLATES=templates):
            original = self.client.get(reverse("business_settings"))

        def clean(raw):
            return re.sub(
                rb">\s+<", b"><", re.sub(rb'name="csrfmiddlewaretoken" value="[^"]+"', b"csrf", raw)
            ).strip()

        self.assertEqual(clean(current.content), clean(original.content))
        self.assertNotContains(current, "services-settings.css")
