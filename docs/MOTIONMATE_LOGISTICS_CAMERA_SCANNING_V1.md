# Motionmate Logistics Camera Scanning V1

Camera scanning is an optional input source on the existing authenticated
Logistics Scan Parcel page. It is online only and introduces no models,
migrations, endpoints, Parcel lifecycle changes, billing changes, native wrapper,
DataWedge integration or offline mutation queue.

## Capability decision and decoder boundary

Native `BarcodeDetector` is preferred only when `getSupportedFormats()` actually
reports QR support. Available requested 1D formats are included too. Merely having
the constructor is insufficient: platform support varies, and Safari/iOS cannot
be assumed to provide an enabled native detector. Detection is capability based,
without user-agent sniffing.

When native QR detection is absent, incomplete, or fails to initialize, the page
loads the pinned, self-contained `@zxing/browser` 0.2.1 UMD bundle from its own
static assets. This maintained release supplies a `BrowserMultiFormatReader` for
practical Safari/iOS and non-native desktop coverage. The bundle is 441,121 bytes
uncompressed / about 108 KiB gzip, loads only after explicit camera activation
when required, and has no runtime CDN or frontend framework dependency. Provenance,
SHA-256 and MIT/Apache notices are in `src/static/vendors/zxing/`.

Sources used for the decision:

- [BarcodeDetector availability and formats](https://developer.mozilla.org/en-US/docs/Web/API/BarcodeDetector)
- [getUserMedia secure-context, permission and error behavior](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
- [ZXing browser 0.2.1 release](https://github.com/zxing-js/browser/releases/tag/v0.2.1)
- [ZXing browser reader implementation](https://github.com/zxing-js/browser/tree/v0.2.1/src/readers)

Both decoders implement one internal `detect(video) / dispose()` interface. They
only decode local pixels and do not own camera capture, timers or Parcel lookup.
The fallback uses a transient canvas, bounds processing width to 960 pixels and
clears it after each attempt; disposal also clears its backing buffer. Ordinary
no-code/checksum/format exceptions mean keep scanning; unexpected decoder errors
stop capture and leave manual entry available. Decoding runs serially, at most
approximately five attempts per second, without overlapping promises.

Requested formats are QR, Code 128, Code 39, EAN-13, EAN-8, UPC-A and UPC-E. Native
formats are intersected with the browser's supported set; fallback formats are
explicitly restricted to that list. If native detection returns several codes,
QR is preferred. Format never changes Parcel validation or authorization. For
example, an ordinary EAN/UPC product number is decoded but fails the existing
48-character hexadecimal Parcel tracking-code validation. URLs and arbitrary
barcode contents are not transformed into tracking codes.

## Flow and camera lifecycle

1. The user selects **Scan with Camera** on Scan Parcel. Page load never requests
   camera permission or starts a stream.
2. Capability/HTTPS/connection checks run. The inline preview, instructions,
   text status and keyboard-accessible **Stop Camera** control appear.
3. `getUserMedia` requests video only, preferring `facingMode: environment` with
   an ideal constraint. A device without a rear camera can use its available
   camera; an overconstrained rear-camera request retries with ordinary video.
4. One decoded string closes the preview and releases all tracks **before** calling
   `window.MotionmateParcelScan.submitCode(rawString)`.
5. Existing normalization, form validation, CSRF-protected POST, authenticated
   tenant-safe resolver and result/actions handle everything after decoding.
6. Existing lifecycle actions still use the event service, UUID receipt and
   expected-status checks. Their success resets/refocuses the existing workflow.
   The user can explicitly open the camera again for the next scan.

Stop, Escape, closing the panel, manual submission, Next Scan, `pagehide`, page
visibility loss and track disconnection release capture and cancel pending work.
No automatic restart occurs after returning to a backgrounded page. A generation
token prevents late permission/playback/decode promises from submitting after
cancel or affecting a newer camera session. If permission arrives after cancel,
the returned stream is stopped immediately. There is one pending decode loop and
one submission per detection burst; the existing pending-submit guard and service
receipts provide lookup/action retry protection.

## Errors, accessibility and privacy

Permission denial, absent cameras, busy/unreadable cameras, unavailable APIs,
insecure contexts, decoder load failure, disconnected tracks and unexpected
decode failures receive readable text guidance. Stop remains usable while
permission is pending. Invalid tracking codes and missing/foreign Parcels use the
existing scanner feedback; capture has already stopped. Manual typing, paste,
Enter and keyboard-wedge input remain available throughout.

The UI has named buttons, `aria-controls`/`aria-expanded`, a labelled preview
region, live text status, `playsinline`/muted video and restored input focus.
It uses the existing 48px action-target minimum and 56px tracking field. The
preview fits its container and is bounded to 42vh, allowing portrait/landscape
layouts without restarting a scan. The page can scroll to reach controls.

Only the Logistics scan template loads the camera adapter. SERVICE pages and the
shared PWA foundation are unchanged. Camera strings always pass through the
existing tenant/role/effective-access checks. No frames, images or recordings are
uploaded, persisted or placed in Cache Storage. No scan analytics or additional
code logging is introduced. The camera adapter sends no HTTP request itself
apart from loading its local decoder script; operational requests remain ordinary
existing scanner POSTs. Offline capture/lookup is not queued.

## Verification and deployment boundary

Automated checks use isolated in-memory SQLite and Chromium. Camera tests use an
ephemeral HTTPS proxy with a self-signed certificate exception **only in the test
browser**; application TLS validation is not changed. Media comes from synthetic
canvas tracks, not a physical camera. Native detection and permission outcomes
are mocked; fallback QR and Code 128 decoding use real generated pixels.

The camera browser suite covers decoded-string delegation to `submitCode`, exact
existing lookup requests, repeated detections, valid lifecycle actions, permission
and busy/missing-camera failures, no rear camera, invalid/EAN codes, missing and
foreign Parcels, absent camera API, decoder-load failure, unexpected decode failure,
manual fallback, cancel while permission/decode is pending, Stop/Escape/panel close,
visibility/pagehide/navigation cleanup, offline rejection and private-cache safety.
Layout checks cover 320, 390, 430 and 768px plus rotation. The iPhone-sized Chromium
profile disables native detection and exercises the real fallback. An actually
installed Chromium PWA opens the scan page in its standalone window over HTTPS;
it uses the same synthetic camera and existing lookup.

Reproduce the checks separately (the existing scanner browser class has its own
migration-seeded fixture lifecycle):

```sh
export LOGISTICS_LOCAL_BILLING_BYPASS=False DEBUG=True DATABASE_URL=
export DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: PYTHONPATH=src:.
export PWA_CHROMIUM=/path/to/chromium
.venv/bin/python src/manage.py test apps.logistics.test_scan apps.logistics.test_parcels apps.logistics.test_mobile_ux taskio.test_pwa --noinput
.venv/bin/python src/manage.py test scripts.logistics_camera_browser_check --noinput
.venv/bin/python src/manage.py test scripts.logistics_scan_browser_check --noinput
```

Results: **74 focused backend/mobile/PWA tests**, **5 camera browser tests** and
**1 existing scanner browser test** pass. Scanner regression includes typing,
paste/CR-LF-tab normalization, duplicate Enter, lost-write-response retry, focus,
320–1440px layout and button contrast in light/dark themes. Layout metrics and
synthetic screenshots are under `/tmp/motionmate-camera-browser/`; final logs are
`/tmp/motionmate-camera-backend-v1.log`, `/tmp/motionmate-camera-browser-v1.log`
and `/tmp/motionmate-camera-scanner-regression.log`.

No physical Android or iPhone/Safari camera has been verified. Chromium device
emulation and localhost HTTPS do not establish deployed or Safari behavior.
SQLite does not establish PostgreSQL locking behavior. No live provider billing,
deployed cache/proxy or broader production-readiness claim follows from these tests.

Before accepting the final real-user pilot checkpoint, serve the new assets via
the normal `collectstatic` deployment and verify the actual trusted HTTPS origin,
camera Permissions Policy (including any iframe policy), Android rear camera and
installed PWA, iPhone Safari/Home Screen fallback, grant/deny/revoke flows, rotation,
background/return/navigation release, low light/damaged labels, rapid repeated scans,
invalid/foreign codes, and ordinary manual/keyboard-scanner fallback. Complete the
existing pilot billing/cache/proxy checks in their intended environment too.
The implementation is ready to enter that supervised checkpoint, not a completed
physical-device or production acceptance certification.
