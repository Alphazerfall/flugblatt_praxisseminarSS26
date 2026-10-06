#!/usr/bin/env python3
"""Mehrfach vorhandene Flugblätter finden, über alle Bände hinweg.

Anders als seiten_duplikate.tsv (exakt gleiche Seiten): arbeitet auf ganzen
Segmenten und verzeiht OCR-Rauschen. Kandidaten über die Embeddings aus dem
Topic-Modelling-Cache (keine API-Kosten), bestätigt über Zeichen-5-Gramme
(Jaccard) auf normalisiertem Text. Einstufung:
    exemplar   gleicher Text trotz OCR-Rauschen -> automatisch gruppieren
    enthalten  ein Segment steckt fast ganz im deutlich längeren anderen
               -> dort fehlt vermutlich ein Schnitt
    fassung    ähnlich, aber mit echten Unterschieden -> von Hand prüfen
Schwellen sind an der Verteilung aller Bände kalibriert; unter Jaccard 0,5
liegen meist nur gemeinsame Bausteine (Formulare, Wahllisten). Kanonisches
Exemplar je Gruppe: der längste Text.

Schreibt docs/korpus/exemplare.tsv und fassungen.tsv (Spalte "art").

    python pipelines/01_pdf/find_copies.py
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "pipelines" / "04_topic"))
import leaflet_topics as lt  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "korpus"


def shingles(text, n=5):
    norm = re.sub(r"[^a-zäöüß0-9]+", " ", text.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return {norm[i:i + n] for i in range(max(1, len(norm) - n + 1))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def containment(a, b):
    """Anteil des kürzeren Texts, der im längeren vorkommt."""
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="baai/bge-m3")
    p.add_argument("--min-cosine", type=float, default=0.85,
                   help="Schwelle für Kandidaten (Embedding-Ähnlichkeit)")
    p.add_argument("--copy", type=float, default=0.75,
                   help="Jaccard ab hier: Exemplar")
    p.add_argument("--version", type=float, default=0.5,
                   help="Jaccard ab hier (bis --copy): mögliche Fassung")
    p.add_argument("--contained", type=float, default=0.8,
                   help="Überdeckung des kürzeren Texts ab hier: enthalten")
    p.add_argument("--min-chars", type=int, default=150,
                   help="kürzere Texte (oft nur Kopfzeile, Inhalt nicht erkannt) "
                        "werden nicht verglichen")
    return p.parse_args()


def main():
    args = parse_args()
    leaflets = lt.load_leaflets()
    cache = lt.load_cache(lt.CACHE_DIR / f"{args.model.replace('/', '__')}.npz")
    missing = sum(lt.text_key(lf["text"]) not in cache for lf in leaflets)
    if missing:
        print(f"{missing} Flugblätter ohne Embedding übersprungen "
              "(leaflet_topics.py --embed-only rechnen)", file=sys.stderr)
    too_short = sum(len(lf["text"]) < args.min_chars for lf in leaflets)
    leaflets = [lf for lf in leaflets if lt.text_key(lf["text"]) in cache
                and len(lf["text"]) >= args.min_chars]

    vecs = np.stack([cache[lt.text_key(lf["text"])] for lf in leaflets])
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    sims = vecs @ vecs.T
    grams = [shingles(lf["text"]) for lf in leaflets]

    copies, versions = [], []
    for i, j in zip(*np.where(np.triu(sims, k=1) >= args.min_cosine)):
        jac = jaccard(grams[i], grams[j])
        if jac >= args.copy:
            copies.append((i, j, sims[i, j], jac))
        elif (containment(grams[i], grams[j]) >= args.contained
              and min(len(grams[i]), len(grams[j])) < 0.7 * max(len(grams[i]), len(grams[j]))):
            versions.append(("enthalten", i, j, sims[i, j], jac))
        elif jac >= args.version:
            versions.append(("fassung", i, j, sims[i, j], jac))

    parent = list(range(len(leaflets)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j, _, _ in copies:
        parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, j, _, _ in copies:
        groups[find(i)] += [i, j]

    def where(lf):
        pages = (f"{lf['start_page']}" if lf["start_page"] == lf["end_page"]
                 else f"{lf['start_page']}-{lf['end_page']}")
        return lf["volume"], pages

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    ordered = sorted(({*m} for m in groups.values()),
                     key=lambda m: min((leaflets[i]["stem"], leaflets[i]["start_page"]) for i in m))
    for n, members in enumerate(ordered, start=1):
        members = sorted(members, key=lambda i: (leaflets[i]["stem"], leaflets[i]["start_page"]))
        canonical = max(members, key=lambda i: (len(leaflets[i]["text"]), -members.index(i)))
        for i in members:
            volume, pages = where(leaflets[i])
            rows.append({"gruppe": n, "kanonisch": "ja" if i == canonical else "",
                         "band": volume, "seiten": pages,
                         "segment_id": leaflets[i]["segment_id"],
                         "zeichen": len(leaflets[i]["text"]),
                         "anfang": leaflets[i]["text"][:90]})
    with (OUT_DIR / "exemplare.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["gruppe"], delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    with (OUT_DIR / "fassungen.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["art", "band_a", "seiten_a", "band_b", "seiten_b", "cosinus",
                    "jaccard", "zeichen_a", "zeichen_b", "anfang_a", "anfang_b"])
        for kind, i, j, cos, jac in sorted(versions, key=lambda v: (v[0], -v[4])):
            w.writerow([kind, *where(leaflets[i]), *where(leaflets[j]), f"{cos:.3f}",
                        f"{jac:.2f}", len(leaflets[i]["text"]), len(leaflets[j]["text"]),
                        leaflets[i]["text"][:70], leaflets[j]["text"][:70]])

    n_copies = sum(len({*m}) for m in groups.values())
    cross = sum(len({leaflets[i]["stem"] for i in m}) > 1 for m in groups.values())
    print(f"{len(leaflets)} Flugblätter geprüft ({too_short} unter {args.min_chars} Zeichen "
          "nicht verglichen)")
    print(f"Exemplare: {len(groups)} Gruppen mit {n_copies} Blättern "
          f"({n_copies - len(groups)} überzählig, {cross} Gruppen über Bandgrenzen)")
    kinds = defaultdict(int)
    for v in versions:
        kinds[v[0]] += 1
    print(f"Zum Prüfen: {kinds['fassung']} mögliche Fassungen, "
          f"{kinds['enthalten']} Segmente in einem anderen enthalten (fehlender Schnitt?)")
    print(f"-> {(OUT_DIR / 'exemplare.tsv').relative_to(REPO_ROOT)}, "
          f"{(OUT_DIR / 'fassungen.tsv').relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
