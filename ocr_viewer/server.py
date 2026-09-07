#!/usr/bin/env python3
"""Local dev server for the OCR comparison webapp.

Serves the repo root as static files (so /data/... and /ocr_viewer/... both
resolve) and exposes /api/manifest, which scans data/ on every request for
available documents and their per-model JSON outputs (see manifest.py).

Usage:
    python ocr_viewer/server.py [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import signal
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from manifest import to_manifest_json

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"
NER_TERMS_DIR = REPO_ROOT / "pipelines" / "03_ner" / "terms"
NER_TERM_FILES = {
    "ACTOR": "actors.txt",
    "LOC": "places.txt",
    "TIME": "times.txt",
    "PERSON": "persons.txt",
}

mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/javascript", ".js")

# Correction/gold-standard annotations are written under
# data/<dataset>/gold/annotations/<annotator>/page_<NNN>.json. The annotator
# goes into a folder + file name, so keep it to a filename-safe charset; the
# dataset comes straight from the manifest (can contain "/", spaces, parens)
# and is validated by containment below rather than by charset.
ANNOTATOR_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_ANNOTATION_BYTES = 10 * 1024 * 1024  # a page's JSON is a few KB; this is just a sanity cap


def annotator_dir(dataset: str, annotator: str) -> Path:
    """Resolve (and validate) an annotator's annotation directory for a dataset.

    Raises ValueError on anything that would escape data/ or isn't a
    well-formed annotator — the value is attacker-controllable in principle
    (any process can hit this dev server), so don't trust it into a path.
    """
    if not ANNOTATOR_RE.match(annotator or ""):
        raise ValueError("annotator must match [A-Za-z0-9_-]{1,64}")
    parts = [p for p in str(dataset or "").replace("\\", "/").split("/") if p]
    if not parts or any(p in ("..", ".") for p in parts):
        raise ValueError("invalid dataset")
    data_root = DATA_ROOT.resolve()
    dest = (data_root.joinpath(*parts) / "gold" / "annotations" / annotator).resolve()
    dest.relative_to(data_root)  # raises ValueError if the path escaped data/
    return dest


def annotation_path(dataset: str, annotator: str, page: int) -> Path:
    """Resolve (and validate) the on-disk path for one page's annotation."""
    if not isinstance(page, int) or isinstance(page, bool) or not (1 <= page <= 100_000):
        raise ValueError("page must be an integer in [1, 100000]")
    return annotator_dir(dataset, annotator) / f"page_{page:03d}.json"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/manifest":
            self._send_manifest()
            return
        if path == "/api/annotator-progress":
            self._send_annotator_progress(urlsplit(self.path).query)
            return
        if path == "/":
            query = urlsplit(self.path).query
            self.path = "/ocr_viewer/index.html" + (f"?{query}" if query else "")
        super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/save-annotation":
            self._save_annotation()
            return
        if path == "/api/ner-blacklist":
            self._add_ner_blacklist()
            return
        self.send_error(404, "Not found")

    def end_headers(self):
        # The app's own code changes constantly during development; without
        # this, browsers apply heuristic caching to it (based on Last-
        # Modified) and can silently keep serving an old index.html or
        # app.js instead of revalidating, producing confusing version
        # mismatches. Data files (PDFs/JSON/images) are left to the browser's
        # normal caching since those are comparatively large and stable.
        path = urlsplit(self.path).path
        if path == "/" or path.startswith("/ocr_viewer/"):
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

    def _send_annotator_progress(self, query):
        # Powers the small "N/M pages complete" counter next to the
        # Annotator field — counts this annotator's saved pages for the
        # dataset and how many are marked complete.
        params = parse_qs(query)
        dataset = params.get("dataset", [""])[0]
        annotator = params.get("annotator", [""])[0]
        try:
            ann_dir = annotator_dir(dataset, annotator)
            completed = 0
            annotated = 0
            if ann_dir.is_dir():
                for page_path in ann_dir.glob("page_*.json"):
                    annotated += 1
                    try:
                        data = json.loads(page_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    if data.get("complete"):
                        completed += 1
            body = json.dumps({"completed": completed, "annotated": annotated}).encode("utf-8")
        except Exception as exc:  # noqa: BLE001 - surface the reason to the client
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _save_annotation(self):
        # Autosave target for the viewer's Correct mode: one JSON per
        # (annotator, page). Written atomically (temp + os.replace) so a
        # concurrent GET of the same file — the frontend re-reads it to resume
        # — never sees a half-written file.
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_ANNOTATION_BYTES:
                raise ValueError("empty or oversized request body")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            dest = annotation_path(payload.get("dataset"), payload.get("annotator"), payload.get("page"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, dest)
        except Exception as exc:  # noqa: BLE001 - surface the reason to the client
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))
            return
        body = json.dumps({"ok": True, "path": f"/{dest.relative_to(REPO_ROOT).as_posix()}"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _add_ner_blacklist(self):
        """Speichert einen Entity-Text als labelbezogenen Blacklist-Eintrag."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 16 * 1024:
                raise ValueError("empty or oversized request body")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            label = str(payload.get("label") or "").upper()
            term = str(payload.get("text") or "").strip()
            if label not in NER_TERM_FILES:
                raise ValueError("invalid NER label")
            if not term or "\n" in term or "\r" in term:
                raise ValueError("invalid NER term")

            path = (NER_TERMS_DIR / NER_TERM_FILES[label]).resolve()
            path.relative_to(NER_TERMS_DIR.resolve())
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            normalized = term.casefold()
            filtered = [
                line for line in lines
                if line.strip().lstrip("!").casefold() != normalized
            ]
            filtered.append(f"!{term}")
            path.write_text("\n".join(filtered) + "\n", encoding="utf-8")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))
            return
        body = json.dumps({"ok": True, "label": label, "text": term}).encode("utf-8")
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
