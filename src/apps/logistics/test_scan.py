"""Exact authenticated resolution and thin action adapter safety."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client as WebClient
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.businesses.models import BusinessSubscription, BusinessUser

from . import test_parcels as fixtures
from .models import ParcelEvent
from .parcel_policy import ALLOWED_TRANSITIONS
from .parcel_services import register_parcel
from .scan import normalize_scan_code, resolve_scanned_parcel


class ScanNormalizationTests(SimpleTestCase):
    def test_manual_paste_and_scanner_suffixes(self):
        code = "A1" * 24
        for raw in (code, code.lower(), " " + code + " ", "\t\r\n" + code + "\r\n\t"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_scan_code(raw), code)

    def test_invalid_input_is_never_repaired_into_a_code(self):
        code = "A1" * 24
        for raw in (
            None,
            42,
            "",
            "A" * 47,
            "A" * 49,
            "G" * 48,
            code[:24] + "\n" + code[24:],
            code + code,
            "https://example.com/" + code,
            " " * 257 + code,
        ):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                normalize_scan_code(raw)


@override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False)
class ScanWorkflowTests(TestCase):
    setUp = fixtures.ParcelTests.setUp
    register = fixtures.ParcelTests.register
    change = fixtures.ParcelTests.change
    switch = fixtures.ParcelTests.switch

    def lookup(self, code, **kwargs):
        return self.client.post(reverse("logistics_parcel_scan"), {"tracking_code": code}, **kwargs)

    def action_data(self, parcel, **overrides):
        return {
            "status": "RECEIVED",
            "expected_status": parcel.current_status,
            "idempotency_key": str(uuid.uuid4()),
            **overrides,
        }

    def action(self, parcel, data, **kwargs):
        return self.client.post(
            reverse("logistics_parcel_scan_action", args=[parcel.pk]), data, **kwargs
        )

    def test_manual_lookup_exact_code_and_normalized_suffix(self):
        parcel = self.register()
        for code in (parcel.tracking_code, " \t" + parcel.tracking_code.lower() + "\r\n"):
            response = self.lookup(code)
            self.assertEqual(response.context["parcel"], parcel)
            self.assertContains(response, parcel.tracking_code)
            self.assertContains(response, "Parcel Customer")
            self.assertContains(response, "Open Full Parcel")
            self.assertEqual(response.context["recent_event"].status, "REGISTERED")
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_resolver_reuses_persisted_access_and_tenant_query(self):
        parcel = self.register()
        self.assertEqual(
            resolve_scanned_parcel(
                business=self.business, actor=self.user, code=parcel.tracking_code
            ),
            parcel,
        )
        with self.assertRaises(PermissionDenied):
            resolve_scanned_parcel(
                business=self.service, actor=self.user, code=parcel.tracking_code
            )

    def test_cross_tenant_and_missing_codes_have_identical_not_found(self):
        foreign = register_parcel(
            business=self.other, actor=self.other_user, client=self.other_customer, **self.fields
        )
        foreign_response = self.lookup(foreign.tracking_code)
        missing_response = self.lookup("0" * 48)
        self.assertEqual(foreign_response.status_code, 404)
        self.assertEqual(missing_response.status_code, 404)
        self.assertEqual(
            foreign_response.context["scan_error"], missing_response.context["scan_error"]
        )
        self.assertIsNone(foreign_response.context["parcel"])
        self.assertNotContains(foreign_response, foreign.client.email, status_code=404)
        self.assertNotContains(foreign_response, "data-scan-parcel", status_code=404)

    def test_invalid_and_partial_codes_do_not_lookup_or_write(self):
        parcel = self.register()
        with patch("apps.logistics.scan_views.resolve_scanned_parcel") as resolver:
            for code in (
                "",
                parcel.tracking_code[:24],
                "G" * 48,
                parcel.tracking_code + parcel.tracking_code,
            ):
                self.assertEqual(self.lookup(code).status_code, 400)
        resolver.assert_not_called()
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_get_never_resolves_tracking_code_in_query_string(self):
        parcel = self.register()
        response = self.client.get(
            reverse("logistics_parcel_scan"), {"tracking_code": parcel.tracking_code}
        )
        self.assertIsNone(response.context["parcel"])
        self.assertNotContains(response, parcel.tracking_code)

    def test_camera_entrypoint_is_local_and_logistics_only(self):
        response = self.client.get(reverse("logistics_parcel_scan"))
        self.assertContains(response, "Scan with Camera")
        self.assertContains(response, "Stop Camera")
        self.assertContains(response, "assets/js/logistics-camera.js")
        self.assertContains(response, "vendors/zxing/zxing-browser-0.2.1.min.js")
        self.switch(self.service)
        for route in ("agent_dashboard", "staff_client_list"):
            response = self.client.get(reverse(route))
            self.assertNotContains(response, "data-scan-camera")
            self.assertNotContains(response, "assets/js/logistics-camera.js")
        self.assertEqual(
            self.client.get(
                reverse("logistics_parcel_scan"), HTTP_ACCEPT="application/json"
            ).status_code,
            403,
        )

    def test_repeated_lookup_is_read_only(self):
        parcel = self.register()
        for _ in range(4):
            self.assertEqual(self.lookup(parcel.tracking_code).status_code, 200)
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_only_policy_actions_presented_including_terminal_parcels(self):
        parcel = self.register()
        for state in ("REGISTERED", "RECEIVED", "IN_TRANSIT", "ARRIVED", "READY", "DELIVERED"):
            if state != "REGISTERED":
                self.change(parcel, state)
                parcel.refresh_from_db()
            response = self.lookup(parcel.tracking_code)
            self.assertEqual(
                {value for value, _ in response.context["scan_actions"]}, ALLOWED_TRANSITIONS[state]
            )

    def test_action_creates_one_event_and_returns_next_scan(self):
        parcel = self.register()
        response = self.action(
            parcel, self.action_data(parcel), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertContains(response, "data-scan-action-success")
        self.assertContains(response, "Ready for the next scan")
        self.assertNotContains(response, "data-scan-parcel")
        self.assertEqual(ParcelEvent.objects.filter(parcel=parcel, status="RECEIVED").count(), 1)
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "RECEIVED")

    def test_duplicate_and_browser_resubmission_do_not_duplicate_events(self):
        parcel = self.register()
        data = self.action_data(parcel)
        for _ in range(3):
            response = self.action(parcel, data)
            self.assertRedirects(response, reverse("logistics_parcel_scan"))
        self.assertEqual(ParcelEvent.objects.filter(parcel=parcel, status="RECEIVED").count(), 1)
        self.assertEqual(ParcelEvent.objects.count(), 2)

    def test_receipt_replay_after_state_moves_and_conflicting_retry(self):
        parcel = self.register()
        data = self.action_data(parcel)
        self.action(parcel, data)
        parcel.refresh_from_db()
        self.change(parcel, "IN_TRANSIT")
        self.assertEqual(self.action(parcel, data).status_code, 302)
        self.assertEqual(self.action(parcel, {**data, "status": "HOLD"}).status_code, 400)
        self.assertEqual(ParcelEvent.objects.count(), 3)

    def test_stale_and_forbidden_actions_are_rejected_and_refreshed(self):
        parcel = self.register()
        for overrides in (
            {"status": "DELIVERED"},
            {"expected_status": "RECEIVED"},
            {"idempotency_key": "bad"},
            {"status": ""},
        ):
            response = self.action(parcel, self.action_data(parcel, **overrides))
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "data-scan-error", status_code=400)
            self.assertEqual(response.context["parcel"].current_status, "REGISTERED")
            self.assertEqual(
                {v for v, _ in response.context["scan_actions"]}, ALLOWED_TRANSITIONS["REGISTERED"]
            )
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_missing_retry_or_expected_status_cannot_mutate(self):
        parcel = self.register()
        for field in ("idempotency_key", "expected_status"):
            data = self.action_data(parcel)
            data.pop(field)
            self.assertEqual(self.action(parcel, data).status_code, 400)
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_cross_tenant_action_is_not_found(self):
        parcel = register_parcel(
            business=self.other, actor=self.other_user, client=self.other_customer, **self.fields
        )
        self.assertEqual(self.action(parcel, self.action_data(parcel)).status_code, 404)
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_readers_can_lookup_but_cannot_mutate(self):
        parcel = self.register()
        for role in (BusinessUser.Role.VIEWER, BusinessUser.Role.ACCOUNTANT):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            response = self.lookup(parcel.tracking_code)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["scan_actions"], [])
            self.assertNotContains(response, "data-scan-action ")
            self.assertEqual(self.action(parcel, self.action_data(parcel)).status_code, 403)
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_logout_and_service_workspace_cannot_scan(self):
        parcel = self.register()
        self.switch(self.service)
        for url in (
            reverse("logistics_parcel_scan"),
            reverse("logistics_parcel_scan_action", args=[parcel.pk]),
        ):
            self.assertEqual(self.client.post(url, HTTP_ACCEPT="application/json").status_code, 403)
        for route in ("agent_dashboard", "staff_client_list"):
            self.assertNotContains(
                self.client.get(reverse(route)), reverse("logistics_parcel_scan")
            )
        self.client.logout()
        response = self.client.get(reverse("logistics_parcel_scan"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("business_login"), response.url)

    def test_csrf_and_post_only_actions(self):
        parcel = self.register()
        csrf_client = WebClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(
            csrf_client.post(
                reverse("logistics_parcel_scan"), {"tracking_code": parcel.tracking_code}
            ).status_code,
            403,
        )
        self.assertEqual(
            csrf_client.post(
                reverse("logistics_parcel_scan_action", args=[parcel.pk]), self.action_data(parcel)
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("logistics_parcel_scan_action", args=[parcel.pk])).status_code,
            405,
        )
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_billing_restrictions_and_private_caching(self):
        parcel = self.register()
        for response in (
            self.client.get(reverse("logistics_parcel_scan")),
            self.lookup(parcel.tracking_code, HTTP_X_REQUESTED_WITH="XMLHttpRequest"),
        ):
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertIn("private", response.headers["Cache-Control"])
        BusinessSubscription.objects.filter(business=self.business).update(status="suspended")
        self.assertEqual(self.lookup(parcel.tracking_code).status_code, 302)
        self.assertEqual(self.action(parcel, self.action_data(parcel)).status_code, 302)
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_readonly_billing_access_allows_lookup_without_actions(self):
        parcel = self.register()
        BusinessSubscription.objects.filter(business=self.business).update(
            status="past_due",
            payment_provider="stripe",
            billing_currency="usd",
            provider_customer_id="cus_scan_test",
            provider_subscription_id="sub_scan_test",
            provider_price_id="price_scan_test",
            past_due_since=timezone.now() - timedelta(days=10),
            grace_period_ends_at=timezone.now() - timedelta(days=3),
        )
        response = self.lookup(parcel.tracking_code)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scan_actions"], [])
        self.assertEqual(self.action(parcel, self.action_data(parcel)).status_code, 302)
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_non_javascript_lookup_and_action_use_same_services(self):
        parcel = self.register()
        response = self.lookup(parcel.tracking_code)
        data = {
            field.name: field.value() for field in response.context["action_form"].hidden_fields()
        }
        self.assertRedirects(
            self.action(parcel, {**data, "status": "RECEIVED"}), reverse("logistics_parcel_scan")
        )
        self.assertEqual(ParcelEvent.objects.count(), 2)
