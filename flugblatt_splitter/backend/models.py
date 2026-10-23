"""Pydantic request/response schemas for the splitter API."""

from __future__ import annotations

from pydantic import BaseModel


class Segment(BaseModel):
    id: int
    title: str
    date: str = ""
    start_page: int
    end_page: int
    confirmed: bool
    no_content: bool = False  # e.g. divider page, blank (incl. blank back side), cover - nothing to extract
    note: str = ""  # free-text flag for a problem, e.g. "Seite fehlt"


class SaveSegmentationRequest(BaseModel):
    pdf: str
    segments: list[Segment]


class ReviewDecisionRequest(BaseModel):
    pdf: str
    key: str        # "<art>:<seiten>", wie von /api/boundaries geliefert
    decision: str   # "übernommen" | "abgelehnt" | "unklar" | "" (zurücknehmen)
