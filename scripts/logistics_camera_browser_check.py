"""HTTPS camera/PWA checks using synthetic media, never a physical camera.

Run with PYTHONPATH=src:. and PWA_CHROMIUM set to the installed Chromium binary.
Uses an ephemeral self-signed TLS proxy to the isolated Django test server.
"""

import http.client
import json
import os
import ssl
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse

from apps.businesses.models import UserOnboardingState
from apps.logistics import test_parcels as fixtures
from apps.logistics.models import ParcelEvent
from apps.logistics.parcel_services import register_parcel

# Real synthetic video tracks make playback/readiness representative. Only camera
# permission and native detection are mocked. Fallback QR decoding uses real pixels.
CAMERA_MOCK = r"""
(() => {
  const state = window.cameraTest = {
    calls: 0, stops: 0, detects: 0, results: [], submissions: [], constraints: [],
    permissionError: '', decodeError: false, pendingPermission: false,
    pendingDecode: false, noRear: false, supported: ['qr_code', 'code_128', 'code_39', 'ean_13', 'ean_8', 'upc_a', 'upc_e'],
  };
  Object.defineProperty(window, 'BarcodeDetector', {configurable: true, writable: true, value: class {
    static async getSupportedFormats() { return state.supported; }
    constructor(options) { state.formats = options.formats; }
    async detect() {
      state.detects++;
      if (state.decodeError) throw new Error('Decode failed');
      if (state.pendingDecode) return new Promise(resolve => { state.resolveDecode = resolve; });
      return state.results;
    }
  }});
  Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {configurable: true, writable: true, value: async constraints => {
    state.calls++;
    state.constraints.push(constraints);
    if (state.permissionError) throw new DOMException('Test permission/camera failure', state.permissionError);
    if (state.noRear && constraints.video.facingMode) throw new DOMException('No rear camera', 'OverconstrainedError');
    const canvas = document.createElement('canvas');
    canvas.width = 640; canvas.height = 480;
    canvas.getContext('2d').fillRect(0, 0, 640, 480);
    state.canvas = canvas;
    const media = canvas.captureStream(10);
    state.media = media;
    for (const track of media.getTracks()) {
      const originalStop = track.stop.bind(track);
      track.stop = () => {
        state.stops++;
        sessionStorage.setItem('cameraStops', String(Number(sessionStorage.getItem('cameraStops') || 0) + 1));
        originalStop();
      };
    }
    if (state.pendingPermission) await new Promise(resolve => { state.resolvePermission = resolve; });
    return media;
  }});
  document.addEventListener('DOMContentLoaded', () => {
    const original = window.MotionmateParcelScan;
    if (!original) return;
    window.MotionmateParcelScan = {
      normalizeCode: original.normalizeCode,
      submitCode: value => { state.submissions.push(value); return original.submitCode(value); },
    };
  });
})();
"""


@override_settings(
    DEBUG=True,
    ALLOWED_HOSTS=["localhost", "testserver"],
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
class CameraBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    switch = fixtures.ParcelTests.switch
    register = fixtures.ParcelTests.register

    def setUp(self):
        fixtures.ParcelTests.setUp(self)
        for business in (self.business, self.service):
            UserOnboardingState.objects.create(
                business=business, user=self.user, completed_welcome=True
            )
        self.parcel = self.register()
        self.foreign = register_parcel(
            business=self.other,
            actor=self.other_user,
            client=self.other_customer,
            **self.fields,
        )
        self.output = Path("/tmp/motionmate-camera-browser")
        self.output.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def https_origin(self):
        target = urlsplit(self.live_server_url)
        self.https_posts = post_paths = []

        class Proxy(BaseHTTPRequestHandler):
            def forward(self):
                if self.command == "POST":
                    post_paths.append(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                headers = dict(self.headers)
                headers["X-Forwarded-Proto"] = "https"
                with closing(
                    http.client.HTTPConnection(target.hostname, target.port, timeout=30)
                ) as upstream:
                    upstream.request(self.command, self.path, body=body, headers=headers)
                    response = upstream.getresponse()
                    payload = response.read()
                    self.send_response(response.status)
                    for key, value in response.getheaders():
                        if key.lower() not in {"connection", "transfer-encoding", "content-length"}:
                            self.send_header(key, value)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    # Navigation/closing a PWA may cancel an in-flight static response.
                    with suppress(BrokenPipeError, ConnectionResetError, ssl.SSLEOFError):
                        self.wfile.write(payload)

            do_GET = do_POST = forward

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory(prefix="motionmate-camera-tls-") as folder:
            cert, key = Path(folder) / "cert.pem", Path(folder) / "key.pem"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=DNS:localhost",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            server = ThreadingHTTPServer(("localhost", 0), Proxy)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                yield f"https://localhost:{server.server_port}"
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)

    def authenticate(self, context, origin):
        context.add_cookies(
            [{"name": "sessionid", "value": self.client.cookies["sessionid"].value, "url": origin}]
        )
        context.add_init_script(CAMERA_MOCK)
        context.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith(origin + "/") else route.abort()
            ),
        )

    @contextmanager
    def browser_page(self, playwright, origin, **options):
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=os.environ.get("PWA_CHROMIUM"),
            args=["--ignore-certificate-errors"],
        )
        context = browser.new_context(ignore_https_errors=True, **options)
        self.authenticate(context, origin)
        page = context.new_page()
        page.set_default_timeout(10000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(origin + reverse("logistics_parcel_scan"))
            self.assertTrue(page.evaluate("isSecureContext"))
            yield page, context
            self.assertEqual(errors, [])
        finally:
            context.close()
            browser.close()

    def start_camera(self, page):
        page.get_by_role("button", name="Scan with Camera", exact=True).click()
        page.wait_for_function(
            "document.querySelector('[data-camera-status]').textContent.startsWith('Scanning…')"
        )

    def assert_stopped(self, page):
        self.assertTrue(page.locator("[data-camera-panel]").is_hidden())
        self.assertTrue(
            page.evaluate("document.querySelector('[data-camera-preview]').srcObject === null")
        )

    def wait_lookup(self, page):
        page.wait_for_function(
            "document.querySelector('[data-scan-workflow]').getAttribute('aria-busy') === 'false'"
        )

    def test_https_native_mobile_layout_decode_actions_and_rotation(self):
        from playwright.sync_api import sync_playwright

        layouts = []
        with (
            self.https_origin() as origin,
            ThreadPoolExecutor(max_workers=1) as database,
            sync_playwright() as playwright,
        ):
            with self.browser_page(
                playwright,
                origin,
                **{
                    key: value
                    for key, value in playwright.devices["Pixel 7"].items()
                    if key != "default_browser_type"
                },
            ) as (page, context):
                posts = self.https_posts
                for width in (320, 390, 430, 768):
                    with self.subTest(width=width):
                        page.set_viewport_size({"width": width, "height": 844})
                        page.reload()
                        self.assertEqual(page.evaluate("cameraTest.calls"), 0)
                        self.start_camera(page)
                        self.assertEqual(
                            page.evaluate("cameraTest.constraints[0].video.facingMode.ideal"),
                            "environment",
                        )
                        for viewport in (
                            {"width": width, "height": 844},
                            {"width": 844, "height": width},
                        ):
                            page.set_viewport_size(viewport)
                            layout = page.evaluate(
                                """() => {
                              const panel = document.querySelector('[data-camera-panel]');
                              const preview = panel.querySelector('video').getBoundingClientRect();
                              const stop = panel.querySelector('button');
                              return {width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
                                previewRight: preview.right, previewLeft: preview.left,
                                buttonHeight: stop.getBoundingClientRect().height};
                            }"""
                            )
                            self.assertEqual(layout["width"], layout["scrollWidth"])
                            self.assertGreaterEqual(layout["previewLeft"], 0)
                            self.assertLessEqual(layout["previewRight"], layout["width"])
                            self.assertGreaterEqual(layout["buttonHeight"], 48)
                            self.assertTrue(page.locator("[data-camera-stop]").is_visible())
                            layouts.append(layout)
                        page.set_viewport_size({"width": width, "height": 844})
                        page.screenshot(
                            path=str(self.output / f"{width}-preview.png"), full_page=True
                        )
                        raw = " \t" + self.parcel.tracking_code.lower() + "\r\n"
                        before = len(posts)
                        page.evaluate(
                            "raw => {cameraTest.results = [{rawValue: '1234567890128', format: 'ean_13'}, ...[1,2,3].map(() => ({rawValue: raw, format: 'qr_code'}))];}",
                            raw,
                        )
                        page.locator(f'[data-scan-parcel="{self.parcel.pk}"]').wait_for()
                        self.wait_lookup(page)
                        self.assert_stopped(page)
                        self.assertEqual(page.evaluate("cameraTest.submissions"), [raw])
                        self.assertEqual(page.evaluate("cameraTest.stops"), 1)
                        self.assertEqual(posts[before:], [reverse("logistics_parcel_scan")])
                        self.assertTrue(
                            page.get_by_label("Parcel tracking code", exact=True).evaluate(
                                "field => document.activeElement === field"
                            )
                        )
                action = page.locator('[data-scan-action] button[value="RECEIVED"]')
                action.evaluate("button => {button.click(); button.click();}")
                page.locator("[data-scan-action-success]").wait_for()
                self.wait_lookup(page)
                self.assertEqual(
                    database.submit(
                        ParcelEvent.objects.filter(parcel=self.parcel, status="RECEIVED").count
                    ).result(),
                    1,
                )
                self.assertEqual(
                    page.get_by_label("Parcel tracking code", exact=True).input_value(), ""
                )
                self.assertFalse(page.locator("[data-scan-parcel]").count())
            database.submit(connections.close_all).result()
        (self.output / "layouts.json").write_text(json.dumps(layouts, indent=2))

    def test_permissions_invalid_foreign_missing_and_manual_fallback(self):
        from playwright.sync_api import sync_playwright

        with self.https_origin() as origin, sync_playwright() as playwright:
            with self.browser_page(playwright, origin, viewport={"width": 390, "height": 844}) as (
                page,
                context,
            ):
                for error, text in (
                    ("NotAllowedError", "permission was denied"),
                    ("SecurityError", "permission was denied"),
                    ("NotFoundError", "No usable camera"),
                    ("NotReadableError", "already in use"),
                    ("AbortError", "already in use"),
                ):
                    with self.subTest(error=error):
                        page.reload()
                        page.evaluate("error => {cameraTest.permissionError = error;}", error)
                        page.get_by_role("button", name="Scan with Camera", exact=True).click()
                        page.locator("[data-camera-status]").filter(has_text=text).wait_for()
                        self.assert_stopped(page)
                page.reload()
                page.evaluate("cameraTest.noRear = true")
                self.start_camera(page)
                self.assertEqual(page.evaluate("cameraTest.constraints[1].video"), True)
                page.get_by_role("button", name="Stop Camera", exact=True).click()
                self.assert_stopped(page)
                page.reload()
                page.evaluate("cameraTest.decodeError = true")
                page.get_by_role("button", name="Scan with Camera", exact=True).click()
                page.locator("[data-camera-status]").filter(
                    has_text="could not continue"
                ).wait_for()
                self.assert_stopped(page)
                self.assertEqual(page.evaluate("cameraTest.stops"), 1)
                for raw, text in (
                    ("invalid", "complete 48-character tracking code"),
                    ("1234567890128", "complete 48-character tracking code"),
                    ("0" * 48, "Parcel not found in this workspace"),
                    (self.foreign.tracking_code, "Parcel not found in this workspace"),
                ):
                    with self.subTest(raw=raw):
                        page.reload()
                        self.start_camera(page)
                        page.evaluate("raw => {cameraTest.results = [{rawValue: raw}];}", raw)
                        page.locator("#scan-feedback").filter(has_text=text).wait_for()
                        self.assert_stopped(page)
                        self.assertEqual(page.evaluate("cameraTest.submissions"), [raw])
                        self.assertFalse(page.locator("[data-scan-parcel]").count())
                page.reload()
                page.evaluate("navigator.mediaDevices.getUserMedia = undefined")
                page.get_by_role("button", name="Scan with Camera", exact=True).click()
                page.locator("[data-camera-status]").filter(has_text="supported browser").wait_for()
                self.assert_stopped(page)
                # Capability exists but cannot decode QR: fallback load fails safely.
                page.reload()
                page.evaluate("cameraTest.supported = ['code_128']")
                context.route("**/vendors/zxing/*", lambda route: route.abort())
                page.get_by_role("button", name="Scan with Camera", exact=True).click()
                page.locator("[data-camera-status]").filter(
                    has_text="unavailable in this browser"
                ).wait_for()
                self.assert_stopped(page)
                self.assertEqual(page.evaluate("cameraTest.calls"), 0)
                field = page.get_by_label("Parcel tracking code", exact=True)
                field.fill(self.parcel.tracking_code)
                field.press("Enter")
                page.locator(f'[data-scan-parcel="{self.parcel.pk}"]').wait_for()
                self.wait_lookup(page)
                self.assertEqual(field.input_value(), self.parcel.tracking_code)

    def test_cleanup_pending_permission_decode_close_navigation_and_offline(self):
        from playwright.sync_api import sync_playwright

        with self.https_origin() as origin, sync_playwright() as playwright:
            with self.browser_page(playwright, origin) as (page, context):
                page.evaluate("cameraTest.pendingPermission = true")
                page.get_by_role("button", name="Scan with Camera", exact=True).click()
                page.wait_for_function("!!cameraTest.resolvePermission")
                page.get_by_role("button", name="Stop Camera", exact=True).click()
                page.evaluate("cameraTest.resolvePermission()")
                page.wait_for_function("cameraTest.stops === 1")
                self.assert_stopped(page)
                self.assertEqual(page.evaluate("cameraTest.submissions"), [])
                page.reload()
                page.evaluate("cameraTest.pendingDecode = true")
                self.start_camera(page)
                page.wait_for_function("!!cameraTest.resolveDecode")
                page.keyboard.press("Escape")
                page.evaluate(
                    "raw => cameraTest.resolveDecode([{rawValue: raw}])", self.parcel.tracking_code
                )
                self.assert_stopped(page)
                self.assertEqual(page.evaluate("cameraTest.submissions"), [])
                for close in (
                    "document.querySelector('[data-camera-panel]').hidden = true",
                    "Object.defineProperty(document, 'hidden', {configurable: true, value: true}); document.dispatchEvent(new Event('visibilitychange'))",
                    "window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))",
                ):
                    page.reload()
                    self.start_camera(page)
                    page.evaluate(close)
                    page.wait_for_function("cameraTest.stops === 1")
                    self.assert_stopped(page)
                page.reload()
                self.start_camera(page)
                field = page.get_by_label("Parcel tracking code", exact=True)
                field.fill(self.parcel.tracking_code)
                field.press("Enter")
                page.locator(f'[data-scan-parcel="{self.parcel.pk}"]').wait_for()
                self.wait_lookup(page)
                self.assert_stopped(page)
                self.assertEqual(page.evaluate("cameraTest.stops"), 1)
                page.reload()
                self.start_camera(page)
                before = page.evaluate("Number(sessionStorage.getItem('cameraStops'))")
                page.goto(origin + reverse("logistics_parcel_list"))
                self.assertEqual(
                    page.evaluate("Number(sessionStorage.getItem('cameraStops'))"), before + 1
                )
                page.goto(origin + reverse("logistics_parcel_scan"))
                context.set_offline(True)
                page.get_by_role("button", name="Scan with Camera", exact=True).click()
                page.locator("[data-camera-status]").filter(
                    has_text="connection is required"
                ).wait_for()
                self.assertEqual(page.evaluate("cameraTest.calls"), 0)
                self.assert_stopped(page)
                context.set_offline(False)

    def test_https_iphone_profile_real_fallback_qr_and_code128_decoding(self):
        from playwright.sync_api import sync_playwright
        from reportlab.graphics.barcode import createBarcodeDrawing

        with self.https_origin() as origin, sync_playwright() as playwright:
            with self.browser_page(
                playwright,
                origin,
                **{
                    key: value
                    for key, value in playwright.devices["iPhone 13"].items()
                    if key != "default_browser_type"
                },
            ) as (page, context):
                page.evaluate("window.BarcodeDetector = undefined")
                self.start_camera(page)
                self.assertTrue(page.evaluate("!!window.ZXingBrowser"))
                # Generate a QR fixture in memory with the pinned library's writer.
                # The app's real decoder sees it through actual synthetic video pixels.
                page.evaluate(
                    """async code => {
                  const svg = new ZXingBrowser.BrowserQRCodeSvgWriter().write(code, 360, 360);
                  const image = new Image();
                  image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(svg));
                  await image.decode();
                  const canvas = cameraTest.canvas;
                  const ctx = canvas.getContext('2d');
                  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
                  ctx.drawImage(image, 140, 60, 360, 360);
                  cameraTest.media.getVideoTracks()[0].requestFrame();
                }""",
                    self.parcel.tracking_code,
                )
                page.locator(f'[data-scan-parcel="{self.parcel.pk}"]').wait_for()
                self.wait_lookup(page)
                self.assert_stopped(page)
                self.assertEqual(
                    page.evaluate("cameraTest.submissions"), [self.parcel.tracking_code]
                )
                self.assertEqual(page.evaluate("cameraTest.stops"), 1)
                page.screenshot(
                    path=str(self.output / "iphone-fallback-result.png"), full_page=True
                )
                page.get_by_role("button", name="Next Scan", exact=True).click()
                barcode = createBarcodeDrawing(
                    "Code128",
                    value=self.parcel.tracking_code,
                    barWidth=1,
                    barHeight=120,
                    humanReadable=False,
                ).asString("svg")
                self.start_camera(page)
                page.evaluate(
                    """async svg => {
                    const canvas = cameraTest.canvas;
                    const image = new Image();
                    image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
                    await image.decode();
                    const ctx = canvas.getContext('2d');
                    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
                    ctx.drawImage(image, 20, 150);
                    cameraTest.media.getVideoTracks()[0].requestFrame();
                }""",
                    barcode,
                )
                page.locator(f'[data-scan-parcel="{self.parcel.pk}"]').wait_for()
                self.wait_lookup(page)
                self.assert_stopped(page)
                self.assertEqual(
                    page.evaluate("cameraTest.submissions"), [self.parcel.tracking_code] * 2
                )
                self.assertEqual(page.evaluate("cameraTest.stops"), 2)

    def test_https_installed_android_pwa_camera_and_private_cache(self):
        from playwright.sync_api import sync_playwright

        with (
            self.https_origin() as origin,
            tempfile.TemporaryDirectory(prefix="motionmate-camera-pwa-") as profile,
            sync_playwright() as playwright,
        ):
            context = playwright.chromium.launch_persistent_context(
                profile,
                headless=True,
                executable_path=os.environ.get("PWA_CHROMIUM"),
                args=["--ignore-certificate-errors"],
                ignore_https_errors=True,
                **{
                    key: value
                    for key, value in playwright.devices["Pixel 7"].items()
                    if key != "default_browser_type"
                },
            )
            self.authenticate(context, origin)
            page = context.new_page()
            page.goto(origin + reverse("agent_dashboard"))
            page.evaluate("navigator.serviceWorker.ready")
            page.reload()
            page.wait_for_function("navigator.serviceWorker.controller !== null")
            app_id = origin + reverse("agent_dashboard")
            cdp = context.browser.new_browser_cdp_session()
            installed = False
            try:
                cdp.send("PWA.install", {"manifestId": app_id, "installUrlOrBundleUrl": page.url})
                installed = True
                cdp.send(
                    "PWA.changeAppUserSettings", {"manifestId": app_id, "displayMode": "standalone"}
                )
                page.goto(origin + reverse("logistics_parcel_scan"))
                # Move the loaded page into the genuinely installed app window.
                # Preserve this test target's self-signed certificate exception.
                context.new_cdp_session(page).send(
                    "PWA.openCurrentPageInApp", {"manifestId": app_id}
                )
                page.wait_for_function("matchMedia('(display-mode: standalone)').matches")
                self.assertTrue(page.evaluate("isSecureContext"))
                self.assertTrue(page.evaluate("matchMedia('(display-mode: standalone)').matches"))
                self.start_camera(page)
                page.evaluate(
                    "raw => {cameraTest.results = [{rawValue: raw}];}", self.parcel.tracking_code
                )
                page.locator(f'[data-scan-parcel="{self.parcel.pk}"]').wait_for()
                self.wait_lookup(page)
                self.assert_stopped(page)
                cached = page.evaluate(
                    """async () => {
                  const urls = [];
                  for (const name of await caches.keys()) {
                    for (const request of await (await caches.open(name)).keys()) urls.push(request.url);
                  }
                  return urls;
                }"""
                )
                self.assertFalse(any("/logistics/" in url for url in cached), cached)
                page.screenshot(path=str(self.output / "installed-pwa-result.png"), full_page=True)
            finally:
                if installed:
                    cdp.send("PWA.uninstall", {"manifestId": app_id})
                context.close()
