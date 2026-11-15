# Motionmate design system

Approved visual direction as of **15 November 2026**: Tailwind CSS 4, DaisyUI 5,
Manrope and the refined [Step 4 Services dashboard](../../../ui-lab/services-dashboard/daisyui/README.md).
This is a reusable **preview system**. Phoenix 1.23.0 remains the production UI;
neither this document nor visual approval authorizes replacing it. Earlier lab
reports retain their historical pending-review wording; the Step 5 brief supplies
the current visual-direction approval.

Read [components](COMPONENTS.md), [vertical boundaries](VERTICALS.md) and the
[preview workflow](../motionmate-ui-lab/PREVIEW-WORKFLOW.md) with this document.
Executable lab sources live in [ui-lab/design-system](../../../ui-lab/design-system/).

## Principles and identity

- Put operational work first: a clear page title, a useful next action, readable
  records and explicit states. Avoid ornamental statistics or a wall of cards.
- Express Motionmate through its existing mark, Manrope, restrained indigo actions,
  navy dark surfaces and small violet/cyan accents. Keep working surfaces calm.
- Keep information truthful: zero, unknown, unavailable and locked differ. A
  request is not an appointment; an invoice lifecycle label is not a receipt.
- Let content grow. Compact means disciplined spacing and alignment, not tiny
  text, clipped names, hidden errors or fewer required choices.
- Share visual patterns; compose them around each vertical's actual work.

Use **Motionmate** in customer-facing text, with **Services** or **Logistics** as
context. Preserve internal identifiers. Use the existing
[SVG mark](../../../src/static/assets/img/icons/motionmate-logo.svg) unchanged,
including its original gradient. In dark mode use the approved quiet `#EEF1FA`
tile behind the mark; do not recolor, crop or redraw it. Keep a 36px mark within
a link at least 44px tall, with an accessible name such as “Motionmate Services
home”. Hiding the visible wordmark on a narrow screen must retain that name.
No new logo or public-site theme is introduced.

## Semantic colors

The [lab token source](../../../ui-lab/design-system/tokens.css) preserves the
Step 4 colors. Use semantic names rather than repeated literals. `--mm-*` names
are lab-local and are not production Phoenix aliases.

| Token (`--mm-` prefix) | Purpose | Light | Dark |
| --- | --- | --- | --- |
| `canvas` | Page background | `#F6F7FB` | `#0B1020` |
| `surface` | Working panel | `#FFFFFF` | `#121A2B` |
| `raised` | Hover, quiet emphasis | `#EEF1FA` | `#1A2440` |
| `text` | Primary text | `#182235` | `#EDF1FC` |
| `secondary` | Supporting text | `#526079` | `#B0BCD2` |
| `primary` | Action/link/focus | `#3949DB` | `#ABB6FF` |
| `on-primary` | Filled action text | `#FFFFFF` | `#101727` |
| `primary-hover` | Hover/pressed fill | `#2E3CB8` | `#BEC6FF` |
| `divider` | Decorative separation | `#D8DFEA` | `#29354D` |
| `control` | Required field/button boundary | `#71819A` | `#7D8EAE` |
| `accent` | Original supporting accent | `#7460D9` | `#B9A8FF` |
| `frame` | Navigation background | `#F0F2FA` | `#101829` |
| `current` | Current navigation/tab | `#E9EDFF` | `#242F53` |
| `header` | Quiet working header | `#FBFBFE` | `#151F33` |
| `violet` | Brand descriptor/eyebrow | `#6A4FC2` | `#C8B6FF` |
| `cyan` | Decorative time rail | `#087B9F` | `#79D9F6` |
| `success` / `success-bg` | Positive supplied state | `#16624A` / `#E7F5EF` | `#8AE0B9` / `#113C30` |
| `warning` / `warning-bg` | Attention | `#7A4A09` / `#FFF3D6` | `#F5CC80` / `#3C2D16` |
| `error` / `error-bg` | Error/destructive state | `#9C2D3A` / `#FCEAEC` | `#FFACB5` / `#40202B` |

The five refinement names replace Step 4's `--mm-services-frame/current/header/
violet/cyan` aliases in new lab compositions. Their values remain identical.
This naming promotion does not make Services workflow assumptions global.

## Typography and density

Use locally served **Manrope** (Latin variable WOFF2, weights 200–800), retaining
its OFL notice. Working weights: 400 body, 600–650 controls/record labels,
700 sections, 750 page headings. Fallback: `Manrope, system-ui, -apple-system,
'Segoe UI', sans-serif`. Let fallback text wrap; do not hide a page while the
font loads. Step 4's optional Nunito comparison remains frozen. Production
still loads its current font; glyph/language coverage needs review before adoption.

| Role | Desktop/tablet | Mobile |
| --- | --- | --- |
| Page title | 32 / 40px, 750 | 28 / 34px, 750 |
| Section heading | 20 / 28px, 700 | 20 / 28px, 700 |
| Record name | 15 / 22px, 650 | 16 / 24px, 650 |
| Body | 15 / 22–24px, 400 | 16 / 24px, 400 |
| Metadata, labels, badges, controls | 14 / 20px | 14 / 20px |
| Inputs/selects | 16px minimum | 16px minimum |
| Dashboard amount | 22 / 28px, 700 | 22 / 28px, 700 |

Use tabular numerals for times, counts and amounts. Keep currency and timezone
explicit. The Appointments preview supplies workspace-local 24-hour labels;
Step 4's dashboard uses 12-hour labels. This records a screen-specific choice,
not a new time-format preference or production timezone fix.

Use the 4px spacing scale: 4, 8, 12, 16, 20, 24, 32, 40, 48px. Common values have
`--mm-space-*` aliases. Panel padding: 20px desktop, 16px mobile; sections:
24px desktop, 20px tablet, 16–20px mobile. Records grow naturally. Panels have
12px radii; controls 8px; badges 6px. Use 1px dividers and separate stronger
control boundaries. No general panel shadow. Overlays use `--mm-shadow`:
`0 12px 32px #1822351F` light / `#0006` dark.

## Responsive and theme behavior

| Width | Composition |
| --- | --- |
| Below 768px | 16px page gutters, 64px header, navigation drawer, stacked/equal action groups, record cards retaining all fields |
| 768–1199px | 24px gutters, drawer, deliberate tablet grid/list treatment |
| 1200px and above | 224px sidebar, 32px gutters, content maximum 1200px, 64px header |

These are approved **lab** thresholds; do not change Phoenix breakpoints. A
dashboard may use two work columns while Appointments uses a record table and
responsive cards. Maintain semantic order. Test 320px reflow and long content;
never use horizontal document scrolling to fit controls. Wide data tables may
use an explicitly labeled scroll region only when that is the reviewed pattern.

Both themes use the same information, permissions and layout. Initialize from
explicit `?theme=light|dark`, then the existing lab-only `mm-services-lab-theme`
preference, then OS preference. Set theme before CSS. `data-bs-theme` selects
semantic tokens and `data-theme=motionmate-light|motionmate-dark` selects DaisyUI.
Theme changes preserve drafts, filters, dialogs and focus. Never write Phoenix
preference keys. Keep Tailwind Preflight/DaisyUI in separate HTML documents;
a selector prefix alone is insufficient isolation.

## Accessibility and interaction

Target WCAG 2.2 AA: normal text 4.5:1, qualifying large text 3:1, required control
boundaries/focus 3:1 against adjacent colors. Project controls aim for **44 × 44
CSS px**, exceeding the WCAG 2.2 minimum in many cases; do not confuse those
requirements. Measure rendered states, including hover/focus/errors/overlays.

Use a skip link, named landmarks, one `h1`, ordered headings, persistent labels,
associated errors, textual statuses and semantic links/buttons. Preserve table
headers and row identity when presenting cards. Modal dialogs need a name,
keyboard containment, an explicit close action and return focus. Escape closes
ordinary preview dialogs; production onboarding's existing static behavior must
remain separately preserved. Announce results once through a polite live region.

Use Feather SVGs already curated in the lab, 20px and decorative `aria-hidden`.
Use 120–160ms color transitions only where useful; disable motion under
`prefers-reduced-motion`. No shimmer, count-up animation or animated decoration.
Run axe and keyboard/reflow checks and retain raw incomplete findings. Chromium
evidence is not full WCAG conformance or assistive-technology certification.

## Anti-patterns

Avoid new dashboard charts, oversized hero greetings, gradients outside the
logo, nested cards for every datum, uppercase microcopy, sub-14px working text,
color-only status, tooltip-only instructions, clipped errors and guessed
financial states. Do not transplant a scheduling calendar, drag-to-reschedule,
payment action or Logistics staff policy into another screen. Do not load lab
assets into Phoenix, edit collected static output or treat a screenshot as proof
of tenant isolation or provider correctness.
