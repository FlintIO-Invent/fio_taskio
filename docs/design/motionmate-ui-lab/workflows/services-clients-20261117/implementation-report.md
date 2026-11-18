# Services Clients implementation for Gate C

The approved Clients v1 direction is implemented locally across the Services
directory, profile, full-page creation/editing, archive confirmation, CSV workflow
and inline client creation. It uses existing Phoenix/Bootstrap, scoped Manrope
and semantic light/dark tokens. Tailwind and DaisyUI remain isolated design
references. The shared Phoenix shell is unchanged.

The exact [31-file manifest](implementation-manifest.json) is complete: twelve
modified files and nineteen additions. Gate A and Gate B approvals remain bound
to the original design and manifest digests. Gate C acceptance is pending in
[state.json](state.json); release authorization is separate.

## Result and contracts

- The directory retains the real server search, district and activity parameters,
  historical activity aliases, existing List.js pagination/sort, selection and
  view-all hooks. Selection can be cleared. Export remains unavailable.
- Profiles show existing contact, business, relationship, notes, appointment and
  invoice data. All existing contact links remain. Assigned users use their
  existing full name/email, avoiding the old template's nonexistent username.
  Invoice facts still come from the unchanged authoritative invoice partial.
- Create/edit retain all 32 existing fields, prefixes/IDs, CSRF, server errors and
  redirect destinations. Six accessible disclosures and a linked error summary
  expose fields without losing drafts. Country-dependent controls preserve
  values and reuse an input when its type already matches. The existing company
  requirement still applies to Individual clients.
- Archive uses the existing owner/admin POST and CSRF. A Bootstrap confirmation
  supports cancel, Escape and focus return. Records and obligations are retained.
- CSV retains Upload → Validate → Preview → Confirm → Result, optional columns,
  capacity decisions, tenant/actor binding and retry protection. No new policy or
  execution service was introduced.
- Inline creation retains the existing quick-create endpoint, prefixed fields,
  JSON outcomes, submit lock and appointment/request drafts. Services receives
  scoped field error associations. Non-Services behavior is preserved.

No models, forms, views, URLs, services, permissions, provider integrations or
migration sources changed. The only edit in the existing CRM test suite replaces
one obsolete inline-JavaScript assertion with the new error-summary hook.

## Preservation and review

[Final preservation](final-preservation.json) verifies all 12,619 protected
baseline files outside the manifest, all 733 approved design artifacts, and the
25 runtime candidate files against the actual AFTER source. The original eight
non-Services/compatibility template bodies are byte-equivalent after removing
the dispatch wrapper; see [branch proof](legacy-branch-preservation.json).

The independently verified disposable databases still match on all 68 original
client records and financial facts: 32 invoices, 32 invoice lines and one receipt,
plus unchanged empty settlement tables. Setup timestamps and generated receipt
retry UUIDs are explicitly excluded from equivalent-side comparison. Validation
created additional synthetic records; they are retained and are not silently
resynchronized. Ordinary databases and customer records were never accessed.

The detailed checks and limitations are in [Django validation](django-validation.md).
Use the real applications and equivalent fixtures in [comparison](comparison.md)
for acceptance. No staging, commit, push, merge or deployment was performed.

Candidate for acceptance: `c9b2403b9f84ad7092ba294aafdf76bf8cc3df497965789dd63c31f60ea18041`.

The offline workflow check confirms Gate C with design and implementation approval
bindings unchanged. Acceptance remains null. See [gate check](gate-c-check.json).
