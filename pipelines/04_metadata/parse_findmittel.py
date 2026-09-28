#!/usr/bin/env python3
"""Findmitteldaten des Universitätsarchivs (Rep. 118) auswerten.

Eingabe ist der HIDA-DOC1-XML-Export aus ACTApro, den das Archiv geliefert hat.
Er beschreibt die Sammlung auf Ebene der *Verzeichnungseinheiten* (ein Karton bzw.
Ordner = eine Einheit = eine unserer Jahrgangs-PDFs), nicht auf Ebene einzelner
Flugblätter. Zwei Felder sind für uns trotzdem Gold wert:

  St_Darin   je Einheit die Liste der herausgebenden Gruppen, meist mit
             ausgeschriebenem Namen ("LSD. Liberaler Studentenbund Deutschland").
             -> Rohbau für organizations.json.
  St_Entha   "Enthält"-Vermerk: eine (mit "u.a.:" ausdrücklich unvollständige)
             Liste einzelner Blätter, Form "HERAUSGEBER: Titel".
             -> Gold-Set für die Metadaten-Extraktion.

Schreibt:
  organizations.seed.json   Normdatei-Rohbau, muss von Hand durchgesehen werden
  archiv_titel.tsv          alle Einzeltitel mit Einheit, Jahr und Herausgeber
  einheiten.tsv             eine Zeile je Verzeichnungseinheit (Abgleich mit den PDFs)

Aufruf:
    python pipelines/04_metadata/parse_findmittel.py \\
        "docs/korpus/findmittel/Rep. 118 ... .xml" -o docs/korpus/findmittel
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://www.startext.de/HiDA/DefService/XMLSchema}"

# Bis Vz 15 reicht unser digitalisierter Zeitraum 1967-1973.
DEFAULT_MAX_VZ = 15


def field(doc, type_):
    for f in doc.iter(NS + "Field"):
        if f.get("Type") == type_:
            return f.get("value_plain") or f.get("Value") or ""
    return ""


def split_list(value):
    """"u.a.: | - A; | - B" -> ["A", "B"]"""
    value = re.sub(r"^\s*u\.a\.:\s*", "", (value or "").strip())
    parts = re.split(r"[\r\n]+", value)
    return [re.sub(r"^[-\s]+", "", p).strip(" ;") for p in parts if p.strip(" ;-\r\n\t ")]


def split_org(name):
    """"LSD. Liberaler Studentenbund Deutschland" -> ("LSD", "Liberaler ...").

    Bewusst konservativ: Was nicht sicher als Kürzel erkennbar ist, bleibt
    ungetrennt und wird beim Durchsehen von Hand korrigiert.
    """
    m = re.match(r"^([A-ZÄÖÜ][A-ZÄÖÜa-zäöüß0-9\-/]{1,11})\.\s+(.+)$", name)
    if m:
        return m.group(1), m.group(2).strip()
    m = re.match(r"^([A-ZÄÖÜ]{2,8})\s+(\S.+)$", name)
    if m and not m.group(2)[:1].islower():
        return m.group(1), m.group(2).strip()
    return "", name.strip()


def parse(xml_path, max_vz):
    tree = ET.parse(xml_path)
    units, titles, org_mentions = [], [], []
    for doc in tree.getroot().findall(NS + "Document"):
        block = doc.find(NS + "Block")
        if block is None or block.get("Type") != "Vz":
            continue
        sign = field(doc, "Vz_Sign1")
        vz = int(sign) if sign.isdigit() else None
        year = field(doc, "Laufzeit")
        label = field(doc, "Vz_Bez") or field(doc, "St_Titel")
        orgs = split_list(field(doc, "St_Darin"))
        entries = split_list(field(doc, "St_Entha"))
        units.append({"vz": vz, "jahr": year, "einheit": label,
                      "n_organisationen": len(orgs), "n_titel": len(entries),
                      "bestellsignatur": field(doc, "Vz_Bestellsignatur")})
        for e in entries:
            org, sep, title = e.partition(":")
            if not sep or len(org) > 60:
                org, title = "", e
            titles.append({"vz": vz, "jahr": year, "einheit": label,
                           "herausgeber_praefix": org.strip(), "titel": title.strip(), "roh": e})
        for o in orgs:
            org_mentions.append((vz, year, o))
    return units, titles, [m for m in org_mentions if max_vz is None or (m[0] or 0) <= max_vz]


def build_seed(org_mentions):
    seed = {}
    for vz, year, raw in org_mentions:
        acro, full = split_org(raw)
        key = re.sub(r"[^a-z0-9]+", "_", (acro or full).lower()).strip("_")
        entry = seed.setdefault(key, {"org_id": key, "name": acro or full, "full_name": "",
                                      "type": "", "variants": set(), "jahre": set(), "vz": set()})
        entry["variants"].add(raw)
        entry["jahre"].add(year)
        entry["vz"].add(vz)
        if acro and full and not entry["full_name"]:
            entry["full_name"] = full
    out = []
    for entry in seed.values():
        entry["variants"] = sorted(entry["variants"])
        entry["jahre"] = sorted(entry["jahre"])
        entry["vz"] = sorted(v for v in entry["vz"] if v)
        entry["gnd_id"] = ""
        entry["notes"] = "Rohbau aus Findmittel Rep. 118, Feld St_Darin - bitte prüfen"
        out.append(entry)
    return sorted(out, key=lambda e: e["org_id"])


def write_tsv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    p = argparse.ArgumentParser(description="Findmittel-XML des Archivs auswerten.")
    p.add_argument("xml", help="HIDA-DOC1-XML-Export")
    p.add_argument("-o", "--out-dir", type=Path, default=Path("."), help="Zielordner")
    p.add_argument("--max-vz", type=int, default=DEFAULT_MAX_VZ,
                   help=f"Normdatei nur aus Einheiten bis zu dieser Nummer (Standard: {DEFAULT_MAX_VZ} "
                        f"= unser digitalisierter Zeitraum); 0 = alle")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    xml_path = Path(args.xml)
    if not xml_path.is_file():
        sys.exit(f"Datei nicht gefunden: {xml_path}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    units, titles, org_mentions = parse(xml_path, args.max_vz or None)
    seed = build_seed(org_mentions)

    write_tsv(args.out_dir / "einheiten.tsv", units,
              ["vz", "jahr", "einheit", "n_organisationen", "n_titel", "bestellsignatur"])
    write_tsv(args.out_dir / "archiv_titel.tsv", titles,
              ["vz", "jahr", "einheit", "herausgeber_praefix", "titel", "roh"])
    (args.out_dir / "organizations.seed.json").write_text(
        json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")

    n_early = sum(1 for t in titles if (t["vz"] or 0) <= (args.max_vz or 10 ** 6))
    per_year = collections.Counter(t["jahr"] for t in titles if (t["vz"] or 0) <= (args.max_vz or 10 ** 6))
    print(f"{len(units)} Verzeichnungseinheiten, {len(titles)} Einzeltitel "
          f"(davon {n_early} in Vz 1-{args.max_vz})")
    print("  Einzeltitel je Jahr: " + ", ".join(f"{y}: {n}" for y, n in sorted(per_year.items())))
    print(f"  Normdatei-Rohbau: {len(seed)} Einträge -> organizations.seed.json")
    print(f"  geschrieben nach {args.out_dir}/")
