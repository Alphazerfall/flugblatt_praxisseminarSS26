#!/usr/bin/env python3
# AI disclosure: This script was written with AI assistance (Claude Code / Anthropic)
# and reviewed and tested by the author before use.

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter

from datalab_sdk import DatalabClient, PipelineProcessor

from fix_image_collisions import unique_batch_images

MAX_WAIT_MINUTES = 30
POLL_SECONDS = 10
DEFAULT_CONCURRENCY = 15

FORMATS = {"markdown": ".md", "html": ".html", "json": ".json", "chunks": ".json"}

PIPELINE_NAME = "Flugblatt_Pipeline"
PIPELINE_STEP_SETTINGS = {
    "output_mode": "accurate",
    "paginate": True,
    "merge_cross_page": True,
    "disable_image_captions": False,
    "keep_pageheader_in_output": True,
    "keep_pagefooter_in_output": True,
    "word_bboxes": False,
    "add_block_ids": False,
    "disable_image_extraction": False,
    "extras": ["new_block_types"],
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


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


def default_output_path(pdf_path, fmt):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    return os.path.normpath(os.path.join(os.path.dirname(pdf_path), stem, stem + FORMATS[fmt]))


def checkpoint_dir_for(out_path, fmt):
    fingerprint = hashlib.sha1(json.dumps(dict(PIPELINE_STEP_SETTINGS, output_format=fmt),
                                           sort_keys=True).encode()).hexdigest()[:8]
    return os.path.join(os.path.dirname(out_path) or ".", f".checkpoints_{fingerprint}")


def load_api_key(cli_value):
    load_dotenv()
    key = cli_value or os.getenv("DATALAB_API_KEY")
    if not key:
        sys.exit("Pass --api-key or set DATALAB_API_KEY in .env.")
    return key.strip()


def find_or_create_pipeline(client):
    for p in client.list_pipelines(saved_only=True, include_archived=False).get("pipelines", []):
        if p.name == PIPELINE_NAME:
            return p.pipeline_id
    draft = client.create_pipeline(steps=[PipelineProcessor(type="convert", settings=PIPELINE_STEP_SETTINGS)])
    return client.save_pipeline(draft.pipeline_id, name=PIPELINE_NAME).pipeline_id


def elapsed_seconds(start, end):
    if not start or not end:
        return None
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (parse(end) - parse(start)).total_seconds()


def nominal_cost_cents(rate_breakdown, page_count):
    if not rate_breakdown or page_count is None:
        return None
    rate = rate_breakdown.get("total_rate_per_1000_cents")
    return None if rate is None else rate * page_count / 1000


def finish_batch(client, execution, ckpt_path, i, n, page_label):
    step = execution.steps[-1]
    if step.status == "failed":
        sys.exit(f"Batch {i + 1}/{n} (pages {page_label}) failed: {step.error_message}")
    result = client.get_step_result(execution.execution_id, step.step_index)
    if not result.get("success", True):
        sys.exit(f"Batch {i + 1}/{n} (pages {page_label}) unsuccessful: {result.get('error')}")

    result["_elapsed_s"] = elapsed_seconds(step.started_at, step.finished_at)
    result["_nominal_cost_cents"] = nominal_cost_cents(execution.rate_breakdown, result.get("page_count"))
    with open(ckpt_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    bits = [f"{result['page_count']} pages"]
    if result["_elapsed_s"] is not None:
        bits.append(f"{result['_elapsed_s']:.0f}s")
    if result.get("total_tokens") is not None:
        bits.append(f"{result['total_tokens']} tokens")
    log(f"Batch {i + 1}/{n}: pages {page_label} - done ({', '.join(bits)})")
    return result


def run_batches(client, pipeline_id, pdf_path, fmt, batch_size, checkpoint_dir, concurrency):
    reader = PdfReader(pdf_path)
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    batches = [list(range(i, min(i + batch_size, len(reader.pages))))
               for i in range(0, len(reader.pages), batch_size)]
    n = len(batches)
    os.makedirs(checkpoint_dir, exist_ok=True)

    results = [None] * n
    pending = []
    tmp_dir = tempfile.mkdtemp(prefix="flugblatt_")
    for i, pages in enumerate(batches):
        page_label = compress_page_list(pages)
        ckpt_path = os.path.join(checkpoint_dir, f"batch_{page_label}.json")
        if os.path.isfile(ckpt_path):
            log(f"Batch {i + 1}/{n}: pages {page_label} - cached")
            with open(ckpt_path, encoding="utf-8") as f:
                results[i] = json.load(f)
            continue
        batch_pdf = os.path.join(tmp_dir, f"{stem}_p{page_label}.pdf")
        writer = PdfWriter()
        for p in pages:
            writer.add_page(reader.pages[p])
        with open(batch_pdf, "wb") as f:
            writer.write(f)
        pending.append((i, page_label, batch_pdf, ckpt_path))

    # Submit up to `concurrency` batches at a time, strictly in page order.
    # One list_pipeline_executions call per poll cycle checks every in-flight
    # execution at once, so polling load stays flat regardless of concurrency.
    in_flight = {}
    idx = 0
    last_progress = time.monotonic()
    while idx < len(pending) or in_flight:
        while idx < len(pending) and len(in_flight) < concurrency:
            i, page_label, batch_pdf, ckpt_path = pending[idx]
            size_mb = os.path.getsize(batch_pdf) / 1e6
            log(f"Batch {i + 1}/{n}: pages {page_label}, {size_mb:.1f} MB - submitting")
            execution = client.run_pipeline(pipeline_id, file_path=batch_pdf, output_format=fmt, max_polls=1)
            in_flight[execution.execution_id] = (i, page_label, ckpt_path)
            idx += 1
            last_progress = time.monotonic()

        if not in_flight:
            break
        time.sleep(POLL_SECONDS)
        if time.monotonic() - last_progress > MAX_WAIT_MINUTES * 60:
            sys.exit(f"No progress in {MAX_WAIT_MINUTES} min, still waiting on batches "
                      f"{sorted(i + 1 for i, _, _ in in_flight.values())}. Rerun to resume from checkpoints.")

        for execution in client.list_pipeline_executions(pipeline_id, limit=100)["executions"]:
            entry = in_flight.get(execution.execution_id)
            if entry and execution.status in ("completed", "completed_with_errors", "failed"):
                i, page_label, ckpt_path = entry
                results[i] = finish_batch(client, execution, ckpt_path, i, n, page_label)
                del in_flight[execution.execution_id]
                last_progress = time.monotonic()

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return results


def merge_results(results, fmt):
    # every batch names its pictures from its own page ids, so names repeat across batches
    results = [unique_batch_images(r, fmt, i) for i, r in enumerate(results)]
    contents = [r[fmt] for r in results]
    if fmt in ("markdown", "html"):
        merged = "\n\n---\n\n".join(contents)
    else:
        list_key = "children" if fmt == "json" else "blocks"
        merged = dict(contents[0]) if isinstance(contents[0], dict) else {}
        merged[list_key] = [item for c in contents if isinstance(c, dict) for item in (c.get(list_key) or [])]

    images = {}
    for r in results:
        images.update(r.get("images") or {})

    def total(key):
        return sum(r[key] for r in results if r.get(key) is not None) or None

    return {
        fmt: merged,
        "images": images,
        "page_count": sum(r.get("page_count") or 0 for r in results),
        "total_tokens": total("total_tokens"),
        "_elapsed_s": total("_elapsed_s"),
        "_nominal_cost_cents": total("_nominal_cost_cents"),
    }


IMAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}_img\.\w+$")


def save_output(result, fmt, out_path):
    content = result[fmt]
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, indent=2)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    out_dir = os.path.dirname(out_path)
    images = result.get("images") or {}

    stale = [name for name in os.listdir(out_dir) if IMAGE_NAME_RE.match(name) and name not in images]
    for name in stale:
        os.remove(os.path.join(out_dir, name))
    if stale:
        log(f"  removed {len(stale)} leftover image(s) from a previous run")

    n_images = 0
    for name, b64 in images.items():
        try:
            data = base64.b64decode(b64)
        except (binascii.Error, ValueError):
            continue
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
        n_images += 1
    return n_images


def log_summary(result, run_start, n_images, out_path):
    pages = result.get("page_count")
    elapsed = timedelta(seconds=round(time.monotonic() - run_start))
    log(f"Done: {pages} pages, {n_images} images in {elapsed}")
    if result.get("_elapsed_s") and pages:
        log(f"  {result['_elapsed_s']:.0f}s server time at {result['_elapsed_s'] / pages:.1f}s/page")
    if result.get("total_tokens") and pages:
        log(f"  {result['total_tokens']} tokens at {result['total_tokens'] / pages:.0f}/page")
    if result.get("_nominal_cost_cents") and pages:
        cost = result["_nominal_cost_cents"] / 100
        rate = cost / pages * 1000
        log(f"  ${cost:.2f} cost at ${rate:.2f}/1k pages nominal (check dashboard for actual)")
    log(f"Saved to {out_path}")


def convert(pdf_path, api_key, fmt, batch_size, concurrency):
    if not os.path.isfile(pdf_path):
        sys.exit(f"File not found: {pdf_path}")

    out_path = default_output_path(pdf_path, fmt)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    run_start = time.monotonic()
    n_pages = len(PdfReader(pdf_path).pages)
    log(f"PDF: {os.path.basename(pdf_path)} ({os.path.getsize(pdf_path) / 1e6:.2f} MB, {n_pages} pages)")

    client = DatalabClient(api_key=api_key)
    pipeline_id = find_or_create_pipeline(client)
    checkpoint_dir = checkpoint_dir_for(out_path, fmt)
    results = run_batches(client, pipeline_id, pdf_path, fmt, batch_size, checkpoint_dir, concurrency)
    result = merge_results(results, fmt)
    try:
        shutil.rmtree(checkpoint_dir)
    except OSError as exc:
        log(f"  couldn't remove checkpoint dir {checkpoint_dir}: {exc} - a rerun may reuse stale batches from it")

    n_images = save_output(result, fmt, out_path)
    log_summary(result, run_start, n_images, out_path)


def parse_args():
    p = argparse.ArgumentParser(
        description="Convert a PDF through the Flugblatt_Pipeline (Accurate mode, paginated, "
                     "headers/footers kept, cross-page merge).")
    p.add_argument("pdf", help="path to the input PDF")
    p.add_argument("--api-key", metavar="KEY", help="Datalab API key (default: DATALAB_API_KEY from .env)")
    p.add_argument("-f", "--format", choices=list(FORMATS), default="json", help="output format (default: json)")
    p.add_argument("--batch-size", type=int, default=50, metavar="N",
                   help="pages per upload, checkpointed as they complete (default: 50)")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, metavar="N",
                   help=f"batches in flight at once (default: {DEFAULT_CONCURRENCY}; "
                        "Datalab caps accounts at 25 concurrent executions)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert(args.pdf, load_api_key(args.api_key), args.format, args.batch_size, args.concurrency)
