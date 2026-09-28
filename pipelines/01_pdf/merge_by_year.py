#!/usr/bin/env python3

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import pikepdf


YEAR_RE = re.compile(r"\((\d{4})\)")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")

def year_of(folder):
    m = YEAR_RE.search(folder.name)
    return m.group(1) if m else None

def merge_year(year, pdfs, out_path):
    merged = pikepdf.Pdf.new()
    for pdf in pdfs:
        with pikepdf.open(pdf) as src:
            merged.pages.extend(src.pages)
    n = len(merged.pages)
    merged.save(out_path)
    merged.close()
    log(f"{year}: {len(pdfs)} file(s), {n} pages -> {out_path}")

def parse_args():
    ap = argparse.ArgumentParser(description="Merge the Rep. 118 flyer PDFs into one PDF per year.")
    ap.add_argument("src", nargs="+", help="folder containing the 'Nr. XXX (YYYY)' subfolders (quoting optional)")
    ap.add_argument("-o", "--out-dir", type=Path, help="output directory (default: <src>/by_year)")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    src = Path(" ".join(args.src))
    if not src.is_dir():
        sys.exit(f"Not a directory: {src}")
    out_dir = args.out_dir or src / "by_year"

    groups = {}
    for sub in sorted(p for p in src.iterdir() if p.is_dir()):
        year = year_of(sub)
        if not year:
            continue
        pdfs = sorted(sub.glob("*.pdf"))
        if not pdfs:
            log(f"  ! no PDF in {sub.name}")
            continue
        groups.setdefault(year, []).extend(pdfs)

    if not groups:
        sys.exit(f"No 'Nr. XXX (YYYY)' subfolders with PDFs in {src}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for year, pdfs in sorted(groups.items()):
        merge_year(year, pdfs, out_dir / f"{year}.pdf")
