#!/usr/bin/env python3
"""Local dev server for the OCR comparison webapp.

Serves the repo root as static files (so /data/... and /webapp/... both
resolve) and exposes /api/manifest, which scans data/ on every request for
available documents and their per-model JSON outputs (see manifest.py).

Usage:
    python webapp/server.py [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from manifest import to_manifest_json

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"

mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/javascript", ".js")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/manifest":
            self._send_manifest()
            return
        if path == "/":
            query = urlsplit(self.path).query
            self.path = "/webapp/index.html" + (f"?{query}" if query else "")
        super().do_GET()

    def _send_manifest(self):
        try:
            body = json.dumps(to_manifest_json(DATA_ROOT)).encode("utf-8")
        except Exception as exc:  # noqa: BLE001 - surface scan errors to the client
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[server] {self.address_string()} {fmt % args}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    handler = partial(Handler, directory=str(REPO_ROOT))
    httpd = HTTPServer(("127.0.0.1", args.port), handler)
    print(f"Serving {REPO_ROOT} at http://127.0.0.1:{args.port}  (open in browser)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
