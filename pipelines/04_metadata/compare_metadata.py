#!/usr/bin/env python3
"""Zwei Metadaten-Läufe nebeneinanderlegen: Abdeckung, Übereinstimmung, Unterschiede.

Versteht beide Sidecar-Formate (v1: `issuing_org` als String, `date_iso` immer
tagesgenau; v2: `issuers` als Liste, unscharfe Daten, Belegzitate) und bringt sie
auf eine gemeinsame Form, damit sie vergleichbar sind.

Beispiele:
    # nur einen Lauf beschreiben
    python pipelines/04_metadata/compare_metadata.py "data/raw/Nr. 002 (1968)/0118_0002.metadata.v2.json"

    # zwei Läufe vergleichen
    python pipelines/04_metadata/compare_metadata.py \\
        "data/raw/Nr. 002 (1968)/0118_0002.metadata.v1.json" \\
        "data/raw/Nr. 002 (1968)/0118_0002.metadata.v2.json" --diffs 15
"""

from __future__ import annotations

import argparse
import collections
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_WS = re.compile(r"\s+")


def norm(s):
    return _WS.sub(" ", unicodedata.normalize("NFC", s or "")).strip().lower()


def similar(a, b):
    a, b = norm(a), norm(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


ACRONYM = re.compile(r"\b([A-ZÄÖÜ]{2,6})\b")


def org_keys(name):
    """Vergleichsschlüssel einer Organisationsschreibweise: die normalisierte
    Form und jedes enthaltene Akronym. Damit gelten 'LSD' und 'Liberaler
    Studentenbund (LSD)' als dieselbe Gruppe - dieselbe Blockbildung, die auch
    die spätere Kanonisierung benutzt."""
    keys = {norm(name)}
    keys |= {a.lower() for a in ACRONYM.findall(name or "")}
    return {k for k in keys if k}


def load(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    records = {}
    for seg in doc["segments"]:
        orgs = seg.get("issuers")
        if orgs is None:
            raw = seg.get("issuing_org") or ""
            orgs = [raw] if raw else []
        else:
            orgs = [o.get("surface", "") for o in orgs if o.get("surface")]
        records[seg["id"]] = {
            "id": seg["id"],
            "pages": (seg.get("start_page"), seg.get("end_page")),
            "title": seg.get("title") or "",
            "title_type": seg.get("title_type", ""),
            "orgs": orgs,
            "date_iso": seg.get("date_iso") or "",
            "date_text": seg.get("date_text") or "",
            "date_type": seg.get("date_type", ""),
            "doc_type": seg.get("doc_type", ""),
            "grounding": seg.get("_grounding") or [],
        }
    return doc, records


def precision_of(iso):
    if not iso:
        return "kein Datum"
    return {4: "Jahr", 7: "Monat", 10: "Tag"}.get(len(iso), "unklar")


def describe(name, doc, recs):
    n = len(recs)
    print(f"\n=== {name} ===")
    print(f"  Datei-Metadaten: Modell {doc.get('model', '?')}, Prompt {doc.get('prompt_version', 'v1?')}, "
          f"{n} Segmente")
    g = doc.get("grounding")
    if g:
        print(f"  Belegprüfung:    {g['checked'] - g['flagged']}/{g['checked']} ohne Beanstandung "
              f"({g['rate_percent']} %)")
    filled = lambda key: sum(1 for r in recs.values() if r[key])
    print(f"  Titel gefüllt:   {filled('title'):>4}/{n}")
    print(f"  Organisation:    {sum(1 for r in recs.values() if r['orgs']):>4}/{n}"
          f"   (mehrere Herausgeber: {sum(1 for r in recs.values() if len(r['orgs']) > 1)})")
    print(f"  Datum gefüllt:   {filled('date_iso'):>4}/{n}")
    prec = collections.Counter(precision_of(r["date_iso"]) for r in recs.values())
    print("  Datumsschärfe:   " + ", ".join(f"{k}: {v}" for k, v in prec.most_common()))
    for key, label in (("date_type", "Datumstyp"), ("title_type", "Titeltyp"), ("doc_type", "Textsorte")):
        vals = collections.Counter(r[key] for r in recs.values() if r[key])
        if vals:
            print(f"  {label:<15}" + ", ".join(f"{k}: {v}" for k, v in vals.most_common()))
    if any(r["grounding"] for r in recs.values()):
        probs = collections.Counter(p.split(":")[0] for r in recs.values() for p in r["grounding"])
        print("  Beanstandungen:  " + ", ".join(f"{k}: {v}" for k, v in probs.most_common()))


def compare(a_recs, b_recs, n_diffs, title_threshold):
    ids = sorted(set(a_recs) & set(b_recs))
    only_a, only_b = set(a_recs) - set(b_recs), set(b_recs) - set(a_recs)
    print(f"\n=== Vergleich ({len(ids)} gemeinsame Segmente) ===")
    if only_a or only_b:
        print(f"  nur in A: {sorted(only_a)}   nur in B: {sorted(only_b)}")

    same_title = same_org = same_date = 0
    diffs = []
    for i in ids:
        a, b = a_recs[i], b_recs[i]
        t = similar(a["title"], b["title"]) >= title_threshold
        oa = set().union(*(org_keys(x) for x in a["orgs"])) if a["orgs"] else set()
        ob = set().union(*(org_keys(x) for x in b["orgs"])) if b["orgs"] else set()
        o = bool(oa & ob) or (not oa and not ob)
        d = a["date_iso"] == b["date_iso"]
        same_title += t
        same_org += o
        same_date += d
        if not (t and o and d):
            diffs.append((i, a, b, t, o, d))

    n = len(ids) or 1
    print(f"  Titel gleich:        {same_title:>4}/{n}  ({100*same_title/n:.0f} %)")
    print(f"  Organisation überlappt {same_org:>4}/{n}  ({100*same_org/n:.0f} %)")
    print(f"  Datum identisch:     {same_date:>4}/{n}  ({100*same_date/n:.0f} %)")

    if diffs:
        print(f"\n  Erste {min(n_diffs, len(diffs))} von {len(diffs)} abweichenden Segmenten:")
        for i, a, b, t, o, d in diffs[:n_diffs]:
            print(f"\n  Segment {i} (S. {a['pages'][0]}-{a['pages'][1]})")
            if not t:
                print(f"    Titel A: {a['title'][:88]}")
                print(f"    Titel B: {b['title'][:88]}")
            if not o:
                print(f"    Org   A: {a['orgs']}")
                print(f"    Org   B: {b['orgs']}")
            if not d:
                print(f"    Datum A: {a['date_iso'] or '-':<12} ({precision_of(a['date_iso'])})"
                      f"   B: {b['date_iso'] or '-':<12} ({precision_of(b['date_iso'])}"
                      + (f", {b['date_type']}" if b["date_type"] else "") + ")")
            if b["grounding"]:
                print(f"    Beleg B: {'; '.join(b['grounding'])}")


def parse_args():
    p = argparse.ArgumentParser(description="Metadaten-Läufe beschreiben und vergleichen.")
    p.add_argument("a", help="erste metadata.json")
    p.add_argument("b", nargs="?", help="zweite metadata.json (optional)")
    p.add_argument("--diffs", type=int, default=10, help="wie viele abweichende Segmente zeigen")
    p.add_argument("--title-threshold", type=float, default=0.9,
                   help="ab welcher Ähnlichkeit zwei Titel als gleich gelten (Standard 0.9)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    doc_a, recs_a = load(args.a)
    describe(Path(args.a).name, doc_a, recs_a)
    if args.b:
        doc_b, recs_b = load(args.b)
        describe(Path(args.b).name, doc_b, recs_b)
        compare(recs_a, recs_b, args.diffs, args.title_threshold)
