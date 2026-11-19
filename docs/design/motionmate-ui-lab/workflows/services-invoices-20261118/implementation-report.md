# Services invoices: implementation review

The approved Services invoice redesign is implemented within the exact 40-file
Gate B manifest. It modernizes the directory, invoice details, creation/editing,
payment and adjustment pages, HTML/email presentation and real customer PDFs.
Phoenix 1.23.0 is retained; the lab's Tailwind/DaisyUI direction was translated into
Services-scoped Django templates/assets rather than imported into production.

[Open AFTER](http://127.0.0.1:8871/billings/) ·
[Open BEFORE](http://127.0.0.1:8870/billings/) ·
[Accounts/password](http://127.0.0.1:8872/)

Start with `invoices.owner@preview.test`. Human review writes on billing routes
remain blocked; complete write journeys passed in the isolated test LiveServer.

## Result and preserved contracts

- Staff retain internal Draft/Issued/Cancelled and payment/review indicators, saved
  currency, receipt/audit history and guarded actions. Record customer payment
  remains a prominent full-width link above Download PDF on the existing page.
  Print retains the original `window.print()` action; its paper view hides staff
  statuses/payment history and keeps required accounting explanations.
- Create/edit preserve line IDs, repeated names, `new_` prefixes, service/category
  snapshots, whole-unit rules, client/appointment source context, CSRF, notes,
  validation and return routes. Inline client creation retains the invoice draft.
- Payment pages render the actual server form and hidden idempotency/allocation
  fields. No ledger, settlement or permission calculation moved to JavaScript.
- Customer PDFs, HTML and emails show saved Subtotal, applicable Tax and Total
  Amount. Download Notes remain conditional. Emailed PDFs still use
  `include_notes=False`; notification code is unchanged. Customer documents omit
  internal Draft/lifecycle labels and routine payment/balance summaries, while
  retaining necessary cancellation/refund/review explanations.
- Letter PDFs embed pinned OFL Manrope fonts, wrap long content, retain logos and
  repeat invoice identity, page numbers and line headers. The amount block occurs
  once and uses the saved total even when it differs from a reconstructed sum.
- Models, views, forms, URLs, finance services, calculations, records, permissions
  and issuance safeguards remain unchanged. All eight original non-Services
  template bodies are byte-identical; Logistics keeps its existing renderer/UI.

## Validation and remaining limits

The final backend runs passed 163 Services/related tests, 7 payment concurrency
tests and 26 Logistics cancellation/settlement tests. Four offline boundary tests
passed. Four additional UI checks verify preserved Print/actions/vertical guards.
Actual browser journeys passed at desktop/mobile widths, and 12 native-print/PDF
cases passed with print-mode axe checks. The 152-case
AFTER matrix has no page errors or Services overflow and zero violations across
112 applicable scoped axe scans.

The two unchanged Logistics financial suites pass 44 of 48 tests on each side,
with the exact same four inherited assertions failing on BEFORE and AFTER. Full
shell axe findings, native-control contrast incompletes, existing Logistics debug
error-page overflow and the debug allocator workaround are disclosed. No ordinary
runtime/provider readiness is claimed. Two synthetic seed receipt timestamps differ
between review clusters; all other financial/client facts match and neither cluster
was rewritten to force equivalence.

See [validation](django-validation.md), [comparison and evidence](comparison.md),
[record parity](saved-record-parity.json), [source preservation](implementation-preservation.json)
and [final source manifest](final-source-manifest.json). Initial failures and fixes
are retained separately; final designated logs/evidence are explicitly identified.

## Approval binding

- Approved design v1: `08215da40bb17baeaa63d5a3482f02a45daf83e26ffecca0f6a78ec13ab77f80`.
- Approved exact manifest: `929e62fa6d6c1288d878b590bfdb8bad26ffa673b6aaddab631883075ef24e9c`.
- Accepted Gate C candidate: `936f7fa66278a40e5d90122d365b6d097d245e7c1822c55b54993b1a51a91abc`.
- Branch/HEAD remain `experiment/motionmate-ui-redesign` /
  `d864d322061dfa03f50076c5381ec26efd0e1ec7`.
- All 12,679 protected baseline files were checked; only the 12 approved existing
  targets changed. The 28 additions match the manifest. All 1,257 frozen design
  artifacts are unchanged. The accepted Clients candidate remains
  `c9b2403b9f84ad7092ba294aafdf76bf8cc3df497965789dd63c31f60ea18041`.

Gate C was explicitly approved by the user on 19 November 2026. The accepted
candidate is unchanged; [approval](gate-c-acceptance.json) and
[finalization](finalization.md) record completion. The disclosed validation limits
remain in effect. Human acceptance does not authorize release.
Nothing was staged, committed, pushed, migrated in an ordinary database, or deployed.
No provider configuration, shared shell, dependency, Logistics source, previous
accepted workflow, or frozen design reference was changed. Review resources remain
available; no cleanup is authorized.
