#!/usr/bin/env python3
"""For each document in a flugblatt_splitter segmentation, ask an LLM to pull
out its date, caption/title, and issuing organization from the OCR text
already produced for that page range - no re-OCR, no page images.

Reads:
  - `<pdf-stem>.segments.json` next to the PDF (flugblatt_splitter's format)
  - `<pdf-stem>/<pdf-stem>.json` next to the PDF (Datalab block-JSON OCR
    output, e.g. from datalab_convert.py/flugblatt_convert.py - has each
    page's text as HTML in `children[i]["html"]`)

Writes:
  - `<pdf-stem>.metadata.json` (default) - a sidecar file, one entry per
    segment, never touches segments.json.
  - with --install: also merges title/date back into segments.json itself
    (issuing_org folded into title as "Org - Caption"), backing up any
    existing segments.json to a timestamped .bak first.

Usage:
    python pipelines/04_metadata/extract_metadata.py "data/raw/Nr. 002 (1968)/0118_0002.pdf"
    python pipelines/04_metadata/extract_metadata.py "data/raw/Nr. 002 (1968)/0118_0002.pdf" --install
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_BATCH_SIZE = 20
TAG_RE = re.compile(r"<[^>]+>")

PROMPT = (
    "Below is the OCR text of several separate documents (German political "
    "flyers/leaflets, 'Flugblätter', from the 1960s-70s) that have already been "
    "split out of a larger scanned collection. Each is delimited by a "
    "'=== segment <id> ===' marker. For EACH segment, independently identify:\n"
    "- title: the flyer's own full headline (its main heading exactly as printed, not a "
    "summary you invent) - include the complete headline even if it spans multiple lines "
    "or has a subtitle after it; if letters are individually spaced out for emphasis "
    "(e.g. 'F A L L H I R S C H'), collapse that back into normal words ('FALL HIRSCH')\n"
    "- issuing_org: the organization, party, committee, or group that issued it, "
    "as named in the text (empty string if genuinely not stated)\n"
    "- date_text: the date exactly as it appears in the text (empty string if none)\n"
    "- date_iso: that date normalized to YYYY-MM-DD if you can confidently resolve it "
    "(the flyers are known to be from the year given below), else empty string\n\n"
    "Return exactly one result per segment id given below - none merged, none skipped, "
    "any order - using that same id in your response.\n\n"
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "issuing_org": {"type": "string"},
                    "date_text": {"type": "string"},
                    "date_iso": {"type": "string"},
                },
                "required": ["id", "title", "issuing_org", "date_text", "date_iso"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["results"],
    "additionalProperties": False,
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def fmt_elapsed(seconds):
    return str(timedelta(seconds=round(seconds)))


def get_client():
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("Set OPENROUTER_API_KEY in your environment or in a local .env file.")
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def html_to_text(fragment_html):
    text = TAG_RE.sub("\n", fragment_html)
    return html_lib.unescape(text)


def load_page_texts(ocr_json_path):
    # Array position, not the "id" field: when this OCR json was produced via
    # flugblatt_convert.py --batch-size, each batch's page ids restart from
    # /page/0/... on merge, so ids collide across batch boundaries - only
    # array order is reliable across the whole document.
    data = json.loads(ocr_json_path.read_text(encoding="utf-8"))
    pages = {}
    for i, child in enumerate(data["children"]):
        pages[i + 1] = html_to_text(child.get("html", ""))  # 1-indexed
    return pages


def segment_text(page_texts, start_page, end_page):
    parts = []
    for p in range(start_page, end_page + 1):
        text = page_texts.get(p, "").strip()
        if text:
            parts.append(f"--- page {p} ---\n{text}")
    return "\n\n".join(parts)


def extract_batch(client, model, year, batch):
    """batch: list of (segment_id, text). Returns {segment_id: meta_dict}."""
    body = "\n\n".join(f"=== segment {seg_id} ===\n{text}" for seg_id, text in batch)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": PROMPT + f"Collection year: {year}\n\n{body}"}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "flugblatt_metadata", "strict": True, "schema": RESPONSE_SCHEMA},
        },
    )
    parsed = json.loads(response.choices[0].message.content)
    return {r["id"]: r for r in parsed["results"]}


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def backup_existing(path):
    if not path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.stem}.bak-{stamp}{path.suffix}")
    path.rename(backup_path)
    return backup_path


def guess_year(pdf_path):
    m = re.search(r"\((\d{4})\)", str(pdf_path))
    return m.group(1) if m else "unknown"


def parse_args():
    p = argparse.ArgumentParser(description="Extract date/title/issuing org per segment via an LLM.")
    p.add_argument("pdf", help="path to the yearly PDF (segments.json and OCR json are found next to it)")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL,
                   help=f"OpenRouter model slug (default: {DEFAULT_MODEL})")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, metavar="N",
                   help=f"segments per API request (default: {DEFAULT_BATCH_SIZE})")
    p.add_argument("--segments", type=Path, help="override path to segments.json")
    p.add_argument("--ocr-json", type=Path, help="override path to the Datalab OCR json")
    p.add_argument("-o", "--output", type=Path, help="override output path for the sidecar metadata.json")
    p.add_argument("--install", action="store_true",
                   help="also merge title/date back into segments.json (backing up any existing "
                        "file first) so flugblatt_splitter picks it up")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.is_file():
        sys.exit(f"File not found: {pdf_path}")

    client = get_client()

    segments_path = args.segments or pdf_path.with_name(pdf_path.stem + ".segments.json")
    ocr_json_path = args.ocr_json or pdf_path.with_name(pdf_path.stem) / (pdf_path.stem + ".json")
    if not segments_path.is_file():
        sys.exit(f"No segments.json found: {segments_path}")
    if not ocr_json_path.is_file():
        sys.exit(f"No OCR json found: {ocr_json_path} (run datalab_convert.py/flugblatt_convert.py first)")

    seg_doc = json.loads(segments_path.read_text(encoding="utf-8"))
    segments = seg_doc["segments"]
    page_texts = load_page_texts(ocr_json_path)
    year = guess_year(pdf_path)

    ordered_segments = sorted(segments, key=lambda s: s["start_page"])
    empty_meta = {"title": "", "issuing_org": "", "date_text": "", "date_iso": ""}

    to_fetch = []  # (segment_id, text)
    meta_by_id = {}
    for seg in ordered_segments:
        text = segment_text(page_texts, seg["start_page"], seg["end_page"])
        if not text:
            log(f"  ! segment {seg['id']} (pages {seg['start_page']}-{seg['end_page']}): no OCR text, skipping")
            meta_by_id[seg["id"]] = empty_meta
        else:
            to_fetch.append((seg["id"], text))

    batches = list(chunked(to_fetch, args.batch_size))
    log(f"{len(segments)} segment(s), {len(to_fetch)} with text -> "
        f"{len(batches)} API request(s) of up to {args.batch_size} segment(s) each (year={year}) ...")

    run_start = time.monotonic()
    for i, batch in enumerate(batches, 1):
        log(f"  batch {i}/{len(batches)}: segments {[seg_id for seg_id, _ in batch]} ...")
        batch_meta = extract_batch(client, args.model, year, batch)
        for seg_id, _ in batch:
            meta = batch_meta.get(seg_id)
            if meta is None:
                log(f"    ! segment {seg_id}: missing from response, leaving blank")
                meta_by_id[seg_id] = empty_meta
                continue
            meta_by_id[seg_id] = meta
            date_display = f"{meta['date_text']} (iso: {meta['date_iso']})" if meta["date_iso"] else meta["date_text"]
            log(f"    segment {seg_id}: \"{meta['title']}\" / {meta['issuing_org']} / {date_display}")

    results = [{**seg, **meta_by_id[seg["id"]]} for seg in ordered_segments]
    log(f"Done in {fmt_elapsed(time.monotonic() - run_start)}.")

    out_path = args.output or pdf_path.with_name(pdf_path.stem + ".metadata.json")
    out_doc = {
        "source_pdf": pdf_path.name,
        "created": datetime.now().isoformat(),
        "model": args.model,
        "segments": results,
    }
    out_path.write_text(json.dumps(out_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Saved: {out_path}")

    if args.install:
        backup_path = backup_existing(segments_path)
        if backup_path:
            log(f"  backed up existing {segments_path.name} -> {backup_path.name}")
        installed_segments = []
        for r in results:
            title = f"{r['issuing_org']} - {r['title']}" if r["issuing_org"] else r["title"]
            installed_segments.append({
                "id": r["id"],
                "title": title,
                "date": r["date_iso"] or r["date_text"],
                "start_page": r["start_page"],
                "end_page": r["end_page"],
                "confirmed": r["confirmed"],
            })
        seg_doc["segments"] = installed_segments
        segments_path.write_text(json.dumps(seg_doc, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"  installed into {segments_path}")
