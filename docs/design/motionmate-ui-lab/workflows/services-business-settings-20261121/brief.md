# Business Settings — design direction v1

21 November 2026 · Full Redesign · Motionmate Services · Gate A pending

Primary route: `/businesses/settings/` (`business_settings`). Operational
sub-screen: `/businesses/settings/booking/` (`business_booking_settings`). Outcome:
make company configuration, invoice branding, personal details and existing
booking configuration easier to navigate while keeping independent save/access
boundaries and every existing field.

## Authorization and evidence

The user requested “Automatically complete both audits and design plans.” and
“Stop at Gate A for design-direction approval.” This phase owns saved audit,
design and state records only. Application changes, runtime/fixture setup,
ordinary database access, migrations, installs, providers and Git/release actions
are excluded.

The [actual Django audit](audit.md) and [source identities](source-audit.json)
trace current routes, form/model/view contracts and downstream consumers. No
browser/runtime evidence is claimed. Prior test reports remain historical.

## Settings composition

| Current task friction | Proposed direction | Preserved contract |
| --- | --- | --- |
| Large workspace/account cards delay the form. | One h1 **Business Settings**, compact workspace/vertical/role context and signed-in identity. Keep existing country/currency facts in a small definition list. | Actual Business/user values; no identity switcher, guessed defaults or new record. |
| Long page has repeated visual framing. | Desktop left section index beside a clear form column; restrained dividers and grouped fields. Retain Business details, Address, Regional defaults and Invoice defaults. | All existing fields, country-specific labels/postcode handling, bound values and validation. |
| Branding can look broader than its actual effect. | Lead Invoice defaults with **Company invoice logo**: current saved preview/fallback, requirements, replace/remove and a concise description of newly generated documents. Follow with currency, tax and numbering. | Existing database-backed invoice logo, multipart upload, atomic save/rollback, mutually exclusive replace/remove. No shell-brand editor or unsaved document preview. |
| Save scope needs to be obvious. | One **Save business settings** group after Invoice defaults, explaining that company/address/region/invoice values save together. Full-width on mobile. | Form ID, CSRF, `section=business`, complete POST and redirect remain. File selection follows native validation behavior; do not fabricate persistent upload. |
| Personal details affect the sign-in rather than company contacts. | Distinct **My account** section with its own Save personal details, followed by Security → Change password. Explicit personal/business email and phone labels. | `account` prefix, request-user binding, `section=account`, action/redirect and existing password route. Shared authentication implementation unchanged. |
| Configuration links look like independent editors. | Compact **Business configuration** rows: Team, Catalogue/import, Booking rules/availability, owner-only Subscription. Retain existing guarded Online booking readiness/share panel. | Exact named routes, role/capability/editability gates and authoritative share context. Completed destination modules unchanged. |
| Restricted users receive only permitted sections. | Explain own-account access versus unavailable workspace editing from existing role/write context. Keep personal/security available to signed-in Services users. | Business POST denial and subscription redirect behavior. No new exposure of Business form fields. Shared no-business fallback unchanged. |

Desktop arrangement (design specification only):

```text
Business Settings                                      [Back to dashboard]
Workspace · Services · Role         Signed in as …
Messages / access explanation

Section index             Workspace settings (one existing multipart form)
Business details          Business details: name / industry / email / phone
Business address          Business address: structured fields + address notes
Regional defaults         Regional defaults: timezone / default locale
Invoice defaults          Invoice defaults: saved logo / upload / remove
My account                                  currency / tax / numbering
Security                                    [Save business settings]
Business configuration
Online booking            Personal account (separate existing form)
                          My account [Save personal details]
                          Security [Change password]
                          Business configuration: existing guarded links
                          Online booking: existing authoritative share panel
```

Retain IDs `business-settings-form`, `business-details`, `business-address`,
`regional-defaults`, `invoice-defaults`, `my-account`, `security`, `workspace-tools`
and `online-booking`, plus field/error hooks. Legacy profile redirects still
land on the same permitted sections. Do not add a General/Preferences model or
promote legacy profile website/tax-ID/currency defaults into Business settings.

## Existing operational sub-screen

Include presentation of **Booking rules & availability**, reached through the
existing Settings link. Keep its route and each independent form.

1. Compact title, workspace context, guarded return links and existing plan/
   readiness notice. Move the existing share panel below configuration so rule/
   availability editing comes first; preserve its readiness and link behavior.
2. **Booking rules** groups enablement and timing fields with existing unit labels,
   confirmation choice, instructions and policy text. Keep `form_kind=settings`
   and one save action. Staff keeps its existing read-only rule summary.
3. **Add weekly availability** retains Single/Bulk Bootstrap tabs, selected error
   panel, CSRF, fields, `form_kind` values and staff/self guidance. Give day choices
   a semantic group label and room to wrap.
4. **Weekly availability** becomes a full-width list below the editors: Staff,
   Day, Time and Deactivate. Keep business-wide/staff identity, inactive count and
   existing empty state. No new calendar, dragging, editing/reactivation endpoint
   or scheduling/conflict policy.

Preserve module/write guards, eligible current-tenant staff, Staff self-only
availability, business-wide windows, atomic bulk creation, time validation and
POST-only tenant/role-scoped deactivation. Keep current time values/formats and
confirmation choices. Existing manual-only wording versus model-choice behavior
is documented; this redesign does not introduce an automation promise.

## Motionmate styling and accessible behavior

Use approved [tokens and typography](../../../motionmate-design-system/DESIGN.md),
[component patterns](../../../motionmate-design-system/COMPONENTS.md) and
[vertical boundaries](../../../motionmate-design-system/VERTICALS.md). Translate
that direction through Phoenix/Bootstrap, local licensed Manrope, restrained
indigo actions, quiet surfaces, navy dark surfaces, 12px panels and 8px controls.
Reuse existing font files unchanged. No framework migration, production Tailwind/
DaisyUI import, global shell retheme or frozen-reference edits. Phoenix 1.23.0
reference examples are available read-only.

- Desktop: compact sticky index, readable form width, up to two field columns,
  20–24px section spacing, 32px title and 20px section headings.
- Tablet: wrapped in-page index links above a full-width form; booking editors
  stack when narrow. Keep forms, errors and selected tab accessible.
- Mobile: 16px gutters/padding, 28px title, one field column, wrapped section links
  and full-width save actions. Availability records retain every field/action,
  semantic row identity and DOM order. No duplicate datasets.
- Light/dark: same fields, data and guards. Preserve Phoenix theme preferences,
  input/file selections and scripts; validate errors, focus and disabled states.
- Accessibility: one h1, ordered headings, persistent labels, grouped-day legend,
  associated errors, keyboard tabs/anchors, fixed-header clearance and 44px
  targets. Check 320px reflow, zoom, RTL and reduced motion. Existing duplicate
  generated availability IDs require an explicit compatibility proposal before
  any ID repair at Gate B; no silent prefix/hook change.

## Shared boundary and separate proposals

Choose the Services composition only for resolved `SERVICE`. Shared entry
files may need a branch, but Logistics markup/assets/forms/links and no-business
fallback must remain identical. Keep shared backend, settings CSS/field/share
includes and authentication behavior unchanged unless a later concrete proposal
identifies a necessary change and both-vertical regression evidence. Exact files
are prepared after Gate A.

Exclude new brand colors/assets, website/tax-ID promotion, currency conversion,
language switching, timezone-validation policy, invoice calculation/numbering
changes, booking automation, new staff roles, schema/data migrations and provider
configuration. Default locale is currently optional text for future formatting,
not a language selector. Invoice branding is not platform branding. The acceptance-
template existing-user gap is a separate repair proposal.

This task owns no [Team implementation](../services-team-20261121/brief.md) or
completed Catalogue/Import/Subscription/Clients/Invoices/Appointments/Dashboard
redesign. It preserves links to those destinations and their existing guards.

## Validation and Gate A decision

See the [independent validation plan](validation.md). Runtime/browser/accessibility/
data-writing tests have not run. After design approval, prepare the exact Gate B
manifest, consumer impacts, baseline, risks and specific disposable PostgreSQL
resource proposal. Stop for implementation/resource authorization.

After B capture actual working-tree BEFORE, implement and validate, refresh AFTER
alone and present one real Django comparison before Gate C acceptance. If both
tasks are authorized, implement Team first then Settings. Capture Settings BEFORE
from the tree containing completed Team edits; keep separate manifests, review/
fixture identities and Gate C decisions. Either design can be approved separately.

Approve **Business Settings v1**: compact indexed workspace/personal sections,
truthful invoice-logo presentation and grouped existing Booking rules/availability,
subject to these preservation rules/exclusions. Exact artifact hashes and design
identity appear in `state.json` and Gate A review. Approved design artifacts stay
immutable. Design approval authorizes preparing Gate B proposals only.
