# Services Clients workspace

Services Clients retains the existing CRM records, routes and server workflows
inside Phoenix 1.23.0. Presentation is scoped to Services; Logistics retains its
existing shared-template branches and location/financial safeguards.

The directory keeps server search/district/activity filters and client-side
10-row pagination, sorting, selection and View all/less. Client profiles show
contact/address, relationship, notes and existing entitled appointment/invoice
history. All 32 PrivateClientForm fields remain on full-page creation/editing
with linked validation and accessible sections. Manual Individual creation still
requires company name. Creation returns to the list; editing returns to detail.

Archive retains the existing owner/admin POST with CSRF and record retention.
CSV remains Upload → Validate → Preview → Confirm → Result with optional columns,
server previews, tenant/actor binding and retry protection. Inline creation keeps
appointment/request drafts and the existing JSON endpoint. Financial labels and
amounts come from the existing authoritative invoice partial/services.

Styles and progressive JavaScript load only for Services client content or its
inline client modal. No Tailwind/DaisyUI production imports, global theme/shell
replacement, model/schema change, migration source change or provider activation.

Implementation review and current evidence are recorded under
`docs/design/motionmate-ui-lab/workflows/services-clients-20261117/`. Real BEFORE
and AFTER review uses separately verified disposable databases and synthetic data;
it does not prove ordinary-runtime/provider readiness. Acceptance and release
remain separate authorization steps. No commit, push or deployment is implied.

See [implementation report](design/motionmate-ui-lab/workflows/services-clients-20261117/implementation-report.md),
[Django validation](design/motionmate-ui-lab/workflows/services-clients-20261117/django-validation.md)
and [interactive comparison](design/motionmate-ui-lab/workflows/services-clients-20261117/comparison.md).
