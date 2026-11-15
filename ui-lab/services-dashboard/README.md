# Motionmate Services dashboard lab

Two independent, standalone design prototypes. Nothing here is imported by Django or production assets. All data is synthetic. Navigation opens a local route-intent preview; setup forms record their field payload in memory; no application request or record write is performed.

- **A:** `tabler/dist/index.html` — Tabler + its bundled Bootstrap interaction runtime.
- **B:** `daisyui/dist/index.html` — Tailwind CSS + DaisyUI; native dialogs and a small interaction adapter.
- Shared inputs: `shared/fixtures.js`, `shared/tokens.css`, curated existing Feather icons, unchanged Motionmate SVG, and one local Nunito Sans variable font file. Shared controller handles only read-only lab behavior, not framework components or layout. Each renderer, stylesheet, adapter and output bundle is separate.

Serve from the repository root with the existing Python environment:

```sh
.venv/bin/python ui-lab/services-dashboard/tools/serve.py --port 8765
```

Open `http://127.0.0.1:8765/` for the state selector. Direct examples:

- `http://127.0.0.1:8765/tabler/dist/?state=populated&theme=light`
- `http://127.0.0.1:8765/daisyui/dist/?state=populated&theme=dark`

The server binds only to loopback, serves this tree, and rejects writes. It does not import Django, read application settings, connect to a database, install a service worker or proxy application destinations. All fonts and assets are local; browser tests reject non-local requests. File URLs are unsuitable for the ES modules/clipboard API; use the local server.

## Rebuild independently

Node 24.2.0 / npm 11.4.2 were available. Exact direct versions are pinned and complete transitive resolutions/integrity hashes are in separate lockfiles. From this directory:

```sh
npm ci --prefix tabler --ignore-scripts --no-audit --no-fund
npm run build --prefix tabler
```

Or, independently:

```sh
npm ci --prefix daisyui --ignore-scripts --no-audit --no-fund
npm run build --prefix daisyui
```

Neither build needs the other framework installed. The local shared font/mark/icons are already supplied; no font acquisition or CDN is needed for rebuilding. Build outputs are kept for direct review; `node_modules` is ignored locally. Do not copy these files into production or run collectstatic as part of this experiment.

## Preflight decisions, 15 November 2026

| Item | Decision / evidence |
| --- | --- |
| User authorization | Step 3 explicitly authorizes both isolated builds, selecting pinned dependencies and browser evidence. Step 2's future approval checkpoints do not require asking again for that authorized work. Production integration remains excluded. |
| Prototype A | `@tabler/core` **1.7.5**, `esbuild` **0.28.2**. Tabler is Bootstrap-based and includes the Bootstrap JS component runtime. Load one copy. No production Bootstrap/Phoenix scripts are included. |
| Prototype B | `tailwindcss` **4.3.5**, `@tailwindcss/cli` **4.3.5**, `daisyui` **5.8.0**, `esbuild` **0.28.2**. CLI versions match; DaisyUI is configured as a Tailwind plugin. No React/Vue or Django plugin. |
| Shared font | Manrope was not available locally. Use the brief's permitted existing-family fallback, **Nunito Sans**, in both. `@fontsource-variable/nunito-sans` **5.3.0** supplies the exact same locally served Latin variable WOFF2 (200–1000), with OFL license. No new typeface direction is asserted. |
| Validation | Existing Python Playwright and cached Chromium; `axe-core` **4.11.1** in the lab-only tools manifest. No browser install. No Django setup/test runner. |
| Supported browser review | Current Tabler docs require Chrome/Edge 123+, Firefox 128+, Safari/iOS 17.5+; Tailwind 4 docs list Chrome 111+, Firefox 128+, Safari 16.4+. The lab uses the common modern target for both; Chromium only is actually verified. This does not change Motionmate's production browser policy. |
| Design defaults | Shared indigo/navy tokens, unchanged mark with protective light tile, three-row mobile previews, 1200px two-column / 768px tablet breakpoints, explicit workspace timezone and honest next-scheduled preview. Neither prototype exposes the hidden currency/review table. |
| Correctness corrections | Both omit broken global mobile search, supply names/focus, show workspace-local times, distinguish unavailable from zero and provide copy feedback. These changes exist only in the prototypes. |
| Role contract | Owner/admin setup and workspace management; owner subscription navigation; staff/viewer/accountant/admin retain the current Services appointment/invoice reads. Empty-state route links preserve their existing role predicates. Lab visibility is not server authorization verification. |
| Setup forms | Actual existing intent field names and identifiers; explicit `lab-preview-not-a-token` placeholder, never a usable CSRF token. No form is submitted; inspect `window.labEvents` to review recorded intents. Static guide Escape behavior is retained. |
| Finance | Amounts, currencies, counts, lifecycle/payment/refund strings are supplied as presentation fixtures. No settlement math or Stripe/customer payment handling. A review-case row is intentionally absent from collectible follow-up. |
| Persistence | Only `mm-services-lab-theme` in localStorage; no production key or application cookie. Read-only simulations and fixture states reset on navigation. |
| Source protection | `evidence/preflight.json` fingerprints existing production sources and earlier design evidence. Verification checks these after all lab work. |

Official primary references: [Tabler installation](https://docs.tabler.io/ui/getting-started/installation), [Tabler browser support](https://docs.tabler.io/ui/getting-started/browser-support), [Tailwind CLI](https://tailwindcss.com/docs/installation/tailwind-cli), [Tailwind compatibility](https://tailwindcss.com/docs/compatibility), [DaisyUI install](https://daisyui.com/docs/install/), [DaisyUI configuration](https://daisyui.com/docs/config/). Package versions were verified through the npm registry at preflight.

## States and interactions

`?state=` accepts: `populated`, `empty`, `future`, `past`, `appointments-locked`, `invoices-locked`, `booking-locked`, `locked`, `long`, `staff`, `viewer`, `accountant`, `admin`, `read-only`, `grace`, `sharing-absent`, `welcome`, `guide`, `loading`, `error`, `financial-edge`, `timezone-boundary`.

`?theme=light|dark` selects the capture theme. `?copy=denied` exercises the copy failure fallback. Pending/error states are controlled visual simulations; they do not add asynchronous endpoints to the server-rendered application. The DST boundary fixture deliberately shows the two distinct 02:30 instants on Europe's autumn changeover date with their different offsets.

Use mobile Show more, menu/Escape, account/arrow keys/Escape, theme toggle, record and section links, Copy, Setup Guide/Choose journey/Continue later and Show workspace details. Detail links never navigate to production. The route preview names the original route and parameters and explains the read-only handoff; it is not a redesign of the destination page. There is no operational approve/schedule/pay/cancel action or real onboarding persistence.

## Reproduce validation

From the repository root:

```sh
npm ci --prefix ui-lab/services-dashboard/tools --ignore-scripts --no-audit --no-fund
.venv/bin/python ui-lab/services-dashboard/tools/validate.py
```

The harness also checks normal-motion focus handoffs separately from the reduced-motion capture matrix. It starts/stops its own loopback server and writes screenshots plus raw metrics, WCAG-tag axe findings, interaction checks, content/route parity and gzip/raw asset sizes into `evidence/`. Tests use synthetic inputs and local GETs only. They do not validate Django authorization, booking transactions, financial calculations or provider behavior. See the comparison report for actual results and limits; a framework is not automatically selected.
