#!/usr/bin/env python3
"""Flag flugblatt_splitter segments that likely still contain a missed cut,
using the PageHeader boundary signals already present in the Datalab OCR
block-JSON - no LLM call, no re-OCR, no page images.

Implements the boundary-signal heuristics from docs/korpus/korpusstruktur.md
Section 7.5 (see also the `boundary_signals` shape in
docs/korpus/schema/page.schema.json):

  - header_page_number: a PageHeader block that is just a (decorated) page
    number, e.g. "- 2 -", "Seite 3". A value > 1 is a near-certain
    continuation page - it should almost never be a segment start.
  - header_is_masthead: a PageHeader block that is a repeated org/sigel
    banner, e.g. "LSD - LSD - LSD - ..." or "LSD - SHB - SDS - LSD - SHB -
    SDS". A near-certain segment start.
  - header_has_date: a PageHeader block containing a printed date. A good
    (not certain) signal for a segment start.

A segment where an internal (non-first) page carries a masthead or date
header almost always means a cut is missing there (`masthead_inside`). A
segment starting on a page whose header is a plain continuation page number
suggests the cut *before* it is misplaced (`continuation_start`). A segment
much longer than the rest of the volume's segments is suspicious even
without a header hit (`long_segment`).

Per docs/korpus/korpusstruktur.md Section 1: auto-segmentation (and, by the
same logic, manual segmentation under time pressure) essentially never
invents a false cut - it *misses* them. So this script only looks for
evidence of missing cuts, not spurious ones.

Reads:
  - `<pdf-stem>.segments.json` next to the PDF (flugblatt_splitter's format)
  - `<pdf-stem>/<pdf-stem>.json` next to the PDF (Datalab block-JSON OCR
    output - has each page's blocks, incl. PageHeader, in `children`)

Writes: nothing by default - prints a report to stdout. Pass --json to also
write `<pdf-stem>.boundary_flags.json` (one entry per flagged segment).

Usage:
    python pipelines/01_pdf/detect_missing_cuts.py "data/raw/Nr. 009 (1972)/0118_0009.pdf"
    python pipelines/01_pdf/detect_missing_cuts.py "data/raw/Nr. 009 (1972)/0118_0009.pdf" --json
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TAG_RE = re.compile(r"<[^>]+>")

PAGE_NUM_RE = re.compile(
    r"^[\s\-–—]*(?:seite|s\.)?[\s.]*?(\d{1,4})[.)]?[\s\-–—]*$",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b\d{1,2}\.\s*\d{1,2}\.\s*\d{2,4}\b"
    r"|\b\d{1,2}\.\s*(?:Jan|Feb|M[äa]r|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)[a-zäöü]*\.?\s*\d{2,4}\b",
    re.IGNORECASE,
)

# Segments longer than this percentile of the volume's own segment lengths
# get flagged as `long_segment` (docs/korpus/korpusstruktur.md 7.5).
LONG_SEGMENT_PERCENTILE = 95
FLAG_SEVERITY = {"masthead_inside": 3, "continuation_start": 2, "long_segment": 1}


def log(msg):
    print(msg, file=sys.stderr)


def block_text(block):
    return html_lib.unescape(TAG_RE.sub(" ", block.get("html", ""))).strip()


def is_masthead(text):
    """A sigel/masthead banner: 3+ dash-separated parts that repeat with a
    short period, e.g. "LSD - LSD - LSD" (period 1) or "LSD - SHB - SDS -
    LSD - SHB - SDS" (period 3, two full cycles)."""
    parts = [p.strip().lower() for p in re.split(r"[-–—]", text) if p.strip()]
    if len(parts) < 3 or any(len(p) > 30 or len(p.split()) > 4 for p in parts):
        return False
    for period in range(1, len(parts) // 2 + 1):
        if len(parts) >= period * 2 and all(parts[i] == parts[i % period] for i in range(len(parts))):
            return True
    return False


def classify_page(page):
    headers = [block_text(c) for c in (page.get("children") or []) if c.get("block_type") == "PageHeader"]
    header_page_number = None
    header_is_masthead = False
    header_has_date = False
    for text in headers:
        if not text:
            continue
        m = PAGE_NUM_RE.match(text)
        if m:
            n = int(m.group(1))
            if not (1900 <= n <= 2099):  # bare 4-digit years ("1973") aren't page numbers
                header_page_number = n
                continue
        if is_masthead(text):
            header_is_masthead = True
        if DATE_RE.search(text):
            header_has_date = True

    children = page.get("children") or []
    first_block_type = children[0].get("block_type") if children else None

    if header_is_masthead:
        start_score = 0.9
    elif header_has_date:
        start_score = 0.7
    elif header_page_number is not None and header_page_number > 1:
        start_score = 0.05
    else:
        start_score = 0.4

    return {
        "header_page_number": header_page_number,
        "header_is_masthead": header_is_masthead,
        "header_has_date": header_has_date,
        "first_block_type": first_block_type,
        "start_score": start_score,
        "headers": [h for h in headers if h],
    }


def load_page_signals(ocr_json_path):
    data = json.loads(ocr_json_path.read_text(encoding="utf-8"))
    return {i + 1: classify_page(pg) for i, pg in enumerate(data["children"])}


def analyze(segments, page_signals):
    ordered = sorted(segments, key=lambda s: s["start_page"])
    lengths = [s["end_page"] - s["start_page"] + 1 for s in ordered]
    if len(lengths) >= 20:
        threshold = statistics.quantiles(lengths, n=100)[LONG_SEGMENT_PERCENTILE - 1]
    else:
        threshold = max(lengths) if lengths else 1

    flagged = []
    for seg in ordered:
        n_pages = seg["end_page"] - seg["start_page"] + 1
        flags = []

        start_sig = page_signals.get(seg["start_page"], {})
        if start_sig.get("header_page_number") and start_sig["header_page_number"] > 1:
            flags.append({"type": "continuation_start", "page": seg["start_page"],
                           "evidence": start_sig["headers"]})

        for p in range(seg["start_page"] + 1, seg["end_page"] + 1):
            sig = page_signals.get(p)
            if sig and (sig["header_is_masthead"] or sig["header_has_date"]):
                flags.append({"type": "masthead_inside", "page": p, "evidence": sig["headers"]})

        if n_pages > 1 and n_pages > threshold:
            flags.append({"type": "long_segment", "page": None, "evidence": [f"{n_pages} pages"]})

        if flags:
            flags.sort(key=lambda f: -FLAG_SEVERITY[f["type"]])
            flagged.append({"segment": seg, "n_pages": n_pages, "flags": flags})

    flagged.sort(key=lambda f: -max(FLAG_SEVERITY[fl["type"]] for fl in f["flags"]))
    return flagged, threshold


def print_report(pdf_path, flagged, threshold, total_segments):
    print(f"\n{pdf_path.name}: {total_segments} segment(s), long_segment threshold = {threshold:.0f} pages")
    if not flagged:
        print("  no flags - nothing obviously missing")
        return
    print(f"  {len(flagged)} segment(s) flagged:\n")
    for entry in flagged:
        seg = entry["segment"]
        types = ", ".join(sorted({f["type"] for f in entry["flags"]}))
        print(f"  segment {seg['id']} (S. {seg['start_page']}-{seg['end_page']}, "
              f"{entry['n_pages']} pages) [{types}]")
        for f in entry["flags"]:
            where = f"S. {f['page']}" if f["page"] else "-"
            evidence = " / ".join(f["evidence"]) if f["evidence"] else ""
            print(f"      {f['type']:<18} {where:<8} {evidence}")
    print()


def parse_args():
    p = argparse.ArgumentParser(description="Flag segments likely missing an internal cut, from OCR PageHeader signals.")
    p.add_argument("pdf", help="path to the yearly PDF")
    p.add_argument("--segments", type=Path, help="override path to segments.json")
    p.add_argument("--ocr-json", type=Path, help="override path to the Datalab OCR json")
    p.add_argument("--json", action="store_true",
                   help="also write <pdf-stem>.boundary_flags.json next to the PDF")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.is_file():
        sys.exit(f"File not found: {pdf_path}")

    segments_path = args.segments or pdf_path.with_name(pdf_path.stem + ".segments.json")
    ocr_json_path = args.ocr_json or pdf_path.with_name(pdf_path.stem) / (pdf_path.stem + ".json")
    if not segments_path.is_file():
        sys.exit(f"No segments.json found: {segments_path}")
    if not ocr_json_path.is_file():
        sys.exit(f"No OCR json found: {ocr_json_path}")

    seg_doc = json.loads(segments_path.read_text(encoding="utf-8"))
    page_signals = load_page_signals(ocr_json_path)
    flagged, threshold = analyze(seg_doc["segments"], page_signals)
    print_report(pdf_path, flagged, threshold, len(seg_doc["segments"]))

    if args.json:
        out_path = pdf_path.with_name(pdf_path.stem + ".boundary_flags.json")
        out_doc = {
            "source_pdf": pdf_path.name,
            "long_segment_threshold_pages": threshold,
            "flagged": flagged,
        }
        out_path.write_text(json.dumps(out_doc, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"Saved: {out_path}")
