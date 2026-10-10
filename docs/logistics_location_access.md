# Logistics Location Access V1

Business remains the tenant. BusinessUser remains the account membership and role. Existing role, active-membership, capability, subscription and lifecycle guards remain authoritative. SERVICE memberships do not use this policy.

## Policy

- OWNER and ADMIN have business-wide operational visibility and may approve/revoke assignments, review rollout readiness, register facilities and associate handling sites. The existing ADMIN role is sufficient; no manager role or global SERVICE permission changes are introduced.
- Other operational readers, including STAFF, ACCOUNTANT and VIEWER, need explicit active location assignments. Shared Client and Invoice permissions remain business-wide according to their existing roles.
- Assignments become usable only after an owner/admin records review on LogisticsProfile. Missing profiles, pending review, no assignments, inactive sites and revoked memberships fail closed. Operational lists and dashboard metrics return empty results for unassigned readers; direct record URLs and scans do not resolve their restricted objects.
- Visibility is the union of assigned sites: structured origin/destination facilities, explicit expected/current/stop associations, and (for Parcels) the sites of their assigned Shipment. Geographic text, country choices, sender addresses and scanner text never grant access.
- STAFF writes require the existing operational role, writable subscription, a separate `can_operate` grant, and a selected active site relevant to the existing target. Existing status transition rules still apply. The selected site is persisted per BusinessUser assignment; one account can work across multiple sites and businesses.
- New staff-created records must originate at the active work site. A company destination selector is limited to assigned sites; geographic destinations without a company branch remain supported. Staff cannot change a saved origin/destination facility or administer handling-site associations. Owners/admins can adjust route associations through the existing edit services.

Assignment, revocation, facility management, site selection and operational mutations take the existing Business transaction lock. PostgreSQL conditional uniqueness permits only one selected assignment per membership. Writes recheck persisted access rather than trusting request caches or a submitted location/membership/business ID. Reads use fresh persisted grants; changes affect subsequent requests without requiring a new login.

## Schema

Migration `0016_worker_location_access` is additive, following Block 02 migrations `0014` and `0015`:

- Nullable, non-editable `LogisticsProfile.location_access_reviewed_at` records explicit rollout review without changing operating areas or transportation modes.
- `LogisticsLocationAssignment`: Business, existing BusinessUser membership, registered LogisticsLocation, separate operational-write flag, selected-site flag. Unique membership/site; one selected site per membership.
- `LogisticsHandlingSite`: Business, registered location, exactly one Parcel or Shipment, and EXPECTED/CURRENT/STOP association. Database checks enforce the target XOR and known kinds; uniqueness prevents duplicate target/site/kind associations. Normal saves validate that all related rows belong to the same tenant.

No historical geographic matches or role-wide assignments are invented. No existing Parcel, Shipment, Event, UUID, tracking code, invoice or invoice line is migrated or rewritten by this block. Existing Block 02 country-only backfills remain separate.

Handling associations are deliberately unordered and manually managed. They do not schedule transport, infer locations from scans, execute status transitions, or automatically expire on departure. A Shipment site makes its cargo expected there, so authorized staff can inspect its complete operational manifest. Complete exports fail closed if any cargo cannot be resolved through the policy.

## Protected surfaces

Parcel/Shipment service querysets protect lists, searches, filters, details, scanner lookup (manual and camera), dashboard record/event counts, manifests/CSV, shared Client parcel panels and operational Django admin inspection. Authenticated route forms receive the actor and scope facility/parcel selectors. All mutating domain services check the target's existing site before applying submitted changes or accepting a replay.

Invoice pages and rendered/downloaded/emailed PDFs retain financial access, totals and saved history. Restricted linked operational references are replaced in the response with a generic Logistics charge description and their operational links are hidden. This prevents saved charge descriptions from revealing the anonymous tracking credential. The saved descriptions and InvoiceLine relationships are unchanged. Free-text invoice notes and unlinked financial descriptions remain subject to existing shared finance permissions.

Public tracking uses its existing minimal projection, code security and throttling. It deliberately does not require a worker assignment.

Workspace Settings → Operating locations → Worker location access provides owner/admin assignment, handling-site and explicit review forms. Reviewed workers choose among their approved sites using the shared work-location selector. All state changes are CSRF-protected POSTs. Revoked current selections require an explicit new selection; the UI does not silently imply another selected site.

Business inventory registers the new ownership relations and detects inbound/outbound tenant corruption. Controlled purge deletes associations before their referenced facilities and memberships. Demo reset refuses to cascade-delete manually created handling associations; durable demo ownership/reset behavior is retained. No demo or development data is reset automatically.

## Deployment and review

1. Apply migrations through `0016` during a controlled rollout. Schema expansion can precede web-worker activation. Back up and review existing Logistics memberships and historical operating-site associations first.
2. Use owners/admins to register verified facilities and approve each intended worker's site(s) and operational-write flag. Associate historical records with verified operating sites; unmatched records remain visible only to owners/admins. Do not infer branch access from free text or grant everyone every site.
3. Confirm that the assignment review is complete using the access settings page (or the same service from a controlled management session). Intentionally unassigned staff retain no operational access.
4. Activate/restart application workers only when the deployed business review and assignments are ready. If configuration is deferred until after activation, staff access is unavailable until review; owners/admins retain business-wide access to complete configuration. There is no temporary default-wide staff bypass.
5. Existing LogisticsProfile classification/modes and SERVICE behavior are retained. No worker login/account migration, seed reset or historical-code migration is required.

## Verification and limits

Focused PostgreSQL tests cover single/multiple sites, active-site changes, read-only grants, unassigned/pending review, inactive/revoked memberships/sites, owners/admins, tenant boundaries, selector tampering, service/replay authorization, scanner/direct URLs/CSV, dashboards, shared Client and invoice projections, schema constraints, demo reset safeguards and SERVICE staff. PostgreSQL concurrency tests verify revocation against an in-flight transition and competing work-site selections. Historical migration tests verify preserved text, relationships, classifications, codes and zero automatic grants. Browser checks exercise real assignment controls and worker site switching at 320/390/1440 pixels.

Raw SQL, direct ORM writes and privileged platform administration remain trusted maintenance paths; tenant consistency is validated by services/models and inventory checks rather than PostgreSQL row-level security. Existing platform finance administration is outside the BusinessUser operational policy and must not be granted to ordinary workspace workers. Association scheduling/history and a delegated Logistics manager capability are outside V1. Shared cache/proxy deployment checks for anonymous tracking remain separate from location-access verification.

Final verification on a disposable PostgreSQL 14 UTF-8 instance: 624 Logistics operational tests (622 passed, 2 actual-Redis endpoint tests skipped), 7 historical migration tests, 372 SERVICE/business-safety regressions, and 44 focused location tests passed. Focused coverage overlaps the operational suite. One Chromium browser test passed with six responsive layouts and live assignment/site-switch interactions; no page JavaScript errors. Django checks, migration consistency, changed-file Ruff checks and `git diff --check` passed. Logs are in `/tmp/mm-access-{operations-final,migration,service,final-focused,browser-final}-tests.log`; browser screenshots are in `/tmp/logistics-location-access-ux/`. No Development records or deployed workspaces were modified.
