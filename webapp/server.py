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
import signal
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
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

    def end_headers(self):
        # The app's own code changes constantly during development; without
        # this, browsers apply heuristic caching to it (based on Last-
        # Modified) and can silently keep serving an old index.html or
        # app.js instead of revalidating, producing confusing version
        # mismatches. Data files (PDFs/JSON/images) are left to the browser's
        # normal caching since those are comparatively large and stable.
        path = urlsplit(self.path).path
        if path == "/" or path.startswith("/webapp/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

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
    # Threaded because the frontend fires many concurrent requests for
    # per-page formats (GLM-OCR, PaddleOCR: one file per page) — a plain
    # single-threaded HTTPServer serializes those and makes loading such a
    # model feel like it's hung.
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    httpd.daemon_threads = True

    # Ctrl+C raises KeyboardInterrupt by default too, but a bare SIGINT can
    # land while the interpreter is blocked inside the server's C-level
    # select() call; installing an explicit handler (and polling often)
    # makes sure it's noticed promptly instead of only on the next request.
    def request_shutdown(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_shutdown)
    if hasattr(signal, "SIGBREAK"):  # Windows Ctrl+Break
        signal.signal(signal.SIGBREAK, request_shutdown)

    print(f"Serving {REPO_ROOT} at http://127.0.0.1:{args.port}  (Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("\n[server] stopped.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
