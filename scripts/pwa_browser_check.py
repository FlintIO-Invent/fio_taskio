"""Optional real Chromium checks on an isolated Django test DB.

Run: python src/manage.py test scripts.pwa_browser_check --noinput
Requires Playwright and a Chromium binary (PWA_CHROMIUM may select one).
Mobile device profiles are simulations, not physical-device installs.
Chromium installs/launches/uninstalls the app in a temporary browser profile.
"""

import json
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import (
    Business,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    UserOnboardingState,
)


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class PWABrowserChecks(StaticLiveServerTestCase):
    def test_desktop_mobile_and_standalone_shells(self):
        from playwright.sync_api import sync_playwright

        output = Path(os.environ.get("PWA_QA_OUTPUT", "/tmp/motionmate-pwa-browser"))
        output.mkdir(parents=True, exist_ok=True)
        ClarivoPlan.objects.filter(slug="logistics").update(is_active=True)
        for vertical in (Business.Vertical.SERVICE, Business.Vertical.LOGISTICS):
            user = TaskIOUser.objects.create_user(
                email=f"pwa-{vertical.lower()}@example.com", password="PwaTestSecret!91"
            )
            business = Business.objects.create(
                name=f"PWA {vertical}", slug=f"pwa-{vertical.lower()}", vertical=vertical
            )
            BusinessUser.objects.create(business=business, user=user, role=BusinessUser.Role.OWNER)
            UserOnboardingState.objects.create(business=business, user=user, completed_welcome=True)
            BusinessSubscription.objects.create(
                business=business,
                plan=ClarivoPlan.objects.get(
                    slug="pro" if vertical == Business.Vertical.SERVICE else "logistics"
                ),
                status=BusinessSubscription.Status.ACTIVE,
                billing_interval=BusinessSubscription.BillingInterval.YEARLY,
            )

        results = []
        with sync_playwright() as playwright:
            profiles = {
                "desktop": {"viewport": {"width": 1440, "height": 900}},
                "android": playwright.devices["Pixel 7"],
                "iphone": playwright.devices["iPhone 13"],
                "ipad": playwright.devices["iPad Mini"],
            }
            for profile, device in profiles.items():
                if os.environ.get("PWA_TEST_PROFILE") not in (None, profile):
                    continue
                for vertical in (Business.Vertical.SERVICE, Business.Vertical.LOGISTICS):
                    if os.environ.get("PWA_TEST_VERTICAL") not in (None, vertical):
                        continue
                    with self.subTest(profile=profile, vertical=vertical), ExitStack() as cleanup:
                        profile_dir = cleanup.enter_context(
                            tempfile.TemporaryDirectory(prefix="motionmate-pwa-")
                        )
                        context = cleanup.enter_context(
                            playwright.chromium.launch_persistent_context(
                                profile_dir,
                                headless=True,
                                executable_path=os.environ.get("PWA_CHROMIUM"),
                                ignore_default_args=["--disable-back-forward-cache"],
                                **{
                                    key: value
                                    for key, value in device.items()
                                    if key != "default_browser_type"
                                },
                            )
                        )
                        context.set_default_timeout(10000)
                        page = context.new_page()
                        errors = []
                        page.on(
                            "pageerror",
                            lambda error, errors=errors: errors.append(error.stack or str(error)),
                        )
                        # External theme fonts are unnecessary to the shell test.
                        page.route("https://**/*", lambda route: route.abort())
                        page.goto(self.live_server_url + reverse("business_login"))
                        page.locator('[name="email"]').fill(f"pwa-{vertical.lower()}@example.com")
                        page.locator('[name="password"]').fill("PwaTestSecret!91")
                        page.get_by_role("button", name="Sign In", exact=True).click()
                        page.wait_for_url("**" + reverse("agent_dashboard"))
                        page.evaluate("navigator.serviceWorker.ready")
                        if not page.evaluate("Boolean(navigator.serviceWorker.controller)"):
                            page.reload()
                        page.wait_for_function("navigator.serviceWorker.controller !== null")
                        cdp = context.new_cdp_session(page)
                        manifest = cdp.send("Page.getAppManifest")
                        self.assertFalse(manifest["errors"], manifest)
                        self.assertEqual(
                            json.loads(manifest["data"])["start_url"], reverse("agent_dashboard")
                        )
                        installability = cdp.send("Page.getInstallabilityErrors")
                        self.assertEqual(installability["installabilityErrors"], [], installability)
                        app_id = self.live_server_url + reverse("agent_dashboard")
                        browser_cdp = context.browser.new_browser_cdp_session()
                        browser_cdp.send(
                            "PWA.install", {"manifestId": app_id, "installUrlOrBundleUrl": page.url}
                        )
                        cleanup.callback(browser_cdp.send, "PWA.uninstall", {"manifestId": app_id})
                        browser_cdp.send(
                            "PWA.changeAppUserSettings",
                            {"manifestId": app_id, "displayMode": "standalone"},
                        )
                        with context.expect_page() as launched:
                            browser_cdp.send("PWA.launch", {"manifestId": app_id})
                        previous_page = page
                        page = launched.value
                        page.wait_for_url("**" + reverse("agent_dashboard"))
                        page.wait_for_load_state()
                        previous_page.close()
                        page.on(
                            "pageerror",
                            lambda error, errors=errors: errors.append(error.stack or str(error)),
                        )
                        page.route("https://**/*", lambda route: route.abort())
                        self.assertTrue(
                            page.evaluate("matchMedia('(display-mode: standalone)').matches")
                        )
                        if page.get_by_role("button", name="Skip for now", exact=True).is_visible():
                            page.get_by_role("button", name="Skip for now", exact=True).click()
                            page.locator(".modal-backdrop").wait_for(state="hidden")
                        page.screenshot(
                            path=str(output / f"{profile}-{vertical.lower()}-dashboard.png"),
                            full_page=True,
                        )
                        self.assertLessEqual(
                            page.evaluate("document.documentElement.scrollWidth"),
                            page.viewport_size["width"],
                        )

                        if page.get_by_role("button", name="Toggle Navigation").is_visible():
                            page.get_by_role("button", name="Toggle Navigation").click()
                        page.locator('[href="#nv-client"]').click()
                        page.locator(
                            '.navbar-vertical a[href="' + reverse("staff_client_list") + '"]'
                        ).click()
                        page.wait_for_url("**" + reverse("staff_client_list"))
                        page.go_back()
                        page.wait_for_url("**" + reverse("agent_dashboard"))
                        self.assertFalse(
                            page.evaluate(
                                "document.documentElement.classList.contains('pwa-private-hidden')"
                            )
                        )

                        form_route = (
                            "logistics_parcel_register"
                            if vertical == Business.Vertical.LOGISTICS
                            else "staff_client_create"
                        )
                        page.goto(self.live_server_url + reverse(form_route))
                        self.assertTrue(
                            page.locator('form [name="csrfmiddlewaretoken"]').first.count()
                        )
                        if vertical == Business.Vertical.LOGISTICS:
                            page.evaluate(
                                """() => {
                              const modal = document.getElementById('parcelClientModal');
                              modal.addEventListener('shown.bs.modal', () => { modal.dataset.qaReady = 'true'; }, {once: true});
                            }"""
                            )
                            page.get_by_role("button", name="Add Client", exact=True).click()
                            page.wait_for_function(
                                "document.getElementById('parcelClientModal').dataset.qaReady === 'true'"
                            )
                            self.assertTrue(
                                page.locator('[name="new_client-first_name"]').is_visible()
                            )
                            page.screenshot(path=str(output / f"{profile}-logistics-modal.png"))
                            page.locator(
                                '#parcelClientModal [data-bs-dismiss="modal"]'
                            ).first.click()
                            page.locator("#parcelClientModal").wait_for(state="hidden")

                        context.set_offline(True)
                        page.locator(".pwa-connectivity").wait_for(state="visible")
                        self.assertFalse(
                            page.evaluate(
                                """() => {
                          const form = document.querySelector('form[method="post"]');
                          return form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
                        }"""
                            )
                        )
                        self.assertEqual(
                            page.evaluate(
                                "fetch('/logistics/parcels/1/update/', {method: 'POST'}).then(() => 'unexpected success', () => 'failed')"
                            ),
                            "failed",
                        )
                        response = page.goto(self.live_server_url + reverse("agent_dashboard"))
                        self.assertEqual(response.status, 503)
                        self.assertTrue(
                            page.get_by_role("heading", name="Connection unavailable").is_visible()
                        )
                        self.assertFalse(page.locator("form").count())
                        page.screenshot(
                            path=str(output / f"{profile}-{vertical.lower()}-offline.png")
                        )
                        cached = page.evaluate(
                            """async () => {
                          const keys = await caches.keys();
                          return (await Promise.all(keys.filter(key => key.startsWith('motionmate-pwa-')).map(async key =>
                            (await (await caches.open(key)).keys()).map(request => new URL(request.url).pathname)))).flat();
                        }"""
                        )
                        self.assertEqual(len(cached), 7)
                        self.assertTrue(
                            all(
                                path == reverse("pwa_offline") or path.startswith("/static/assets/")
                                for path in cached
                            )
                        )

                        context.set_offline(False)
                        page.get_by_role("button", name="Try again").click()
                        page.wait_for_url("**" + reverse("agent_dashboard"))
                        page.locator("#navbarDropdownUser").click()
                        page.get_by_role("link", name="Logout", exact=True).click()
                        page.wait_for_url(
                            lambda url: urlsplit(url).path == reverse("business_login")
                        )
                        page.go_back()
                        page.wait_for_url(
                            lambda url: urlsplit(url).path == reverse("business_login")
                        )
                        self.assertFalse(page.locator("#navbarDropdownUser").count())
                        # Login through the installed window uses the same Django session/CSRF flow.
                        page.locator('[name="email"]').fill(f"pwa-{vertical.lower()}@example.com")
                        page.locator('[name="password"]').fill("PwaTestSecret!91")
                        page.get_by_role("button", name="Sign In", exact=True).click()
                        page.wait_for_url("**" + reverse("agent_dashboard"))
                        self.assertTrue(
                            page.evaluate("matchMedia('(display-mode: standalone)').matches")
                        )
                        page.locator("#navbarDropdownUser").click()
                        page.get_by_role("link", name="Logout", exact=True).click()
                        page.wait_for_url(
                            lambda url: urlsplit(url).path == reverse("business_login")
                        )
                        # A logged-out offline back/navigation cannot recover private HTML.
                        context.set_offline(True)
                        page.go_back()
                        self.assertTrue(
                            page.get_by_role("heading", name="Connection unavailable").is_visible()
                        )
                        self.assertFalse(page.locator("#navbarDropdownUser").count())
                        self.assertEqual(errors, [], errors)
                        results.append(
                            {
                                "profile": profile,
                                "vertical": vertical,
                                "installability_errors": [],
                                "cached_paths": cached,
                                "page_errors": errors,
                            }
                        )
        (output / "browser-results.json").write_text(json.dumps(results, indent=2))
