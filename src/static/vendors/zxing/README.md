# Camera decoder fallback

Pinned self-contained upstream UMD bundle: `@zxing/browser` 0.2.1.
Source: https://github.com/zxing-js/browser/tree/v0.2.1
Package: https://registry.npmjs.org/@zxing/browser/-/browser-0.2.1.tgz
File: `package/umd/zxing-browser.min.js` (unmodified, 441,121 bytes).
SHA-256: `066bc34edfcdd4a33f0964aeec967752a0dea1ccaf36e58e319ac9fcb5070f6a`

The bundle contains `@zxing/library` 0.23.0 and `ts-custom-error` 3.3.1;
the corresponding MIT / Apache 2.0 notices are retained alongside it.
It loads from local static assets only when usable native QR detection is
unavailable and the user explicitly starts camera scanning. No runtime CDN,
frontend framework, package manager, camera capture helper, writer, or upload
API is used by the application.

To update, fetch the pinned npm tarball, extract only its UMD minified file and
license, review bundled dependencies and licenses, update the version/path/hash,
and rerun the camera browser checks (including real fallback QR decoding).
