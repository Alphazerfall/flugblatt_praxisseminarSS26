#!/usr/bin/env python3

import argparse
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image
import img2pdf


QUALITY = 75
DPI = 400
TIFF_SUFFIXES = {".tif", ".tiff"}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")

def tiff_to_jpeg(tiff_path, jpeg_path, quality, dpi):
    with Image.open(tiff_path) as im:
        im.convert("RGB").save(jpeg_path, "JPEG", quality=quality, dpi=(dpi, dpi))

def build_pdf(src, out_path, quality, dpi, jpeg_dir):
    tiffs = sorted(p for p in src.iterdir() if p.suffix.lower() in TIFF_SUFFIXES)
    if not tiffs:
        sys.exit(f"No .tif/.tiff files in {src}")
    log(f"{len(tiffs)} TIFF(s) in {src.name} -> JPEG q{quality} @ {dpi} DPI")

    jpegs = []
    for i, tiff in enumerate(tiffs, 1):
        jpeg = jpeg_dir / (tiff.stem + ".jpg")
        tiff_to_jpeg(tiff, jpeg, quality, dpi)
        jpegs.append(str(jpeg))
        if i % 50 == 0 or i == len(tiffs):
            log(f"  converted {i}/{len(tiffs)}")

    with open(out_path, "wb") as f:
        f.write(img2pdf.convert(jpegs))

    size_mb = out_path.stat().st_size / 1e6
    log(f"Done. {len(jpegs)} pages, {size_mb:.1f} MB -> {out_path}")

def parse_args():
    ap = argparse.ArgumentParser(description="Merge a folder of TIFF scans into one PDF.")
    ap.add_argument("src", nargs="+", help="directory containing the TIFF scans (quoting optional)")
    ap.add_argument("-o", "--output", type=Path, help="output PDF (default: <dir-name>.pdf inside the folder)")
    ap.add_argument("-q", "--quality", type=int, default=QUALITY, help=f"JPEG quality (default: {QUALITY})")
    ap.add_argument("-d", "--dpi", type=int, default=DPI, help=f"DPI tag / page sizing (default: {DPI}; do not upscale)")
    ap.add_argument("--keep-jpeg", action="store_true", help="keep the intermediate JPEGs in a 'jpg' subfolder")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    src = Path(" ".join(args.src))  # rejoin tokens so unquoted paths with spaces work
    if not src.is_dir():
        sys.exit(f"Not a directory: {src}")
    out_path = args.output or src / f"{src.name}.pdf"

    if args.keep_jpeg:
        jpeg_dir = src / "jpg"
        jpeg_dir.mkdir(exist_ok=True)
        build_pdf(src, out_path, args.quality, args.dpi, jpeg_dir)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            build_pdf(src, out_path, args.quality, args.dpi, Path(tmp))
