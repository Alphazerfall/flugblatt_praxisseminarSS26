"""Segment validation and exact JSON save/load.

The frontend owns live cut-point editing and only ever POSTs the already-
derived `segments` array — this module's job is purely to validate
contiguity/coverage and persist/read the exact JSON file format:

    {
      "source_pdf": "flugblaetter_1969.pdf",
      "created": "<ISO timestamp>",
      "segments": [
        {"id": 1, "title": "...", "start_page": 1, "end_page": 3, "confirmed": true}
      ]
    }
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def segmentation_path_for(pdf_path: Path) -> Path:
    return pdf_path.with_name(pdf_path.stem + ".segments.json")


def validate_segments(segments: list[dict], page_count: int) -> None:
    if not segments:
        raise ValueError("segments must not be empty")
    ordered = sorted(segments, key=lambda s: s["start_page"])
    if ordered[0]["start_page"] != 1:
        raise ValueError("first segment must start at page 1")
    if ordered[-1]["end_page"] != page_count:
        raise ValueError(f"last segment must end at page {page_count}")
    for prev, cur in zip(ordered, ordered[1:]):
        if cur["start_page"] != prev["end_page"] + 1:
            raise ValueError("segments must be contiguous with no gaps/overlaps")
    for seg in ordered:
        if seg["start_page"] > seg["end_page"]:
            raise ValueError("start_page must be <= end_page")


def build_segmentation_json(source_pdf_name: str, segments: list[dict]) -> dict:
    return {
        "source_pdf": source_pdf_name,
        "created": datetime.now(timezone.utc).isoformat(),
        "segments": segments,
    }


def save_segmentation(pdf_path: Path, segments: list[dict], page_count: int) -> dict:
    validate_segments(segments, page_count)
    doc = build_segmentation_json(pdf_path.name, segments)
    out_path = segmentation_path_for(pdf_path)
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return doc


def load_segmentation(pdf_path: Path) -> dict:
    out_path = segmentation_path_for(pdf_path)
    if not out_path.is_file():
        raise FileNotFoundError(out_path)
    return json.loads(out_path.read_text(encoding="utf-8"))


def latest_metadata_path_for(pdf_path: Path) -> Path | None:
    """The most recently written v2 metadata sidecar for this PDF.

    extract_metadata_v2.py tags each run by prompt+model
    (`<stem>.metadata.v2.<tag>.json`), so several runs can exist side by
    side for comparison (see compare_metadata.py/eval_metadata.py) - this
    picks whichever was extracted last, skipping the `.bak-*` copies that
    get created when a run overwrites an earlier one with the same tag.
    """
    candidates = [p for p in pdf_path.parent.glob(f"{pdf_path.stem}.metadata.v2.*.json")
                  if ".bak-" not in p.name]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def load_boundary_candidates(pdf_path: Path, tsv_path: Path) -> list[dict]:
    """Verdachtsfälle aus segmentgrenzen.tsv für den Band dieses PDFs (der
    Bandordner heißt wie die Spalte `band`, z. B. "Nr. 002 (1968)").

    `seiten` ist entweder ein Übergang "81|82" (Schnitt nach S. 81 fehlt bzw.
    ist überflüssig) oder ein Bereich "14-23" (Hinweis auf das ganze Segment).
    """
    if not tsv_path.is_file():
        return []
    band = pdf_path.parent.name
    items = []
    with open(tsv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["band"] != band:
                continue
            seiten = row["seiten"]
            if "|" in seiten:
                after, _ = (int(x) for x in seiten.split("|"))
                kind, first, last = "boundary", after, after + 1
            else:
                first, last = (int(x) for x in seiten.split("-"))
                kind, after = "segment", None
            items.append({
                "key": f"{row['art']}:{seiten}",
                "kind": kind, "after_page": after, "first_page": first, "last_page": last,
                "seiten": seiten, "art": row["art"], "stufe": row["stufe"],
                "staerke": float(row["stärke"] or 0), "signale": row["signale"],
                "beleg": row["beleg"], "bekannt": bool(row.get("bekannt")),
            })
    return sorted(items, key=lambda i: (i["first_page"], i["key"]))


def review_path_for(pdf_path: Path) -> Path:
    return pdf_path.with_name(pdf_path.stem + ".boundary_review.json")


def load_review(pdf_path: Path) -> dict:
    """Entscheidungen zur Prüfliste: {key: {"decision": ..., "at": ...}}."""
    path = review_path_for(pdf_path)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("decisions", {})


REVIEW_DECISIONS = {"übernommen", "abgelehnt", "unklar", ""}


def save_review_decision(pdf_path: Path, key: str, decision: str) -> dict:
    """Eine Entscheidung setzen ("" nimmt sie zurück). Die Datei ist zugleich
    ein geprüfter Datensatz, an dem sich check_boundaries.py messen lässt."""
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"unknown decision: {decision}")
    decisions = load_review(pdf_path)
    if decision:
        decisions[key] = {"decision": decision, "at": datetime.now(timezone.utc).isoformat()}
    else:
        decisions.pop(key, None)
    doc = {"source_pdf": pdf_path.name, "decisions": decisions}
    review_path_for(pdf_path).write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    return decisions


def load_metadata(pdf_path: Path) -> dict:
    """The latest v2 sidecar written by pipelines/04_metadata/extract_metadata_v2.py."""
    out_path = latest_metadata_path_for(pdf_path)
    if out_path is None:
        raise FileNotFoundError(pdf_path)
    return json.loads(out_path.read_text(encoding="utf-8"))
