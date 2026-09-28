#!/usr/bin/env python3
"""Turn the OCR-viewer's gold annotations into dinglehopper CER inputs.

The viewer's Correct mode writes one JSON per (annotator, page) under
    data/<dataset>/gold/annotations/<annotator>/page_<NNN>.json
Each block keeps its Datalab `id` alongside the raw OCR text (`ocr_text`), the
corrected text (`gt_text`), a `status` (unchanged | corrected | illegible),
structural `flags` (missed_region | spurious_region | merge | split) and an
`added` marker for annotator-inserted (missed) blocks. Each page also carries a
whole-page `layout` review from the sidebar: two ratings (general layout,
reading order), each unrated | ok | error, sharing one free-text `note`
saying what's wrong and where — see LAYOUT_SCHEMA below. Files on an older
layout schema are read through a fallback here; migrate_layout_annotations.py
converts them on disk.

This script serialises those into the flat gt/ocr text pairs dinglehopper
compares, at two granularities, plus a structural-error CSV:

    data/<dataset>/gold/eval/<annotator>/
        page/gt/page_<NNN>.txt      page/ocr/page_<NNN>.txt      (full page)
        block/gt/page_<NNN>_b<II>.txt  block/ocr/...             (per matched block)
        structural_report.csv

Page-level text is joined in reading order (block `order`). GT includes every
non-illegible, non-spurious block (added/missed blocks in place); OCR includes
every non-added, non-illegible block. So a missed region counts as an error on
the OCR side and a spurious region as an error on the GT side, while illegible
regions (no fair ground truth) are dropped from both — an honest page CER.
Block-level pairs are emitted only for *matched* blocks (present in both: not
added, not illegible, not flagged spurious).

Usage:
    python pipelines/03_eval/build_dinglehopper_inputs.py
    python pipelines/03_eval/build_dinglehopper_inputs.py --annotator fw --all
    python pipelines/03_eval/build_dinglehopper_inputs.py --score   # also run dinglehopper
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"

STRUCTURAL_FLAGS = ["missed_region", "spurious_region", "merge", "split"]

# Block types that aren't transcribable text (their content is an image, not
# something to score) — excluded from both gt and ocr. Keep in sync with
# NON_TEXT_TYPES in ocr_viewer/app.js.
NON_TEXT_TYPES = {"Picture", "Figure"}

# Whole-page layout review: two ratings (unrated | ok | error) — general
# layout and reading order — sharing one free-text note. Keep LAYOUT_SCHEMA
# in sync with ocr_viewer/app.js, where annotators fill this in. Also
# imported by migrate_layout_annotations.py.
#
# v4 (current) mirrors the two-checkbox-plus-note structure two annotators
# used outside this tool ("Layout has errors" / "Reading order correct").
# layout_row() below also reads v3 (one combined rating — replaced because it
# made "the regions are wrong" indistinguishable from "the order is wrong"
# when reporting), v2 (segmentation/classification/reading_order rated
# separately — replaced because three toggles and three notes per page cost
# more than the precision was worth) and v1 (the original
# reading_order_correct / layout_has_errors / layout_error_note /
# layout_reviewed quartet) files, so nothing has to go through
# migrate_layout_annotations.py first to export.
LAYOUT_SCHEMA = 4


def _ratings_from_v1_flags(v1: dict) -> tuple[str, str, str]:
    """(general_rating, reading_order_rating, note) from the raw v1 fields.

    "error" wins regardless of layout_reviewed: it's a specific finding,
    while layout_reviewed was only ever a completion marker. "ok" only where
    layout_reviewed explicitly confirmed a clean page — an untouched default
    `true` means nothing.
    """
    note = (v1.get("layout_error_note") or "").strip()
    reviewed = v1.get("layout_reviewed") is True
    general = "error" if v1.get("layout_has_errors") is True else ("ok" if reviewed else "unrated")
    reading_order = "error" if v1.get("reading_order_correct") is False else ("ok" if reviewed else "unrated")
    return general, reading_order, note


def layout_row(data: dict) -> dict[str, str]:
    """Flatten a page's layout review into CSV columns.

    Counting is on the ratings — `df["general_rating"].value_counts()` — with
    the note there to be read, not parsed.
    """
    schema = int(data.get("layout_schema", 1))
    row = {"layout_schema": schema}

    if schema >= 4:
        layout = data.get("layout") or {}
        row["general_rating"] = (layout.get("general") or {}).get("rating", "unrated")
        row["reading_order_rating"] = (layout.get("reading_order") or {}).get("rating", "unrated")
        row["layout_note"] = (layout.get("note") or "").strip()
        return row

    if schema == 3:
        # The single combined rating can't say which aspect it was about;
        # layout_legacy (if this file has been through migrate_layout_
        # annotations.py before) has the real answer.
        legacy = data.get("layout_legacy")
        if isinstance(legacy, dict):
            general, reading_order, note = _ratings_from_v1_flags(legacy)
            row["general_rating"], row["reading_order_rating"], row["layout_note"] = general, reading_order, note
            return row
        layout = data.get("layout") or {}
        rating = layout.get("rating", "unrated")
        row["general_rating"] = row["reading_order_rating"] = rating
        row["layout_note"] = (layout.get("note") or "").strip()
        return row

    if schema == 2:
        layout = data.get("layout") or {}
        general_dims = [layout.get(k) or {} for k in ("segmentation", "classification")]
        general_ratings = [d.get("rating", "unrated") for d in general_dims]
        if "error" in general_ratings:
            general = "error"
        elif general_ratings and all(r == "ok" for r in general_ratings):
            general = "ok"
        else:
            general = "unrated"
        ro = layout.get("reading_order") or {}
        all_dims = [*general_dims, ro]
        notes = dict.fromkeys((d.get("note") or "").strip() for d in all_dims if (d.get("note") or "").strip())
        row["general_rating"] = general
        row["reading_order_rating"] = ro.get("rating", "unrated")
        row["layout_note"] = " · ".join(notes)
        return row

    general, reading_order, note = _ratings_from_v1_flags(data)
    row["general_rating"], row["reading_order_rating"], row["layout_note"] = general, reading_order, note
    return row


def _is_text(block: dict) -> bool:
    return block.get("type") not in NON_TEXT_TYPES

# Toggled by --keep-whitespace; when True, runs of whitespace (incl. newlines)
# are collapsed to a single space in both gt and ocr before scoring, so that
# line-break-vs-space and multiple-space differences don't count as CER errors
# (they aren't recognition errors — see pipelines/03_eval/README.md).
_COLLAPSE_WS = True


def _norm(text: str) -> str:
    text = text or ""
    if _COLLAPSE_WS:
        return re.sub(r"\s+", " ", text).strip()
    return text.strip()


def page_texts(blocks: list[dict]) -> tuple[str, str]:
    """(gold, ocr) for the whole page, joined in reading order."""
    ordered = [b for b in sorted(blocks, key=lambda b: b.get("order", 0)) if _is_text(b)]
    gold = "\n\n".join(
        _norm(b.get("gt_text"))
        for b in ordered
        if b.get("status") != "illegible" and "spurious_region" not in b.get("flags", [])
        if _norm(b.get("gt_text"))
    )
    ocr = "\n\n".join(
        _norm(b.get("ocr_text"))
        for b in ordered
        if not b.get("added") and b.get("status") != "illegible"
        if _norm(b.get("ocr_text"))
    )
    return gold, ocr


def matched_blocks(blocks: list[dict]) -> list[dict]:
    """Blocks present in both gold and OCR — the ones with a per-block CER."""
    return [
        b
        for b in sorted(blocks, key=lambda b: b.get("order", 0))
        if _is_text(b)
        and not b.get("added")
        and b.get("status") != "illegible"
        and "spurious_region" not in b.get("flags", [])
    ]


def structural_counts(blocks: list[dict]) -> dict[str, int]:
    counts = {flag: 0 for flag in STRUCTURAL_FLAGS}
    counts["illegible"] = 0
    counts["added"] = 0
    for b in blocks:
        if b.get("added"):
            counts["added"] += 1
        if b.get("status") == "illegible":
            counts["illegible"] += 1
        for flag in b.get("flags", []):
            if flag in counts:
                counts[flag] += 1
    return counts


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def process_annotator(ann_dir: Path, out_root: Path, only_complete: bool) -> dict:
    pages = sorted(ann_dir.glob("page_*.json"))
    struct_rows: list[dict] = []
    page_pairs: list[tuple[Path, Path]] = []
    n_pages = 0

    for page_path in pages:
        try:
            data = json.loads(page_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  ! skipping {page_path.name}: {exc}", file=sys.stderr)
            continue
        if only_complete and not data.get("complete"):
            continue

        page = int(data.get("page", 0))
        nnn = f"{page:03d}"
        blocks = data.get("blocks", [])
        n_pages += 1

        gold, ocr = page_texts(blocks)
        gt_path = out_root / "page" / "gt" / f"page_{nnn}.txt"
        ocr_path = out_root / "page" / "ocr" / f"page_{nnn}.txt"
        write_text(gt_path, gold)
        write_text(ocr_path, ocr)
        page_pairs.append((gt_path, ocr_path))

        for i, b in enumerate(matched_blocks(blocks)):
            bii = f"{i:02d}"
            write_text(out_root / "block" / "gt" / f"page_{nnn}_b{bii}.txt", _norm(b.get("gt_text")))
            write_text(out_root / "block" / "ocr" / f"page_{nnn}_b{bii}.txt", _norm(b.get("ocr_text")))

        row = {
            "page": page,
            **structural_counts(blocks),
            # Layout section (sidebar): whole-page structural signals the
            # annotator sets while auditing the full layout with "Show all
            # boxes" — distinct from the per-block flags above.
            **layout_row(data),
        }
        struct_rows.append(row)

    if struct_rows:
        struct_rows.sort(key=lambda r: r["page"])
        csv_path = out_root / "structural_report.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            fields = [
                "page", "added", "missed_region", "spurious_region", "illegible", "merge", "split",
                "general_rating", "reading_order_rating", "layout_note", "layout_schema",
            ]
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in struct_rows:
                writer.writerow({k: row.get(k, 0) for k in fields})

    return {"pages": n_pages, "page_pairs": page_pairs}


_REPORT_FIELD_RE = re.compile(r'"(cer|wer|n_characters|n_words)"\s*:\s*([0-9.eE+-]+)')


def _read_report_metrics(path: Path) -> dict[str, float] | None:
    """(cer, wer, n_characters, n_words) from one dinglehopper .json report.

    Plain `json.loads` fails on Windows: dinglehopper writes the gt/ocr
    *paths* into the JSON unescaped, so a backslash-containing path (any
    Windows path) breaks the parse — a dinglehopper bug, not a repo string,
    so it's worked around here rather than "fixed" upstream. The numeric
    fields we actually need never contain backslashes, so a targeted regex
    gets them regardless of whether the surrounding JSON is valid.
    """
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        if "cer" in data and "wer" in data:
            return {k: float(data[k]) for k in ("cer", "wer", "n_characters", "n_words")}
    except json.JSONDecodeError:
        pass
    found = dict(_REPORT_FIELD_RE.findall(text))
    if "cer" not in found or "wer" not in found:
        return None
    return {k: float(found[k]) for k in ("cer", "wer", "n_characters", "n_words")}


def summarize_reports(reports: Path) -> list[dict[str, float]]:
    """Per-page metrics for every report in `reports`, in place of the
    broken `dinglehopper-summarize` (see `_read_report_metrics`)."""
    rows = []
    for report in sorted(reports.glob("*.json")):
        metrics = _read_report_metrics(report)
        if metrics is None:
            print(f"  ! could not read {report.name}", file=sys.stderr)
            continue
        rows.append(metrics)
    return rows


def print_summary(label: str, rows: list[dict[str, float]]) -> None:
    if not rows:
        print(f"  ! no readable reports for {label}", file=sys.stderr)
        return
    macro_cer = sum(r["cer"] for r in rows) / len(rows)
    macro_wer = sum(r["wer"] for r in rows) / len(rows)
    total_chars = sum(r["n_characters"] for r in rows)
    total_words = sum(r["n_words"] for r in rows)
    weighted_cer = sum(r["cer"] * r["n_characters"] for r in rows) / total_chars if total_chars else 0.0
    weighted_wer = sum(r["wer"] * r["n_words"] for r in rows) / total_words if total_words else 0.0
    print(f"  {label}: {len(rows)} page(s)")
    print(f"    macro-avg    CER {macro_cer:.4%}  WER {macro_wer:.4%}  (mean of per-page rates)")
    print(f"    length-weighted CER {weighted_cer:.4%}  WER {weighted_wer:.4%}  (pooled over all characters/words)")


def run_dinglehopper(page_pairs: list[tuple[Path, Path]], out_root: Path) -> list[dict[str, float]]:
    exe = shutil.which("dinglehopper")
    if not exe:
        print("  ! dinglehopper not installed — skip --score, or `pip install -e \".[eval]\"`", file=sys.stderr)
        return []
    reports = out_root / "page" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    for gt_path, ocr_path in page_pairs:
        stem = gt_path.stem  # page_NNN
        subprocess.run([exe, str(gt_path), str(ocr_path), str(reports / stem)], check=False)
    print(f"  dinglehopper reports written to {reports}")
    rows = summarize_reports(reports)
    print_summary(out_root.name, rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--dataset", default="test_set", help="dataset folder under data/ (default: test_set)")
    parser.add_argument("--annotator", default=None, help="only this annotator (default: all found)")
    parser.add_argument("--all", action="store_true", help="include pages not yet marked complete")
    parser.add_argument("--score", action="store_true", help="also run dinglehopper on the page-level pairs")
    parser.add_argument("--keep-whitespace", action="store_true",
                        help="do NOT collapse whitespace; count line-break/space differences as CER errors")
    args = parser.parse_args()

    global _COLLAPSE_WS
    _COLLAPSE_WS = not args.keep_whitespace

    annotations_root = args.data_root / args.dataset / "gold" / "annotations"
    if not annotations_root.is_dir():
        parser.error(f"no annotations found at {annotations_root}")

    ann_dirs = (
        [annotations_root / args.annotator]
        if args.annotator
        else sorted(p for p in annotations_root.iterdir() if p.is_dir())
    )

    all_rows: list[dict[str, float]] = []
    for ann_dir in ann_dirs:
        if not ann_dir.is_dir():
            print(f"! no such annotator dir: {ann_dir}", file=sys.stderr)
            continue
        out_root = args.data_root / args.dataset / "gold" / "eval" / ann_dir.name
        print(f"{ann_dir.name}:")
        result = process_annotator(ann_dir, out_root, only_complete=not args.all)
        print(f"  {result['pages']} page(s) -> {out_root}")
        if args.score:
            all_rows.extend(run_dinglehopper(result["page_pairs"], out_root))

    if args.score and len(ann_dirs) > 1:
        print("\ncombined:")
        print_summary("all annotators", all_rows)

    print("\nNext: dinglehopper <gt.txt> <ocr.txt> <report>  (or re-run with --score)")


if __name__ == "__main__":
    main()
