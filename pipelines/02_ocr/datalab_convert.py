#!/usr/bin/env python3
# AI disclosure: This script was written with AI assistance (Claude Code / Anthropic)
# and reviewed and tested by the author before use.

import argparse
import base64
import binascii
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter


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
    n_pages = len(PdfReader(pdf_path).pages)
    log(f"PDF: {name} ({size}, {n_pages} pages)")
    return n_pages


def parse_page_list(page_range, n_pages):
    if not page_range:
        return list(range(n_pages))
    pages = set()
    for part in page_range.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-")
            pages.update(range(int(start), int(end) + 1))
        else:
            pages.add(int(part))
    return sorted(pages)


def compress_page_list(pages):
    ranges = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = p
    ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ",".join(ranges)


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


def submit_conversion(pdf_path, mode, fmt, page_range, headers, paginate=False,
                       keep_header=False, keep_footer=False):
    log(f"Submitting (mode={mode}, format={fmt}) ...")
    data = {"output_format": fmt, "mode": mode}
    if page_range:
        data["page_range"] = page_range
    if paginate:
        data["paginate"] = "true"
    additional_config = {}
    if keep_header:
        additional_config["keep_pageheader_in_output"] = True
    if keep_footer:
        additional_config["keep_pagefooter_in_output"] = True
    if additional_config:
        data["additional_config"] = json.dumps(additional_config)

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


def extract_batch_pdf(reader, pages, out_path):
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p])
    with open(out_path, "wb") as f:
        writer.write(f)


def merge_results(results, fmt, result_key, paginate=False):
    contents = [r[result_key] for r in results]
    if fmt in ("markdown", "html"):
        # With --paginate, each batch's own content already has a page
        # separator between the pages inside it, from the Datalab API itself
        # - but batches are separate requests, so without this the boundary
        # between one batch's last page and the next batch's first page would
        # have no separator, breaking anything that relies on separator count
        # matching page count (e.g. the ocr_viewer webapp's markdown page
        # split).
        joiner = "\n\n---\n\n" if paginate else "\n\n"
        merged_content = joiner.join(contents)
    else:
        list_key = "children" if fmt == "json" else "blocks"
        merged_content = dict(contents[0]) if isinstance(contents[0], dict) else {}
        merged_content[list_key] = [
            item
            for c in contents if isinstance(c, dict)
            for item in (c.get(list_key) or [])
        ]

    images = {}
    for r in results:
        images.update(r.get("images") or {})

    quality_scores = [r["parse_quality_score"] for r in results
                       if r.get("parse_quality_score") is not None]
    cost_breakdown = {}
    for r in results:
        for item, cents in (r.get("cost_breakdown") or {}).items():
            cost_breakdown[item] = cost_breakdown.get(item, 0) + cents

    return {
        result_key: merged_content,
        "images": images,
        "page_count": sum(r.get("page_count") or 0 for r in results),
        "parse_quality_score": sum(quality_scores) / len(quality_scores) if quality_scores else None,
        "total_cost": sum(r["total_cost"] for r in results if r.get("total_cost") is not None) or None,
        "cost_breakdown": cost_breakdown or None,
        "runtime": sum(r["runtime"] for r in results if r.get("runtime") is not None) or None,
        "checkpoint_id": results[-1].get("checkpoint_id"),
    }


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


def run_batch(pdf_path, mode, fmt, page_range, max_wait_min, poll_seconds, run_start, batch_size,
              paginate=False, keep_header=False, keep_footer=False):
    reader = PdfReader(pdf_path)
    pages = parse_page_list(page_range, len(reader.pages))
    batches = [pages[i:i + batch_size] for i in range(0, len(pages), batch_size)]

    headers = {"X-API-Key": get_api_key()}
    results = []
    tmp_dir = tempfile.mkdtemp(prefix="datalab_batch_")
    try:
        for i, batch_pages in enumerate(batches, 1):
            batch_pdf = os.path.join(tmp_dir, f"batch_{i}.pdf")
            extract_batch_pdf(reader, batch_pages, batch_pdf)
            size_mb = os.path.getsize(batch_pdf) / 1e6
            log(f"Batch {i}/{len(batches)}: pages {compress_page_list(batch_pages)} ({size_mb:.2f} MB)")
            check_url = submit_conversion(batch_pdf, mode, fmt, None, headers,
                                           paginate, keep_header, keep_footer)
            result = poll_conversion(check_url, headers, max_wait_min, poll_seconds, run_start)
            if not result.get("success"):
                sys.exit(f"Batch {i} conversion unsuccessful: {result.get('error')}")
            results.append(result)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return results


# ---------- Convert ----------
def convert(pdf_path, mode, fmt, out_path, page_range, max_wait_min, poll_seconds, batch_size,
            paginate=False, keep_header=False, keep_footer=False):
    if not os.path.isfile(pdf_path):
        sys.exit(f"File not found: {pdf_path}")

    result_key, _ = FORMATS[fmt]
    if not out_path:
        out_path = default_output_path(pdf_path, fmt)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    run_start = time.monotonic()
    describe_pdf(pdf_path)

    if batch_size:
        results = run_batch(pdf_path, mode, fmt, page_range, max_wait_min, poll_seconds, run_start, batch_size,
                             paginate, keep_header, keep_footer)
        result = merge_results(results, fmt, result_key, paginate)
    else:
        headers = {"X-API-Key": get_api_key()}
        check_url = submit_conversion(pdf_path, mode, fmt, page_range, headers,
                                       paginate, keep_header, keep_footer)
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
                   default="accurate", metavar="MODE",
                   help="conversion mode: fast, balanced, accurate (default: accurate)")
    p.add_argument("-f", "--format", choices=list(FORMATS), default="json",
                   metavar="FMT",
                   help="output format: markdown, html, json, chunks (default: json)")
    p.add_argument("-o", "--output", metavar="OUT",
                   help="output path (default: alongside the PDF)")
    p.add_argument("--page-range", metavar="RANGE",
                   help='specific 0-indexed pages to convert, e.g. "0-5,10"')
    p.add_argument("--max-wait", type=int, default=MAX_WAIT_MINUTES, metavar="MIN",
                   help=f"minutes to wait before timing out (default: {MAX_WAIT_MINUTES})")
    p.add_argument("--poll", type=int, default=POLL_SECONDS, metavar="SEC",
                   help=f"seconds between status checks (default: {POLL_SECONDS})")
    p.add_argument("--batch-size", type=int, metavar="N",
                   help="split the PDF into separate uploads of N pages each and merge "
                        "the results (use this to stay under the API's upload size limit)")
    p.add_argument("--paginate", action="store_true",
                   help="separate pages with horizontal rules in the output")
    p.add_argument("--keep-header", action="store_true",
                   help="keep page header text in the output")
    p.add_argument("--keep-footer", action="store_true",
                   help="keep page footer text in the output")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert(args.pdf, args.mode, args.format, args.output,
            args.page_range, args.max_wait, args.poll, args.batch_size,
            args.paginate, args.keep_header, args.keep_footer)
