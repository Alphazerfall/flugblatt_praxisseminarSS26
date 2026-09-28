"""FastAPI app for the Flugblatt Splitter.

Run from the repo root:
    uvicorn flugblatt_splitter.backend.main:app --reload --port 8010

/api/* routes are registered before the static frontend mount, since
Starlette matches routes in registration order and a Mount("/") added first
would shadow every /api/* route.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import pdf_service, segmentation
from .config import DATA_ROOT, ORGANIZATIONS_PATH, THUMBNAIL_DPI
from .models import SaveSegmentationRequest

app = FastAPI(title="Flugblatt Splitter")


def _resolve_pdf(rel: str) -> Path:
    data_root = DATA_ROOT.resolve()
    candidate = (data_root / rel).resolve()
    if data_root not in candidate.parents or candidate.suffix.lower() != ".pdf" or not candidate.is_file():
        raise HTTPException(404, f"pdf not found: {rel}")
    return candidate


@app.get("/api/pdfs")
def list_pdfs():
    pdfs = sorted(
        str(p.relative_to(DATA_ROOT)).replace("\\", "/") for p in DATA_ROOT.rglob("*.pdf")
    )
    return {"pdfs": pdfs}


@app.get("/api/document")
def get_document(pdf: str):
    p = _resolve_pdf(pdf)
    return {"pdf": pdf, "page_count": pdf_service.get_page_count(p)}


@app.get("/api/pages")
def get_pages(pdf: str):
    p = _resolve_pdf(pdf)
    return {"pages": pdf_service.extract_all_pages(p)}


@app.get("/api/thumbnail")
def get_thumbnail(pdf: str, page: int, dpi: int = THUMBNAIL_DPI):
    p = _resolve_pdf(pdf)
    n = pdf_service.get_page_count(p)
    if not (1 <= page <= n):
        raise HTTPException(404, f"page {page} out of range (1..{n})")
    png = pdf_service.render_thumbnail(p, page - 1, dpi=dpi)
    return Response(content=png, media_type="image/png")


@app.post("/api/segmentation/save")
def save_segmentation(req: SaveSegmentationRequest):
    p = _resolve_pdf(req.pdf)
    n = pdf_service.get_page_count(p)
    try:
        doc = segmentation.save_segmentation(p, [s.model_dump() for s in req.segments], n)
    except ValueError as e:
        raise HTTPException(400, str(e))
    saved_to = str(segmentation.segmentation_path_for(p).relative_to(DATA_ROOT)).replace("\\", "/")
    return {"saved_to": saved_to, **doc}


@app.get("/api/segmentation/load")
def load_segmentation_endpoint(pdf: str):
    p = _resolve_pdf(pdf)
    try:
        return segmentation.load_segmentation(p)
    except FileNotFoundError:
        raise HTTPException(404, "no saved segmentation for this pdf yet")


@app.get("/api/metadata/load")
def load_metadata_endpoint(pdf: str):
    p = _resolve_pdf(pdf)
    try:
        return segmentation.load_metadata(p)
    except FileNotFoundError:
        raise HTTPException(404, "no extracted metadata for this pdf yet")


@app.get("/api/organizations/load")
def load_organizations_endpoint():
    if not ORGANIZATIONS_PATH.is_file():
        raise HTTPException(404, "no organizations normdatei found")
    return json.loads(ORGANIZATIONS_PATH.read_text(encoding="utf-8"))


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
