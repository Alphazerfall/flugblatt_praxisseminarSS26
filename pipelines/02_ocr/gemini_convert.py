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
from google import genai
from pypdf import PdfReader, PdfWriter


# ---------- Constants ----------
DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_DPI = 200
DEFAULT_PROMPT = (
    "Convert this document to markdown. Preserve reading order and structure, "
    "and represent any tables as markdown tables."
)
PAGE_BREAK_INSTRUCTION = ' Insert "\\n\\n---\\n\\n" between each original page of the document.'

BLOCKS_PROMPT = (
    "Detect all layout elements on this page (headings, paragraphs, tables, images, "
    "captions, lists, headers, footers) in reading order. For each element, return its "
    "type, its bounding box as box_2d: [ymin, xmin, ymax, xmax] normalized to 0-1000, "
    "and its content as text (render tables as markdown tables within content)."
)
BLOCKS_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "box_2d": {"type": "array", "items": {"type": "integer"}},
                    "content": {"type": "string"},
                },
                "required": ["type", "box_2d", "content"],
            },
        }
    },
    "required": ["blocks"],
}


# ---------- Helpers ----------
def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def fmt_elapsed(seconds):
    return str(timedelta(seconds=round(seconds)))


def check_api_key():
    load_dotenv()
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        sys.exit("Set GEMINI_API_KEY (or GOOGLE_API_KEY) in your environment or in a local .env file.")


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
    return sorted(pages)


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


def render_pages(pdf_path, page_range, dpi, tmp_dir):
    doc = fitz.open(pdf_path)
    pages = parse_page_list(page_range, doc.page_count)
    rendered = []
    for p in pages:
        pix = doc[p].get_pixmap(dpi=dpi)
        img_path = os.path.join(tmp_dir, f"page_{p + 1:03d}.png")
        pix.save(img_path)
        rendered.append({"page": p, "path": img_path, "width": pix.width, "height": pix.height})
    return rendered


def default_output_path(pdf_path, fmt):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    subdir, ext = ("jsonGemini", ".json") if fmt == "json" else ("markdownGemini", ".md")
    return os.path.join(os.path.dirname(pdf_path), subdir, stem + ext)


def save_output(text, fmt, out_path, model):
    if fmt == "json":
        content = json.dumps({"model": model, "text": text}, ensure_ascii=False, indent=2)
    else:
        content = text
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)


def ocr_page_blocks(client, model, img_path):
    with open(img_path, "rb") as f:
        b64_image = base64.b64encode(f.read()).decode("utf-8")

    interaction = client.interactions.create(
        model=model,
        input=[
            {"type": "image", "data": b64_image, "mime_type": "image/png"},
            {"type": "text", "text": BLOCKS_PROMPT},
        ],
        response_format={"type": "text", "mime_type": "application/json", "schema": BLOCKS_SCHEMA},
    )
    return json.loads(interaction.output_text).get("blocks", [])


def save_blocks_output(pages, out_path, model):
    content = json.dumps({"model": model, "pages": pages}, ensure_ascii=False, indent=2)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------- Convert ----------
def convert_blocks(pdf_path, model, out_path, page_range, dpi):
    client = genai.Client()
    run_start = time.monotonic()
    pages = []

    with tempfile.TemporaryDirectory(prefix="gemini_convert_") as tmp_dir:
        log("Rendering pages ...")
        rendered = render_pages(pdf_path, page_range, dpi, tmp_dir)
        log(f"{len(rendered)} pages to process.")

        for i, page in enumerate(rendered, 1):
            log(f"Verarbeite Seite {i}/{len(rendered)} (page {page['page']}) ...")
            blocks = ocr_page_blocks(client, model, page["path"])
            pages.append({
                "page": page["page"],
                "dimensions": {"width": page["width"], "height": page["height"]},
                "blocks": blocks,
            })

    save_blocks_output(pages, out_path, model)
    log(f"Done in {fmt_elapsed(time.monotonic() - run_start)}. {len(pages)} pages.")
    log(f"Saved: {out_path}")


def convert(pdf_path, model, fmt, out_path, page_range, paginate, prompt, blocks, dpi):
    if not os.path.isfile(pdf_path):
        sys.exit(f"File not found: {pdf_path}")

    check_api_key()
    if not out_path:
        out_path = default_output_path(pdf_path, "json" if blocks else fmt)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if blocks:
        convert_blocks(pdf_path, model, out_path, page_range, dpi)
        return

    full_prompt = prompt + (PAGE_BREAK_INSTRUCTION if paginate else "")

    client = genai.Client()
    run_start = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="gemini_convert_") as tmp_dir:
        upload_path = extract_pages(pdf_path, page_range, tmp_dir)
        log(f"Uploading {os.path.basename(upload_path)} ...")
        uploaded = client.files.upload(file=upload_path)

        log(f"Running OCR (model={model}) ...")
        interaction = client.interactions.create(
            model=model,
            input=[
                {"type": "document", "uri": uploaded.uri, "mime_type": uploaded.mime_type},
                {"type": "text", "text": full_prompt},
            ],
        )

    text = interaction.output_text
    save_output(text, fmt, out_path, model)
    log(f"Done in {fmt_elapsed(time.monotonic() - run_start)}.")
    log(f"Saved: {out_path}")


# ---------- CLI ----------
def parse_args():
    p = argparse.ArgumentParser(description="Convert a PDF with the Gemini API.")
    p.add_argument("pdf", help="path to the input PDF")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL, metavar="MODEL",
                   help=f"Gemini model to use (default: {DEFAULT_MODEL})")
    p.add_argument("-f", "--format", choices=["json", "markdown"], default="markdown",
                   metavar="FMT", help="output format: json, markdown (default: markdown)")
    p.add_argument("-o", "--output", metavar="OUT",
                   help="output path (default: alongside the PDF)")
    p.add_argument("--page-range", metavar="RANGE",
                   help='specific 0-indexed pages to convert, e.g. "0-5,10"')
    p.add_argument("--paginate", action="store_true",
                   help="ask the model to mark original page breaks with a horizontal rule")
    p.add_argument("--prompt", default=DEFAULT_PROMPT, metavar="TEXT",
                   help="override the extraction prompt")
    p.add_argument("--blocks", action="store_true",
                   help="request positioned layout blocks (type/box_2d/content) per page instead of "
                        "markdown - renders pages to images locally, always saves as JSON, and "
                        "ignores --prompt/--paginate/--format")
    p.add_argument("--dpi", type=int, default=DEFAULT_DPI, metavar="N",
                   help=f"render DPI for page images, used with --blocks (default: {DEFAULT_DPI})")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert(args.pdf, args.model, args.format, args.output,
            args.page_range, args.paginate, args.prompt, args.blocks, args.dpi)
