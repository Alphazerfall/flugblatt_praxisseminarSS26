#!/usr/bin/env python3
# AI disclosure: This script was written with AI assistance (Claude Code / Anthropic)
# and reviewed and tested by the author before use.

import argparse
import base64
import binascii
import json
import os
import sys
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from mistralai.client import Mistral


# ---------- Constants ----------
DEFAULT_MODEL = "mistral-ocr-latest"


# ---------- Helpers ----------
def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def fmt_elapsed(seconds):
    return str(timedelta(seconds=round(seconds)))


def get_api_key():
    load_dotenv()
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        sys.exit("Set MISTRAL_API_KEY in your environment or in a local .env file.")
    return api_key


def parse_page_list(page_range):
    if not page_range:
        return None
    pages = set()
    for part in page_range.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-")
            pages.update(range(int(start), int(end) + 1))
        else:
            pages.add(int(part))
    return sorted(pages)


def default_output_path(pdf_path, fmt):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    subdir, ext = ("jsonMistral", ".json") if fmt == "json" else ("markdownMistral", ".md")
    return os.path.join(os.path.dirname(pdf_path), subdir, stem + ext)


def save_images(pages, out_dir):
    n = 0
    for page in pages:
        for img in (page.images or []):
            b64 = img.image_base64 or ""
            if b64.startswith("data:") and "," in b64:
                b64 = b64.split(",", 1)[1]
            try:
                data = base64.b64decode(b64)
            except (binascii.Error, ValueError) as exc:
                log(f"  skipped image {img.id}: {exc}")
                continue
            with open(os.path.join(out_dir, img.id), "wb") as f:
                f.write(data)
            n += 1
    return n


def save_output(response, fmt, out_path):
    if fmt == "markdown":
        content = "\n\n---\n\n".join(page.markdown for page in response.pages)
    else:
        content = json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return save_images(response.pages, os.path.dirname(out_path))


# ---------- Convert ----------
def convert(pdf_path, model, fmt, out_path, page_range, table_format):
    if not os.path.isfile(pdf_path):
        sys.exit(f"File not found: {pdf_path}")

    if not out_path:
        out_path = default_output_path(pdf_path, fmt)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    client = Mistral(api_key=get_api_key())
    run_start = time.monotonic()

    log(f"Uploading {os.path.basename(pdf_path)} ...")
    with open(pdf_path, "rb") as f:
        uploaded = client.files.upload(
            file={"file_name": os.path.basename(pdf_path), "content": f},
            purpose="ocr",
        )

    try:
        signed_url = client.files.get_signed_url(file_id=uploaded.id).url

        log(f"Running OCR (model={model}) ...")
        pages = parse_page_list(page_range)
        kwargs = {"pages": pages} if pages else {}
        response = client.ocr.process(
            model=model,
            document={"type": "document_url", "document_url": signed_url},
            include_image_base64=True,
            include_blocks=True,
            table_format=table_format,
            **kwargs,
        )
    finally:
        try:
            client.files.delete(file_id=uploaded.id)
        except Exception as exc:
            log(f"  warning: could not delete uploaded file: {exc}")

    n_images = save_output(response, fmt, out_path)
    log(f"Done in {fmt_elapsed(time.monotonic() - run_start)}. "
        f"{len(response.pages)} pages, {n_images} images.")
    log(f"Saved: {out_path}")


# ---------- CLI ----------
def parse_args():
    p = argparse.ArgumentParser(description="Convert a PDF with the Mistral OCR API.")
    p.add_argument("pdf", help="path to the input PDF")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL, metavar="MODEL",
                   help=f"OCR model to use (default: {DEFAULT_MODEL})")
    p.add_argument("-f", "--format", choices=["json", "markdown"], default="json",
                   metavar="FMT", help="output format: json, markdown (default: json)")
    p.add_argument("-o", "--output", metavar="OUT",
                   help="output path (default: alongside the PDF)")
    p.add_argument("--page-range", metavar="RANGE",
                   help='specific 0-indexed pages to convert, e.g. "0-5,10"')
    p.add_argument("--table-format", choices=["markdown", "html"], default="markdown",
                   metavar="FMT", help="how tables are rendered in the markdown (default: markdown)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert(args.pdf, args.model, args.format, args.output, args.page_range, args.table_format)
