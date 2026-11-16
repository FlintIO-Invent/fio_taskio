# Motionmate — reusable design system and preview workflow

> Historical step report. Steps 1–8 were subsequently completed and approved.
> Current setup/approval boundaries: [reproducible workflow](REPRODUCIBILITY.md).
> Complete historical evidence is in the [separate local archive](PRESERVATION.md).

**15 November 2026 · Step 5 · Preview mode · Services Appointments · Ready for human design review**

Created a reusable lab design system and workflow from the approved Tailwind 4 /
DaisyUI 5 / Manrope direction, with a second independently reviewable screen.
The production application remains on Phoenix. No production integration is
included or authorized by this work.

Start with the [new screenshot gallery](../../../ui-lab/services-appointments/evidence/gallery.html),
[lab launcher](../../../ui-lab/index.html), [Appointments contract](../../../ui-lab/services-appointments/README.md)
and [workflow guide](PREVIEW-WORKFLOW.md).

## Deliverables

| Deliverable | What it provides |
| --- | --- |
| [DESIGN.md](../motionmate-design-system/DESIGN.md) | Principles, existing logo, exact colors/semantic tokens, Manrope/fallback, spacing/density, radii/borders/shadows, breakpoints, both themes, accessibility and anti-patterns |
| [COMPONENTS.md](../motionmate-design-system/COMPONENTS.md) | Navigation/headers, actions, fields/errors, tables/cards, search/filtering/dropdowns, badges, dialogs/drawers, empty/loading/error/locked states, notifications/confirmations and mobile patterns; purpose, behavior, responsive/a11y expectations and use examples |
| [VERTICALS.md](../motionmate-design-system/VERTICALS.md) | Shared identity with distinct Services/Logistics data, workflows, permissions and financial restrictions |
| [Shared lab sources](../../../ui-lab/design-system/) | Semantic tokens, DaisyUI light/dark configuration, Manrope loading, reusable shell/buttons/fields/badges/dialog compositions and generic interaction helpers |
| [Reusable workflow](PREVIEW-WORKFLOW.md) | Request/audit/preview/review/refine/approve/implement/validate/release gates, request example, adding another screen and concrete production proposal requirements |
| [Updated UI skill](../../../.agents/skills/motionmate-ui/SKILL.md) | Audit/Preview/Implementation modes; source/vertical audit, shared system, isolated preview, evidence and explicit design approval followed by separate implementation authorization |
| [AGENTS.md](../../../AGENTS.md) | One short added reference to the system, skill, vertical distinction and authorization boundary; unrelated instructions retained |
| [Services Appointments](../../../ui-lab/services-appointments/README.md) | Synthetic combined work list with original filter/route intents, independent request/appointment access, full record fields and existing creation/detail/edit/history destinations |
| [Launcher/commands](../../../ui-lab/README.md) | One manifest, common build/capture tools and the existing read-only loopback server extended with an optional root; old commands retain their behavior |

## How reuse works

The dashboard stays the frozen Step 4 reference. New previews import the
promoted semantic tokens and shared presentation helpers directly; Appointments
uses these in its own filter-and-record composition. There is no cloned
dashboard layout, new Django app, domain model or JavaScript booking service.

The small registry in `ui-lab/previews.json` lets the launcher select a screen,
synthetic scenario and theme. `build.mjs <screen>` reuses the installed pinned
Step 4 compiler/font packages; `capture.py --screen <screen>` provides standard
Chromium/axe screenshots and comparisons. Screen-specific interaction checks
cover tasks that a generic screenshot tool cannot establish. No new package,
browser installation, root dependency/configuration, generator or server was added.

**Request → Audit → Preview → Review → Refine → Approve → Implement → Validate → Release approval.**
Each screen can be reviewed/refined independently. Shared lab changes require
checks for their consumers; production changes require their own authorization.

To request another screen, name its vertical, existing route/page and task to
improve, then ask for an isolated synthetic preview using the Motionmate UI
skill. For example: “Preview the Services invoice list; preserve current filters,
payment vocabulary and role/entitlement behavior; stop for design approval.”
The [workflow guide](PREVIEW-WORKFLOW.md) supplies the complete reusable example.

## Appointments source audit and design decisions

Inspected the actual workspace template, read projection/filter form, view and
route guards, models/forms, navigation/shared shell, creation/draft-client
contracts and relevant project documentation. The
[screen contract](../../../ui-lab/services-appointments/README.md) records source
links and original paths/methods/fields/conditions.

- Kept scheduled/other existing Appointments and eligible unlinked REQUEST Leads
  distinct. Request preferred time remains unscheduled; request New/Contacted
  remains separate from its Needs follow-up presentation.
- Kept the six original filter names, status bookmark compatibility, row identity,
  history query and 50-row pagination. Filtering acts only on fixture metadata;
  the browser does not compute tenant scope, eligibility or classification.
- Kept New Appointment/Create Request and View/Edit as separate existing route
  intents under supplied independent write flags. No scheduling, approval,
  conversion, status-change, invoice or payment writer is implemented.
- Combined the nine original information subjects into six desktop columns and
  labeled tablet/mobile cards, retaining all fields and meaningful links. Search
  and state lead; secondary filters use a disclosure with submitted values visible.
- Supplied workspace-local timestamps and an explicit zone without changing UTC
  instants. The existing template's timezone presentation is a separate production
  issue. Loading/error/unavailable shells are controlled lab illustrations, not
  claims about new production async handling or decorator responses.
- Preserved current Services role/entitlement behavior in explicit fixtures,
  including request-only, appointment-only, read-only and accountant/viewer cases.
  Documented the separate Logistics financial policy without applying it to Services.

## Browser and preservation evidence

Actual cached **Chromium 148.0.7778.96**, DPR 1, fixed synthetic clock
**14 November 2026 09:00 UTC**, local assets and GET-only static networking.
Standard matrix uses reduced motion; interaction runs use normal-motion preference.

| Check | Result and evidence |
| --- | --- |
| Responsive/theme matrix | **96/96 renders passed:** 15 Appointments scenarios × 3 widths × 2 themes, plus 6 fresh dashboard reference captures. 1440×900, 768×1024, 390×844, viewport/full-page pairs. [Raw results](../../../ui-lab/services-appointments/evidence/results.json), [log](../../../ui-lab/services-appointments/evidence/validation.log) |
| State coverage | Populated, empty, long, admin, staff, accountant, viewer, read-only, request-only, appointments-only, unavailable, controlled loading/error, invalid filter and 52-row pagination |
| Accessibility | Axe-core 4.11.1 WCAG-tag checks: **zero violations and zero incomplete cases** in the final matrix. Visible controls met the 44px target; working text ≥14px; no measured document overflow. Overlay/expanded-filter/account checks and keyboard traversal passed separately. |
| Interactions | Six viewport/theme scenarios, **758/758 checks passed**: applied/combined filters, search/Enter/escaping/validation, historical queries, original route IDs/paths, draft/theme retention, creation/history handoffs, pagination query retention, permission projections, drawer/account/modal keyboard and return focus. [Results](../../../ui-lab/services-appointments/evidence/interactions.json), [log](../../../ui-lab/services-appointments/evidence/interactions.log) |
| Reflow | 320px long-content reflow and 200% layout emulation at 720 CSS px/DPR 2 passed in both themes. This emulates a 1440px viewport at 200%; it is not native browser zoom. |
| Reusable review workflow | **230/230 checks passed:** launcher opens both independent screens/scenarios, gallery links resolve, existing server URLs remain valid, broader roots are rejected, write methods return 405 and launcher handoffs have no browser errors. [Workflow checks](../../../ui-lab/services-appointments/evidence/workflow-checks.json) |
| Design consistency | All **21 sampled semantic colors** match the reference across 6 viewport/theme pairs, including the 5 promoted refinement aliases. Existing mark and Manrope bytes match. Recorded in matrix `comparisons` and `assets`. |
| Step 4 baseline | All **498 existing DaisyUI files** and shared inputs preserved byte-for-byte. All 6 fresh reference viewport captures are **pixel-identical** to the approved Step 4 PNGs. [Pixel comparison](../../../ui-lab/services-appointments/evidence/reference-comparison.json) |
| Scope | **13,576 protected existing files unchanged**, including 12,320 production `src/` files, earlier design evidence and dashboard shared inputs. [Scope report](../../../ui-lab/services-appointments/evidence/scope-check.json), [recheck manifest](../../../ui-lab/services-appointments/evidence/protected-before.json) |
| Source/build checks | Deterministic rebuild of all 11 distribution files; Python lint/format, JavaScript syntax, skill validation, Markdown links and whitespace checks pass. No production lab imports found. [Tool checks](../../../ui-lab/services-appointments/evidence/tool-checks.json) |

The gallery shows current reference and demonstration captures alongside each
other to compare design consistency. It does not present them as before/after
versions of the same application screen. Actual selected images were visually
reviewed in addition to automated geometry/accessibility checks.

Only existing files intentionally edited: `AGENTS.md`, the local UI skill, and
the original lab server's optional static-root parameter. New work stays in
`docs/design/` and `ui-lab/`. The skill is Git-ignored in this checkout: it was
updated locally and validated, without changing ignore rules or force-adding it.

No production source/assets/configuration, Logistics files, ordinary DB records,
migrations, provider settings or existing screenshot artifacts changed. No
Django application/test process, data-writing fixture, collectstatic, commit,
push or deployment ran. Source hash preservation and browser network evidence
support isolation; they are not a live application regression result.

## Open and review

From the repository root:

```sh
.venv/bin/python ui-lab/services-dashboard/tools/serve.py --root ui-lab --port 8765
```

Open <http://127.0.0.1:8765/> for the launcher or
<http://127.0.0.1:8765/services-appointments/evidence/gallery.html> for screenshots.
The [lab README](../../../ui-lab/README.md) includes direct preview URLs, build,
capture and interaction commands. Use another port if 8765 is already occupied.

Try both themes and all three widths; search Jamie, choose Needs follow-up,
combine filters, open a record, toggle theme with unapplied fields, navigate the
drawer with Tab/Escape and inspect request-only/viewer/pagination scenarios.
Give feedback with screen, scenario, viewport and theme so the next refinement
can remain scoped to this preview.

## Approval and remaining limits

The requested deliverables are complete. **Stop for human design review.**
No production implementation has started. After design approval, a separate
explicit authorization must define production files and validation. Likely
Appointments candidates begin with `src/templates/appointments/workspace.html`
and an approved Services-only template/asset boundary. Shared shell/includes,
`src/static/`, `src/apps/`, routes/forms/views, build/configuration and collected
output remain outside preview authorization; the concrete proposal must identify
any required changes before asking to proceed. Commit, push, DB/schema work and
release/deployment remain separately authorized decisions.

Limitations: Chromium only; no Firefox/WebKit, real mobile hardware, native zoom,
screen reader, RTL or full WCAG certification. Latin Manrope coverage needs a
language decision before adoption. CSS table-to-card semantics need real
assistive-technology review. Hover/pressed/disabled variants are specified in
shared CSS but this Step 5 run does not certify every rendered state pairing.
Dialog/role tests prove synthetic presentation, not actual Django authorization,
CSRF, draft persistence, booking availability, quotas, retry transactions,
invoicing, receipt settlement, notifications or provider behavior. No Logistics
browser/runtime verification is claimed because no Logistics implementation was
changed. Production integration, manual usability testing and release work are
separate future tasks.
