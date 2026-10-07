import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db.models import QuerySet
from django.test import Client as WebClient
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client

from .models import Parcel, ParcelEvent
from .parcel_services import change_parcel_status, record_parcel_event, register_parcel
from .public_tracking import (
    LOOKUP_LIMIT,
    allow_tracking_lookup,
    lookup_public_tracking,
    tracking_client_identity,
)
from .public_tracking_views import NOT_FOUND_MESSAGE

TRACKING_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "public-tracking-tests",
    }
}


@override_settings(
    CACHES=TRACKING_CACHE,
    LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=False,
    LOGISTICS_TRACKING_CLIENT_IP_MODE="direct",
)
class PublicTrackingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("logistics_public_tracking")
        self.business = Business.objects.create(
            name="Public Courier",
            slug="private-courier-slug",
            vertical=Business.Vertical.LOGISTICS,
            email="private-business-contact@example.com",
            phone="PRIVATE-BUSINESS-PHONE",
            address="PRIVATE-BUSINESS-ADDRESS",
        )
        self.other = Business.objects.create(
            name="Other Courier", slug="other-courier", vertical=Business.Vertical.LOGISTICS
        )
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        for business in (self.business, self.other):
            BusinessSubscription.objects.create(
                business=business, plan=plan, status="active", billing_interval="yearly"
            )
        self.user = TaskIOUser.objects.create_user(
            email="private-staff@example.com", password="testpass123"
        )
        self.other_user = TaskIOUser.objects.create_user(email="other-staff@example.com")
        for business, user in ((self.business, self.user), (self.other, self.other_user)):
            BusinessUser.objects.create(business=business, user=user, role=BusinessUser.Role.OWNER)
        self.customer = Client.objects.create(
            business=self.business,
            first_name="PRIVATE-CUSTOMER-FIRST",
            last_name="PRIVATE-CUSTOMER-LAST",
            email="private-customer@example.com",
            phone="+19995550099",
            street_address="PRIVATE-CUSTOMER-ADDRESS",
            communication_notes="PRIVATE-CUSTOMER-COMMUNICATION",
            notes="PRIVATE-CUSTOMER-NOTES",
        )
        self.other_customer = Client.objects.create(business=self.other, first_name="Other")
        self.parcel = register_parcel(
            business=self.business,
            client=self.customer,
            actor=self.user,
            origin="PRIVATE-ORIGIN-ADDRESS",
            destination="PRIVATE-DESTINATION-ADDRESS",
            package_description="PRIVATE-PACKAGE-DESCRIPTION",
            internal_reference="PRIVATE-REFERENCE",
            declared_value="987654.32",
            dimensions="PRIVATE-DIMENSIONS",
        )
        record_parcel_event(
            business=self.business,
            parcel=self.parcel,
            actor=self.user,
            public_message="Customer-facing update",
            internal_note="PRIVATE-INTERNAL-NOTE",
            location="PRIVATE-LOCATION-ADDRESS",
            idempotency_key=uuid.uuid4(),
        )

    def lookup(self, code=None, **kwargs):
        return self.client.post(
            self.url,
            {"tracking_code": self.parcel.tracking_code if code is None else code},
            **kwargs,
        )

    def test_anonymous_input_and_valid_result_without_redirect_or_login(self):
        self.assertContains(self.client.get(self.url), 'name="tracking_code"')
        response = self.lookup()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)
        for text in (
            self.parcel.tracking_code,
            "Registered",
            "Customer-facing update",
            "Public Courier",
        ):
            self.assertContains(response, text)
        self.assertContains(response, "Parcel registered.")
        self.assertContains(response, "parcel receipt")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("noindex", response["X-Robots-Tag"])

    def test_projection_is_explicit_json_compatible_allowlist(self):
        result = lookup_public_tracking(self.parcel.tracking_code)
        self.assertEqual(
            set(result), {"tracking_code", "status", "status_label", "business", "events"}
        )
        self.assertEqual(result["business"], {"name": self.business.name})
        self.assertEqual(len(result["events"]), 2)
        for event in result["events"]:
            self.assertEqual(set(event), {"status", "status_label", "timestamp", "message"})
        self.assertIn("Customer-facing update", json.dumps(result))

    def test_private_fields_absent_from_html_and_projection(self):
        html = self.lookup().content.decode()
        projection = json.dumps(lookup_public_tracking(self.parcel.tracking_code))
        for private in (
            self.customer.first_name,
            self.customer.last_name,
            self.customer.email,
            self.customer.phone,
            self.customer.street_address,
            self.customer.communication_notes,
            self.customer.notes,
            self.user.email,
            self.business.email,
            self.business.phone,
            self.business.address,
            self.business.slug,
            self.parcel.origin,
            self.parcel.destination,
            self.parcel.package_description,
            self.parcel.internal_reference,
            str(self.parcel.declared_value),
            self.parcel.dimensions,
            "PRIVATE-INTERNAL-NOTE",
            "PRIVATE-LOCATION-ADDRESS",
        ):
            with self.subTest(private=private):
                self.assertNotIn(private, html)
                self.assertNotIn(private, projection)

    def test_invalid_codes_and_database_identifiers_are_generic(self):
        for code in (
            "F" * 48,
            str(self.parcel.pk),
            str(uuid.uuid4()),
            self.parcel.tracking_code.lower(),
            " " + self.parcel.tracking_code,
            self.parcel.tracking_code + "\n",
            "' OR 1=1 --",
            "",
        ):
            with self.subTest(code=code):
                response = self.lookup(code)
                self.assertContains(response, NOT_FOUND_MESSAGE, status_code=404)
                self.assertNotContains(response, "Public Courier", status_code=404)

    def test_no_get_lookup_or_identifier_route(self):
        response = self.client.get(self.url, {"tracking_code": self.parcel.tracking_code})
        self.assertNotContains(response, self.parcel.tracking_code)
        self.assertNotContains(response, "Customer-facing update")
        self.assertEqual(self.client.get(f"{self.url}{self.parcel.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"{self.url}{uuid.uuid4()}/").status_code, 404)

    def test_internal_only_and_whitespace_public_events_are_hidden(self):
        for public_message in ("", "   "):
            record_parcel_event(
                business=self.business,
                parcel=self.parcel,
                actor=self.user,
                public_message=public_message,
                internal_note="INTERNAL-ONLY-EVENT",
                location="INTERNAL-ONLY-LOCATION",
            )
        result = lookup_public_tracking(self.parcel.tracking_code)
        self.assertEqual(len(result["events"]), 2)
        self.assertNotContains(self.lookup(), "INTERNAL-ONLY")

    def test_public_messages_escaped_and_ordered_chronologically(self):
        event = record_parcel_event(
            business=self.business,
            parcel=self.parcel,
            actor=self.user,
            public_message="<script>public-message</script>",
        )
        response = self.lookup()
        self.assertContains(response, "&lt;script&gt;public-message&lt;/script&gt;")
        self.assertNotContains(response, "<script>public-message</script>")
        html = response.content.decode()
        self.assertLess(html.index("Parcel registered."), html.index("Customer-facing update"))
        self.assertLess(html.index("Customer-facing update"), html.index("public-message"))
        self.assertContains(response, event.timestamp.isoformat())

    def test_cross_tenant_events_excluded_and_client_corruption_fails_closed(self):
        foreign = register_parcel(
            business=self.other,
            client=self.other_customer,
            actor=self.other_user,
            origin="Other",
            destination="Other",
            package_description="Other",
        )
        record_parcel_event(
            business=self.other,
            parcel=foreign,
            actor=self.other_user,
            public_message="OTHER-TENANT-MESSAGE",
        )
        QuerySet(model=ParcelEvent).filter(
            parcel=self.parcel, public_message="Customer-facing update"
        ).update(business=self.other)
        response = self.lookup()
        self.assertNotContains(response, "Customer-facing update")
        self.assertNotContains(response, "OTHER-TENANT-MESSAGE")
        self.assertNotContains(response, foreign.tracking_code)
        QuerySet(model=Parcel).filter(pk=self.parcel.pk).update(client=self.other_customer)
        self.assertContains(self.lookup(), NOT_FOUND_MESSAGE, status_code=404)

    def test_logged_in_workspace_does_not_affect_public_lookup_or_leak_context(self):
        self.client.force_login(self.other_user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.other.pk
        session.save()
        response = self.lookup()
        self.assertContains(response, "Public Courier")
        self.assertNotContains(response, "Other Courier")
        self.assertNotContains(response, self.other_user.email)

    @patch("apps.logistics.public_tracking_views.get_token", return_value="a" * 64)
    def test_invalid_and_inaccessible_responses_have_identical_body_status_and_headers(self, token):
        invalid = self.lookup("F" * 48)
        cases = [
            ("business", {"is_active": False}),
            ("subscription", {"status": "suspended"}),
            ("subscription", {"status": "cancelled"}),
            ("subscription", {"status": "expired"}),
            ("subscription", {"status": "pending_checkout"}),
            ("subscription", {"status": "past_due"}),
        ]
        for kind, fields in cases:
            with self.subTest(fields=fields):
                if kind == "business":
                    Business.objects.filter(pk=self.business.pk).update(**fields)
                else:
                    BusinessSubscription.objects.filter(business=self.business).update(**fields)
                response = self.lookup()
                self.assertEqual(response.status_code, invalid.status_code)
                self.assertEqual(response.content, invalid.content)
                for header in ("Cache-Control", "Referrer-Policy", "X-Robots-Tag", "Content-Type"):
                    self.assertEqual(response[header], invalid[header])
                Business.objects.filter(pk=self.business.pk).update(is_active=True)
                BusinessSubscription.objects.filter(business=self.business).update(status="active")

    def test_subscription_grace_allowed_but_restricted_denied(self):
        now = timezone.now()
        subscriptions = BusinessSubscription.objects.filter(business=self.business)
        subscriptions.update(
            status="past_due",
            payment_provider="stripe",
            billing_currency="usd",
            provider_customer_id="cus_tracking",
            provider_subscription_id="sub_tracking",
            provider_price_id="price_tracking",
            past_due_since=now - timedelta(days=5),
            grace_period_ends_at=now + timedelta(days=1),
        )
        self.assertEqual(self.lookup().status_code, 200)
        subscriptions.update(grace_period_ends_at=now - timedelta(days=1))
        self.assertTrue(subscriptions.get().has_restricted_access)
        self.assertContains(self.lookup(), NOT_FOUND_MESSAGE, status_code=404)

    def test_scheduled_cancellation_allowed_until_period_end(self):
        subscriptions = BusinessSubscription.objects.filter(business=self.business)
        subscriptions.update(
            cancel_at_period_end=True, current_period_end=timezone.now() + timedelta(days=1)
        )
        self.assertEqual(self.lookup().status_code, 200)
        subscriptions.update(current_period_end=timezone.now() - timedelta(days=1))
        self.assertContains(self.lookup(), NOT_FOUND_MESSAGE, status_code=404)

    def test_missing_subscription_inactive_plan_and_missing_entitlements_denied(self):
        plan = ClarivoPlan.objects.get(slug="logistics")
        ClarivoPlan.objects.filter(pk=plan.pk).update(is_active=False)
        self.assertContains(self.lookup(), NOT_FOUND_MESSAGE, status_code=404)
        ClarivoPlan.objects.filter(pk=plan.pk).update(is_active=True)
        for denied_module in ("tracking", "parcels"):
            with self.subTest(denied_module=denied_module):
                with patch.object(
                    ClarivoPlan,
                    "allows_module",
                    side_effect=lambda module, denied=denied_module: module != denied,
                ):
                    self.assertContains(self.lookup(), NOT_FOUND_MESSAGE, status_code=404)
        BusinessSubscription.objects.filter(business=self.business).delete()
        self.assertContains(self.lookup(), NOT_FOUND_MESSAGE, status_code=404)

    def test_service_vertical_and_incompatible_offering_cannot_expose_parcels(self):
        Business.objects.filter(pk=self.business.pk).update(vertical=Business.Vertical.SERVICE)
        self.assertContains(self.lookup(), NOT_FOUND_MESSAGE, status_code=404)
        Business.objects.filter(pk=self.business.pk).update(vertical=Business.Vertical.LOGISTICS)
        BusinessSubscription.objects.filter(business=self.business).update(
            plan=ClarivoPlan.objects.get(slug="pro")
        )
        self.assertContains(self.lookup(), NOT_FOUND_MESSAGE, status_code=404)

    def test_delivered_parcel_stays_trackable_with_eligible_business(self):
        for status in ("RECEIVED", "IN_TRANSIT", "ARRIVED", "READY", "DELIVERED"):
            change_parcel_status(
                business=self.business,
                parcel=self.parcel,
                actor=self.user,
                status=status,
                public_message=f"Public {status}",
            )
        self.assertContains(self.lookup(), "Delivered")
        self.assertContains(self.lookup(), "Public DELIVERED")
        Business.objects.filter(pk=self.business.pk).update(is_active=False)
        self.assertContains(self.lookup(), NOT_FOUND_MESSAGE, status_code=404)

    def test_cancelled_parcel_remains_trackable_without_changing_lifecycle(self):
        change_parcel_status(
            business=self.business,
            parcel=self.parcel,
            actor=self.user,
            status="CANCELLED",
            public_message="Parcel cancelled.",
        )
        self.assertContains(self.lookup(), "Parcel cancelled.")

    def test_post_requires_csrf_but_no_authentication(self):
        client = WebClient(enforce_csrf_checks=True)
        self.assertEqual(
            client.post(self.url, {"tracking_code": self.parcel.tracking_code}).status_code, 403
        )
        self.assertEqual(client.get(self.url).status_code, 200)
        response = client.post(
            self.url,
            {
                "tracking_code": self.parcel.tracking_code,
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            },
        )
        self.assertContains(response, "Customer-facing update")

    @override_settings(
        ALLOWED_HOSTS=["localhost", "127.0.0.1", "development.example", "production.example"],
        CSRF_TRUSTED_ORIGINS=["https://development.example", "https://production.example"],
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    )
    def test_csrf_native_form_post_supported_origins_and_proxy_https(self):
        for origin in (
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "https://development.example",
            "https://production.example",
        ):
            with self.subTest(origin=origin):
                client = WebClient(enforce_csrf_checks=True)
                host = origin.split("://", 1)[1]
                headers = {"HTTP_HOST": host}
                if origin.startswith("https:"):
                    headers["HTTP_X_FORWARDED_PROTO"] = "https"
                response = client.get(self.url, **headers)
                self.assertEqual(response["Referrer-Policy"], "same-origin")
                response = client.post(
                    self.url,
                    {
                        "tracking_code": self.parcel.tracking_code,
                        "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
                    },
                    HTTP_ORIGIN=origin,
                    **headers,
                )
                self.assertContains(response, "Customer-facing update")

    def test_csrf_null_malformed_cross_origin_and_bad_token_fail_before_lookup(self):
        client = WebClient(enforce_csrf_checks=True)
        client.get(self.url)
        form = {
            "tracking_code": self.parcel.tracking_code,
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        }
        with patch("apps.logistics.public_tracking_views.lookup_public_tracking") as lookup:
            for origin in (
                "null",
                "https://evil.example",
                "not-an-origin",
                "https://testserver.evil.example",
            ):
                with self.subTest(origin=origin):
                    self.assertEqual(
                        client.post(self.url, form, HTTP_ORIGIN=origin).status_code, 403
                    )
            self.assertEqual(
                client.post(
                    self.url,
                    {**form, "csrfmiddlewaretoken": "malformed"},
                    HTTP_ORIGIN="http://testserver",
                ).status_code,
                403,
            )
            lookup.assert_not_called()

    def test_https_csrf_same_origin_referer_fallback_and_missing_referer_rejected(self):
        client = WebClient(enforce_csrf_checks=True)
        client.get(self.url, secure=True)
        form = {
            "tracking_code": self.parcel.tracking_code,
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        }
        self.assertEqual(client.post(self.url, form, secure=True).status_code, 403)
        self.assertContains(
            client.post(self.url, form, secure=True, HTTP_REFERER=f"https://testserver{self.url}"),
            "Customer-facing update",
        )

    @override_settings(LOGISTICS_TRACKING_CLIENT_IP_MODE="heroku")
    @patch.dict("os.environ", {"DYNO": "web.1"})
    @patch("apps.logistics.public_tracking.time.time", return_value=120)
    def test_heroku_spoofed_left_forwarded_values_cannot_bypass_limit(self, clock):
        for index in range(LOOKUP_LIMIT):
            self.assertEqual(
                self.lookup(
                    "bad",
                    REMOTE_ADDR="10.0.0.2",
                    HTTP_X_FORWARDED_FOR=f"192.0.2.{index}, 198.51.100.1",
                    HTTP_X_REAL_IP=f"192.0.2.{index}",
                ).status_code,
                404,
            )
        self.assertEqual(
            self.lookup(
                REMOTE_ADDR="10.0.0.3", HTTP_X_FORWARDED_FOR="garbage, 198.51.100.1"
            ).status_code,
            429,
        )
        self.assertEqual(self.lookup(HTTP_X_FORWARDED_FOR="198.51.100.2").status_code, 200)

    @override_settings(LOGISTICS_TRACKING_CLIENT_IP_MODE="heroku")
    @patch.dict("os.environ", {"DYNO": "web.1"})
    def test_untrusted_identity_fails_before_parcel_lookup(self):
        with patch("apps.logistics.public_tracking_views.lookup_public_tracking") as lookup:
            for headers in (
                {},
                {"HTTP_X_FORWARDED_FOR": "null"},
                {"HTTP_X_FORWARDED_FOR": "198.51.100.1:8080"},
            ):
                self.assertEqual(self.lookup(**headers).status_code, 429)
            lookup.assert_not_called()

    def test_not_found_request_log_contains_no_tracking_input(self):
        invalid_code = "E" * 48
        with self.assertLogs("django.request", level="WARNING") as logs:
            self.assertEqual(self.lookup(invalid_code).status_code, 404)
        self.assertNotIn(invalid_code, " ".join(logs.output))
        self.assertNotIn(self.customer.email, " ".join(logs.output))

    @patch("apps.logistics.public_tracking.time.time", return_value=120)
    def test_throttling_precedes_lookup_and_does_not_depend_on_code(self, clock):
        with patch(
            "apps.logistics.public_tracking_views.lookup_public_tracking", return_value=None
        ) as lookup:
            for _ in range(LOOKUP_LIMIT):
                self.assertEqual(self.lookup("bad-code").status_code, 404)
            lookup.reset_mock()
            response = self.lookup()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response["Retry-After"], "60")
            lookup.assert_not_called()
            self.assertNotContains(response, self.parcel.tracking_code, status_code=429)

    @patch("apps.logistics.public_tracking.time.time", return_value=120)
    def test_forwarded_header_cannot_bypass_direct_peer_limit(self, clock):
        for index in range(LOOKUP_LIMIT):
            self.assertEqual(
                self.lookup("bad", HTTP_X_FORWARDED_FOR=f"192.0.2.{index}").status_code, 404
            )
        self.assertEqual(self.lookup(HTTP_X_FORWARDED_FOR="198.51.100.1").status_code, 429)
        self.assertEqual(self.lookup(REMOTE_ADDR="198.51.100.2").status_code, 200)


@override_settings(CACHES=TRACKING_CACHE, LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=False)
class TrackingThrottleTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("apps.logistics.public_tracking.time.time", return_value=120)
    def test_limit_window_expiry_and_peer_isolation(self, clock):
        for _ in range(LOOKUP_LIMIT):
            self.assertTrue(allow_tracking_lookup("192.0.2.1"))
        self.assertFalse(allow_tracking_lookup("192.0.2.1"))
        self.assertTrue(allow_tracking_lookup("192.0.2.2"))
        clock.return_value = 180
        self.assertTrue(allow_tracking_lookup("192.0.2.1"))

    def test_cache_failure_denies_lookup(self):
        with patch("apps.logistics.public_tracking.cache.add", side_effect=RuntimeError):
            self.assertFalse(allow_tracking_lookup("192.0.2.1"))
        with patch("apps.logistics.public_tracking.cache.add", return_value=False):
            with patch("apps.logistics.public_tracking.cache.incr", side_effect=ValueError):
                self.assertFalse(allow_tracking_lookup("192.0.2.1"))

    @override_settings(LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=True)
    def test_deployment_local_cache_fails_closed_without_cache_access(self):
        with patch("apps.logistics.public_tracking.cache.add") as add:
            self.assertFalse(allow_tracking_lookup("192.0.2.1"))
        add.assert_not_called()

    def test_unknown_identity_fails_closed(self):
        self.assertFalse(allow_tracking_lookup(None))
        self.assertFalse(allow_tracking_lookup(""))

    def test_keys_contain_no_raw_peer_or_tracking_code(self):
        with patch("apps.logistics.public_tracking.cache.add", return_value=True) as add:
            self.assertTrue(allow_tracking_lookup("192.0.2.123"))
        key = add.call_args.args[0]
        self.assertNotIn("192.0.2.123", key)
        self.assertEqual(add.call_args.kwargs["timeout"], 120)


class TrackingClientIdentityTests(SimpleTestCase):
    def request(self, **headers):
        return RequestFactory().get("/logistics/track/", **headers)

    @override_settings(LOGISTICS_TRACKING_CLIENT_IP_MODE="direct")
    def test_direct_peer_ignores_every_forwarded_header_and_normalizes_ip(self):
        self.assertEqual(
            tracking_client_identity(
                self.request(
                    REMOTE_ADDR="::ffff:192.0.2.1",
                    HTTP_X_FORWARDED_FOR="203.0.113.1",
                    HTTP_FORWARDED="for=203.0.113.2",
                    HTTP_X_REAL_IP="203.0.113.3",
                )
            ),
            "192.0.2.1",
        )
        self.assertIsNone(tracking_client_identity(self.request(REMOTE_ADDR="")))
        self.assertEqual(
            tracking_client_identity(self.request(REMOTE_ADDR="2001:0db8::1")), "2001:db8::1"
        )

    @override_settings(LOGISTICS_TRACKING_CLIENT_IP_MODE="heroku")
    @patch.dict("os.environ", {}, clear=True)
    def test_heroku_mode_requires_platform_environment_not_request_header(self):
        self.assertIsNone(
            tracking_client_identity(
                self.request(HTTP_DYNO="web.1", HTTP_X_FORWARDED_FOR="192.0.2.1")
            )
        )

    @override_settings(LOGISTICS_TRACKING_CLIENT_IP_MODE="heroku")
    @patch.dict("os.environ", {"DYNO": "web.1"})
    def test_heroku_only_rightmost_router_address_and_no_port_or_chain_guessing(self):
        for value, expected in (
            ("spoof, 192.0.2.1", "192.0.2.1"),
            ("spoof, 2001:0db8::1", "2001:db8::1"),
            ("192.0.2.1,", None),
            ("192.0.2.1:80", None),
            ("a" * 4097, None),
            ("unknown", None),
        ):
            with self.subTest(value=value[:40]):
                self.assertEqual(
                    tracking_client_identity(self.request(HTTP_X_FORWARDED_FOR=value)), expected
                )
