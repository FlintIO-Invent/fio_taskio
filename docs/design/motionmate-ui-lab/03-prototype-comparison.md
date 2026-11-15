# Motionmate UI Lab — Tabler vs. DaisyUI prototype comparison

> Historical step report. Steps 1–8 were subsequently completed and approved.
> Current setup/approval boundaries: [reproducible workflow](REPRODUCIBILITY.md).
> Complete historical evidence is in the [separate local archive](PRESERVATION.md).

**15 November 2026 · Step 3 · Isolated Services dashboard prototypes**

Both prototypes are ready for human review. **No framework has been selected.** They implement the same synthetic Services workspace and task hierarchy with different component treatments. Neither is integrated into Motionmate, and Logistics is unchanged.

Start with the [lab README](../../../ui-lab/services-dashboard/README.md), [review launcher](../../../ui-lab/services-dashboard/index.html), [screenshot gallery](../../../ui-lab/services-dashboard/evidence/gallery.html), or [complete screenshot index](../../../ui-lab/services-dashboard/evidence/screenshot-index.md). The launcher and gallery work through the local read-only server described below.

## What was built

| | Prototype A | Prototype B |
| --- | --- | --- |
| Framework | Tabler + its bundled Bootstrap interaction runtime | Tailwind CSS + DaisyUI; native dialogs and a local interaction adapter |
| Source | [Tabler renderer](../../../ui-lab/services-dashboard/tabler/src/render.js), [styles](../../../ui-lab/services-dashboard/tabler/src/style.css), [adapter](../../../ui-lab/services-dashboard/tabler/src/app.js) | [DaisyUI renderer](../../../ui-lab/services-dashboard/daisyui/src/render.js), [styles/theme configuration](../../../ui-lab/services-dashboard/daisyui/src/input.css), [adapter](../../../ui-lab/services-dashboard/daisyui/src/app.js) |
| Independent output | [tabler/dist/index.html](../../../ui-lab/services-dashboard/tabler/dist/index.html) | [daisyui/dist/index.html](../../../ui-lab/services-dashboard/daisyui/dist/index.html) |
| Exact dependencies | `@tabler/core` **1.7.5**, `esbuild` **0.28.2** | `tailwindcss` / `@tailwindcss/cli` **4.3.5**, `daisyui` **5.8.0**, `esbuild` **0.28.2** |
| Dependency resolution | [Separate lockfile](../../../ui-lab/services-dashboard/tabler/package-lock.json) | [Separate lockfile](../../../ui-lab/services-dashboard/daisyui/package-lock.json) |

The separate renderers and CSS use native framework components and custom compositions. Shared inputs are [synthetic fixtures and route intents](../../../ui-lab/services-dashboard/shared/fixtures.js), [semantic tokens](../../../ui-lab/services-dashboard/shared/tokens.css), existing Feather SVGs, the unchanged Motionmate mark, and one local font file. The [common controller](../../../ui-lab/services-dashboard/shared/controller.js) implements only the identical read-only simulation contract. Framework-specific component behavior remains in each adapter. Each output bundles its own dependencies and can be rebuilt without the other framework installed.

The user authorized dependency selection/building in Step 3. The repository's Phoenix preservation rules still apply to production; these experiments do not inherit its shell or alter its assets. No root package manifest, production configuration, Django app or route was added.

### Preflight choices and unresolved design defaults

- Used the existing **Node 24.2.0 / npm 11.4.2** toolchain, project Python environment, installed Python Playwright and cached Chromium. No new browser or Python package was installed. Lab dependency installs used exact versions, separate locks and disabled install scripts.
- No suitable locally bundled Manrope/Nunito text font asset was found. Both use the brief's existing-family fallback, **Nunito Sans**, supplied locally through pinned `@fontsource-variable/nunito-sans` **5.3.0**. The same Latin variable WOFF2, mark and icons are copied into both independent outputs, with license notices. This compares the fallback typography, not the proposed Manrope candidate.
- Adopted the approved indigo/navy tokens, restrained surfaces, canonical **Motionmate** spelling, 1200px two-column threshold and 768px tablet threshold. Mobile previews show three rows with local reveal-more controls. Secondary metrics, sharing and settings follow the work queues.
- Kept “Today's appointments” with an explicit capped **Next scheduled** preview and authoritative today/upcoming counts. The fixture times are workspace-local, with an explicit zone; the two different 02:30 instants in the DST variant retain their different offsets.
- Both omit the broken global mobile search. Both preserve supplied invoice lifecycle/payment labels and currency; neither exposes the commented finance table or calculates financial settlement.
- Current framework documentation has different browser floors: Tabler lists Chrome/Edge 123+, Firefox 128+, Safari/iOS 17.5+; Tailwind 4 lists Chrome 111+, Firefox 128+, Safari 16.4+. The prototypes use the common modern build target. **Only Chromium was actually tested**; this does not establish a new Motionmate browser-support policy. [Tabler support](https://docs.tabler.io/ui/getting-started/browser-support), [Tailwind compatibility](https://tailwindcss.com/docs/compatibility).

## Screenshots

These are actual Chromium **148.0.7778.96** captures of the standalone builds, not mockups. Standard captures use DPR 1, a fixed synthetic clock of **14 November 2026, 09:00 UTC**, identical locally served assets, reduced motion and the same viewport sizes. Full-page images are taller than the viewport.

### Populated workspace

| Prototype / viewport | Light viewport | Light full page | Dark viewport | Dark full page |
| --- | --- | --- | --- | --- |
| A · 1440 × 900 | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-1440-light-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-1440-light-full.png) | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-1440-dark-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-1440-dark-full.png) |
| B · 1440 × 900 | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-1440-light-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-1440-light-full.png) | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-1440-dark-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-1440-dark-full.png) |
| A · 768 × 1024 | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-768-light-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-768-light-full.png) | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-768-dark-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-768-dark-full.png) |
| B · 768 × 1024 | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-768-light-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-768-light-full.png) | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-768-dark-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-768-dark-full.png) |
| A · 390 × 844 | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-390-light-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-390-light-full.png) | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-390-dark-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-populated-390-dark-full.png) |
| B · 390 × 844 | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-390-light-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-390-light-full.png) | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-390-dark-viewport.png) | [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-390-dark-full.png) |

### Selected mobile states

The [complete index](../../../ui-lab/services-dashboard/evidence/screenshot-index.md) links every state at all three widths in both themes, with viewport/full-page pairs. These examples make the important edge cases easy to inspect:

| State | A | B |
| --- | --- | --- |
| Empty, light | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-empty-390-light-full.png) | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-empty-390-light-full.png) |
| Modules locked, dark | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-locked-390-dark-full.png) | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-locked-390-dark-full.png) |
| Long content, dark | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-long-390-dark-full.png) | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-long-390-dark-full.png) |
| Viewer role, light | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-viewer-390-light-full.png) | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-viewer-390-light-full.png) |
| Financial edges, light | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-financial-edge-390-light-full.png) | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-financial-edge-390-light-full.png) |
| Setup guide, dark | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-guide-390-dark-viewport.png) | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-guide-390-dark-viewport.png) |
| Expanded navigation, light | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-navigation-390-light.png) | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-navigation-390-light.png) |
| Clipboard denied, light | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/tabler-copy-denied-390-light.png) | [Full page](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-copy-denied-390-light.png) |

## Objective results against the brief

The [reproducible validation harness](../../../ui-lab/services-dashboard/tools/validate.py), [raw results](../../../ui-lab/services-dashboard/evidence/results.json) and [final matrix log](../../../ui-lab/services-dashboard/evidence/validation.log) distinguish browser observations from synthetic business inputs.

- **264 distinct renders passed**: 2 prototypes × 22 states × 3 widths × 2 themes. All received viewport and full-page captures: **528 standard PNGs**.
- **132 A/B pairs matched** on the complete supplied fixture payload, normalized content tokens and ordered named-route/ID/query intent maps. Different markup ordering is allowed; missing content is not. Normalization separates DOM text-node boundaries so a badge placed earlier does not create a false content mismatch.
- **12 interaction scenarios passed**, covering both frameworks at each width/theme, with **184 passing checks** across the scenarios. Checks exercised skip navigation, theme/disclosure state, mobile/tablet menu focus trapping and return, drawer navigation handoffs, account keyboard behavior, record/detail routes, needs-follow-up query strings, clipboard success/denial, setup intent fields, the static guide's Escape behavior and reflow.
- **Six additional normal-motion handoff cases passed** (16 checks). They verify that guide-to-workspace spotlight, welcome-to-guide and drawer-to-detail transitions preserve focus after animations complete. The final [normal-motion log](../../../ui-lab/services-dashboard/evidence/normal-motion-final.log) records these separately from the reduced-motion matrix.
- **Zero unexpected page errors, failed required requests or axe WCAG-tag violations** were recorded in the final matrix. All recorded application/asset requests were local GETs; route handoffs and form submits were intercepted in memory.
- Additional navigation, copy-denied, reflow and zoom-emulation captures bring the total to **566 PNGs**. A final manual review found the native mobile drawer pane extending beyond its viewport; its padding was corrected, and B's two mobile guide renders and two interaction scenarios were recaptured/retested. This scoped verification is recorded in `results.json.verification_history` and confirms a 390 × 844 pane at x=0/y=0.

### Measured hierarchy and density

Coordinates are document positions for the standard light fixture; dark geometry matches. “Appointments top” is the section top, not a claim that the preview is the entire day's schedule.

| Viewport / measure | Phoenix baseline | A · Tabler | B · DaisyUI |
| --- | ---: | ---: | ---: |
| 1440 · appointments top | 1,302px | 214.5px | 214px |
| 1440 · booking follow-up top | 737px | 214.5px | 214px |
| 768 · first appointment row | Not separately recorded | 316.6px | 317.1px |
| 768 · booking follow-up top | 1,054px | 818.6px | 819.1px |
| 390 · appointments top | 2,345px | 194px | 194px |
| 390 · first appointment row | Not separately recorded | 293.1px | 295.1px |
| 390 · booking follow-up top | 1,661px | 779.1px | 871.1px |
| 390 · first request row | Not separately recorded | 858.2px | 950.2px |
| 390 · booking URL input | 94px wide | 324px wide | 324px wide |
| 390 · default page height | 3,963px | 2,926px | 3,007px |

The mobile height reduction uses intentional three-row previews with reveal-more controls. Both retain all five supplied preview rows; desktop/tablet show all five initially. These are useful task-density differences, not a claim that the frameworks themselves determine page height.

| Brief requirement | Result / practical limit |
| --- | --- |
| V1 desktop hierarchy | **Pass, both.** Both section headings start before y=240; at least three records from each queue are visible before y=900. |
| V2 tablet hierarchy | **Pass, both.** First appointment before y=320, follow-up heading before y=820, first request before y=1024. |
| V3 mobile hierarchy | **Pass, both.** First appointment before y=300; follow-up heading before y=960 and first request before y=1120. Readable rows remain ahead of metrics. |
| V4 responsive integrity | **Pass for measured cases.** No document/main overflow across the matrix; 320px reflow checks passed. Desktop 200% zoom was emulated with half the CSS viewport and DPR 2, not CSS `zoom`. Browser-native zoom controls, real touch zoom and other browser engines remain unverified. |
| V5 useful density | **Pass.** No KPI wall/charts; metric subjects remain in their relevant regions; mobile URL uses a full row. Working text is at least 14px and measured visible controls meet the 44px project target. |
| V6 light/dark states | **Pass for captured/default and scripted states.** Shared semantic colors, preserved disclosure/theme state and local font loading. Comprehensive hover/pressed-state contrast certification is not claimed. |
| A1 accessibility | **Automated/name/focus/size checks passed; manual review remains.** Axe reported no WCAG-tag violations, but **16 renders have incomplete color-contrast checks** in welcome/guide and long-content variants. They are recorded rather than treated as automatic passes. No screen-reader or full conformance audit was performed. |
| F1 data/route parity | **Pass, 132 pairs.** Identical fixture values, currencies, ordering and intent maps. No workflow or financial calculation is implemented. |
| F2 preview honesty | **Pass in fixtures.** Today/next-scheduled/empty/locked/DST states stay distinct; reveal-more is local and does not fetch another dataset. |
| F3 permissions/guidance | **Pass as simulation.** Viewer keeps existing Services financial/appointment reads; settings/setup actions follow supplied role flags. Guides record the original intent fields. Actual Django authorization, persistence and transaction behavior were not executed. |
| F4 interaction behavior | **Pass for scripted cases.** Both framework adapters support the required simulations, focus and feedback without real navigation or POSTs. |
| I1 isolation | **Pass.** Separate assets/build graphs; no production inheritance or provider/database calls. Font/mark bytes match across builds. Scope fingerprints confirm existing sources/evidence were preserved. |
| E1 fair evidence | **Pass for automated comparison.** Same browser, fixtures, fonts, clock, dimensions and scripts. No human timing study or blinded preference scoring has occurred. |

## Visual strengths and weaknesses

### A — Tabler + Bootstrap

**Strengths:** clear time/customer/status columns, restrained full-width row dividers and a familiar operational reading rhythm. The appointment section has less mobile vertical overhead: follow-up starts approximately **92px earlier** than B with the same three visible appointments. The light and navy dark surfaces remain coherent without a large brand-colored banner. Finance uses explicit table headings on desktop and readable stacked records on mobile.

**Weaknesses:** the schedule header/table label region still occupies noticeable space on desktop, and the bordered secondary buttons can make lower-page configuration feel busy. The structural treatment is more conventional; humans should assess whether it expresses enough Motionmate character without adding decoration. Long company/service lines still produce substantial row growth, although they do not overflow.

### B — Tailwind CSS + DaisyUI

**Strengths:** the narrow appointment accent and tinted time anchors make the schedule's entry point more distinct. Inset list dividers and the quieter finance summary separate working records from secondary figures. The navigation's current-page accent and native-dialog treatment provide a different interpretation of the same token system without adding product features.

**Weaknesses:** time tiles plus status placement use more height on mobile; the standard default page is approximately **81px taller** than A. Full long-content examples grow significantly and may warrant a review of secondary detail placement. Native dialogs needed an explicit keyboard trap and a mobile padding correction; DaisyUI styling alone did not establish the required behavior.

### Shared concerns for review

- Mobile section actions and Setup Guide are icon-only to preserve the readable header layout. Their accessible names and target sizes pass, but discoverability needs human task testing. A labeled “All appointments” treatment is a reasonable refinement to compare, provided both prototypes keep the same intent and density rules.
- Nunito Sans makes the comparison reproducible and preserves the approved fallback; it does not settle the Manrope typography decision.
- “Today's appointments” plus a next-scheduled preview is labeled honestly, but people may still prefer the brief's alternative heading “Appointments” with a separate “Today: 5 scheduled” caption. Neither prototype adds a full-day schedule query.
- All supplied secondary figures remain available, so the lower page is still substantial. Choosing a default expansion policy for workspace/share details is a product-design decision, not a reason to drop information from one candidate.
- Complete the 16 incomplete contrast reviews and real assistive-technology checks before calling either design accessible or ready for production.

## Asset sizes

Sizes are the actual standalone outputs, rounded to **KiB (1024 bytes)**. Gzip values use the same local level-9 compression for each file. The static review server serves uncompressed files; these gzip figures are a controlled comparison, **not observed production transfer sizes or page-speed scores**. Legal notices and test-only axe code are excluded from page-loaded totals.

| Asset group | A raw | A gzip | B raw | B gzip |
| --- | ---: | ---: | ---: | ---: |
| CSS, including shared tokens | 688.8 | 88.1 | 56.2 | 10.5 |
| JavaScript | 186.5 | 53.5 | 39.0 | 10.3 |
| Identical local WOFF2 | 30.3 | 30.4 | 30.3 | 30.4 |
| Identical Motionmate SVG | 1.7 | 0.7 | 1.7 | 0.7 |
| HTML | 1.0 | 0.5 | 0.9 | 0.5 |
| **Page-loaded total** | **908.2** | **173.2** | **128.2** | **52.3** |

WOFF2 is already compressed, so gzip does not improve it. Exact byte sizes and SHA-256 values are in `results.json.assets`.

A uses Tabler's distributed core CSS plus local overrides, and its core module retains Bootstrap/component initialization code. B uses a compiled utility/component subset plus a small native interaction layer. The size difference reflects those actual build choices; it is not a lower bound for a selectively compiled Tabler build or a complete measure of maintenance effort. No chart/map/editor bundles, CDN assets or application Phoenix/Silicon assets are loaded in either page.

## Dependency, CSS isolation and Django integration risks

| Concern | A | B |
| --- | --- | --- |
| Framework runtime | Familiar Bootstrap-style components still require version-specific initialization. A duplicate dropdown handler was found and fixed by letting the native data API own it. | Native dialogs provide useful behavior, but keyboard cycling, menu handling and setup contracts require a small adapter. Those adapters are code to maintain. |
| Global CSS | Tabler/Bootstrap globals collide with existing `.btn`, `.card`, navbar and reset rules if mixed into the production shell. | Tailwind Preflight, DaisyUI component names, theme roots and scroll behavior can conflict with the existing shell. Prefixes do not isolate every global rule. |
| Theme state | A uses the shared lab key and explicit attributes instead of default Tabler/Phoenix persistence. Native component state needs continued testing. | Custom DaisyUI themes map to the same tokens. Source scanning and theme configuration must include future templates/variants explicitly. |
| Existing setup JS | This prototype imports the pinned module APIs; it does not prove compatibility with production `window.bootstrap` consumers. | Preserved IDs/intent metadata are not a Bootstrap compatibility shim. Porting the existing guide interaction would require explicit integration work. |
| Django templates | Static markup can later consume the existing context and named routes, but this is not a drop-in replacement of the shared parent. | Same server context can be consumed without a frontend framework, but generated class detection and local behavior need a deliberate build/template boundary. |
| Production navigation | Moving from this standalone dashboard into unchanged Services pages needs a reviewed visual/asset handoff. | Same boundary. A lab success does not authorize replacing all Services screens or any Logistics page. |

The [Tabler installation documentation](https://docs.tabler.io/ui/getting-started/installation) warns against a second Bootstrap runtime. [DaisyUI configuration](https://daisyui.com/docs/config/) and [Tailwind Preflight](https://tailwindcss.com/docs/preflight) explain controls relevant to B's CSS boundary. These risks are recorded for both candidates; neither is automatically considered the easier or safer Django integration.

Separate documents and asset graphs currently provide the isolation. Production integration would require a Services-dashboard-only implementation plan, server-side contract tests and evidence that Logistics asset requests/rendering are unchanged. That work is outside Step 3.

## Evidence boundaries and next review

The 22 fixture states cover populated/empty data, future and earlier appointments, independent module locks, all five current roles, read-only/grace messaging, sharing absence, long text/large amounts, welcome/guide, controlled pending/error, financial presentation edges and a DST boundary. These are **presentation simulations**, not provider events or seeded tenants. Current role rules were inspected in source; hiding controls here does not test financial authorization.

Actual browser checks cover rendering, text/target sizing, focus/navigation, copy feedback and intent payloads. They do **not** prove booking availability, inline client draft preservation, invoicing calculations, payment settlement, real onboarding persistence, tenant authorization, PostgreSQL concurrency or provider behavior. Those existing workflows were not modified or exercised. The future integration must keep their existing services/routes and CSRF/operation/retry fields authoritative.

Production source and earlier audit/brief artifacts were fingerprinted before work; **12,350 existing files remained unchanged**. Scope/independent-build verification is recorded in [scope-check.json](../../../ui-lab/services-dashboard/evidence/scope-check.json). New implementation files are confined to `ui-lab/services-dashboard/`; this report is the only new design document. No database, migration, commit, push or deployment action occurred.

For local review, from the repository root:

```sh
.venv/bin/python ui-lab/services-dashboard/tools/serve.py --port 8765
```

Open `http://127.0.0.1:8765/`, choose a state and open either prototype. Rebuild and validation commands are in the README. The server serves only the lab tree on loopback and rejects writes.

Next human checkpoint: review both at the same widths/themes and with the same task prompts, complete contrast/accessibility review, and decide which visual details to refine. A separate decision can consider dependency/build/integration costs after the visual review. **No winning framework or production rollout is recommended automatically. Step 3 stops here.**
