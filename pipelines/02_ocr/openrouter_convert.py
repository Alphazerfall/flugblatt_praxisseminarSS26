#!/usr/bin/env python3
# AI disclosure: This script was written with AI assistance (Claude Code / Anthropic)
# and reviewed and tested by the author before use.

import argparse
import base64
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

import fitz  # PyMuPDF
from dotenv import load_dotenv
from openai import OpenAI


# ---------- Constants ----------
BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_DPI = 200
DEFAULT_PROMPT = (
    "Convert this page to markdown. Preserve reading order and structure, "
    "and represent any tables as markdown tables."
)


# ---------- Helpers ----------
def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def fmt_elapsed(seconds):
    return str(timedelta(seconds=round(seconds)))


def get_client():
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("Set OPENROUTER_API_KEY in your environment or in a local .env file.")
    return OpenAI(base_url=BASE_URL, api_key=api_key)


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


def render_pages(pdf_path, page_range, dpi, tmp_dir):
    doc = fitz.open(pdf_path)
    pages = parse_page_list(page_range, doc.page_count)
    paths = []
    for p in pages:
        pix = doc[p].get_pixmap(dpi=dpi)
        img_path = os.path.join(tmp_dir, f"page_{p + 1:03d}.png")
        pix.save(img_path)
        paths.append((p, img_path))
    return paths


def default_output_path(pdf_path, fmt):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    subdir, ext = ("jsonOpenRouter", ".json") if fmt == "json" else ("markdownOpenRouter", ".md")
    return os.path.join(os.path.dirname(pdf_path), subdir, stem + ext)


def ocr_page(client, model, prompt, img_path):
    with open(img_path, "rb") as f:
        b64_image = base64.b64encode(f.read()).decode("utf-8")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}},
                ],
            }
        ],
    )
    return response.choices[0].message.content


def save_output(results, fmt, out_path, model):
    if fmt == "markdown":
        content = "\n\n---\n\n".join(r["text"] for r in results)
    else:
        content = json.dumps({"model": model, "pages": results}, ensure_ascii=False, indent=2)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------- Convert ----------
def convert(pdf_path, model, fmt, out_path, page_range, dpi, prompt):
    if not os.path.isfile(pdf_path):
        sys.exit(f"File not found: {pdf_path}")

    client = get_client()
    if not out_path:
        out_path = default_output_path(pdf_path, fmt)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    run_start = time.monotonic()
    results = []
    with tempfile.TemporaryDirectory(prefix="openrouter_convert_") as tmp_dir:
        log("Rendering pages ...")
        pages = render_pages(pdf_path, page_range, dpi, tmp_dir)
        log(f"{len(pages)} pages to process.")

        for i, (page_index, img_path) in enumerate(pages, 1):
            log(f"Verarbeite Seite {i}/{len(pages)} (page {page_index}) ...")
            text = ocr_page(client, model, prompt, img_path)
            results.append({"page": page_index, "text": text})

    save_output(results, fmt, out_path, model)
    log(f"Done in {fmt_elapsed(time.monotonic() - run_start)}. {len(results)} pages.")
    log(f"Saved: {out_path}")


# ---------- CLI ----------
def parse_args():
    p = argparse.ArgumentParser(description="Convert a PDF with a model via OpenRouter.")
    p.add_argument("pdf", help="path to the input PDF")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL, metavar="MODEL",
                   help=f"OpenRouter model slug (default: {DEFAULT_MODEL})")
    p.add_argument("-f", "--format", choices=["json", "markdown"], default="json",
                   metavar="FMT", help="output format: json, markdown (default: json)")
    p.add_argument("-o", "--output", metavar="OUT",
                   help="output path (default: alongside the PDF)")
    p.add_argument("--page-range", metavar="RANGE",
                   help='specific 0-indexed pages to convert, e.g. "0-5,10"')
    p.add_argument("--dpi", type=int, default=DEFAULT_DPI, metavar="N",
                   help=f"render DPI for page images (default: {DEFAULT_DPI})")
    p.add_argument("--prompt", default=DEFAULT_PROMPT, metavar="TEXT",
                   help="override the extraction prompt")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert(args.pdf, args.model, args.format, args.output,
            args.page_range, args.dpi, args.prompt)
