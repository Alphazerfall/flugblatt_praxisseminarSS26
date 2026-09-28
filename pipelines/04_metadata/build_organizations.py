#!/usr/bin/env python3
"""Aus dem Findmittel-Rohbau und den Extraktionsläufen eine prüfbare Normdatei bauen.

Zwei Quellen fließen zusammen:

  organizations.seed.json  Rohbau aus dem Findmittel (Feld St_Darin) - autoritativ
                           für Kürzel und Langform, aber mit Parsefehlern.
  *.metadata.*.json        die Schreibweisen, die in unseren Extraktionsläufen
                           tatsächlich vorkommen ("Liberaler Studentenbund
                           Deutschlands (LSD)", "RCDS-Uni-Regensburg e.V.").
                           Erst diese machen die Zuordnung später zum Lookup.

Das Ergebnis ist ein ENTWURF: `organizations.draft.json`. Einträge, über die ein
Mensch entscheiden muss, tragen ein Feld `_review` mit der Frage. Erst nach der
Durchsicht wird daraus `organizations.json`.

Aufruf:
    python pipelines/04_metadata/build_organizations.py \\
        --seed docs/korpus/findmittel/organizations.seed.json \\
        --runs "data/raw/*/*.metadata.*.json" \\
        -o docs/korpus/findmittel/organizations.draft.json
"""

from __future__ import annotations

import argparse
import collections
import difflib
import glob
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ACRONYM = re.compile(r"\b([A-ZÄÖÜ][A-ZÄÖÜ0-9]{1,7})\b")
NOISE = re.compile(r"\s*(e\.\s?V\.|Regensburg|Uni-?Regensburg|an der Universität Regensburg)\s*",
                   re.IGNORECASE)


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "")).strip()


def key_of(s):
    return re.sub(r"[^a-z0-9]+", "_", norm(s).lower()).strip("_")


def acronyms(s):
    return {a for a in ACRONYM.findall(s or "") if len(a) >= 2}


def fix_seed_entry(entry):
    """Die Heuristik im Findmittel-Parser trennt manchmal falsch:
    "1. Mai-Komitee" -> Kürzel "1"; "AK Kritische Juristen" -> Kürzel "AK".
    Kurze oder rein numerische Kürzel gelten deshalb als Fehlparse."""
    name, full = norm(entry.get("name")), norm(entry.get("full_name"))
    note = None
    if name.isdigit() or len(name) < 2:
        name, full, note = (f"{name}. {full}".strip(". "), "", "Kürzel war ein Parsefehler")
    elif full and not name.isupper() and len(name.split()) == 1 and len(name) > 4:
        # "Aktion Ostern´70" o.ä. - kein Kürzel, sondern der Name selbst
        name, full = norm(f"{name} {full}"), ""
    entry = dict(entry, name=name, full_name=full)
    if note:
        entry["_review"] = note
    return entry


def merge_seed(seed):
    """Einträge mit demselben Kürzel zusammenlegen. Verschiedene Langformen zum
    selben Kürzel werden NICHT stillschweigend vereinheitlicht, sondern als
    Rückfrage markiert - der SHB hieß über die Jahre verschieden."""
    merged = {}
    for raw in seed:
        entry = fix_seed_entry(raw)
        k = key_of(entry["name"])
        if k not in merged:
            merged[k] = {"org_id": k, "name": entry["name"], "full_name": entry["full_name"],
                         "type": entry.get("type", ""), "variants": set(entry.get("variants", [])),
                         "jahre": set(entry.get("jahre", [])), "vz": set(entry.get("vz", [])),
                         "gnd_id": "", "notes": "aus Findmittel Rep. 118 (St_Darin)",
                         "_review": entry.get("_review", ""), "_langformen": set()}
        m = merged[k]
        m["variants"] |= set(entry.get("variants", []))
        m["jahre"] |= set(entry.get("jahre", []))
        m["vz"] |= set(entry.get("vz", []))
        if entry["full_name"]:
            m["_langformen"].add(entry["full_name"])
            if not m["full_name"]:
                m["full_name"] = entry["full_name"]
        # Die Langformen stecken auch in den Findmittel-Varianten ("SHB.
        # Sozialistischer Hochschulbund" vs "SHB. Sozialdemokratischer ...").
        # Der Rohbau hat sie schon zusammengelegt, hier holen wir sie zurueck.
        for v in entry.get("variants", []):
            mm = re.match(r"^[A-ZÄÖÜ][A-ZÄÖÜa-zäöüß0-9\-/]{1,11}[.\s]\s*(.+)$", norm(v))
            if mm and len(mm.group(1).split()) > 1:
                m["_langformen"].add(norm(mm.group(1)))
    for m in merged.values():
        if len(m["_langformen"]) > 1:
            m["_review"] = ("mehrere Langformen im Findmittel: "
                            + " | ".join(sorted(m["_langformen"]))
                            + " - welche gilt, oder sind es zwei Einträge?")
    return merged


def harvest_surfaces(patterns):
    """Alle issuer-Schreibweisen aus den Extraktionsläufen einsammeln."""
    seen = collections.Counter()
    files = [f for p in patterns for f in sorted(glob.glob(p))]
    for path in files:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        for seg in doc.get("segments", []):
            issuers = seg.get("issuers")
            if issuers is None:
                if seg.get("issuing_org"):
                    seen[norm(seg["issuing_org"])] += 1
                continue
            for i in issuers:
                if i.get("role") == "issuer" and i.get("surface"):
                    seen[norm(i["surface"])] += 1
    return seen, files


def assign(surface, merged):
    """Schreibweise einem Normdatei-Eintrag zuordnen: erst über das Kürzel,
    dann über Wortähnlichkeit der Langform."""
    s_acr = acronyms(surface)
    for k, m in merged.items():
        if m["name"].upper() in s_acr or (s_acr & acronyms(m["name"])):
            return k, "kürzel"
    def words(x):
        return {w for w in re.findall(r"[^\W\d_]{4,}", NOISE.sub(" ", x).lower())}

    sw = words(surface)
    best, score = None, 0.0
    for k, m in merged.items():
        for cand in {m["full_name"], m["name"]} | set(m["_langformen"]):
            if not cand:
                continue
            cw = words(cand)
            if not cw:
                continue
            # Anteil der Kandidatenwoerter, die in der Schreibweise vorkommen -
            # so passt "Bund der Deutschen Katholischen Jugend" auch auf
            # "... - Dioezese Regensburg - Arbeitskreis PFFF".
            r = max(len(cw & sw) / len(cw), len(cw & sw) / len(sw)) if sw else 0.0
            if r > score:
                best, score = k, r
    # 2/3 gemeinsame Inhaltswoerter reichen: "Liberaler Studentenbund Regensburg"
    # gegen "Liberaler Studentenbund Deutschland". Was darunter liegt, bleibt
    # unaufgeloest und wandert in die Rueckfrageliste.
    return (best, f"wortabdeckung {score:.2f}") if score >= 0.66 else (None, "")


def parse_args():
    p = argparse.ArgumentParser(description="Normdatei-Entwurf bauen.")
    p.add_argument("--seed", type=Path, default=Path("docs/korpus/findmittel/organizations.seed.json"))
    p.add_argument("--runs", nargs="*", default=["data/raw/*/*.metadata.*.json"],
                   help="Extraktionsläufe, aus denen Schreibweisen geerntet werden")
    p.add_argument("-o", "--out", type=Path,
                   default=Path("docs/korpus/findmittel/organizations.draft.json"))
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not args.seed.is_file():
        sys.exit(f"Rohbau nicht gefunden: {args.seed}")

    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    merged = merge_seed(seed)
    print(f"Findmittel-Rohbau: {len(seed)} Einträge -> {len(merged)} nach Zusammenlegung")

    surfaces, files = harvest_surfaces(args.runs)
    print(f"Extraktionsläufe: {len(files)} Datei(en), {len(surfaces)} verschiedene Schreibweisen")

    unresolved = []
    for surface, count in surfaces.most_common():
        k, how = assign(surface, merged)
        if k:
            if surface not in merged[k]["variants"]:
                merged[k]["variants"].add(surface)
        else:
            unresolved.append({"surface": surface, "count": count})

    out = []
    for m in sorted(merged.values(), key=lambda m: m["org_id"]):
        m["variants"] = sorted(m["variants"])
        m["jahre"] = sorted(m["jahre"])
        m["vz"] = sorted(v for v in m["vz"] if v)
        m.pop("_langformen", None)
        if not m["_review"]:
            m.pop("_review")
        out.append(m)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    unresolved_path = args.out.with_name(args.out.stem.replace("draft", "unaufgeloest") + ".json")
    unresolved_path.write_text(json.dumps(unresolved, ensure_ascii=False, indent=2), encoding="utf-8")

    todo = sum(1 for m in out if "_review" in m)
    print(f"\nEntwurf: {args.out}  ({len(out)} Einträge, davon {todo} mit Rückfrage)")
    print(f"Unaufgelöst: {unresolved_path}  ({len(unresolved)} Schreibweisen)")
    if todo:
        print("\nRückfragen:")
        for m in out:
            if "_review" in m:
                print(f"  {m['org_id']:<22} {m['_review'][:110]}")
    if unresolved:
        print("\nNicht zugeordnete Schreibweisen (Auszug):")
        for u in unresolved[:12]:
            print(f"  {u['count']:>3}x  {u['surface'][:80]}")
