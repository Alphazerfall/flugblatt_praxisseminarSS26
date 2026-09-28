#!/usr/bin/env python3
"""Metadaten-Läufe gegen den Archiv-Goldstandard messen und vergleichen.

Grundlage ist `docs/korpus/findmittel/abgleich.tsv` - die Zuordnung der im
Findmittel verzeichneten Blätter zu unseren Segmenten (erzeugt von
`pipelines/01_pdf/align_findmittel.py`). Für jedes Segment mit Archivtitel
lässt sich damit prüfen, ob unsere Extraktion Titel und Herausgeber trifft.

Gemessen wird je Lauf:

  Belegquote     Anteil der Records ohne Beanstandung der Belegprüfung.
                 Braucht keine Referenz und gilt deshalb für ALLE Segmente.
  Titel          unscharfer Vergleich mit dem Archivtitel (Token-Überlappung),
                 weil das Archiv normalisiert und kürzt - eine Prüfung auf
                 Gleichheit wäre unfair.
  Herausgeber    Überlappung der Namen inkl. Akronymen ("LSD" == "Liberaler
                 Studentenbund (LSD)").
  Datum          Verteilung der Genauigkeit und Anteil erfundener Tagesdaten
                 (date_iso tagesgenau, ohne Beleg im Text).
  Vollständigkeit leere Titel, leere Herausgeberlisten, fehlende Records.

Das Findmittel taugt für Precision, nicht für Recall: Es ist eine Auswahl
("u.a."). Ein Blatt, das dort fehlt, ist deshalb kein Fehler unserer Seite.

Aufruf:
    python pipelines/04_metadata/eval_metadata.py \\
        "data/raw/Nr. 002 (1968)/0118_0002.metadata.v2.google-gemini-2-5-flash.json" \\
        "data/raw/Nr. 002 (1968)/0118_0002.metadata.v2.qwen-qwen3-flash.json" \\
        --gold docs/korpus/findmittel/abgleich.tsv
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_WS = re.compile(r"\s+")
ACRONYM = re.compile(r"\b([A-ZÄÖÜ]{2,8})\b")
STOP = {"der", "die", "das", "und", "von", "vom", "des", "dem", "den", "ein", "eine",
        "für", "zur", "zum", "auf", "аn", "an", "im", "in", "mit", "über", "oder", "aus"}


def norm(text):
    return _WS.sub(" ", unicodedata.normalize("NFC", text or "")).strip().lower()


def content_tokens(text):
    return {w for w in re.findall(r"[^\W\d_]{3,}", norm(text)) if w not in STOP}


def title_overlap(ours, gold):
    """Anteil der Inhaltswörter des Archivtitels, die auch bei uns vorkommen."""
    g, o = content_tokens(gold), content_tokens(ours)
    if not g:
        return 1.0 if not o else 0.0
    return len(g & o) / len(g)


def load_orgs(path):
    """Normdatei -> {normalisierte Schreibweise: org_id}. Damit zaehlt
    "Ring christlich-demokratischer Studenten ... e.V." als Treffer fuer "RCDS"."""
    if not path or not Path(path).is_file():
        return {}
    table = {}
    for entry in json.loads(Path(path).read_text(encoding="utf-8")):
        oid = entry["org_id"]
        for form in [entry.get("name"), entry.get("full_name")] + list(entry.get("variants") or []):
            if form:
                table[norm(form)] = oid
    return table


def org_keys(name, orgs=None):
    if orgs:
        oid = orgs.get(norm(name))
        if oid:
            return {"#" + oid}                    # eindeutiger Schluessel aus der Normdatei
    keys = {norm(name)}
    keys |= {a.lower() for a in ACRONYM.findall(name or "")}
    keys |= {w for w in norm(name).split() if len(w) > 3}
    return {k for k in keys if k}


def load_run(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    records = {}
    for seg in doc["segments"]:
        issuers = seg.get("issuers")
        if issuers is None:
            raw = seg.get("issuing_org") or ""
            issuers = [{"surface": raw}] if raw else []
        records[seg["id"]] = {
            "title": seg.get("title") or "",
            "title_type": seg.get("title_type", ""),
            "series": seg.get("series", ""),
            "orgs": [i.get("surface", "") for i in issuers if i.get("surface")],
            "date_iso": seg.get("date_iso") or "",
            "date_evidence": seg.get("date_evidence", ""),
            "date_type": seg.get("date_type", ""),
            "grounding": seg.get("_grounding") or [],
        }
    label = doc.get("tag") or f"{doc.get('prompt_version', 'v?')}/{doc.get('model', '?')}"
    return label, doc, records


def load_gold(path, band):
    gold = collections.defaultdict(list)
    for row in csv.DictReader(Path(path).open(encoding="utf-8-sig"), delimiter="\t"):
        if row["band"] != band or row["status"] != "ok" or not row["segment_id"]:
            continue
        gold[int(row["segment_id"])].append(row)
    return gold


def precision_of(iso):
    return {4: "Jahr", 7: "Monat", 10: "Tag"}.get(len(iso or ""), "kein Datum")


def is_empty(r):
    """Record ohne jede Angabe - entsteht, wenn ein Batch scheitert. Solche
    Records haben naturgemaess keine Beanstandung und wuerden die Belegquote
    sonst auf 100 % treiben."""
    return not (r["title"] or r["orgs"] or r["date_iso"])


def evaluate(label, doc, records, gold, threshold, orgs=None):
    n = len(records)
    filled = [r for r in records.values() if not is_empty(r)]
    grounded = sum(1 for r in filled if not r["grounding"])
    stats = {
        "lauf": label,
        "modell": doc.get("model", "?"),
        "records": n,
        "leer": n - len(filled),
        "belegquote": 100 * grounded / len(filled) if filled else float("nan"),
        "titel_leer": sum(1 for r in records.values() if not r["title"]),
        "ohne_herausgeber": sum(1 for r in records.values() if not r["orgs"]),
        "series_gesetzt": sum(1 for r in records.values() if r["series"]),
    }

    dt = collections.Counter(r["date_type"] for r in records.values() if r["date_type"])
    stats["dt_issued"] = dt["issued"]
    stats["dt_event"] = dt["event"]
    stats["dt_mentioned"] = dt["mentioned"]
    prec = collections.Counter(precision_of(r["date_iso"]) for r in records.values())
    stats["datum_tag"] = prec["Tag"]
    stats["datum_monat"] = prec["Monat"]
    stats["datum_jahr"] = prec["Jahr"]
    stats["datum_fehlt"] = prec["kein Datum"]
    # Tagesgenaues Datum ohne Belegzitat ist der klassische Erfindungsfall
    stats["tag_ohne_beleg"] = sum(1 for r in records.values()
                                  if len(r["date_iso"]) == 10 and not r["date_evidence"])

    hits_t, hits_o, cmp_t, cmp_o, misses = 0, 0, 0, 0, []
    for seg_id, rows in gold.items():
        rec = records.get(seg_id)
        if rec is None:
            continue
        best_t = max(title_overlap(rec["title"], r["archiv_titel"]) for r in rows)
        cmp_t += 1
        hits_t += best_t >= threshold
        gold_orgs = {k for r in rows if r["archiv_herausgeber"]
                     for k in org_keys(r["archiv_herausgeber"], orgs)}
        if gold_orgs:
            ours = {k for o in rec["orgs"] for k in org_keys(o, orgs)}
            cmp_o += 1
            hit = bool(gold_orgs & ours)
            hits_o += hit
            if not hit:
                misses.append(("org", seg_id, rows[0]["archiv_herausgeber"], ", ".join(rec["orgs"]) or "-"))
        if best_t < threshold:
            misses.append(("titel", seg_id, rows[0]["archiv_titel"], rec["title"] or "-"))

    stats["titel_geprueft"] = cmp_t
    stats["titel_treffer"] = 100 * hits_t / cmp_t if cmp_t else float("nan")
    stats["org_geprueft"] = cmp_o
    stats["org_treffer"] = 100 * hits_o / cmp_o if cmp_o else float("nan")
    return stats, misses


def parse_args():
    p = argparse.ArgumentParser(description="Metadaten-Läufe gegen den Archiv-Goldstandard messen.")
    p.add_argument("runs", nargs="+", help="eine oder mehrere metadata.json")
    p.add_argument("--gold", type=Path, default=Path("docs/korpus/findmittel/abgleich.tsv"))
    p.add_argument("--band", default=None, help="Band-Stem (Standard: aus source_pdf abgeleitet)")
    p.add_argument("--threshold", type=float, default=0.6,
                   help="ab welcher Wortüberlappung ein Titel als Treffer gilt (Standard 0.6)")
    p.add_argument("--misses", type=int, default=8, help="wie viele Abweichungen je Lauf zeigen")
    p.add_argument("--orgs", type=Path, default=Path("docs/korpus/findmittel/organizations.draft.json"),
                   help="Normdatei; ohne sie werden Herausgeber nur ueber Kuerzel verglichen")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Platzhalter selbst auflösen: Die Windows-Eingabeaufforderung expandiert
    # keine Wildcards, dort käme sonst "*.metadata.v2.*.json" wörtlich an.
    runs = []
    for pattern in args.runs:
        hits = sorted(glob.glob(pattern)) if any(c in pattern for c in "*?[") else [pattern]
        if not hits:
            print(f"[warn] keine Datei zu {pattern!r}", file=sys.stderr)
        runs += hits
    if not runs:
        sys.exit("keine Eingabedateien gefunden")

    orgs = load_orgs(args.orgs)
    if orgs:
        print(f"[info] Normdatei: {len(set(orgs.values()))} Organisationen, {len(orgs)} Schreibweisen")
    all_stats, all_misses, gold_size = [], {}, 0
    for run in runs:
        label, doc, records = load_run(run)
        band = args.band or Path(doc.get("source_pdf", run)).stem
        gold = load_gold(args.gold, band) if args.gold.is_file() else {}
        gold_size = max(gold_size, len(gold))
        stats, misses = evaluate(label, doc, records, gold, args.threshold, orgs)
        all_stats.append(stats)
        all_misses[label] = misses

    if not all_stats:
        sys.exit("keine Läufe gelesen")

    print(f"\nGoldstandard: {gold_size} Segment(e) mit Archivtitel aus {args.gold}\n")
    head = (f"{'Lauf':<34}{'Rec':>5}{'leer':>5}{'Beleg%':>8}{'Titel%':>8}{'Org%':>7}"
            f"{'Tag':>5}{'Mon':>5}{'o.Dat':>6}{'issu':>5}{'evnt':>5}{'ment':>5}{'o.Org':>6}")
    print(head)
    print("-" * len(head))
    for s in all_stats:
        print(f"{s['lauf'][:33]:<34}{s['records']:>5}{s['leer']:>5}{s['belegquote']:>8.1f}"
              f"{s['titel_treffer']:>8.1f}{s['org_treffer']:>7.1f}"
              f"{s['datum_tag']:>5}{s['datum_monat']:>5}{s['datum_fehlt']:>6}"
              f"{s['dt_issued']:>5}{s['dt_event']:>5}{s['dt_mentioned']:>5}{s['ohne_herausgeber']:>6}")
    print("\n  Beleg%  = Records ohne Beanstandung der Belegprüfung (alle Segmente)")
    print(f"  Titel%  = Archivtitel mit >= {args.threshold:.0%} Wortüberlappung getroffen")
    print("  Org%    = Herausgeber stimmt mit dem Archiv überein (inkl. Akronym)")
    print("  leer    = Records ganz ohne Angaben (gescheiterte Batches) - aus der Belegquote ausgenommen")
    print("  issu/evnt/ment = date_type: issued / event / mentioned")

    for label, misses in all_misses.items():
        if not misses:
            continue
        print(f"\n{label} — Abweichungen vom Archiv (erste {args.misses}):")
        for kind, seg_id, gold_val, our_val in misses[:args.misses]:
            print(f"  Segment {seg_id:>3} [{kind}]")
            print(f"     Archiv: {gold_val[:88]}")
            print(f"     unser : {our_val[:88]}")
