import shutil
import struct
import subprocess
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client as BusinessClient
from taskio.pwa import PWA_ASSETS


@override_settings(ALLOWED_HOSTS=["testserver"])
class PWAResourceTests(SimpleTestCase):
    def test_manifest_and_existing_icon_dimensions(self):
        response = self.client.get(reverse("pwa_manifest"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        manifest = response.json()
        self.assertEqual(manifest["name"], "Motionmate")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["start_url"], reverse("agent_dashboard"))
        self.assertEqual(manifest["id"], manifest["start_url"])
        self.assertNotIn("http", str(manifest))
        self.assertEqual(self.client.get(reverse("pwa_manifest_legacy")).json(), manifest)
        for size, icon in zip((192, 512), manifest["icons"], strict=True):
            self.assertEqual(icon["sizes"], f"{size}x{size}")
            image = Path(finders.find(f"assets/img/favicons/android-chrome-{size}x{size}.png"))
            self.assertEqual(struct.unpack(">II", image.read_bytes()[16:24]), (size, size))

    def test_service_worker_scope_content_and_revalidation(self):
        response = self.client.get(reverse("pwa_service_worker"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/javascript")
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn(b"__PWA_VERSION__", response.content)
        for asset in PWA_ASSETS:
            self.assertIn(asset.encode(), response.content)

    def test_offline_is_public_and_has_no_workspace_or_csrf_context(self):
        with patch(
            "apps.businesses.context_processors.current_business", side_effect=AssertionError
        ):
            response = self.client.get(reverse("pwa_offline"))
        self.assertContains(response, "Changes cannot be saved offline and nothing is queued.")
        self.assertNotContains(response, "csrfmiddlewaretoken")
        self.assertNotContains(response, "<form")
        self.assertNotIn("sessionid", response.cookies)
        self.assertNotIn("csrftoken", response.cookies)

    def test_worker_cache_policy_with_real_javascript(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for worker policy verification")
        source = self.client.get(reverse("pwa_service_worker")).content.decode()
        result = subprocess.run(
            [node, str(settings.BASE_DIR.parent / "scripts/pwa_worker_test.cjs")],
            input=source,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_csrf_still_rejects_untrusted_writes_and_error_is_not_cached(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("business_login"), {"email": "someone@example.com"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("no-store", response["Cache-Control"])


@override_settings(ALLOWED_HOSTS=["testserver"])
class PWAWorkspaceTests(TestCase):
    def setUp(self):
        self.user = TaskIOUser.objects.create_user(
            email="pwa@example.com", password="PwaTestSecret!91"
        )
        self.businesses = []
        ClarivoPlan.objects.filter(slug="logistics").update(is_active=True)
        for vertical, plan in (
            (Business.Vertical.SERVICE, "pro"),
            (Business.Vertical.LOGISTICS, "logistics"),
        ):
            business = Business.objects.create(
                name=f"PWA {vertical}", slug=f"pwa-{vertical.lower()}", vertical=vertical
            )
            BusinessUser.objects.create(
                business=business, user=self.user, role=BusinessUser.Role.OWNER
            )
            BusinessSubscription.objects.create(
                business=business,
                plan=ClarivoPlan.objects.get(slug=plan),
                status=BusinessSubscription.Status.ACTIVE,
                billing_interval=BusinessSubscription.BillingInterval.YEARLY,
            )
            self.businesses.append(business)
        self.client.force_login(self.user)

    def switch(self, business):
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = business.pk
        session.save()

    def test_both_verticals_reuse_pwa_shell_and_private_headers(self):
        for business in self.businesses:
            with self.subTest(vertical=business.vertical):
                self.switch(business)
                for route in (
                    "agent_dashboard",
                    "staff_client_list",
                    "business_subscription",
                    "business_settings",
                    "saas_profile",
                ):
                    response = self.client.get(reverse(route))
                    self.assertEqual(response.status_code, 200, route)
                    self.assertContains(response, 'data-worker="/service-worker.js"')
                    self.assertContains(response, 'data-private="true"')
                    self.assertIn("no-store", response["Cache-Control"])
                    self.assertIn("private", response["Cache-Control"])

    def test_logout_and_following_private_navigation_never_return_cached_screen(self):
        self.switch(self.businesses[0])
        self.client.get(reverse("agent_dashboard"))
        response = self.client.get(reverse("logout"))
        self.assertRedirects(response, reverse("business_login"))
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("no-store", response["Cache-Control"])
        login = self.client.get(reverse("business_login"))
        self.assertContains(login, 'data-private="false"')

    def test_offline_document_is_identical_for_both_authenticated_workspaces(self):
        documents = []
        for business in self.businesses:
            self.switch(business)
            with self.assertNumQueries(0):
                response = self.client.get(reverse("pwa_offline"))
            documents.append(response.content)
            self.assertNotContains(response, business.name)
            self.assertNotContains(response, self.user.email)
        self.assertEqual(*documents)

    def test_tenant_and_vertical_access_remain_enforced(self):
        foreign = BusinessClient.objects.create(
            business=self.businesses[1], first_name="Private", last_name="Customer"
        )
        self.switch(self.businesses[0])
        response = self.client.get(reverse("staff_client_detail", args=[foreign.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.get(reverse("logistics_parcel_list"))
        self.assertRedirects(response, reverse("business_subscription"))

    def test_public_tracking_remains_separate(self):
        self.switch(self.businesses[1])
        with self.assertNumQueries(0):
            response = self.client.get(reverse("logistics_public_tracking"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-worker=")
        self.assertNotContains(response, self.user.email)
        self.assertIn("no-store", response["Cache-Control"])
