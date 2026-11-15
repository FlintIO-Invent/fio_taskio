---
name: motionmate-ui
description: Audit Motionmate UI, run real Django before/after implementation reviews, explore optional isolated prototypes, or implement separately authorized presentation changes while preserving Django workflows and Phoenix. Use for Services, Logistics, or shared-platform screens. Excludes standalone website builds and backend-only changes.
---

# Motionmate UI/UX

Read the repository [AGENTS.md](../../../AGENTS.md) and applicable directory instructions first. **Approved preview direction:** Tailwind CSS 4 + DaisyUI 5, Manrope, existing Motionmate mark and refined Step 4 Services dashboard. **Production foundation:** Phoenix 1.23.0 remains in place. Visual approval is not a production integration or framework migration decision.

For redesigns consult [DESIGN.md](../../../docs/design/motionmate-design-system/DESIGN.md), [COMPONENTS.md](../../../docs/design/motionmate-design-system/COMPONENTS.md), [VERTICALS.md](../../../docs/design/motionmate-design-system/VERTICALS.md), and the [reusable preview workflow](../../../docs/design/motionmate-ui-lab/PREVIEW-WORKFLOW.md). The [Step 4 reference](../../../ui-lab/services-dashboard/daisyui/README.md) stays frozen; the [Appointments demonstration](../../../ui-lab/services-appointments/README.md) shows a second composition.

## Select mode and vertical

At the start of every task, state the **mode**, **target vertical**, **page/route**, and **intended outcome**, using the request and repository evidence.

| Mode | Behavior |
| --- | --- |
| Audit | Inspect and recommend only. Do not edit files, save artifacts, submit forms, create fixtures, or run write-producing checks. Return findings in the response, distinguishing source evidence from browser observations and assumptions. |
| Preview | Optional synthetic design exploration when requested or separately authorized. Create isolated lab files and synthetic fixtures, capture Chromium evidence, refine and stop for explicit human design approval. These are design references, never production previews. |
| Real application review | Default for implementation reviews. Run frozen BEFORE/AFTER Django sources with equivalent synthetic fixtures in separately verified disposable databases. Use local tooling only; actual login, forms, permissions and navigation remain Django behavior. Environment/fixture setup must be authorized. |
| Implementation | Use after design approval and separate explicit authorization identifying the production scope, or for a directly authorized narrow existing-UI repair that does not adopt a redesign. Reuse that authorization within scope; do not ask repeatedly. Preserve Phoenix unless a separate integration decision explicitly authorizes a scoped alternative. |

Use Audit for recommendations/planning, synthetic Preview for optional design exploration, and Real application review for implementation reviews. Skill activation alone authorizes neither fixtures nor production edits. If the screen or vertical is unclear, inspect first and clarify only what cannot be established from repository evidence.

Classify the target as **Services**, **Logistics**, or **Shared platform**. A shared file can serve a vertical-specific task; its directory does not establish the permitted impact.

- Never propagate a vertical-specific design to the other vertical without explicit authorization.
- For a vertical-specific task, scope selectors, includes, and rendering conditions to its existing page or vertical context. Preserve the other vertical's behavior and presentation.
- Before editing a shared parent, include, asset, or token, identify consumers in both verticals and record the intended effect and checks for each. If the proposed change necessarily expands impact beyond authorization, first develop a scoped alternative; otherwise present the concrete expansion for approval and keep dependent edits pending.
- Shared-platform authorization permits the requested shared presentation change, not unification of business logic, roles, or workflows.

## Repeatable workflow

1. **Request and scope:** identify the route, vertical, intended outcome and authorized files.
2. **Audit the actual Django screen:** trace source, workflows, roles and unrelated changes.
3. **Capture interactive BEFORE:** freeze actual working-tree bytes; run real Django only in an authorized disposable environment.
4. **Design proposal and approval:** use the approved Motionmate design system and audited contracts; optional DaisyUI prototypes support this decision.
5. **Scoped implementation:** preserve Phoenix and the authorized vertical; reuse existing authorization within scope.
6. **Django/browser/accessibility/regression validation:** cover actual forms, responsive themes and relevant permissions; shared components require both verticals.
7. **Interactive AFTER comparison:** refresh AFTER alone, retain BEFORE and compare equivalent synthetic context.
8. **Human approval:** identify source, fixtures, findings and limitations; stop for review.
9. **Separate release authorization:** staging, commits, pushes, merges and deployment require explicit approval.

Real application pairs are the default for implementation reviews. Optional
synthetic prototypes support initial design exploration and its separate design
approval; they are never substitutes for working Django applications. Application
implementation still requires its own explicit file/scope authorization. Release
preparation does not authorize commits, pushes, migrations, deployments or providers.
Never modify ordinary local, staging, production or Test Lab databases. Request
the applicable authorization before runtime checks that create temporary files,
use the network, change the environment or create disposable databases. Source
and archive work explicitly requested by the user remains authorized.

### Real application review

Use [the real preview workflow](../../../docs/design/motionmate-ui-lab/PREVIEW-WORKFLOW.md)
and [fresh-checkout setup](../../../docs/design/motionmate-ui-lab/REPRODUCIBILITY.md)
with `scripts/motionmate_preview.py`. Capture BEFORE from actual working-tree bytes,
including uncommitted/untracked runtime sources; never assume Git HEAD is the
baseline. Preserve current work. Run two independent copies, not template mockups,
screenshots or a UI Lab controller. `capture` freezes source, `create` prepares
verified disposable clusters and starts both real apps; `refresh-after` updates
AFTER alone following authorized implementation. It refuses migration changes.
For the historical Step 7 comparison only, `capture --git-ref
34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c` reads the verified original runtime
directly from local Git objects without checking out or resetting the worktree.
No temporary Step 7 runner/backup is needed. Follow the
[preservation guide](../../../docs/design/motionmate-ui-lab/PRESERVATION.md) for
essential screenshots and the separate local historical archive.

Verify host, port, process, actual PostgreSQL directory/system identifier and
disposable ownership before database work. Never clone ordinary records, secrets,
uploads or environment files. Keep providers, real email and financial operations
disabled. Use distinct databases and session/CSRF cookies so both apps can remain
open. Exercise real login/POST/CSRF, navigation, roles, subscription states,
responsive themes and affected contracts; check other verticals when shared
sources are involved. Record intentional unavailable integrations and runtime
workarounds instead of pretending those interactions work.

Fixtures match at creation. Review writes persist independently; never silently
resynchronize/reset them. Preserve source/evidence identities, provide actual
BEFORE/AFTER URLs, local test accounts and start/stop/cleanup commands, then stop
for human review. Leave previews available unless the user asks to stop them.

### Optional synthetic prototype

For every synthetic Preview/prototype task:

1. Identify the screen, route, vertical, scope and desired task outcome.
2. Audit the real template/shell, view/service, form, route and current interactions, including unrelated edits.
3. Consult the approved design system and existing components before composing the screen.
4. Record data, workflow, role, entitlement, write, financial and tenant constraints. Services and Logistics policies remain separate.
5. Create a separate document under `ui-lab/<screen>/`, using synthetic data and shared lab tokens/components. Reuse the existing static server and pinned toolchain; add no Django app/route, production CSS import or ordinary-database fixture. Use `scenario` for review states when `state` is an existing application filter.
6. Run actual Chromium light/dark captures at 1440/768/390px, keyboard/interaction checks, axe and targeted reflow checks. Record errors, failed requests, incomplete accessibility results and what was not exercised. Keep comparisons in the new screen's evidence tree; preserve existing reference files.
7. Present screenshot/gallery links, a concise change summary, contract decisions, scope evidence and limitations. Request → review → refinement can repeat independently for each screen; regenerate only affected evidence and label partial runs.
8. **Stop for explicit human design approval. After approval, request separate authorization before modifying production application files.** Prepare a concrete file/scope/validation proposal first. Never treat design approval as authorization to commit, push, migrate or deploy; release approval is a further decision.

The sections below guide audits and separately authorized implementation. In synthetic Prototype/Preview mode, navigation/actions are simulations. In real application reviews, interactions run the actual application against only the authorized disposable data.

### 1. Identify the target and baseline

Read the working-tree status and relevant project documentation. Resolve the actual template, inherited shell, current-business context, and existing interaction. Record unrelated edits to preserve. Establish whether the screen uses Phoenix or the separate public-site theme before choosing assets.

### 2. Audit the implementation

Trace relevant templates/includes, CSS, JavaScript, views/services, forms, named routes, permissions, and existing interactions. Inspect loaded assets rather than assuming an editable source file is the served file. Review normal, empty, error, restricted, and long-content states.

Identify a concrete task-completion problem: unclear next action, avoidable navigation, lost context, weak hierarchy, redundant information, inaccessible controls, or responsive friction. Support findings with file references. Do not claim browser behavior or measured contrast from source inspection alone.

### 3. Select the component pattern

For Preview mode, use approved lab tokens/components and the screen's audited contracts. Consult [the Phoenix and application map](references/phoenix-map.md) to understand the real integration. For authorized Phoenix implementation, prefer an existing application include, then a Phoenix component/composition. Inspect applicable read-only, Git-ignored `design_references/phoenix/` examples; report if absent. Do not mix Tailwind/DaisyUI with the production shell or copy the frozen dashboard to create each new screen.

### 4. Define the smallest improvement

Describe the intended change, affected files/components, and the reason it improves the task. Distinguish Phoenix configuration, component customization, and a new application composition. Separate proposed process changes from presentation work; do not redesign a business process without explicit authorization.

Use these design conventions:

- Aim for a modern, distinctive, professional workspace through clear operational content and Motionmate branding. Avoid generic AI dashboard styling, excessive cards, unnecessary gradients, ornamental metrics, and decorative animation.
- Establish a clear page title, readable typography, consistent spacing, and an obvious primary task. Keep secondary and destructive actions distinguishable; do not suppress required choices to achieve visual simplicity.
- Reuse approved semantic lab tokens in previews; use semantic Phoenix tokens for authorized Phoenix changes. Keep existing brand assets and define both themes for any new scoped token.
- Use shared lab components in previews and existing Phoenix/Django includes in production work. Keep status meaning and accessible text consistent while allowing vertical-specific layouts.
- Make mobile, tablet, and desktop behavior deliberate. Prioritize essential record information, preserve table semantics and actions, and keep related controls aligned or stacked appropriately.
- Provide labels, semantic headings, keyboard access, visible focus, readable contrast, touch-friendly controls, and accessible errors. Support existing light/dark modes and reduced motion; animate only useful state changes.

### 5. Preserve functional contracts

Before editing, identify the affected contracts and retain them:

| Contract | Inspect and preserve |
| --- | --- |
| Forms and navigation | URLs, HTTP methods, query parameters, return links, field names/prefixes, hidden values, CSRF, retry/operation keys, validation and submitted payloads |
| Authorization and isolation | Resolved Business, scoped querysets, membership/role/module/subscription/write conditions, quotas, and Logistics location grants; server checks remain authoritative |
| JavaScript | IDs, selectors, `data-*` hooks, events, modal/tab targets, initialization order, and progressive fallback |
| Drafts and bookings | Inline client creation, unsaved inputs, selected values, availability, request review, and appointment confirmation |
| Finance and operations | Authoritative totals, lifecycle versus payments/credits/refunds/review, clearance, allowed transitions, scanner fallback, and print/PDF behavior where affected |

Move complete conditional blocks with their guards. Do not substitute different endpoints, infer payment or permission state in the browser, or hide validation errors to simplify a design.

### 6. Implement only authorized scope

In Audit mode, stop before edits. In Preview mode, edit only authorized lab/documentation files and stop after review evidence. In Implementation mode, modify only the separately authorized production files. Preserve local Phoenix patches and unrelated edits; do not replace vendor bundles or regenerate reference/collected assets casually. Dependency additions and process changes require their own scope. Data, migrations, external services, commits, pushes and deployment remain separately controlled actions.

### 7. Validate the result

Check the diff for scope and contract preservation, then run checks appropriate to the change. Inspect existing browser scripts before execution: some create fixtures or artifacts and need an authorized disposable environment. Never submit verification writes against an uncertain or ordinary application database.

For implementation, verify actual browser rendering at representative mobile, tablet, and desktop widths (for example 390, 768, and 1440 pixels), both light/dark themes, long text, empty/error/restricted states, wrapping, overflow, and accessible action placement. Check keyboard navigation, focus/return focus, labels, validation feedback, and reduced motion where relevant.

Exercise the affected navigation, filters, pagination, draft preservation, form payloads, and permitted/restricted actions. For shared changes, cover both verticals; for vertical-specific changes touching shared files, also verify the other vertical remains unchanged. Use targeted existing tests for affected behavior rather than tests that merely mirror markup.

If browser tooling or authorized fixtures are unavailable, complete safe checks and explicitly report the missing verification. Do not install tooling, create data, or claim a rendered pass to fill that gap without authorization.

### 8. Report evidence

Report mode, vertical, page, findings or changes, file references, preserved contracts, and shared-component impact. List checks actually performed and their results; separate static inspection, isolated tests, browser evidence, and live verification. State remaining limitations and any separately proposed work. Audit recommendations are not implementation authorization.
