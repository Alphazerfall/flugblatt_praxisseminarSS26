#!/usr/bin/env python3
"""Prüfliste falscher und fehlender Segmentgrenzen über alle Bände.

Je Seitenübergang: Spricht der Seiteninhalt für ein neues Blatt oder eine Fortsetzung?
Widerspricht das der Segmentierung, kommt er auf die Prüfliste (fehlender oder
überflüssiger Schnitt).

Seitenmerkmale aus der Datalab-OCR, ohne LLM: Eingangsstempel, Datum im Kopf, Kopfleiste
("LSD - LSD - LSD"), Impressum auf der Vorseite, Seitenzahl 2-19, "b.w.", Trennstrich,
"Fortsetzung". Gewichtet wird per Likelihood-Verhältnis (geglättet) gegen die vorhandene
Segmentierung, verrechnet naiv-bayesianisch zur Wahrscheinlichkeit "Blattanfang".

Segmenthinweise: mehrere Findmitteltitel, enthaltener Text eines anderen Blatts,
segmentation_hints der Metadaten-Läufe.

Ausgabe: docs/korpus/segmentgrenzen.tsv und Übersicht je Band auf stdout.

Aufruf:
    python pipelines/01_pdf/check_boundaries.py [--min-odds 3]
"""

from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipelines/04_metadata"))
sys.path.insert(0, str(ROOT / "pipelines/01_pdf"))
from detect_missing_cuts import DATE_RE, is_masthead  # noqa: E402
from extract_metadata_v2 import STAMP_INLINE, is_stamp_block, load_page_blocks  # noqa: E402
from prompt_v2 import RESPONSIBLE_LINE  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PAGENUM = re.compile(r"^[\s\-–—]*(?:seite|s\.)?[\s.]*?([2-9]|1\d)[.)]?[\s\-–—]*$", re.I)
CONT_WORD = re.compile(r"(?i)^\W*(fortsetzung|forts\.)")
BW = re.compile(r"(?i)\b(b\.\s?w\.|bitte\s+wenden|bitte\s+umblättern|siehe\s+rückseite)\W*$")
IMPRINT = re.compile(r"(?im)^\s*(herausgeber|hrsg\.|eigendruck|druck\s*:|selbstverlag)")
SKIP = {"PageHeader", "PageFooter", "Picture", "Figure"}

START_FEATURES = ("stamp", "headdate", "masthead", "prev_imprint")
CONT_FEATURES = ("pagenum", "prev_bw", "prev_hyphen", "cont_word")
# schwächere Merkmale, nur für den Vorschlag von Schnitten (extended=True); die Prüfliste bleibt bei den acht oben
EXTRA_FEATURES = ("overlap_low", "first_heading", "prev_blank")
CANDIDATE_FEATURES = ("overlap_high", "blank", "prev_end")
WORD = re.compile(r"[a-zäöüß]{4,}")

LABEL = {
    "stamp": "Eingangsstempel", "headdate": "Datum in Kopfzeile", "masthead": "Kopfleiste",
    "prev_imprint": "Impressum auf Vorseite", "pagenum": "Seitenzahl",
    "prev_bw": "b.w. auf Vorseite", "prev_hyphen": "Trennstrich auf Vorseite",
    "cont_word": "„Fortsetzung“", "overlap_low": "kaum gemeinsame Wörter mit der Vorseite",
    "first_heading": "Überschrift am Anfang", "prev_blank": "Vorseite fast leer",
}


def short(text, n=70):
    return " ".join((text or "").split())[:n]


def body_words(blocks):
    return set(WORD.findall(" ".join(x.lower() for _, t, x in blocks if x and t not in SKIP)))


def page_features(blocks, prev_blocks, extended=False):
    """-> {Merkmal: Belegtext} der vorhandenen Merkmale einer Seite."""
    texts = [(t, x) for _, t, x in blocks if x]
    found = {}
    for t, x in texts[:2] + texts[-2:]:
        if PAGENUM.match(x):
            found["pagenum"] = x
    for t, x in texts[:3]:
        if is_masthead(" ".join(x.split())):
            found["masthead"] = x
        if t == "PageHeader" and DATE_RE.search(x):
            found["headdate"] = x
    for t, x in texts:
        if is_stamp_block(t, x) or (t != "Picture" and STAMP_INLINE.search(x)):
            found["stamp"] = x
            break
    body = [x for t, x in texts if t not in SKIP and not is_stamp_block(t, x)]
    if body and CONT_WORD.match(body[0]):
        found["cont_word"] = body[0]
    prev = [x for _, t, x in prev_blocks or [] if x and t not in SKIP]
    if prev:
        for x in prev[-2:]:
            if BW.search(x.strip()):
                found["prev_bw"] = x
        last = prev[-1].strip()
        # "-Eigendruck im Selbstverlag-" ist Schmuck, keine Silbentrennung
        if re.search(r"[a-zäöüß]-$", last) and not last.startswith(("-", "–")):
            found["prev_hyphen"] = prev[-1]
        for x in prev[-4:]:
            if RESPONSIBLE_LINE.search(x) or IMPRINT.search(x):
                found["prev_imprint"] = x
    if extended:
        body = [(t, x) for _, t, x in blocks if x and t not in SKIP]
        mine, before = body_words(blocks), body_words(prev_blocks or [])
        if len(mine & before) < 0.03 * len(mine | before):
            found["overlap_low"] = ""
        if body and body[0][0] == "SectionHeader":
            found["first_heading"] = body[0][1]
        if sum(len(x) for _, t, x in prev_blocks or [] if x and t not in SKIP) < 30:
            found["prev_blank"] = ""
        # Kandidaten, einzeln ohne Wirkung (docs/korpus/schnittvorschlag.md)
        if len(mine & before) > 0.12 * len(mine | before):
            found["overlap_high"] = ""
        if sum(len(x) for _, x in body) < 30:
            found["blank"] = ""
        if prev and re.search(r"[.!?:)\"“”]\s*$", prev[-1]):
            found["prev_end"] = prev[-1]
    return {k: short(v) for k, v in found.items()}


def load_volumes(root):
    vols = []
    for vol in sorted((root / "data/raw").iterdir()):
        segf = next(vol.glob("*.segments.json"), None)
        if not segf:
            continue
        stem = segf.name.split(".")[0]
        ocr = vol / stem / f"{stem}.json"
        if not ocr.is_file():
            continue
        segs = sorted(json.loads(segf.read_text(encoding="utf-8"))["segments"],
                      key=lambda s: s["start_page"])
        vols.append({"band": vol.name, "stem": stem, "dir": vol, "segments": segs,
                     "pages": load_page_blocks(ocr)})
    return vols


def calibrate(vols, extended=False):
    """Log-Likelihood-Verhältnis je Merkmal (Laplace-geglättet) und
    Vorab-Chance eines Blattanfangs."""
    n = {"start": 0, "inner": 0}
    hits = {"start": collections.Counter(), "inner": collections.Counter()}
    for v in vols:
        starts = {s["start_page"] for s in v["segments"]}
        for p in sorted(v["pages"])[1:]:
            kind = "start" if p in starts else "inner"
            n[kind] += 1
            hits[kind].update(page_features(v["pages"][p], v["pages"].get(p - 1), extended).keys())
    llr = {}
    for f in START_FEATURES + CONT_FEATURES + (EXTRA_FEATURES + CANDIDATE_FEATURES if extended else ()):
        a = (hits["start"][f] + 1) / (n["start"] + 2)
        b = (hits["inner"][f] + 1) / (n["inner"] + 2)
        llr[f] = math.log(a / b)
    return llr, math.log(n["start"] / n["inner"])


def segment_of(segs, page):
    for s in segs:
        if s["start_page"] <= page <= s["end_page"]:
            return s
    return None


def page_candidates(vols, llr, prior, min_odds):
    rows = []
    for v in vols:
        starts = {s["start_page"] for s in v["segments"]}
        for p in sorted(v["pages"])[1:]:
            feats = page_features(v["pages"][p], v["pages"].get(p - 1))
            if not feats:
                continue
            logit = prior + sum(llr[f] for f in feats)
            prob = 1 / (1 + math.exp(-logit))
            is_start = p in starts
            if not is_start and logit >= math.log(min_odds):
                art = "fehlender Schnitt"
            elif is_start and logit <= -math.log(min_odds):
                art = "überflüssiger Schnitt"
            else:
                continue
            seg = segment_of(v["segments"], p)
            rows.append({
                "band": v["band"], "seiten": f"{p - 1}|{p}", "art": art,
                "segment": seg["id"] if seg else "",
                "p_anfang": round(prob, 2),
                "stärke": round(abs(logit), 2),
                "signale": ", ".join(LABEL[f] for f in feats),
                "beleg": " / ".join(f"{LABEL[f]}: {t}" for f, t in feats.items()),
            })
    return rows


def findmittel_candidates(vols, path):
    """Segmente, auf die mehrere Archivtitel fallen."""
    if not path.is_file():
        return []
    by_stem = {v["stem"]: v for v in vols}
    titles = collections.defaultdict(list)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("start_page") and r["band"] in by_stem:
                titles[(r["band"], int(r["start_page"]))].append(r["archiv_titel"])
    rows = []
    for (stem, start), ts in titles.items():
        if len(set(ts)) < 2:
            continue
        v = by_stem[stem]
        seg = segment_of(v["segments"], start)
        if not seg or seg["start_page"] != start:
            continue                           # Segmentierung hat sich seither geändert
        rows.append({
            "band": v["band"], "seiten": f"{seg['start_page']}-{seg['end_page']}",
            "art": "fehlender Schnitt", "segment": seg["id"], "p_anfang": "",
            "stärke": round(math.log(len(set(ts)) + 1), 2),
            "signale": f"Findmittel: {len(set(ts))} Titel",
            "beleg": " | ".join(short(t, 50) for t in sorted(set(ts))[:4]),
        })
    return rows


def contained_candidates(vols, path):
    """Längeres Segment enthält den Text eines anderen Blatts."""
    if not path.is_file():
        return []
    by_band = {v["band"]: v for v in vols}
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["art"] != "enthalten":
                continue
            longer, shorter = (("a", "b") if int(r["zeichen_a"]) >= int(r["zeichen_b"])
                               else ("b", "a"))
            v = by_band.get(r[f"band_{longer}"])
            if not v:
                continue
            start = int(r[f"seiten_{longer}"].split("-")[0])
            seg = segment_of(v["segments"], start)
            if not seg or seg["end_page"] == seg["start_page"]:
                continue                           # einseitig: kein Schnitt möglich
            rows.append({
                "band": v["band"], "seiten": f"{seg['start_page']}-{seg['end_page']}",
                "art": "fehlender Schnitt", "segment": seg["id"], "p_anfang": "",
                "stärke": 1.0,
                "signale": "enthält anderes Blatt",
                "beleg": f"{r[f'band_{shorter}']} S. {r[f'seiten_{shorter}']}: "
                         f"{short(r[f'anfang_{shorter}'], 50)}",
            })
    return rows


def metadata_candidates(vols, min_runs=2):
    """segmentation_hints aller Metadaten-Läufe eines Bandes. Ein einzelner
    Lauf zitiert Nachbarseiten auch aus Versehen (großer Batch, schwacher
    Prompt); gezählt wird eine Grenze erst, wenn mindestens `min_runs` Läufe
    sie melden."""
    rows = []
    for v in vols:
        seen = collections.defaultdict(set)
        mark = set()
        for path in glob.glob(str(v["dir"] / "*.metadata.*.json")):
            if ".bak-" in path or ".partial" in path:
                continue
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            for h in doc.get("segmentation_hints") or []:
                p = h["page"] if h["relation"] == "folgende Seite" else h["page"] + 1
                seen[p].add(Path(path).name)
                if h.get("continuation_mark"):
                    mark.add(p)
        for p, runs in sorted(seen.items()):
            if len(runs) < min_runs:
                continue
            seg = segment_of(v["segments"], p)
            rows.append({
                "band": v["band"], "seiten": f"{p - 1}|{p}", "art": "überflüssiger Schnitt",
                "segment": seg["id"] if seg else "", "p_anfang": "",
                "stärke": round(0.5 * len(runs) + (1.0 if p in mark else 0), 2),
                "signale": f"Metadaten: {len(runs)} Läufe zitieren Nachbarseite"
                           + (" (mit Seitenzählung)" if p in mark else ""),
                "beleg": f"Modell bezog Blöcke von S. {p - 1} bzw. {p} auf das Nachbarsegment",
            })
    return rows


def known_ranges(md_path):
    """Seitenangaben aus segmentierungsfehler.md: {(Band, Seite)}."""
    known = set()
    if not md_path.is_file():
        return known
    for line in md_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(Nr\. \d{3} \(\d{4}\))\s*\|\s*([^|]+(?:\\\|[^|]+)*)\|", line)
        if not m:
            continue
        for a, b in re.findall(r"(\d+)(?:[–-](\d+))?", m.group(2)):
            for p in range(int(a), int(b or a) + 1):
                known.add((m.group(1), p))
    return known


def merge(rows, known):
    """Hinweise auf dieselbe Stelle zusammenführen, Stärken addieren."""
    merged = {}
    for r in rows:
        key = (r["band"], r["art"], r["seiten"])
        if key in merged:
            m = merged[key]
            m["stärke"] = round(m["stärke"] + r["stärke"], 2)
            m["signale"] += "; " + r["signale"]
            m["beleg"] += " || " + r["beleg"]
        else:
            merged[key] = dict(r)
    out = list(merged.values())
    for r in out:
        pages = [int(x) for x in re.findall(r"\d+", r["seiten"])]
        r["bekannt"] = "ja" if any((r["band"], p) in known for p in pages) else ""
    # Seitenhinweise, die in einem Segment mit Segmenthinweis liegen, stützen sich
    by_seg = collections.Counter((r["band"], r["segment"]) for r in out)
    for r in out:
        r["mehrfach"] = by_seg[(r["band"], r["segment"])] if by_seg[(r["band"], r["segment"])] > 1 else ""
        r["stufe"] = stage(r)
    order = {"sicher": 0, "wahrscheinlich": 1, "prüfen": 2}
    return sorted(out, key=lambda r: (order[r["stufe"]], -r["stärke"], r["band"]))


def stage(r):
    """Stichprobe vom 29.09.2026: mehrere unabhängige Signale fast immer echt;
    Stempel, Kopfleiste oder Datum allein etwa drei von vier; Impressum,
    Seitenzahl, Trennstrich oder Metadaten allein etwa jeder zweite. "b.w."
    ist oft eine Rückseite mit eigenem Kopf - eine Richtlinienfrage."""
    signals = {s.strip() for s in re.split(r"[;,]", r["signale"]) if s.strip()}
    strong = {"Eingangsstempel", "Datum in Kopfzeile", "Kopfleiste"}
    if len(signals) >= 2 or r["stärke"] >= 3:
        return "sicher"
    if signals & strong or any(s.startswith("Findmittel") for s in signals):
        return "wahrscheinlich"
    return "prüfen"


def parse_args():
    p = argparse.ArgumentParser(description="Prüfliste falscher und fehlender Segmentgrenzen.")
    p.add_argument("--min-odds", type=float, default=4.0,
                   help="Mindestchance gegen die vorhandene Segmentierung (Standard 4:1)")
    p.add_argument("-o", "--out", type=Path, default=ROOT / "docs/korpus/segmentgrenzen.tsv")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    vols = load_volumes(ROOT)
    llr, prior = calibrate(vols)
    print("Gewichte (Log-Likelihood-Verhältnis, >0 spricht für Blattanfang):")
    for f, w in sorted(llr.items(), key=lambda x: -x[1]):
        print(f"  {LABEL[f]:<26}{w:+.2f}  (Faktor {math.exp(w):.2f})")

    rows = (page_candidates(vols, llr, prior, args.min_odds)
            + findmittel_candidates(vols, ROOT / "docs/korpus/findmittel/abgleich.tsv")
            + contained_candidates(vols, ROOT / "docs/korpus/fassungen.tsv")
            + metadata_candidates(vols))
    rows = merge(rows, known_ranges(ROOT / "docs/korpus/segmentierungsfehler.md"))

    cols = ["stufe", "band", "seiten", "art", "segment", "p_anfang", "stärke", "signale",
            "mehrfach", "bekannt", "beleg"]
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    print(f"\n{len(rows)} Verdachtsfälle -> {args.out.relative_to(ROOT)}\n")
    table = collections.defaultdict(collections.Counter)
    for r in rows:
        table[r["band"]][r["art"]] += 1
        table[r["band"]][r["stufe"]] += 1
    print(f"{'Band':<16}{'Segmente':>9}{'fehlend':>9}{'überflüssig':>13}"
          f"{'sicher':>8}{'wahrsch.':>10}{'prüfen':>8}")
    for v in vols:
        c = table[v["band"]]
        print(f"{v['band']:<16}{len(v['segments']):>9}{c['fehlender Schnitt']:>9}"
              f"{c['überflüssiger Schnitt']:>13}{c['sicher']:>8}{c['wahrscheinlich']:>10}"
              f"{c['prüfen']:>8}")
    total = collections.Counter(r["stufe"] for r in rows)
    print(f"{'gesamt':<16}{sum(len(v['segments']) for v in vols):>9}"
          f"{sum(1 for r in rows if r['art'] == 'fehlender Schnitt'):>9}"
          f"{sum(1 for r in rows if r['art'] == 'überflüssiger Schnitt'):>13}"
          f"{total['sicher']:>8}{total['wahrscheinlich']:>10}{total['prüfen']:>8}")
