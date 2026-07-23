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
