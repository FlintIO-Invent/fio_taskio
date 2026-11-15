"""Serve only the isolated lab tree; no Django import, database, or writes."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]


class ReadOnlyHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        self.send_error(405, "Read-only lab")

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()


def make_server(port=0, root=LAB_ROOT):
    root = Path(root).resolve()
    if not root.is_relative_to(LAB_ROOT.parent):
        raise ValueError("The preview root must be inside ui-lab")
    return ThreadingHTTPServer(
        ("127.0.0.1", port), partial(ReadOnlyHandler, directory=str(root))
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root", type=Path, default=LAB_ROOT, help="Static root inside ui-lab; default preserves the dashboard launcher")
    args = parser.parse_args()
    server = make_server(args.port, args.root)
    print(f"Local read-only UI Lab: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
