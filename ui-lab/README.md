# Motionmate UI Preview Lab

Optional synthetic design prototypes. These documents do not run Django workflows.
For implementation reviews, use the real BEFORE/AFTER applications in
[the real preview workflow](../docs/design/motionmate-ui-lab/PREVIEW-WORKFLOW.md)
and [Step 8 operations](../docs/design/motionmate-ui-lab/08-real-application-preview.md).
The separately approved Step 7 application dashboard remains preserved.
The approved direction is Tailwind CSS 4 + DaisyUI 5 + Manrope, based on the
unchanged [Step 4 dashboard](services-dashboard/daisyui/README.md).

From the repository root, open the reusable launcher with the **existing** server:

```sh
.venv/bin/python ui-lab/services-dashboard/tools/serve.py --root ui-lab --port 8765
```

- Launcher: <http://127.0.0.1:8765/>
- Appointments: <http://127.0.0.1:8765/services-appointments/dist/?scenario=populated&theme=light>
- New evidence: <http://127.0.0.1:8765/services-appointments/evidence/gallery.html>
- Frozen reference: <http://127.0.0.1:8765/services-dashboard/daisyui/dist/?state=populated&theme=light>
- Preserved Step 4 gallery: <http://127.0.0.1:8765/services-dashboard/daisyui/evidence/step4/gallery.html>

If this port is occupied, choose another with `--port`; there is no Django server
to start. Without `--root`, the old server command retains its dashboard-only
root and old URLs. All serving binds to loopback and rejects write methods.
Use HTTP rather than `file://` for modules and the launcher manifest.

## Build and evidence

See [fresh-checkout setup](../docs/design/motionmate-ui-lab/REPRODUCIBILITY.md)
for authorized Python/Chromium/npm installation. The frozen Step 4 `dist/` can
be reviewed directly. Rebuild Appointments from its source after installing the
pinned Step 4 toolchain. Full historical galleries and optional generated output
are retained in the [separate local archive](../docs/design/motionmate-ui-lab/PRESERVATION.md);
the gallery links above require that archive restored to a separate review tree.

```sh
node ui-lab/tools/build.mjs services-appointments
.venv/bin/python -B ui-lab/tools/capture.py --screen services-appointments
.venv/bin/python -B ui-lab/services-appointments/check.py
```

Set `PWA_CHROMIUM` to an available compatible Chromium executable when overriding
the browser. Without it, Playwright uses its default cache. The capture tool uses
the locked Python UI extra and Pillow package.
No browser/package installation is performed by these scripts.
If dependencies are absent, report that and authorize any needed lab-only setup
separately; do not change root application manifests or silently install updates.
The existing manifests/locks pin Tailwind 4.3.5, DaisyUI 5.8.0, esbuild 0.28.2,
Manrope 5.3.0 and axe-core 4.11.1. No dependency was added for Step 5.

`capture.py` starts an ephemeral instance of the same read-only server, captures
the registered state/viewport/theme matrix and six fresh Step 4 comparisons,
runs axe and writes only the new screen's evidence. `--states populated,long`
supports scoped rechecks and overwrites `results.json` with that **partial** run;
run the full matrix for a complete final report. The launcher opens either screen
independently. The old dashboard's build/validation scripts remain independent.

The [workflow guide](../docs/design/motionmate-ui-lab/PREVIEW-WORKFLOW.md)
explains requests, audits, approvals and adding another screen. The
[Appointments contract](services-appointments/README.md) maps this demonstration
to actual Django behavior. The [Step 5 report](../docs/design/motionmate-ui-lab/05-design-system-and-workflow.md)
records completed checks and limitations.
