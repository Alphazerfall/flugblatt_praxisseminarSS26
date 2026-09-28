#!/usr/bin/env python3
"""Archivtitel aus dem Findmittel gegen unsere Segmente ausrichten.

Das Findmittel (Rep. 118, Feld St_Entha) nennt für einzelne Jahrgänge die
enthaltenen Flugblätter in der Form "Herausgeber: Titel" - für 1968 und 1969
nahezu vollständig. Diese Liste ist die einzige projektexterne Wahrheit über
die Dokumentgrenzen, die wir haben.

Verfahren: monotone Ausrichtung (Needleman-Wunsch-artig) zwischen der
geordneten Titelliste und der geordneten Segmentliste. Die Reihenfolge im
Findmittel folgt der Ablage im Karton, also derselben Reihenfolge wie unsere
Seiten - das ist eine starke Nebenbedingung, die die meisten Fehlzuordnungen
eines reinen Ähnlichkeitsvergleichs ausschließt.

Die Bewertung eines Paares nutzt IDF-gewichtete Wortabdeckung: Ein seltenes
Wort wie "Trojanische" entscheidet, ein häufiges wie "Studenten" trägt kaum bei.

Mehrere Titel dürfen auf dasselbe Segment fallen - genau das ist der Befund,
auf den es ankommt: Dort fehlt ein Schnitt.

Aufruf:
    python pipelines/01_pdf/align_findmittel.py 0118_0002 --tsv bericht.tsv
    python pipelines/01_pdf/align_findmittel.py 0118_0002 0118_0003
"""

from __future__ import annotations

import argparse
import collections
import csv
import html as html_lib
import json
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://www.startext.de/HiDA/DefService/XMLSchema}"
TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"[^\W\d_]{3,}")

# Bewertung
MATCH_THRESHOLD = 0.35      # darunter gilt ein Paar nicht als Treffer
SAME_SEGMENT_PENALTY = 0.15  # Abschlag, wenn ein weiterer Titel auf dasselbe Segment faellt
SEGMENT_GAP = 0.02          # Kosten fuer ein Segment ohne Titel (Findmittel ist unvollstaendig)
TITLE_GAP = 0.60            # Kosten fuer einen Titel ohne Segment - teuer, er muss irgendwo sein


def norm(text):
    return unicodedata.normalize("NFC", text or "").lower()


def tokens(text):
    return WORD_RE.findall(norm(text))


# ------------------------------------------------------------------ Einlesen

def load_archive_titles(xml_path, vz):
    tree = ET.parse(xml_path)
    for doc in tree.getroot().findall(NS + "Document"):
        block = doc.find(NS + "Block")
        if block is None or block.get("Type") != "Vz":
            continue
        fields = {}
        for f in doc.iter(NS + "Field"):
            fields.setdefault(f.get("Type"), f.get("value_plain") or f.get("Value") or "")
        if fields.get("Vz_Sign1") != str(vz):
            continue
        raw = re.sub(r"^\s*u\.a\.:\s*", "", fields.get("St_Entha", "").strip())
        out = []
        for part in re.split(r"[\r\n]+", raw):
            part = re.sub(r"^[-\s]+", "", part).strip(" ;")
            if not part:
                continue
            org, sep, title = part.partition(":")
            if not sep or len(org) > 60:
                org, title = "", part
            out.append({"org": org.strip(), "titel": title.strip(), "roh": part})
        return out
    return []


def load_segment_texts(raw_dir, stem):
    band = next(d for d in raw_dir.iterdir() if d.is_dir() and d.name.startswith(f"Nr. {stem[-3:]}"))
    segments = json.loads((band / f"{stem}.segments.json").read_text(encoding="utf-8"))["segments"]
    ocr = json.loads((band / stem / f"{stem}.json").read_text(encoding="utf-8"))
    pages = {i + 1: html_lib.unescape(TAG_RE.sub("\n", c.get("html", "")))
             for i, c in enumerate(ocr["children"])}
    segments = sorted(segments, key=lambda s: s["start_page"])
    texts = []
    for seg in segments:
        text = "\n".join(pages.get(p, "") for p in range(seg["start_page"], seg["end_page"] + 1))
        texts.append(set(tokens(text)))
    return segments, texts


# ----------------------------------------------------------------- Bewertung

def build_idf(segment_tokens):
    n = len(segment_tokens)
    df = collections.Counter()
    for toks in segment_tokens:
        df.update(toks)
    return {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}, n


def score(title_tokens, seg_tokens, idf):
    weights = [idf.get(w, 3.0) for w in title_tokens]
    total = sum(weights)
    if not total:
        return 0.0
    hit = sum(w for t, w in zip(title_tokens, weights) if t in seg_tokens)
    return hit / total


# ------------------------------------------------------------- Ausrichtung

def align_free(titles_tokens, segment_tokens, idf, segments=None):
    """Zuordnung ohne Reihenfolgebedingung - nötig für Einheiten, in denen das
    Findmittel nach Herausgeber gruppiert statt nach Ablage sortiert ist.

    Mit `segments` gilt eine Kapazitätsgrenze: Ein Segment nimmt höchstens so
    viele Titel auf, wie es Seiten hat. Ohne diese Grenze landen mehrere
    ähnlich formulierte Titel ("Zulassungssperre Psychologie" /
    "Zulassungs-Stop im Fach Psychologie") auf derselben Einzelseite, und der
    Bericht meldet fehlende Schnitte, wo nur der Abgleich unscharf ist.
    Titel, die so keinen Platz finden, bleiben unzugeordnet - auch das ist ein
    Hinweis auf einen fehlenden Schnitt, aber ein vorsichtiger.
    """
    candidates = []
    for i, t in enumerate(titles_tokens):
        for j, s in enumerate(segment_tokens):
            sc = score(t, s, idf)
            if sc >= MATCH_THRESHOLD:
                candidates.append((sc, i, j))
    candidates.sort(reverse=True)
    capacity = {j: (segments[j]["end_page"] - segments[j]["start_page"] + 1) if segments else 10 ** 6
                for j in range(len(segment_tokens))}
    taken, pairs = set(), []
    for sc, i, j in candidates:
        if i in taken or capacity[j] <= 0:
            continue
        taken.add(i)
        capacity[j] -= 1
        pairs.append((i, j, sc))
    for i in range(len(titles_tokens)):
        if i not in taken:
            pairs.append((i, None, 0.0))
    pairs.sort(key=lambda p: p[0])
    return pairs


def order_is_monotone(titles_tokens, segment_tokens, idf, threshold=0.6, max_descents=0.25):
    """Folgt die Titelreihenfolge des Findmittels der Seitenreihenfolge?

    In Einheit 2 (1968) ist sie es, in Einheit 3 (1969) nicht - dort hat die
    Verzeichnung nach Herausgebern gruppiert. Die Antwort entscheidet, welches
    Zuordnungsverfahren zulässig ist.
    """
    seq = [j for _, j, sc in align_free(titles_tokens, segment_tokens, idf)
           if j is not None and sc >= threshold]
    if len(seq) < 5:
        return True, 0.0
    descents = sum(1 for a, b in zip(seq, seq[1:]) if b < a)
    ratio = descents / (len(seq) - 1)
    return ratio <= max_descents, ratio


def align(titles_tokens, segment_tokens, idf):
    """Monotone Zuordnung. -> Liste (titel_index, segment_index, score)."""
    n, m = len(titles_tokens), len(segment_tokens)
    S = [[score(t, s, idf) for s in segment_tokens] for t in titles_tokens]

    NEG = float("-inf")
    best = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for j in range(1, m + 1):
        best[0][j] = best[0][j - 1] - SEGMENT_GAP
        back[0][j] = ("skip_seg", 0, j - 1)
    for i in range(1, n + 1):
        best[i][0] = best[i - 1][0] - TITLE_GAP
        back[i][0] = ("skip_title", i - 1, 0)

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = [
                (best[i - 1][j - 1] + S[i - 1][j - 1], ("match", i - 1, j - 1)),
                (best[i - 1][j] + S[i - 1][j - 1] - SAME_SEGMENT_PENALTY, ("match_same", i - 1, j)),
                (best[i][j - 1] - SEGMENT_GAP, ("skip_seg", i, j - 1)),
                (best[i - 1][j] - TITLE_GAP, ("skip_title", i - 1, j)),
            ]
            val, move = max(options, key=lambda o: o[0])
            best[i][j], back[i][j] = val, move

    pairs, i, j = [], n, m
    while i > 0 or j > 0:
        move = back[i][j]
        if move is None:
            break
        kind, pi, pj = move
        if kind in ("match", "match_same"):
            seg_index = j - 1 if kind == "match" else j - 1
            pairs.append((i - 1, seg_index, S[i - 1][seg_index]))
        i, j = pi, pj
    pairs.reverse()
    return pairs


# ------------------------------------------------------------------ Bericht

def report(stem, vz, jahr, titles, segments, pairs, tsv_rows, mode, ratio):
    matched = [p for p in pairs if p[1] is not None and p[2] >= MATCH_THRESHOLD]
    weak = [p for p in pairs if p[1] is None or p[2] < MATCH_THRESHOLD]
    per_segment = collections.Counter(p[1] for p in matched)
    multi = sorted((s for s, c in per_segment.items() if c > 1), key=lambda s: segments[s]["start_page"])
    covered = set(per_segment)

    print(f"\n{'='*78}\n{stem} — Findmittel-Einheit {vz} ({jahr})")
    print(f"  Zuordnungsverfahren:    {mode}  (absteigende Schritte in der freien Zuordnung: {ratio:.0%})")
    print(f"  Archivtitel:            {len(titles)}")
    print(f"  Segmente:               {len(segments)}")
    print(f"  sicher zugeordnet:      {len(matched)}  ({100*len(matched)/max(len(titles),1):.0f} % der Titel)")
    print(f"  unsicher/ohne Segment:  {len(titles) - len(matched)}")
    print(f"  Segmente mit Titel:     {len(covered)}/{len(segments)}")
    print(f"  Segmente mit >1 Titel:  {len(multi)}   <- dort fehlen Schnitte")

    if multi:
        print("\n  Segmente, auf die mehrere Archivtitel fallen:")
        for s in multi:
            seg = segments[s]
            n_pages = seg["end_page"] - seg["start_page"] + 1
            print(f"    Segment {seg['id']:>3} (S. {seg['start_page']}-{seg['end_page']}, "
                  f"{n_pages} S.) — {per_segment[s]} Titel, mindestens {per_segment[s]-1} fehlende Schnitte:")
            for ti, si, sc in matched:
                if si == s:
                    print(f"        [{sc:.2f}] {titles[ti]['roh'][:88]}")

    if weak:
        print("\n  Titel ohne sichere Zuordnung:")
        for ti, si, sc in weak:
            wo = "kein freies Segment" if si is None else f"bestes S. {segments[si]['start_page']}"
            print(f"    [{sc:.2f}, {wo}] {titles[ti]['roh'][:76]}")

    for ti, si, sc in pairs:
        if si is None:
            tsv_rows.append({"band": stem, "vz": vz, "jahr": jahr,
                             "archiv_herausgeber": titles[ti]["org"], "archiv_titel": titles[ti]["titel"],
                             "segment_id": "", "start_page": "", "end_page": "", "score": 0.0,
                             "status": "ohne Segment", "titel_auf_segment": 0})
            continue
        seg = segments[si]
        tsv_rows.append({
            "band": stem, "vz": vz, "jahr": jahr,
            "archiv_herausgeber": titles[ti]["org"], "archiv_titel": titles[ti]["titel"],
            "segment_id": seg["id"], "start_page": seg["start_page"], "end_page": seg["end_page"],
            "score": round(sc, 3),
            "status": "ok" if sc >= MATCH_THRESHOLD else "unsicher",
            "titel_auf_segment": per_segment.get(si, 0),
        })
    return {"titles": len(titles), "segments": len(segments), "matched": len(matched),
            "multi": len(multi), "missing_cuts": sum(per_segment[s] - 1 for s in multi)}


def parse_args():
    p = argparse.ArgumentParser(description="Archivtitel gegen Segmente ausrichten.")
    p.add_argument("stems", nargs="+", help="Band-Stems, z.B. 0118_0002")
    p.add_argument("--xml", type=Path,
                   default=Path("docs/korpus/findmittel/Rep. 118 Allgemeine Flugblattsammlung "
                                "Universität Regensburg.xml"),
                   help="Findmittel-XML")
    p.add_argument("--raw", type=Path, default=Path("data/raw"), help="Ordner data/raw")
    p.add_argument("--tsv", type=Path, help="Zuordnungen als TSV schreiben")
    p.add_argument("--order", choices=["auto", "monotone", "free"], default="auto",
                   help="auto = selbst erkennen, ob die Titelreihenfolge der Ablage folgt")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not args.xml.is_file():
        sys.exit(f"Findmittel-XML nicht gefunden: {args.xml}")

    tsv_rows, summary = [], []
    for stem in args.stems:
        vz = int(stem[-3:])
        titles = load_archive_titles(args.xml, vz)
        if not titles:
            print(f"\n{stem}: keine Einzeltitel im Findmittel (Einheit {vz}) — übersprungen")
            continue
        segments, seg_tokens = load_segment_texts(args.raw, stem)
        idf, _ = build_idf(seg_tokens)
        tt = [tokens(t["titel"] or t["org"]) for t in titles]
        monotone, ratio = order_is_monotone(tt, seg_tokens, idf)
        if args.order == "monotone" or (args.order == "auto" and monotone):
            mode, pairs = "monoton (Findmittel folgt der Ablage)", align(tt, seg_tokens, idf)
        else:
            mode = "frei mit Kapazitätsgrenze (Findmittel nach Herausgebern gruppiert)"
            pairs = align_free(tt, seg_tokens, idf, segments)
        jahr = 1966 + vz if vz <= 5 else ""      # nur Anzeige; echte Laufzeit steht im XML
        summary.append((stem, report(stem, vz, jahr, titles, segments, pairs, tsv_rows, mode, ratio)))

    if args.tsv and tsv_rows:
        args.tsv.parent.mkdir(parents=True, exist_ok=True)
        with args.tsv.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(tsv_rows[0]), delimiter="\t")
            w.writeheader()
            w.writerows(tsv_rows)
        print(f"\nZuordnungen geschrieben: {args.tsv} ({len(tsv_rows)} Zeilen)")

    if len(summary) > 1:
        print(f"\n{'='*78}\nZusammenfassung")
        print(f"  {'Band':<12}{'Titel':>7}{'Segm':>7}{'zugeordnet':>12}{'Sammel-Segm':>13}{'fehl. Schnitte':>16}")
        for stem, s in summary:
            print(f"  {stem:<12}{s['titles']:>7}{s['segments']:>7}{s['matched']:>12}"
                  f"{s['multi']:>13}{s['missing_cuts']:>16}")
