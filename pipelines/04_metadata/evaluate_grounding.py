#!/usr/bin/env python3
"""Re-check the evidence of existing metadata runs with the current rules.

Read-only. For every title, date and issuer with a value it reports how the
evidence holds up; record rates are given with and without incipits lacking
evidence (required by the prompt up to round 9).

    python evaluate_grounding.py "../../data/raw/Nr. 002 (1968)/0118_0002.metadata.claude-r9.json" ...
    python evaluate_grounding.py --all
"""

import argparse
import collections
import json
from pathlib import Path

from extract_metadata_v2 import guess_year, load_page_blocks, segment_texts
from prompt_v2 import check_grounding, evidence_fields, evidence_status, _norm

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
KINDS = ["exakt", "unscharf", "Incipit ohne Beleg", "ohne Beleg", "ohne Block",
         "Block unbekannt", "anderer Block", "nicht im Text"]


def evaluate(meta_path):
    doc = json.loads(meta_path.read_text(encoding="utf-8"))
    stem = doc["source_pdf"].removesuffix(".pdf")
    page_blocks = load_page_blocks(meta_path.parent / stem / f"{stem}.json")
    year = guess_year(meta_path.with_name(doc["source_pdf"]))
    kinds = collections.Counter()
    clean = clean_but_incipit = 0
    records = [r for r in doc["segments"] if not r.get("no_content")]
    for r in records:
        _, text, blocks = segment_texts(page_blocks, r["start_page"], r["end_page"])
        for label, value, quote, ids in evidence_fields(r):
            if not (value or "").strip():
                continue
            if not _norm(quote):
                incipit = label == "title" and r.get("title_type") == "incipit"
                kinds["Incipit ohne Beleg" if incipit else "ohne Beleg"] += 1
            else:
                kinds[evidence_status(quote, ids, blocks, text)] += 1
        problems = check_grounding(r, text, collection_year=year, blocks=blocks)
        clean += not problems
        clean_but_incipit += all(p == "title: Incipit ohne Beleg" for p in problems)
    return {"records": len(records), "old_rate": (doc.get("grounding") or {}).get("rate_percent"),
            "clean": clean, "clean_but_incipit": clean_but_incipit, "kinds": kinds}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("files", nargs="*", type=Path)
    p.add_argument("--all", action="store_true", help="all runs under data/raw")
    args = p.parse_args()
    files = args.files or []
    if args.all:
        files += sorted(f for f in RAW.glob("*/*.metadata.*.json") if ".partial" not in f.name)

    print("Datei | Records | alte Quote | neue Quote | ohne Incipit-Fälle | "
          + " | ".join(KINDS))
    for f in files:
        try:
            res = evaluate(f)
        except (FileNotFoundError, KeyError) as e:
            print(f"{f.name} | übersprungen: {e}")
            continue
        n = res["records"] or 1
        print(f"{f.parent.name}/{f.name} | {res['records']} | {res['old_rate']} % | "
              f"{100 * res['clean'] / n:.1f} % | {100 * res['clean_but_incipit'] / n:.1f} % | "
              + " | ".join(str(res["kinds"][k]) for k in KINDS))


if __name__ == "__main__":
    main()
