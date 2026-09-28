#!/usr/bin/env python3
"""Run Datalab's auto-segmentation API on a yearly PDF and save the result as
a flugblatt_splitter segments.json, so the suggested cuts can be reviewed
visually in that tool instead of squinting at raw API JSON.

By default this writes to `<pdf-stem>.segments.auto.json` next to the PDF -
it never touches `<pdf-stem>.segments.json`, since that's the file
flugblatt_splitter auto-loads for a PDF and may already hold real manual
work. Pass --install to promote the result to that canonical path (any
existing file there is backed up first, never deleted).

Usage:
    python pipelines/01_pdf/datalab_auto_segment.py "data/raw/Nr. 002 (1968)/0118_0002.pdf"
    python pipelines/01_pdf/datalab_auto_segment.py "data/raw/Nr. 002 (1968)/0118_0002.pdf" --install
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from flugblatt_splitter.backend import segmentation as splitter_seg  # noqa: E402

API_URL = "https://www.datalab.to/api/v1/segment"
POLL_SECONDS = 3
MAX_WAIT_MINUTES = 30


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def fmt_elapsed(seconds):
    return str(timedelta(seconds=round(seconds)))


def get_api_key():
    load_dotenv()
    api_key = os.getenv("DATALAB_API_KEY")
    if not api_key:
        sys.exit("Set DATALAB_API_KEY in your environment or in a local .env file.")
    return api_key


def submit_segmentation(pdf_path, mode, output_format, headers):
    log(f"Submitting {pdf_path.name} for auto-segmentation (mode={mode}) ...")
    data = {
        "mode": mode,
        "segmentation_schema": json.dumps({"segments": []}),  # empty -> auto-detect
    }
    if output_format:
        data["output_format"] = output_format
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            API_URL,
            headers=headers,
            files={"file": (pdf_path.name, f, "application/pdf")},
            data=data,
        )
    resp.raise_for_status()
    log("Submitted. Polling for completion ...")
    return resp.json()["request_check_url"]


def poll_segmentation(check_url, headers, max_wait_min, poll_seconds):
    start = time.monotonic()
    deadline = time.time() + max_wait_min * 60
    while time.time() < deadline:
        result = requests.get(check_url, headers=headers).json()
        status = result.get("status")
        if status == "complete":
            return result
        if status == "failed":
            sys.exit(f"Segmentation failed: {result.get('error')}")
        log(f"  status={status} (elapsed {fmt_elapsed(time.monotonic() - start)}) ...")
        time.sleep(poll_seconds)
    sys.exit(f"Timed out after {max_wait_min} min.")


def to_splitter_segments(datalab_segments):
    """Datalab gives 0-indexed inclusive page lists per named segment;
    flugblatt_splitter wants 1-indexed start_page/end_page."""
    ordered = sorted(datalab_segments, key=lambda s: min(s["pages"]))
    segments = []
    for i, seg in enumerate(ordered, 1):
        pages = sorted(seg["pages"])
        segments.append({
            "id": i,
            "title": seg.get("name", ""),
            "date": "",
            "start_page": pages[0] + 1,
            "end_page": pages[-1] + 1,
            "confirmed": False,
        })
    return segments


def backup_existing(path):
    if not path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.stem}.bak-{stamp}{path.suffix}")
    path.rename(backup_path)
    return backup_path


def parse_args():
    p = argparse.ArgumentParser(description="Run Datalab auto-segmentation on a yearly PDF.")
    p.add_argument("pdf", help="path to the yearly PDF")
    p.add_argument("-m", "--mode", choices=["fast", "balanced", "accurate"], default="balanced",
                   help="segmentation mode (default: balanced)")
    p.add_argument("--output-format", default=None, metavar="FMT",
                   help="also have Datalab return per-segment content in this format "
                        "(e.g. markdown) - unused by flugblatt_splitter, ignored if omitted")
    p.add_argument("--max-wait", type=int, default=MAX_WAIT_MINUTES, metavar="MIN",
                   help=f"minutes to wait before timing out (default: {MAX_WAIT_MINUTES})")
    p.add_argument("--poll", type=int, default=POLL_SECONDS, metavar="SEC",
                   help=f"seconds between status checks (default: {POLL_SECONDS})")
    p.add_argument("--install", action="store_true",
                   help="write to <pdf-stem>.segments.json (the file flugblatt_splitter "
                        "auto-loads) instead of the default .segments.auto.json sidecar. "
                        "Any existing file at that path is renamed to a timestamped "
                        ".bak file first, never overwritten in place.")
    p.add_argument("-o", "--output", type=Path, metavar="PATH",
                   help="explicit output path (overrides --install's default target)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.is_file():
        sys.exit(f"File not found: {pdf_path}")

    headers = {"X-API-Key": get_api_key()}
    run_start = time.monotonic()

    check_url = submit_segmentation(pdf_path, args.mode, args.output_format, headers)
    result = poll_segmentation(check_url, headers, args.max_wait, args.poll)
    if not result.get("success", True):
        sys.exit(f"Segmentation unsuccessful: {result.get('error')}")

    seg_results = result["segmentation_results"]
    datalab_segments = seg_results["segments"]
    total_pages = seg_results.get("metadata", {}).get("total_pages")
    log(f"Done in {fmt_elapsed(time.monotonic() - run_start)}. "
        f"{len(datalab_segments)} segment(s) found over {total_pages} pages.")
    for seg in datalab_segments:
        pages = sorted(seg["pages"])
        log(f"  - \"{seg.get('name', '')}\" pages {pages[0] + 1}-{pages[-1] + 1} "
            f"(confidence: {seg.get('confidence', '?')})")

    segments = to_splitter_segments(datalab_segments)
    page_count = total_pages if total_pages is not None else segments[-1]["end_page"]
    try:
        splitter_seg.validate_segments(segments, page_count)
    except ValueError as e:
        log(f"  ! WARNING: result doesn't cleanly cover all pages ({e}) - "
            f"writing it anyway for inspection, but flugblatt_splitter's own "
            f"Save may reject it until you fix the gaps by hand.")

    doc = splitter_seg.build_segmentation_json(pdf_path.name, segments)

    if args.output:
        out_path = args.output
    elif args.install:
        out_path = splitter_seg.segmentation_path_for(pdf_path)
        backup_path = backup_existing(out_path)
        if backup_path:
            log(f"  backed up existing {out_path.name} -> {backup_path.name}")
    else:
        out_path = pdf_path.with_name(pdf_path.stem + ".segments.auto.json")

    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Saved: {out_path}")
    if not args.install and not args.output:
        log(f"  To view in flugblatt_splitter, copy/rename this to "
            f"{pdf_path.stem}.segments.json (or re-run with --install to do that "
            f"safely, backing up any existing one first).")
