# Parcel shipping labels V1

Existing Parcel party names, contact fields and legacy addresses are reused.
Migration 0018 adds eleven nullable shipping snapshot fields: address lines 1/2,
city, region and postal code for each party, plus recipient ISO alpha-2 country.
Existing sender ISO alpha-2/alpha-3 values remain supported. New choices use the
existing maintained pycountry country/territory list and searchable selectors.
An unchanged historical unmatched sender code can be retained; new invalid
country codes are rejected. There is no automatic historical backfill.

The existing registration/edit services validate and persist these fields and
record metadata changes in the normal private audit history. CRM Client remains
the bill-to reference. Optional prefill copies only empty fields after an explicit
button click and requires existing CRM read and Parcel write access. It saves
neither Client nor Parcel. Labels use stored snapshots, never live Client values.

## Label and export

Parcel detail provides Preview Shipping Label, Print Shipping Label and Download
PDF, including immediately after registration. Preview is a standalone page.
One ReportLab vector drawing supplies both SVG preview/browser printing and the
PDF. PDF and print CSS use exactly 288 × 432 points / 4 × 6 inches; dashboard
chrome and the preview toolbar are absent from print output.

The black-and-white drawing includes Business name, Motionmate Logistics,
shipping-party snapshots, country names, geographic origin/destination,
registered facility codes where present, the stored tracking code, a real QR
symbol, Code 128, optional weight and permitted Shipment reference/transport mode.
Related Shipment details are included only through the existing Shipment access
query. No invoice amounts, tax IDs, private notes or actor/site audit history are
printed. Missing historical party information is explicitly marked as missing.
Structured streets take precedence over legacy free text; legacy streets remain
available when only a locality has been added.

Both symbols encode the exact stored tracking code, without URL, another token,
case conversion or shortened identifier. The existing ReportLab encoders handle
QR and Code 128. Code 128 runs vertically along the six-inch edge so legacy
48-character codes and secure 46-character V2 codes fit without compressing them
across four inches. Its module width is 0.66 points (9.17 mils), with the encoder's
quiet zones; QR keeps its four-module border. Reference:
[ReportLab barcode documentation](https://docs.reportlab.com/reportlab/barcode/).

Text wraps using the embedded font's measured widths, including long unbroken
tokens. Party text fits down to a 6.5-point minimum. No values are silently
truncated. If text cannot fit readably on one label, preview/export returns 422
with a review action; the Parcel remains valid and unchanged. The bundled Vera
fonts preserve supported accented characters in PDF and SVG. Text outside that
font's glyph coverage produces an explicit error rather than missing glyphs.

All endpoints reuse persisted tenant membership, role, effective module access
and location-scoped Parcel queries. Label reads use the existing read/export
policy, not a status transition or operational event. Responses use private
no-store caching, no-referrer and nosniff headers. Preview markup is generated
by ReportLab, which escapes text. Downloads and printing do not create events
or stored files. Anonymous public tracking's restricted projection is unchanged.
The existing PWA worker already bypasses caching of operational responses.

## Demo and deployment

Only newly seeded Parcels receive fictional party/address snapshots, through
the existing Parcel creation service and ownership metadata. Even the unweighed,
unassigned demo Parcel is addressed. Existing seed records are never overwritten.
Preview remains read-only; duplicate-run protection, ownership-based reset,
profile settings, transport modes, invoice counts/lines and lifecycle scenarios
remain intact. Verified-site demo options and guards from Block 04 are unchanged.

Apply `uv run python src/manage.py migrate` and the normal static-asset deployment
for the updated workflow script. No production dependency is added: ReportLab and
pycountry are already installed. Optional dev dependencies pypdf, pypdfium2 and
zxing-cpp inspect/rasterize PDFs and independently decode the printed symbols;
they are not loaded by runtime label views or camera scanning.

Focused tests cover persistence, CRM independence, maintained country choices,
historical migration preservation, legacy codes, private projection, scoped
exports, readonly GET behavior, long text and physical page dimensions. Symbol
tests decode generated PDFs at 203 and 300 DPI, then use the existing scanner
resolver. The optional browser script exercises explicit prefill, preserving
typed values, registration, responsive preview, print actions and decoding of
Chromium's actual print output without toolbar/chrome.

Physical printer checks remain: 4 × 6 stock, actual size / 100% scaling,
nonprintable margins, thermal darkness, feed/orientation, barcode quiet zones and
scan reliability after attachment. No postage, printer SDK, carrier API or
permanent label storage is introduced.

## Changed files

* `docs/logistics_shipping_labels.md`
* `pyproject.toml`
* `uv.lock`
* `scripts/logistics_shipping_label_browser_check.py`
* `src/apps/logistics/demo.py`
* `src/apps/logistics/forms.py`
* `src/apps/logistics/models.py`
* `src/apps/logistics/parcel_services.py`
* `src/apps/logistics/label_views.py`
* `src/apps/logistics/shipping_labels.py`
* `src/apps/logistics/urls.py`
* `src/apps/logistics/views.py`
* `src/apps/logistics/migrations/0018_parcel_shipping_snapshots.py`
* `src/apps/logistics/test_demo_data.py`
* `src/apps/logistics/test_shipping_labels.py`
* `src/apps/logistics/test_shipping_label_migrations.py`
* `src/static/assets/js/logistics-workflows.js`
* `src/templates/logistics/parcel_form.html`
* `src/templates/logistics/parcel_detail.html`
* `src/templates/logistics/shipping_label.html`
