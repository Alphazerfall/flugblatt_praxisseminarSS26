#!/usr/bin/env python3
"""One-off: lift the viewer's gold annotations to the current layout schema.

Handles v1 -> v4 directly, v2 (three separately rated dimensions —
segmentation/classification/reading_order) -> v4, and v3 (one combined
rating) -> v4. Files already on v4 are left alone, so re-running is safe.

## Why v4

v1 recorded the whole-page layout review in four fields with mixed polarity
and unusable defaults:

    reading_order_correct   positive, *checked by default*
    layout_has_errors       negative, one bucket for every kind of layout error
    layout_error_note       free text
    layout_reviewed         "I've checked" — only there because the two flags
                            above default to "looks fine", so an untouched page
                            was indistinguishable from a checked one

v3 replaced them with one combined rating, which made it impossible to tell
"the regions are wrong" from "the order is wrong" apart when reporting. v2
(before that) rated three separate dimensions, which cost more time per page
than the extra precision was worth. v4 is the middle ground: two ratings —
general layout, reading order — sharing one note, which is also what the two
annotators who worked outside this tool actually used ("Layout has errors" /
"Reading order correct", one text field underneath):

    "layout_schema": 4,
    "layout": {
      "general":       {"rating": "unrated|ok|error"},
      "reading_order": {"rating": "unrated|ok|error"},
      "note": "<free text, shared>"
    }

## v1 -> v4

  * general: "error" if layout_has_errors was; "ok" only where
    layout_reviewed explicitly confirmed a clean page (an untouched `true`
    is just the old default and means nothing); otherwise "unrated".
  * reading_order: same rule, reading reading_order_correct instead.
  * note: layout_error_note, verbatim.
  * all four v1 fields are kept verbatim under `layout_legacy`, and
    `complete` is recomputed.

`READING_ORDER_OVERRIDE` below corrects the two pages found where a v1 note
contradicts its own reading_order_correct flag (the annotator apparently
forgot to also flip the checkbox) — everywhere else, the flags are trusted
mechanically. Read it before `--apply`; the original flags survive in
layout_legacy regardless, so a wrong reading can always be corrected.

## v2 -> v4

  * general: "error" if segmentation or classification was; "ok" if both
    were; otherwise "unrated".
  * reading_order: carried over as its own dimension already was.
  * note: all three dimensions' notes, deduplicated and joined with " · ".

## v3 -> v4

  * The single combined rating is mirrored onto both `general` and
    `reading_order` — which of the two was actually the problem isn't
    recoverable from that shape alone. Only relevant for a page created
    natively while v3 was current (no `layout_legacy` to fall back to); every
    page that went through v1 keeps its real per-flag history there instead.

Usage:
    python pipelines/03_eval/migrate_layout_annotations.py            # dry run
    python pipelines/03_eval/migrate_layout_annotations.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from build_dinglehopper_inputs import LAYOUT_SCHEMA, NON_TEXT_TYPES, _ratings_from_v1_flags

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"

DIM_KEYS = ("segmentation", "classification", "reading_order")

# (annotator, page) -> the v1 note found there, as a guard: a page whose note
# no longer matches is left to the mechanical mapping and reported, so a
# hand-edited or re-annotated file can't be silently mis-corrected by a stale
# table.
READING_ORDER_OVERRIDE: dict[tuple[str, int], str] = {
    ("fl", 32): '"Ablage"-Block kommt nach Überschrift in Block 1',
    ("vk", 5): "Wrong Order",
}


def blocks_all_reviewed(blocks: list[dict]) -> bool:
    text_blocks = [b for b in blocks if b.get("type") not in NON_TEXT_TYPES]
    return bool(text_blocks) and all(
        b.get("status") == "illegible" or b.get("review") == "done" for b in text_blocks
    )


def layout_open(layout: dict) -> bool:
    """Mirrors layoutOpen/computePageComplete in ocr_viewer/app.js."""
    ratings = [(layout.get(k) or {}).get("rating") for k in ("general", "reading_order")]
    if any(r not in ("ok", "error") for r in ratings):
        return True
    return "error" in ratings and not (layout.get("note") or "").strip()


def _apply_reading_order_override(
    general: str, reading_order: str, note: str, *, annotator: str, page: int, report: list[str]
) -> tuple[str, str, str]:
    expected = READING_ORDER_OVERRIDE.get((annotator, page))
    if expected is None:
        return general, reading_order, note
    if note != expected.strip():
        report.append(
            f"    ! reading_order override skipped — note no longer matches\n"
            f"      expected: {expected}\n"
            f"      found:    {note}"
        )
    elif reading_order != "error":
        reading_order = "error"
        report.append("    reading_order: error (note contradicted reading_order_correct=true)")
    return general, reading_order, note


def migrate(data: dict, annotator: str) -> tuple[bool, list[str]]:
    """Rewrite `data` in place. Returns (changed, notes-for-the-report)."""
    report: list[str] = []
    layout = data.get("layout")

    if isinstance(layout, dict) and "general" in layout and "reading_order" in layout:
        # Already the current shape — repair only.
        changed = int(data.get("layout_schema", 0)) != LAYOUT_SCHEMA
        for key in ("general", "reading_order"):
            if not isinstance(layout.get(key), dict) or layout[key].get("rating") not in ("unrated", "ok", "error"):
                layout[key] = {"rating": "unrated"}
                changed = True
        if not isinstance(layout.get("note"), str):
            layout["note"] = ""
            changed = True
        if changed:
            data["layout_schema"] = LAYOUT_SCHEMA
            data["complete"] = blocks_all_reviewed(data.get("blocks", [])) and not layout_open(layout)
        return changed, report

    if isinstance(layout, dict) and any(k in layout for k in ("segmentation", "classification")):
        seg = layout.get("segmentation") or {}
        cls = layout.get("classification") or {}
        ro = layout.get("reading_order") or {}
        general_ratings = [seg.get("rating", "unrated"), cls.get("rating", "unrated")]
        if "error" in general_ratings:
            general = "error"
        elif all(r == "ok" for r in general_ratings):
            general = "ok"
        else:
            general = "unrated"
        notes = dict.fromkeys((d.get("note") or "").strip() for d in (seg, cls, ro) if (d.get("note") or "").strip())
        note = " · ".join(notes)
        data["layout"] = {"general": {"rating": general}, "reading_order": {"rating": ro.get("rating", "unrated")}, "note": note}
        data["layout_schema"] = LAYOUT_SCHEMA
        data["complete"] = blocks_all_reviewed(data.get("blocks", [])) and not layout_open(data["layout"])
        report.append(f"    v2 -> v4: general={general}, reading_order={ro.get('rating', 'unrated')}" + (f", note: {note}" if note else ""))
        return True, report

    page = int(data.get("page", 0))
    legacy = data.get("layout_legacy")

    if isinstance(layout, dict) and "rating" in layout:
        if isinstance(legacy, dict):
            # The single combined rating can't say which aspect was the
            # problem — re-derive both from the real v1 flags preserved
            # under layout_legacy instead of guessing from it.
            general, reading_order, note = _apply_reading_order_override(
                *_ratings_from_v1_flags(legacy), annotator=annotator, page=page, report=report
            )
            report.insert(0, f"    v3 -> v4 (from layout_legacy): general={general}, reading_order={reading_order}")
        else:
            rating = layout.get("rating", "unrated")
            note = (layout.get("note") or "").strip()
            general = reading_order = rating
            report.append(f"    v3 -> v4: mirrored rating={rating} onto both (no layout_legacy to split from)")
        data["layout"] = {"general": {"rating": general}, "reading_order": {"rating": reading_order}, "note": note}
        data["layout_schema"] = LAYOUT_SCHEMA
        data["complete"] = blocks_all_reviewed(data.get("blocks", [])) and not layout_open(data["layout"])
        return True, report

    general, reading_order, note = _apply_reading_order_override(
        *_ratings_from_v1_flags(data), annotator=annotator, page=page, report=report
    )
    report.insert(0, f"    v1 -> v4: general={general}, reading_order={reading_order}" + (f", note: {note}" if note else ""))

    # Keep the v1 values verbatim — the mapping above drops information on
    # purpose (mixed polarity, a "reviewed" flag with no v4 equivalent), and
    # this is a gold standard, so the provenance should survive it.
    data["layout_legacy"] = {
        "reading_order_correct": data.get("reading_order_correct"),
        "layout_has_errors": data.get("layout_has_errors"),
        "layout_error_note": data.get("layout_error_note"),
        "layout_reviewed": data.get("layout_reviewed"),
    }
    for key in ("reading_order_correct", "layout_has_errors", "layout_error_note", "layout_reviewed"):
        data.pop(key, None)

    data["layout_schema"] = LAYOUT_SCHEMA
    data["layout"] = {"general": {"rating": general}, "reading_order": {"rating": reading_order}, "note": note}
    data["complete"] = blocks_all_reviewed(data.get("blocks", [])) and not layout_open(data["layout"])
    return True, report


def write_atomic(path: Path, data: dict) -> None:
    """Same tmp-then-replace dance the viewer's save endpoint uses."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--dataset", default="test_set", help="dataset folder under data/ (default: test_set)")
    parser.add_argument("--annotator", default=None, help="only this annotator (default: all found)")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = parser.parse_args()

    annotations_root = args.data_root / args.dataset / "gold" / "annotations"
    if not annotations_root.is_dir():
        parser.error(f"no annotations found at {annotations_root}")

    ann_dirs = (
        [annotations_root / args.annotator]
        if args.annotator
        else sorted(p for p in annotations_root.iterdir() if p.is_dir())
    )

    seen = migrated = already = 0
    complete_before = complete_after = 0

    for ann_dir in ann_dirs:
        if not ann_dir.is_dir():
            print(f"! no such annotator dir: {ann_dir}", file=sys.stderr)
            continue
        print(f"{ann_dir.name}:")
        for path in sorted(ann_dir.glob("page_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"  ! skipping {path.name}: {exc}", file=sys.stderr)
                continue
            seen += 1
            complete_before += bool(data.get("complete"))
            changed, report = migrate(data, ann_dir.name)
            if not changed:
                already += 1
                complete_after += bool(data.get("complete"))
                continue
            migrated += 1
            complete_after += bool(data.get("complete"))
            print(f"  {path.name}:")
            for line in report:
                print(line)
            if args.apply:
                write_atomic(path, data)

    print(
        f"\n{seen} file(s): {migrated} migrated, {already} already at schema {LAYOUT_SCHEMA}."
        f"\ncomplete: {complete_before} -> {complete_after}"
    )
    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply once the override table reads right.")


if __name__ == "__main__":
    main()
