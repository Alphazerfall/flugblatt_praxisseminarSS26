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


class SaveSegmentationRequest(BaseModel):
    pdf: str
    segments: list[Segment]
