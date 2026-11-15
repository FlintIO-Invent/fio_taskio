# Motionmate UI Lab — DaisyUI visual refinement

> Historical step report. Steps 1–8 were subsequently completed and approved.
> Current setup/approval boundaries: [reproducible workflow](REPRODUCIBILITY.md).
> Complete historical evidence is in the [separate local archive](PRESERVATION.md).

**15 November 2026 · Step 4 · Services dashboard · Ready for human review**

The existing DaisyUI prototype now has a stronger Motionmate frame, clearer typography and actions, and a substantially denser mobile appointment queue. **Manrope is the recommended typography candidate.** Tabler remains an unchanged reference. This is an isolated design study, with no production integration.

Start with the [before/after and typography gallery](../../../ui-lab/services-dashboard/daisyui/evidence/step4/gallery.html), [complete screenshot index](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshot-index.md), or [refinement README](../../../ui-lab/services-dashboard/daisyui/README.md). The gallery includes original DaisyUI, refined DaisyUI and Tabler at identical viewport sizes and in both themes.

## Scope and preserved contracts

Read the root `AGENTS.md`, `motionmate-ui` skill and Phoenix map, and all three preceding lab documents. Reviewed the actual baseline/prototype screenshots, recorded geometry, current DaisyUI renderer/styles/build, shared fixture/controller contracts and read-only Phoenix component reference. Implementation mode applies only to the standalone **Motionmate Services dashboard**.

Changes are confined to `ui-lab/services-dashboard/daisyui/` and this report. Tabler, shared fixtures/tokens/icons/controller, original Step 3 tools/evidence, audit/brief/comparison documents, production templates/assets/routes/configuration, and Motionmate Logistics remain unchanged. A frozen copy of the original DaisyUI distribution is saved inside the DaisyUI evidence directory for reproducible comparisons.

The same 22 synthetic states, instants, record order, counts, currencies, supplied financial amounts, invoice lifecycle/payment labels, role and entitlement predicates remain in use. All existing route intents, query parameters, public-link attributes, setup forms/fields, hooks and overlay contracts are preserved. No scheduling, approval, payment, search or other workflow capability was added. Navigation and form actions remain local simulations; no application POST is executed.

## Visual changes

| Area | Refined treatment and reason |
| --- | --- |
| Brand frame | Existing logo unchanged; violet Services descriptor, indigo active-navigation icon and restrained cyan time rail. Slightly tinted sidebar separates navigation from white/navy working surfaces. No new gradient, chart or ornamental illustration. |
| Typography | Manrope default; 32px desktop/28px mobile page title, 20px section headings, 15px desktop/16px mobile record names, and 14px supporting text. More deliberate weights and alignment; tabular time/amount figures retained. |
| Appointments | Compact time/date anchors remain distinctive. Scheduled status sits beside the customer on desktop/tablet and within the time column on mobile. Customer, service, visit title and company remain readable and complete. Natural row growth handles long content. |
| Page and section hierarchy | Heading becomes **Appointments**, with the authoritative scheduled-today count and explicit **Next scheduled** caption. This adopts the brief's wording alternative without implying that five future records form a complete daily schedule. Appointments and follow-up remain ahead of finance, sharing and configuration. |
| Actions | Mobile section actions now visibly say **Open** or **View** in their section context; full accessible names and route-preview titles remain Open Appointments, View bookings and View invoices. Mobile navigation says Menu; the setup control says Setup, with Open Setup Guide as its accessible name. Desktop retains full labels. |
| Navigation | Clearer active icon/surface, consistent menu rhythm and a calmer workspace identity. Mobile drawer uses the same frame treatment and 48px navigation rows. Existing focus trapping, Escape and return-focus behavior remains. |
| Secondary information | Finance stays one quiet region, with slightly smaller 22px summary amounts, explicit currency and unchanged terminology. Workspace rows and footers use less vertical padding. No metric subject or reporting period was removed. |
| Themes and interaction | Equal light/dark treatments, explicit hover/pressed/busy colors, readable disabled clipboard state and visible focus. Record focus rings sit inside the row to avoid clipping at panel edges. Scroll margins protect keyboard focus from the sticky header. |

Refinement aliases are local to this document; shared tokens are unchanged:

| Alias / purpose | Light | Dark |
| --- | --- | --- |
| `--mm-services-frame` · navigation | `#F0F2FA` | `#101829` |
| `--mm-services-current` · current page | `#E9EDFF` | `#242F53` |
| `--mm-services-header` · appointment header | `#FBFBFE` | `#151F33` |
| `--mm-services-violet` · brand labels | `#6A4FC2` | `#C8B6FF` |
| `--mm-services-cyan` · decorative time rail | `#087B9F` | `#79D9F6` |

Indigo actions, semantic status colors, canvas/text colors and the existing logo remain grounded in the approved brief. The cyan rail is decorative; text communicates time and status independently of color.

## Before and after screenshots

Actual Chromium **148.0.7778.96**, DPR 1, fixed synthetic clock of 14 November 2026 at 09:00 UTC. Standard screenshots use reduced motion. Full-page captures are taller than their named viewport. Original screenshots are preserved Step 3 artifacts; refined captures are from the rebuilt prototype.

| Viewport / theme | Original DaisyUI | Refined DaisyUI |
| --- | --- | --- |
| 1440 × 900 · light | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-1440-light-viewport.png) · [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-1440-light-full.png) | [Viewport](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-1440-light-viewport.png) · [Full](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-1440-light-full.png) |
| 1440 × 900 · dark | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-1440-dark-viewport.png) · [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-1440-dark-full.png) | [Viewport](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-1440-dark-viewport.png) · [Full](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-1440-dark-full.png) |
| 768 × 1024 · light | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-768-light-viewport.png) · [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-768-light-full.png) | [Viewport](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-768-light-viewport.png) · [Full](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-768-light-full.png) |
| 768 × 1024 · dark | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-768-dark-viewport.png) · [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-768-dark-full.png) | [Viewport](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-768-dark-viewport.png) · [Full](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-768-dark-full.png) |
| 390 × 844 · light | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-390-light-viewport.png) · [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-390-light-full.png) | [Viewport](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-390-light-viewport.png) · [Full](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-390-light-full.png) |
| 390 × 844 · dark | [Viewport](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-390-dark-viewport.png) · [Full](../../../ui-lab/services-dashboard/evidence/screenshots/daisyui-populated-390-dark-full.png) | [Viewport](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-390-dark-viewport.png) · [Full](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-populated-390-dark-full.png) |

Additional evidence includes [long content](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-long-390-dark-full.png), [empty](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-empty-390-light-full.png), [locked](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-locked-390-dark-full.png), [viewer](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-viewer-390-light-full.png), [drawer](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-navigation-390-light.png), [setup guide](../../../ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/daisyui-guide-390-dark-viewport.png), and [keyboard focus](../../../ui-lab/services-dashboard/daisyui/evidence/step4/details/focus-light-primary.png). Every state has viewport/full-page pairs at all three widths in both themes.

## Density and comparison with Tabler

Document coordinates below use the populated light fixture; dark geometry matches. Original A/B use Nunito Sans. Refined default uses Manrope, so the final column provides the **same refined layout in Nunito Sans** to separate layout improvements from font effects.

| Measurement | Original DaisyUI | Tabler reference | Refined Manrope | Refined Nunito |
| --- | ---: | ---: | ---: | ---: |
| 1440 · work areas start | 214px | 214.5px | 205px | 206px |
| 768 · first appointment | 317.1px | 316.6px | 294.6px | 295.1px |
| 768 · follow-up section | 819.1px | 818.6px | 811.6px | 812.1px |
| 390 · first appointment | 295.1px | 293.1px | 291.6px | 291.1px |
| 390 · first appointment height | 149px | 118px | 109px | 109px |
| 390 · follow-up section | 871.1px | 779.1px | 731.6px | 731.1px |
| 390 · first request | 950.2px | 858.2px | 809.2px | 808.2px |
| 390 · document height | 3,007px | 2,926px | 2,782px | 2,781px |

The mobile appointment row is **40px / 27% shorter** than original DaisyUI. Follow-up starts approximately **140px earlier**, and the complete page is **225px / 7.5% shorter**. The same improvement holds with Nunito, without shrinking record text, dropping fields or changing the three-row disclosure policy. Tabler's useful density informed the change; its prototype was not edited. Long records still grow naturally and are not held to these standard-fixture heights.

The refined time treatment is more distinctive than Tabler's plain time column. Tabler still offers a very straightforward operational reading rhythm. The new mobile labels are more discoverable than the former arrows, but Open/View/Setup are intentionally short and need human task testing in context.

## Typography comparison and recommendation

Captured **12 controlled font renders**, each with viewport/full-page screenshots: both fonts × three sizes × two themes. Only the font changes; normalized content, fixtures and route intents match in all six pairs. Browser font-face status confirms the selected local font loaded and the alternate remained unloaded.

Compare [Manrope desktop](../../../ui-lab/services-dashboard/daisyui/evidence/step4/details/font-manrope-1440-light-viewport.png) with [Nunito desktop](../../../ui-lab/services-dashboard/daisyui/evidence/step4/details/font-nunito-1440-light-viewport.png), and [Manrope mobile](../../../ui-lab/services-dashboard/daisyui/evidence/step4/details/font-manrope-390-dark-viewport.png) with [Nunito mobile](../../../ui-lab/services-dashboard/daisyui/evidence/step4/details/font-nunito-390-dark-viewport.png). All six pairs and full pages are in the gallery.

**Recommend Manrope for human approval.** In the inspected captures its more geometric headings and less rounded record/control treatment give the workspace a more precise character while retaining the brand's approachable shape. This is a visual judgment, not a measured reading-speed or user-preference result. Nunito remains a credible continuity option. Both produce the same 109px mobile row; the standard mobile page differs by only 1px.

Added only `@fontsource-variable/manrope` **5.3.0**, pinned in DaisyUI's manifest/lock, installed with scripts disabled. The local Latin variable WOFF2 is **24,836 bytes**, with the OFL notice copied into the build. [Google Fonts metadata](https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/METADATA.pb) confirms the 200–800 variable weight range and OFL licensing; [Fontsource](https://fontsource.org/fonts/manrope/use) documents local package use. No CDN font is requested. Framework/compiler versions remain unchanged. The unchanged Nunito asset is retained for comparison through `?font=nunito`; it is not downloaded in the default Manrope renders.

## Validation results

Evidence: [matrix results](../../../ui-lab/services-dashboard/daisyui/evidence/step4/results.json), [validation log](../../../ui-lab/services-dashboard/daisyui/evidence/step4/validation.log), [font/field/keyboard/contrast details](../../../ui-lab/services-dashboard/daisyui/evidence/step4/details.json), [final contrast and state checks](../../../ui-lab/services-dashboard/daisyui/evidence/step4/contrast-states.json), [full contract comparison](../../../ui-lab/services-dashboard/daisyui/evidence/step4/contracts.json), and [scope/build checks](../../../ui-lab/services-dashboard/daisyui/evidence/step4/scope-check.json).

| Requirement | Actual result |
| --- | --- |
| Rebuild and original lab gates | **132/132 renders pass:** 22 states × three viewports × two themes. The original validator's checks are retained in a DaisyUI-local adaptation, with the font assertion updated for Manrope. Original tools/results remain unchanged. |
| Work priority · V1–V3 | **Pass.** Desktop headings start at y=205, with three rows from both queues visible before y=900. Tablet first appointment y=294.6, follow-up y=811.6, first request y=889.2. Mobile first appointment y=291.6, follow-up y=731.6, first request y=809.2. |
| Responsive/readability · V4–V5 | **Pass in measured cases.** No document/main horizontal overflow, sub-14px working text or sub-44px visible controls in the matrix. Additional 320px target/reflow checks pass in both themes; the brand remains a 44px target when shortened to its mark. Booking URL is 324px wide at 390px. Desktop 200% zoom layout emulation passes. Long-content captures were inspected. |
| Interactions · F4 | **6/6 cases, 92 checks pass.** Navigation previews, menu/drawer, account keyboard control, theme preservation, mobile disclosures, exact clipboard content, denied-copy fallback and setup intent fields. Six added action-name/title checks pass. No unexpected JavaScript errors or failed required assets in the matrix. |
| Focus and motion · A1 | **3/3 normal-motion cases, eight handoff checks pass.** Guide spotlight, welcome→guide and drawer→preview focus survive closure. Six supplemental keyboard traversals cover 168 Tab steps, with visible outlines and no measured sticky-header obstruction. Reduced-motion captures retain the same content. |
| Data/routes · F1–F3 | **264/264 saved-baseline pairs pass** against original DaisyUI and Tabler for complete fixture objects and ordered main route intents. **44 record-field checks pass** across all states at desktop/mobile widths. **22/22 complete contract comparisons pass** for every route (including navigation/account/hidden overlays), public-link attributes, form fields/actions, hooks and overlay settings against frozen original DaisyUI. |
| States and finance | Empty, future/past, independent/all locks, long data, five roles, read-only/grace, share absence, welcome/guide, controlled loading/error, financial-edge and timezone-boundary cases pass. Supplied amounts and lifecycle/payment terminology are unchanged; no client-side financial calculation is introduced. |
| Isolation · I1 | **Pass.** GET-only loopback static harness; no Django import, application database, provider request or production preference key. Protected hashes verify unchanged Tabler/shared/original evidence and existing production files. Rebuild output is deterministic. |

The 283 matrix/interaction PNGs and 166 supplemental font/contrast/focus PNGs are stored separately from the original Step 3 evidence. The screenshot index contains all 264 standard viewport/full-page captures; the gallery makes the comparison pairs accessible without replacing their original files.

### Contrast follow-up

Axe reports **zero WCAG-tag violations** across the refined matrix. It still marks color contrast indeterminate in **10 welcome/guide renders**, with **30 nodes**, reporting partial element overlap/background uncertainty. Original DaisyUI had six such renders; four additional guide renders receive that automated classification with the new typography. This is explicitly recorded, not silently counted as an automated contrast pass.

Supplemental review revisited **all 16 originally incomplete renders**, using the unchanged Tabler and frozen original DaisyUI, and checked every incomplete node in the refined build. Across those three versions there are **82 distinct node cases**: 52 original and 30 refined. For each, evidence records foreground/ancestor colors, opacity, geometry, axe reason and an actual Chromium element screenshot. Its dominant rendered background matches the computed opaque background. The sampled text contrast is at least **15.38:1**; screenshots of representative overlays were also visually inspected. These targeted numerical/background checks resolve the sampled color pairs while preserving axe's raw indeterminate result.

Thirty additional rendered component samples cover brand labels, time/status/source/finance text, primary/secondary/navigation default/hover/focus and held clipboard busy states. Minimum sampled text contrast is **5.30:1 light / 6.76:1 dark**. Sixteen additional primary/secondary default/hover/pressed/keyboard-focus samples confirm text ≥4.5:1, required control boundaries ≥**3.50:1**, and focus rings against adjacent surfaces ≥**6.45:1**. These measurements supplement accessibility checks; they are not a full WCAG conformance certification.

## Assets and integration implications

Actual page-loaded output, **KiB raw / level-9 gzip**, rounded. Gzip is a controlled calculation; the review server serves uncompressed files. Licenses, review tools and the unused alternate font are excluded from page-loaded totals.

| Group | Original DaisyUI | Refined default |
| --- | ---: | ---: |
| CSS including tokens | 56.2 / 10.5 | 63.5 / 11.8 |
| JavaScript | 39.0 / 10.3 | 39.4 / 10.4 |
| Selected font | 30.3 / 30.4 | 24.3 / 24.3 |
| Logo | 1.7 / 0.7 | 1.7 / 0.7 |
| HTML | 0.9 / 0.5 | 1.1 / 0.6 |
| **Total** | **128.2 / 52.3** | **129.9 / 47.7** |

Both font files are shipped for this comparison, but only Manrope was fetched in all 132 default renders. Final byte sizes/hashes are in the matrix results. The modest CSS/JS increase reflects refinement styles and explicit action metadata; the gzip total is lower because Manrope's local file is smaller. No production performance conclusion follows from these totals.

Tailwind **4.3.5**, DaisyUI **5.8.0** and esbuild **0.28.2** remain pinned. Separate-document isolation remains essential: Tailwind Preflight, DaisyUI component names/root rules and Phoenix globals must not be combined casually. Native-dialog behavior and the existing onboarding adapter still need deliberate Django integration; this refinement is not a compatibility shim for production Bootstrap hooks. Future class scanning must cover approved templates explicitly. No production build/configuration or browser policy changed.

## Remaining issues and adoption recommendation

- Human review must approve Manrope, the accent intensity, the mobile Scheduled placement, and whether short Open/View/Setup labels are sufficiently clear in task testing. A task-timing or blinded preference study has not occurred.
- Only Chromium was exercised. Firefox/WebKit, real mobile hardware, browser-native zoom, screen readers and RTL remain unverified. The 200% check emulates reflow with half the CSS viewport and DPR 2; it is not native browser zoom. Latin-only font assets require a language/glyph coverage decision before production adoption.
- Raw axe contrast indeterminates remain as described above. Supplemental evidence covers their color pairs, but does not substitute for assistive-technology testing or full accessibility review.
- Long company/workspace values intentionally increase page height. Tablet follow-up is within the brief's y=820 target with limited margin; later content/type changes must retain that check.
- The original mobile-search defect, application timezone presentation, hidden multi-currency/review context and actual authorization/onboarding behavior remain separate production decisions. Their lab treatments do not fix or verify the running Django application.
- The stylesheet retains the original prototype plus a clearly marked refinement section. Before any production work, consolidate the approved composition into a maintainable Services-only stylesheet/includes rather than copying accumulated overrides into shared Phoenix assets.

**Recommend adopting this visual direction as the candidate Services design system for review**, centered on restrained indigo actions, the existing mark, the compact time anchor, readable type, semantic surfaces and complete responsive states. Keep the selected DaisyUI implementation isolated until a separately authorized Services-dashboard integration plan defines asset/template boundaries, real server contracts and a handoff to unchanged Services pages. That plan must prove Logistics remains untouched. The current Phoenix application is not migrated by this recommendation.

Human review is the next checkpoint. No database changes, migrations, commits, pushes, deployment or production integration occurred. **Step 4 stops here.**
