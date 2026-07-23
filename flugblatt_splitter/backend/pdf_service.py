"""PDF loading and thumbnail rendering (PyMuPDF-backed).

Open documents are cached in-memory keyed by (path, mtime), so repeated
thumbnail requests for the same PDF (as the frontend loads ~100 pages) don't
reopen and reparse it every time. Dropping a fresh PDF under the same
filename changes its mtime and transparently invalidates the cache entry.
"""

from __future__ import annotations

import threading
from pathlib import Path

import fitz  # PyMuPDF

from .config import THUMBNAIL_DPI

_cache_lock = threading.Lock()
_doc_cache: dict[str, tuple[float, fitz.Document]] = {}


def get_document(pdf_path: Path) -> fitz.Document:
    key = str(pdf_path)
    mtime = pdf_path.stat().st_mtime
    with _cache_lock:
        cached = _doc_cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        doc = fitz.open(pdf_path)
        _doc_cache[key] = (mtime, doc)
        return doc


def get_page_count(pdf_path: Path) -> int:
    return get_document(pdf_path).page_count


def render_thumbnail(pdf_path: Path, page_index: int, dpi: int = THUMBNAIL_DPI) -> bytes:
    doc = get_document(pdf_path)
    page = doc[page_index]
    return page.get_pixmap(dpi=dpi).tobytes("png")


def extract_all_pages(pdf_path: Path) -> list[dict]:
    doc = get_document(pdf_path)
    pages = []
    for i in range(doc.page_count):
        rect = doc[i].rect
        pages.append({
            "page_number": i + 1,
            # Real page proportions, so the frontend can reserve the correct
            # thumbnail box height before the (lazy-loaded) image arrives —
            # without this, boxes start at 0 height and expand as images
            # load, shifting the layout out from under any in-flight
            # scroll-to-page.
            "width": rect.width,
            "height": rect.height,
        })
    return pages
