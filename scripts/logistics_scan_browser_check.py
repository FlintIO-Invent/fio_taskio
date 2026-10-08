"""Optional Playwright checks on an isolated database; no physical scanner required.

Run with PYTHONPATH=src:. and PWA_CHROMIUM pointing to the Chromium binary:
python src/manage.py test scripts.logistics_scan_browser_check --noinput
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse

from apps.businesses.models import UserOnboardingState
from apps.logistics import test_parcels as fixtures
from apps.logistics.models import ParcelEvent
from apps.logistics.shipment_services import assign_parcel, create_shipment


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class ScanBrowserChecks(StaticLiveServerTestCase):
    switch = fixtures.ParcelTests.switch
    register = fixtures.ParcelTests.register

    def setUp(self):
        fixtures.ParcelTests.setUp(self)
        UserOnboardingState.objects.create(
            business=self.business, user=self.user, completed_welcome=True
        )
        UserOnboardingState.objects.create(
            business=self.service, user=self.user, completed_welcome=True
        )
        self.parcels = [self.register() for _ in range(4)]
        shipment = create_shipment(
            business=self.business,
            actor=self.user,
            origin="Miami",
            destination="Curacao",
            transport_mode="SEA",
        )
        assign_parcel(
            business=self.business, actor=self.user, shipment=shipment, parcel=self.parcels[0]
        )

    def test_manual_wedge_paste_retry_and_layout(self):
        from playwright.sync_api import sync_playwright

        output = Path("/tmp/motionmate-scanner-browser")
        output.mkdir(parents=True, exist_ok=True)
        metrics = []
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as playwright:

            def db(action, *args, **kwargs):
                return database.submit(action, *args, **kwargs).result()

            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            context = browser.new_context(viewport={"width": 320, "height": 844}, has_touch=True)
            context.add_cookies(
                [
                    {
                        "name": "sessionid",
                        "value": self.client.cookies["sessionid"].value,
                        "url": self.live_server_url,
                    }
                ]
            )
            context.route("https://**/*", lambda route: route.abort())
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for width, parcel in zip((320, 390, 768, 1440), self.parcels, strict=True):
                with self.subTest(width=width):
                    page.set_viewport_size({"width": width, "height": 844})
                    page.goto(self.live_server_url + reverse("logistics_parcel_scan"))
                    field = page.get_by_label("Parcel tracking code", exact=True)
                    self.assertTrue(field.evaluate("(input) => document.activeElement === input"))
                    self.assertGreaterEqual(field.bounding_box()["height"], 56)
                    # A physical wedge sends these ordinary keys to the focused field.
                    page.keyboard.type(parcel.tracking_code.lower())
                    held = []

                    def pause_lookup(route, _request, held=held):
                        if route.request.method == "POST":
                            held.append(route)
                        else:
                            route.continue_()

                    context.route("**/logistics/parcels/scan/", pause_lookup)
                    page.keyboard.press("Enter")
                    page.wait_for_function(
                        'document.querySelector("[data-scan-workflow]").getAttribute("aria-busy") === "true"'
                    )
                    page.keyboard.press("Enter")
                    page.evaluate('document.querySelector("[data-scan-lookup]").requestSubmit()')
                    self.assertEqual(len(held), 1)
                    held[0].continue_()
                    context.unroute("**/logistics/parcels/scan/", pause_lookup)
                    page.locator(f'[data-scan-parcel="{parcel.pk}"]').wait_for()
                    page.wait_for_function(
                        'document.querySelector("[data-scan-workflow]").getAttribute("aria-busy") === "false"'
                    )
                    self.assertEqual(field.input_value(), parcel.tracking_code)
                    if width == 320:
                        self.assertTrue(
                            page.locator("[data-scan-result]")
                            .get_by_text("Sea", exact=False)
                            .count()
                        )
                    layout = page.evaluate(
                        """() => ({width:innerWidth, scrollWidth:document.documentElement.scrollWidth, shortButtons:[...document.querySelectorAll('.logistics-scan button')].filter(e=>e.getClientRects().length && e.getBoundingClientRect().height < 48).map(e=>e.innerText)})"""
                    )
                    self.assertEqual(layout["scrollWidth"], width)
                    self.assertEqual(layout["shortButtons"], [])
                    # Check normal action text in both theme modes using rendered colors.
                    for theme in ("light", "dark"):
                        page.evaluate(
                            "(theme) => document.documentElement.dataset.bsTheme=theme", theme
                        )
                        page.wait_for_timeout(250)
                        contrast = page.evaluate(
                            r"""() => {
                          const rgb = value => value.match(/[\d.]+/g).slice(0,3).map(Number);
                          const lum = channels => channels.map(v => {v /= 255; return v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4;}).reduce((sum,v,i) => sum+v*[.2126,.7152,.0722][i],0);
                          return [...document.querySelectorAll('.logistics-scan button')].filter(e => e.getClientRects().length).map(button => {
                            const style = getComputedStyle(button);
                            let element = button, background;
                            do {background = getComputedStyle(element).backgroundColor; element = element.parentElement;} while(element && (background === 'transparent' || background === 'rgba(0, 0, 0, 0)'));
                            const a = lum(rgb(style.color)), b = lum(rgb(background));
                            return {name:button.innerText, ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
                          });
                        }"""
                        )
                        for control in contrast:
                            self.assertGreaterEqual(control["ratio"], 4.5, (theme, control))
                    page.evaluate('document.documentElement.dataset.bsTheme="light"')
                    page.wait_for_timeout(250)
                    metrics.append(layout)
                    page.screenshot(path=str(output / f"{width}-scan-result.png"), full_page=True)
                    # Keyboard activation and Next Scan remain usable on each viewport.
                    page.get_by_role("button", name="Next Scan", exact=True).click()
                    self.assertEqual(field.input_value(), "")
                    self.assertEqual(page.locator("[data-scan-parcel]").count(), 0)
                    self.assertTrue(field.evaluate("(input) => document.activeElement === input"))
                    # Pasted CR/LF/tab suffixes feed the same resolver.
                    field.evaluate(
                        r"""(input, code) => {
                      const clipboard = new DataTransfer(); clipboard.setData('text/plain', ' \t' + code.toLowerCase() + '\r\n\t');
                      input.dispatchEvent(new ClipboardEvent('paste', {clipboardData:clipboard, bubbles:true, cancelable:true}));
                    }""",
                        parcel.tracking_code,
                    )
                    field.press("Enter")
                    page.locator(f'[data-scan-parcel="{parcel.pk}"]').wait_for()
                    page.wait_for_function(
                        'document.querySelector("[data-scan-workflow]").getAttribute("aria-busy") === "false"'
                    )
                    self.assertEqual(db(ParcelEvent.objects.filter(parcel=parcel).count), 1)
                    action = page.locator('[data-scan-action] button[value="RECEIVED"]')
                    token = page.locator(
                        '[data-scan-action] [name="idempotency_key"]'
                    ).input_value()
                    action_url = "**" + reverse("logistics_parcel_scan_action", args=[parcel.pk])

                    def lose_write_response(route):
                        route.fetch()  # Commit the ordinary service-backed POST, then lose its response.
                        route.abort()

                    context.route(action_url, lose_write_response)
                    action.evaluate("(button) => {button.click(); button.click();}")
                    page.get_by_text("The update could not be confirmed.", exact=False).wait_for()
                    page.wait_for_function(
                        'document.querySelector("[data-scan-workflow]").getAttribute("aria-busy") === "false"'
                    )
                    self.assertEqual(
                        page.locator('[data-scan-action] [name="idempotency_key"]').input_value(),
                        token,
                    )
                    self.assertEqual(
                        db(ParcelEvent.objects.filter(parcel=parcel, status="RECEIVED").count), 1
                    )
                    context.unroute(action_url, lose_write_response)
                    action.click()
                    page.locator("[data-scan-action-success]").wait_for()
                    page.wait_for_function(
                        'document.querySelector("[data-scan-workflow]").getAttribute("aria-busy") === "false"'
                    )
                    self.assertEqual(field.input_value(), "")
                    self.assertEqual(page.locator("[data-scan-parcel]").count(), 0)
                    self.assertTrue(field.evaluate("(input) => document.activeElement === input"))
                    self.assertEqual(
                        db(ParcelEvent.objects.filter(parcel=parcel, status="RECEIVED").count), 1
                    )
                    # Camera-ready adapter is independent of keyboard events.
                    self.assertTrue(
                        page.evaluate(
                            '(code) => window.MotionmateParcelScan.submitCode(code + "\\r\\n")',
                            parcel.tracking_code,
                        )
                    )
                    page.locator(f'[data-scan-parcel="{parcel.pk}"]').wait_for()
                    page.wait_for_function(
                        'document.querySelector("[data-scan-workflow]").getAttribute("aria-busy") === "false"'
                    )
                    field.fill("invalid")
                    self.assertEqual(page.locator("[data-scan-parcel]").count(), 0)
                    field.press("Enter")
                    page.get_by_text(
                        "Enter a complete 48-character tracking code.", exact=True
                    ).wait_for()
                    self.assertTrue(field.evaluate("(input) => document.activeElement === input"))
                    field.fill("0" * 48)
                    field.press("Enter")
                    page.get_by_text("Parcel not found in this workspace.", exact=False).wait_for()
                    self.assertEqual(page.locator("[data-scan-parcel]").count(), 0)
                    self.assertTrue(field.evaluate("(input) => document.activeElement === input"))
                    # Offline capture rejects writes; it never clears or queues them as a success.
                    context.set_offline(True)
                    field.fill(parcel.tracking_code)
                    field.press("Enter")
                    self.assertEqual(field.input_value(), parcel.tracking_code)
                    self.assertFalse(page.locator("[data-scan-action-success]").count())
                    context.set_offline(False)
            self.assertEqual(errors, [])
            context.close()
            browser.close()
            database.submit(connections.close_all).result()
        (output / "results.json").write_text(
            json.dumps({"layouts": metrics, "page_errors": errors}, indent=2)
        )
