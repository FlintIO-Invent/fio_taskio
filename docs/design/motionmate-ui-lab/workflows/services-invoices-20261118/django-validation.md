# Services invoices: Django validation

The approved 40-file implementation was validated only in verified disposable
resources. This is local implementation evidence, not ordinary-runtime or provider
verification. No ordinary local, Test Lab, staging or production database was used.

| Check | Final result | Evidence |
| --- | --- | --- |
| Services billing, saved facts, tenant/role scope, documents/logos, payments, existing Clients and Appointments UI | 163 tests passed | [Backend log](tests-services-final-02.log) |
| PostgreSQL payment concurrency | 7 tests passed | [Concurrency log](tests-payment-concurrency-final.log) |
| Logistics cancellation/settlement, including isolated concurrency | 26 tests passed | [Settlement log](tests-cancellation-final.log) |
| Real browser create/edit/issue/payment/refund/email safeguards | 1 test, 2 complete desktop/mobile journeys passed | [Browser log](tests-browser-final-04.log), [journey summary](django-journey-summary.json) |
| Offline adapter refusal boundaries | 4 tests passed | [Offline log](tests-offline-final-02.log) |
| Preserved Print and action/vertical guards | 4 UI tests passed | [Print/UI log](tests-print-ui-final.log) |
| Native browser Print | 12 customer-safe print/PDF cases passed, including print-mode axe | [Print summary](django-print-summary.json) |
| Existing Logistics financial access/coverage | 44 of 48 passed on each side; same 4 failures on BEFORE and AFTER | [Parity](logistics-test-parity.json) |
| Core real Django matrix | 48 cases: 6 screens × 4 widths × 2 themes | [Browser summary](django-browser-summary.json) |
| States, roles, source forms, RTL and Logistics | 104 additional captures | [Browser summary](django-browser-summary.json) |
| Changed Services content accessibility | 112 applicable capture scans, zero violations; payment-error scans also passed in browser journeys | Raw axe results in the retained capture directories |
| Ruff, JavaScript syntax and Git whitespace | Passed | [Ruff](ruff-final.log), `node --check`, `git diff --check` |
| Protected source/design and accepted Clients candidate | Passed | [Source preservation](implementation-preservation.json), [Clients check](clients-preservation-check.json) |

The browser journeys use actual Django forms, CSRF and hidden retry UUIDs in
`test_services_rollout`, under `taskio.services_test_settings` on port 55621, with
LiveServer port 8768. They cover Choices search, rejected and successful inline
client creation, draft retention, saved/new service prefixes and categories,
actual calculated totals, confirmation Escape/return focus, issuance, invalid
payment feedback, a cash receipt, a completed refund, locmem email metadata and
refusal to cancel an invoice with active receipts. They close the worker's database
connection explicitly. No financial write guard was relaxed for human previews.

The final real preview matrix covers 320/390/768/1440 pixels, light/dark modes,
empty/long/quota/locked and all five roles, draft/issued/paid/cancelled/legacy and
zero-value/tax cases, client/appointment source forms, receipt adjustment and RTL.
There are no page errors, changed role/route outcomes, or Services/RTL overflow.
The two existing Logistics debug-404 overflow cases remain identical to BEFORE.

Actual authenticated downloads cover draft, partial, legacy, zero-tax and 48-line
invoices. The long invoice renders five pages with repeated line headers, invoice
identity/page numbers and one closing amount block. Text extraction, saved-currency
values, conditional tax/Notes, logos, wrapping, embedded Manrope and unchanged
Logistics document operations are covered by the focused document tests. Emailed
attachments continue to exclude Notes. Native Print remains `window.print()`; print
media hides staff lifecycle/payment history/actions and retains saved amounts,
Notes and required accounting exceptions. Twelve print cases cover six invoice
states at desktop/light and mobile/dark, with actual Chromium PDFs and print-mode
axe checks. Short invoices print on one page; long invoices retain line headings.
The last print-only color refinement is isolated in
[the exact source delta](final-print-source-delta.json); all screen rules and other
application files are byte-identical to the final 152-case screen matrix.

## Limits and inherited findings

- Four existing Logistics assertions fail on both sides, with no new failure or
  error. They expect older issuance copy or currency formatting. The unchanged
  tests were not rewritten to hide the baseline result.
- Full-shell axe results retain 24 color-contrast and 60 link-name node occurrences
  across core captures. The Services region has zero violations. There are 112
  incomplete contrast-rule occurrences, including native select controls; raw
  results and screenshots remain available for human review. This is not a claim
  of whole-page WCAG conformance.
- Previews retain the existing debug allocator workaround. Ordinary-runtime
  stability and real email/payment/provider delivery are not established.
- Human preview `/billings/` POSTs, including financial actions, return 409 under
  the unchanged guard. Write journeys were exercised only in the disposable test
  database, which was destroyed after each successful run.
- Eleven tables were compared read-only. Saved invoice/line, client/service/category
  and financial facts match. Two synthetic receipt `recorded_at` defaults differ
  from separate initial seeding; all other values match. No rows or timestamps
  were rewritten to force parity. See [record parity](saved-record-parity.json).

Initial failures and subsequent fixes remain in separate logs/evidence. The first
mixed transaction run had fixture-restoration and connection-teardown interference;
serialized suites now run in separate fresh test processes. The one stranded test
database was removed only after independently verifying its owned cluster and zero
remaining sessions; neither review database nor any other database was removed.
