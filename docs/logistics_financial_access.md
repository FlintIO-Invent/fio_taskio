# Logistics financial access

The shared `Invoice` / `InvoiceLine` models remain authoritative. `apps.logistics.financial_access` centralizes the Logistics overlay on existing BusinessUser roles, subscription/module checks, tenant boundaries and persisted location assignments. SERVICE billing retains its existing permissions and controls. The access fix itself requires no migrations; the subsequent [financial coverage implementation](logistics_financial_coverage.md) adds nullable snapshots and frozen charge membership while preserving historical amounts.

| Role | Invoice reads / PDF | Financial writes |
| --- | --- | --- |
| OWNER / ADMIN | Business-wide | Existing Invoice management; Parcel/Shipment charges and invoice generation/append |
| ACCOUNTANT | Existing business-wide accounting scope | Existing accounting management, charges and generation/append; Invoice deletion remains OWNER/ADMIN-only |
| STAFF with reviewed locations | Complete Parcel-only Invoices whose every line is accessible through assigned active sites | Parcel charges, generation, append, DRAFT → SENT and SENT → PAID; every Parcel on the affected Invoice must be relevant to the selected active site with `can_operate=True` |
| STAFF with read-only grants or no selected site | Same assigned-site read scope | None |
| Unassigned STAFF / pending review | None | None |
| VIEWER | Existing business-wide read-only financial scope | None |

Accounting access is independent of operational work-site selection. It does not grant accountants or viewers operational Parcel/Shipment visibility. STAFF financial clearance excludes empty, manual, Shipment-linked and partially accessible Invoices. Generic Invoice creation/editing, emailing and cancellation remain accounting actions. This conservative boundary avoids giving a location worker authority over unrelated financial rows or shipment-wide charges.

The financial coverage implementation also exposes a bounded status-only clearance service for an accessible Parcel. It can account for shared freight without exposing the Invoice, amounts or other cargo, and grants no additional Invoice access or mutation rights.

All roles remain subject to active Business, active membership/user and invoicing subscription/module access. Charge targets additionally require the relevant Parcel/Shipment module. STAFF Invoice access also requires the Parcel module. Restricted subscriptions may retain reads but never permit writes.

Shared Invoice list/detail/PDF/status/edit/delete/email/create routes apply the policy. Logistics dashboard totals and Parcel billing panels use the same Invoice scope; a linked restricted Invoice appears only as “Invoiced (restricted)” without its number, status or link. Accounting readers retain the existing response-only redaction of inaccessible operational references. Direct PDF rendering requires an actor for Logistics and applies the same authorization and redaction.

The charge services, shared Invoice creation/totals/status services and email entry point recheck persisted authorization. Mutating Invoice and charge services use the existing Business lock and lock the actor's BusinessUser membership, serializing with grant/site changes and membership deactivation. No request-cached location or role can authorize a write. Draft selection filters the entire Invoice, and append / exact replay recheck its full contents after obtaining the Business lock. Issuance and append serialize, so appending cannot modify an already-issued Invoice.

The existing full Logistics demo dataset includes business-wide and Shipment financial scenarios, so its actor preflight now requires an OWNER/ADMIN. Both preview and execution reject STAFF before any seed writes. No staff grants, roles or financial scope are broadened for fixture creation.

“Mark as Sent” is independent of editing eligibility. Protected Logistics lines and their saved snapshots cannot be edited or deleted through the shared editor, and charge-linked Invoices remain protected from deletion. Issuance preserves every saved line, reference and total.

Automated coverage lives in `test_financial_access.py` and `test_financial_access_concurrency.py`, alongside existing billing/location/SERVICE regressions. Optional real Chromium checks live in `scripts/logistics_financial_access_browser_check.py` and exercise OWNER/STAFF issuance at 390 and 1440 pixels, protected-line controls, restricted Invoice URLs and read-only grants.

Raw ORM/SQL writes and platform Django administration remain trusted maintenance surfaces under the existing architecture. Actual email delivery and deployed workspace configuration require deployment verification; mocked email tests prove authorization and call behavior, not provider delivery.

## Original access-fix verification

- Final PostgreSQL 14.24 run: 62 permission, billing/location concurrency and demo tests passed, including 13 concurrency tests. Log: `/tmp/mm-finance-final-postgres.log`.
- Final SQLite run: 119 Logistics finance/demo and shared SERVICE billing regressions passed. Log: `/tmp/mm-finance-final-regression.log`.
- Chromium: one browser test passed for OWNER/STAFF issuance at mobile/desktop widths, restricted URLs and read-only controls. Log: `/tmp/mm-finance-final-browser.log`; screenshots: `/tmp/mm-finance-browser/`.
- Initial full PostgreSQL run: 1,461 tests; 1,458 passed, two actual-Redis tests skipped, one obsolete STAFF demo expectation errored. Its expectation and demo preflight were corrected and verified in both final reruns above. The entire broad suite was not repeated after that correction. Log: `/tmp/mm-finance-full-postgres.log`.
- Django checks, migration-drift check, changed-file Ruff/Black and `git diff --check` passed. No migrations are needed. The broad/final regression runs used a temporary test-only MD5 password hasher for speed; the earlier 26-test PostgreSQL permission/concurrency run passed with the project's normal test settings.

All PostgreSQL work used a disposable local cluster. No deployed workspaces, assignments, subscriptions, or provider data were changed. Actual email delivery and deployment configuration were not tested.
