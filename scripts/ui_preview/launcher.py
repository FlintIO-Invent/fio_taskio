"""Loopback landing page only; all app interactions go to the two Django servers."""

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ui_preview.core import load_session


def render(root, state):
    links = []
    approved = state.get("comparison", "step7") == "step7"
    for side, title in [
        (
            "before",
            "BEFORE — Original Services dashboard" if approved else "BEFORE — Captured application",
        ),
        (
            "after",
            "AFTER — Approved Services dashboard"
            if approved
            else "AFTER — Current application for review",
        ),
    ]:
        url = f"http://127.0.0.1:{state[side]['http_port']}"
        links.append(
            f'<section><h2>{title}</h2><p><a class="open" href="{url}{html.escape(state["route"], quote=True)}" target="_{side}" rel="noopener">Open {side.upper()} Django application</a></p><p><a href="{url}/accounts/login/" target="_{side}">Sign in</a> · <a href="{url}/accounts/logout/" target="_{side}">Sign out / change account</a></p><small>Independent source, PostgreSQL cluster, sessions and theme storage.<br>{url}</small></section>'
        )
    fixtures = json.loads((root / "after/fixtures.json").read_text())
    rows = "".join(
        f"<tr><td><code>{html.escape(a['email'])}</code></td><td>{html.escape(a['role'])}</td><td>{html.escape(a['scenario'])}</td><td>{a['vertical']}</td></tr>"
        for a in fixtures["accounts"]
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Motionmate · Real application previews</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;color:#182235;background:#f6f7fb;max-width:1100px;margin:32px auto;padding:0 20px}}h1{{font-size:30px}}h2{{font-size:21px}}a{{color:#3949db}}.versions{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}section{{background:white;border:1px solid #d8dfea;border-radius:12px;padding:20px}}.open{{display:inline-flex;min-height:44px;align-items:center;font-weight:700}}.notice{{padding:16px;background:#fff3d6;border-radius:8px}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #d8dfea}}.table{{overflow:auto}}code{{overflow-wrap:anywhere}}a:focus-visible{{outline:2px solid #3949db;outline-offset:4px}}@media(max-width:767px){{.versions{{grid-template-columns:1fr}}}}</style>
<h1>Motionmate real application review</h1><p>Two actual Django applications with equivalent synthetic fixtures. No ordinary application database or customer data is used.</p><div class="versions">{"".join(links)}</div>
<p class="notice">Local disposable review only. External providers, real email, financial writes and service workers are disabled. Existing menus, authentication, booking and setup forms use real Django behavior. Changes you make stay on that side; data is not silently resynchronized.</p>
<h2>Local test accounts</h2><p>Shared preview-only password: <code>{html.escape(state["password"])}</code>. Start with <code>owner@preview.test</code>. Use Sign out to change roles. You can stay signed in to both versions simultaneously.</p><div class="table"><table><thead><tr><th>Email</th><th>Role</th><th>Scenario</th><th>Vertical</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Review and lifecycle</h2><p>Resize either real app and use its existing theme switch. Each side retains the behavior in its frozen source, including existing defects. Approval is a human decision. Billing/provider controls return an explicit unavailable response. External links, optional external maps/icons and PWA behavior are unavailable under the local network policy.</p>
<p>These local preview processes use the Python debug allocator to avoid an observed runtime crash. This is not production-runtime verification. The validation account is reserved for automated form checks; use the other accounts for review.</p>
<p>Fixture epoch: <code>{state["clock"]}</code>. Both apps use the real current clock after seeding, so appointments and grace states age normally. Recreate the pair for a fresh comparison.</p>
<p>Session: <code>{root}</code></p><p><code>.venv/bin/python scripts/motionmate_preview.py status --session {root}</code></p><p><code>.venv/bin/python scripts/motionmate_preview.py stop --session {root}</code></p>
<p>The separate synthetic UI Lab remains an optional <strong>prototype</strong>, not application behavior or implementation-review evidence.</p></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    root, state = load_session(args.session)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Host") not in {
                f"127.0.0.1:{state['launcher_port']}",
                f"localhost:{state['launcher_port']}",
            }:
                self.send_error(400)
                return
            if self.path != "/":
                self.send_error(404)
                return
            _, current = load_session(root)
            data = render(root, current).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Motionmate-Preview", "launcher")
            self.send_header("X-Motionmate-Preview-Session", current["id"])
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self.send_error(405)

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("127.0.0.1", state["launcher_port"]), Handler).serve_forever()


if __name__ == "__main__":
    main()
