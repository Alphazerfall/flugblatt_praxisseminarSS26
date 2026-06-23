#!/usr/bin/env python3

import argparse
import base64
import binascii
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from pypdf import PdfReader


# ---------- Constants ----------
API_URL = "https://www.datalab.to/api/v1/convert"
POLL_SECONDS = 3
MAX_WAIT_MINUTES = 30

FORMATS = {
    "markdown": ("markdown", ".md"),
    "html": ("html", ".html"),
    "json": ("json", ".json"),
    "chunks": ("chunks", ".json"),
}


# ---------- Helpers ----------
def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def fmt_elapsed(seconds):
    return str(timedelta(seconds=round(seconds)))


def describe_pdf(pdf_path):
    name = os.path.basename(pdf_path)
    size = f"{os.path.getsize(pdf_path) / 1e6:.2f} MB"
    reader = PdfReader(pdf_path)
    log(f"PDF: {name} ({size}, {len(reader.pages)} pages)")


def save_images(result, out_dir):
    n = 0
    for name, b64 in (result.get("images") or {}).items():
        try:
            data = base64.b64decode(b64)
        except (binascii.Error, ValueError) as exc:
            log(f"  skipped image {name}: {exc}")
            continue
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
        n += 1
    return n


def get_api_key():
    load_dotenv()
    api_key = os.getenv("DATALAB_API_KEY")
    if not api_key:
        sys.exit("Set DATALAB_API_KEY in your environment or in a local .env file.")
    return api_key


def default_output_path(pdf_path, fmt):
    _, ext = FORMATS[fmt]
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    return os.path.join(os.path.dirname(pdf_path), stem, stem + ext)


def submit_conversion(pdf_path, mode, fmt, page_range, headers):
    log(f"Submitting (mode={mode}, format={fmt}) ...")
    data = {"output_format": fmt, "mode": mode}
    if page_range:
        data["page_range"] = page_range

    with open(pdf_path, "rb") as f:
        resp = requests.post(
            API_URL,
            headers=headers,
            files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
            data=data,
        )
    resp.raise_for_status()
    log("Submitted. Polling for completion ...")
    return resp.json()["request_check_url"]


def poll_conversion(check_url, headers, max_wait_min, poll_seconds, run_start):
    deadline = time.time() + max_wait_min * 60
    while time.time() < deadline:
        result = requests.get(check_url, headers=headers).json()
        status = result.get("status")
        if status == "complete":
            return result
        if status == "failed":
            sys.exit(f"Conversion failed: {result.get('error')}")
        log(f"  status={status} (elapsed {fmt_elapsed(time.monotonic() - run_start)}) ...")
        time.sleep(poll_seconds)

    sys.exit(f"Timed out after {max_wait_min} min.")


def save_output(result, result_key, out_path):
    content = result[result_key]
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, indent=2)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return save_images(result, os.path.dirname(out_path))


def log_summary(result, run_start, n_images, out_path):
    log(f"Done in {fmt_elapsed(time.monotonic() - run_start)}."
        f"{result.get('page_count')} pages, {n_images} images, "
        f"quality score {result.get('parse_quality_score')}.")
    if result.get("total_cost") is not None:
        log(f"  cost: {result['total_cost']:.2f} cents (${result['total_cost'] / 100:.4f})")
    if isinstance(result.get("cost_breakdown"), dict):
        for item, cents in result["cost_breakdown"].items():
            log(f"    - {item}: {cents:.2f} cents")
    if result.get("runtime") is not None:
        log(f"  server runtime: {result['runtime']:.1f} s")
    if result.get("checkpoint_id"):
        log(f"  checkpoint id: {result['checkpoint_id']}")
    log(f"Saved: {out_path}")


# ---------- Convert ----------
def convert(pdf_path, mode, fmt, out_path, page_range, max_wait_min, poll_seconds):
    api_key = get_api_key()
    if not os.path.isfile(pdf_path):
        sys.exit(f"File not found: {pdf_path}")

    result_key, _ = FORMATS[fmt]
    if not out_path:
        out_path = default_output_path(pdf_path, fmt)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    run_start = time.monotonic()
    describe_pdf(pdf_path)

    headers = {"X-API-Key": api_key}
    check_url = submit_conversion(pdf_path, mode, fmt, page_range, headers)
    result = poll_conversion(check_url, headers, max_wait_min, poll_seconds, run_start)

    if not result.get("success"):
        sys.exit(f"Conversion unsuccessful: {result.get('error')}")

    n_images = save_output(result, result_key, out_path)
    log_summary(result, run_start, n_images, out_path)


# ---------- CLI ----------
def parse_args():
    p = argparse.ArgumentParser(description="Convert a PDF with the Datalab Convert API.")
    p.add_argument("pdf", help="path to the input PDF")
    p.add_argument("-m", "--mode", choices=["fast", "balanced", "accurate"],
                   default="accurate", help="conversion mode (default: accurate)")
    p.add_argument("-f", "--format", choices=list(FORMATS), default="json",
                   help="output format (default: json)")
    p.add_argument("-o", "--output", help="output path (default: alongside the PDF)")
    p.add_argument("--page-range",
                   help='specific 0-indexed pages to convert, e.g. "0-5,10"')
    p.add_argument("--max-wait", type=int, default=MAX_WAIT_MINUTES,
                   help=f"minutes to wait before timing out (default: {MAX_WAIT_MINUTES})")
    p.add_argument("--poll", type=int, default=POLL_SECONDS,
                   help=f"seconds between status checks (default: {POLL_SECONDS})")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert(args.pdf, args.mode, args.format, args.output,
            args.page_range, args.max_wait, args.poll)
