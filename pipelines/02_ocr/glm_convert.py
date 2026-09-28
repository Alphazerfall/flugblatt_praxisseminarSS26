#!/usr/bin/env python3
# AI disclosure: This script was written with AI assistance (Claude Code / Anthropic)
# and reviewed and tested by the author before use.

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

from pypdf import PdfReader, PdfWriter


# ---------- Constants ----------
DEFAULT_OCR_HOST = "127.0.0.1"
DEFAULT_OCR_PORT = 8080
DEFAULT_MODEL = "glm-ocr"

# Ollama serves on a different port than the vLLM/SGLang convention this
# script otherwise defaults to, and needs its native /api/generate endpoint
# for vision requests - the OpenAI-compatible shim (glmocr's default
# api_mode) is known to 502 on image input. --ollama switches all of these
# at once; see README.md for the full setup (ollama pull glm-ocr, etc).
OLLAMA_PORT = 11434
OLLAMA_MODEL = "glm-ocr:latest"

# The SDK's default max_workers=32 fires that many concurrent region-OCR
# requests at the OCR server. That's fine against a real GPU server, but a
# single CPU-bound Ollama instance can only actually work on ~1 at a time -
# 32 at once means every request queues behind the others, all blow past
# request_timeout together, and all retry together (a stampede that may
# never converge). Serialize to 1 and give each call more time to finish.
OLLAMA_MAX_WORKERS = 1
OLLAMA_REQUEST_TIMEOUT = 300

# GLM-OCR's stock pipeline config discards headers, footers, footnotes, page
# numbers and references outright (label_task_mapping: "abandon" - no bbox,
# no content, not even a block). Every other engine in this pipeline keeps
# that page furniture as its own typed block, so route these through the
# "text" OCR task instead of dropping them, to keep results comparable.
LABEL_TASK_MAPPING = {
    "text": [
        "abstract", "algorithm", "content", "doc_title", "figure_title",
        "paragraph_title", "reference_content", "text", "vertical_text",
        "vision_footnote", "seal", "formula_number",
        "header", "footer", "footnote", "number", "reference",
    ],
    "table": ["table"],
    "formula": ["display_formula", "inline_formula"],
    "skip": ["chart", "image", "header_image", "footer_image"],
}


# ---------- Helpers ----------
def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def fmt_elapsed(seconds):
    return str(timedelta(seconds=round(seconds)))


def parse_page_list(page_range, n_pages):
    if not page_range:
        return list(range(n_pages))
    pages = set()
    for part in page_range.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-")
            pages.update(range(int(start), int(end) + 1))
        else:
            pages.add(int(part))
    return sorted(p for p in pages if p < n_pages)


def extract_pages(pdf_path, page_range, tmp_dir):
    reader = PdfReader(pdf_path)
    pages = parse_page_list(page_range, len(reader.pages))
    if pages == list(range(len(reader.pages))):
        return pdf_path
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p])
    sub_path = os.path.join(tmp_dir, "subset.pdf")
    with open(sub_path, "wb") as f:
        writer.write(f)
    return sub_path


def default_output_path(pdf_path):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    return os.path.join(os.path.dirname(pdf_path), "jsonGLM", stem + ".json")


def save_output(pages, out_path, model):
    content = json.dumps({"model": model, "pages": pages}, ensure_ascii=False, indent=2)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------- Convert ----------
def convert(pdf_path, model, out_path, page_range, ocr_host, ocr_port, layout_device, ollama,
            max_workers, request_timeout):
    if not os.path.isfile(pdf_path):
        sys.exit(f"File not found: {pdf_path}")

    from glmocr import GlmOcr  # deferred: pulls in torch/transformers

    if ollama:
        ocr_port = ocr_port or OLLAMA_PORT
        model = model or OLLAMA_MODEL
        max_workers = max_workers or OLLAMA_MAX_WORKERS
        request_timeout = request_timeout or OLLAMA_REQUEST_TIMEOUT
    else:
        ocr_port = ocr_port or DEFAULT_OCR_PORT
        model = model or DEFAULT_MODEL

    dotted = {"pipeline.layout.label_task_mapping": LABEL_TASK_MAPPING}
    if ollama:
        dotted["pipeline.ocr_api.api_mode"] = "ollama_generate"
        dotted["pipeline.ocr_api.api_path"] = "/api/generate"
    if max_workers:
        dotted["pipeline.max_workers"] = max_workers
    if request_timeout:
        dotted["pipeline.ocr_api.request_timeout"] = request_timeout

    if not out_path:
        out_path = default_output_path(pdf_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    run_start = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="glm_convert_") as tmp_dir:
        upload_path = extract_pages(pdf_path, page_range, tmp_dir)

        log(f"Starting GLM-OCR pipeline (ocr_api={ocr_host}:{ocr_port}, model={model}, "
            f"layout_device={layout_device or 'auto'}, max_workers={max_workers or 'default'}) ...")
        with GlmOcr(
            mode="selfhosted",
            model=model,
            ocr_api_host=ocr_host,
            ocr_api_port=ocr_port,
            layout_device=layout_device,
            _dotted=dotted,
        ) as parser:
            log(f"Parsing {os.path.basename(upload_path)} (this loads PP-DocLayout-V3 "
                f"on first run) ...")
            result = parser.parse(upload_path, save_layout_visualization=False)

    # bbox_2d is normalized 0-1000 independently per axis (PP-DocLayout-V3's
    # own convention), so dimensions:1000x1000 is exact regardless of the
    # page's real pixel size - no separate page render needed to know it.
    # bbox_2d kept under its native GLM-OCR SDK key name (not Gemini's
    # box_2d) - besides being more faithful, it also keeps ocr_viewer's
    # adapters distinguishable: the two use different axis orders
    # ([x1,y1,x2,y2] here vs. Gemini's [ymin,xmin,ymax,xmax]), so they must
    # never be picked up by the same adapter.
    pages = []
    for page_idx, regions in enumerate(result.json_result or []):
        blocks = [
            {
                "type": r.get("native_label") or r.get("label") or "text",
                "bbox_2d": r.get("bbox_2d") or [0, 0, 0, 0],
                "content": r.get("content") or "",
            }
            for r in regions
        ]
        pages.append({"page": page_idx, "dimensions": {"width": 1000, "height": 1000}, "blocks": blocks})

    save_output(pages, out_path, model)
    log(f"Done in {fmt_elapsed(time.monotonic() - run_start)}. {len(pages)} pages.")
    log(f"Saved: {out_path}")


# ---------- CLI ----------
def parse_args():
    p = argparse.ArgumentParser(
        description="Convert a PDF with a self-hosted GLM-OCR server, via the glmocr SDK's "
                     "PP-DocLayout-V3 pipeline - positioned layout blocks with boxes, not just markdown text."
    )
    p.add_argument("pdf", help="path to the input PDF")
    p.add_argument("-m", "--model", default=None, metavar="MODEL",
                   help=f"model name as registered on the OCR server (default: {DEFAULT_MODEL}, "
                        f"or {OLLAMA_MODEL} with --ollama)")
    p.add_argument("-o", "--output", metavar="OUT",
                   help="output path (default: alongside the PDF, jsonGLM/<stem>.json)")
    p.add_argument("--page-range", metavar="RANGE",
                   help='specific 0-indexed pages to convert, e.g. "0-5,10"')
    p.add_argument("--ocr-host", default=DEFAULT_OCR_HOST, metavar="HOST",
                   help=f"host of the self-hosted GLM-OCR model server (default: {DEFAULT_OCR_HOST})")
    p.add_argument("--ocr-port", type=int, default=None, metavar="PORT",
                   help=f"port of the self-hosted GLM-OCR model server "
                        f"(default: {DEFAULT_OCR_PORT}, or {OLLAMA_PORT} with --ollama)")
    p.add_argument("--ollama", action="store_true",
                   help=f"talk to a local Ollama server instead of vLLM/SGLang: switches the "
                        f"port to {OLLAMA_PORT}, the model to {OLLAMA_MODEL}, and the API mode to "
                        f"Ollama's native /api/generate (the OpenAI-compatible endpoint is known "
                        f"to fail on vision requests) - see README.md for the `ollama pull` setup")
    p.add_argument("--layout-device", default=None, metavar="DEVICE",
                   help='device for the local PP-DocLayout-V3 layout model: "cpu", "cuda", '
                        'or "cuda:N" (default: auto - CUDA if available, else CPU)')
    p.add_argument("--max-workers", type=int, default=None, metavar="N",
                   help=f"concurrent region-OCR requests to the server (SDK default: 32, fine "
                        f"for a real GPU server; forced to {OLLAMA_MAX_WORKERS} with --ollama since "
                        f"a single CPU-bound instance can't usefully parallelize)")
    p.add_argument("--request-timeout", type=int, default=None, metavar="SECONDS",
                   help=f"per-request timeout to the OCR server (SDK default: 120; forced to "
                        f"{OLLAMA_REQUEST_TIMEOUT} with --ollama, since a single CPU-bound region "
                        f"call can legitimately take longer)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert(args.pdf, args.model, args.output, args.page_range,
            args.ocr_host, args.ocr_port, args.layout_device, args.ollama,
            args.max_workers, args.request_timeout)
