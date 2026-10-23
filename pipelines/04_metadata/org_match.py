#!/usr/bin/env python3
"""Herausgeber-Schreibweisen der Normdatei zuordnen.

Das Modell übernimmt die Schreibweise des Blatts: "RCDS", "RCDS-Fachbereichsgruppe
WiWi", "Ring Christlich-Demokratischer Studenten (RCDS), Landesverband Bayern".
Für Auswertungen nach Organisation zählt nur, welcher Eintrag der Normdatei
gemeint ist. Jede Schreibweise bekommt deshalb `org_ids`.

Abgeglichen wird nur gegen Kürzel und Langform der Normdatei, nicht gegen die
gesammelten `variants`: Die stammen aus einer früheren Zuordnung und enthalten
Fehlgriffe ("HSU LSD SDS SHB ASTA" nur beim AStA). Gesucht werden alle Kürzel
und Langformen, die in der Schreibweise vorkommen; bei Überlappung gewinnt die
längere ("Linke AStA-Fraktion" vor "AStA"). Mehrere Treffer ohne Überlappung
sind gemeinsame Herausgeber ("LSD, SHB und SDS Regensburg").

Aufruf (ergänzt `org_ids` in einer vorhandenen Ausgabe, schreibt sie neu):
    python pipelines/04_metadata/org_match.py "data/raw/Nr. 010 (1973)/0118_0010.metadata.claude-herausgeber.json"
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_REGISTRY = (Path(__file__).resolve().parents[2]
                    / "docs/korpus/findmittel/organizations.draft.json")

TOKEN = re.compile(r"[^\W_]+")


def _fold(word):
    """"Deutschlands" -> "deutschland": Genitiv-s langer Wörter weg, damit
    "Liberaler Studentenbund Deutschlands" die Langform "... Deutschland" trifft."""
    w = word.lower().replace("ß", "ss")
    return w[:-1] if len(w) >= 6 and w.endswith("s") else w


def tokens(text):
    text = unicodedata.normalize("NFC", text or "")
    return [(m.group(), _fold(m.group())) for m in TOKEN.finditer(text)]


def is_acronym(form):
    return form.isupper() and " " not in form and len(form) <= 6


def load_registry(path=DEFAULT_REGISTRY):
    """-> Liste von (org_id, Formtokens, ist_Kürzel).

    Eine Langform aus nur einem Wort ist meist ein Parsefehler des Findmittels
    ("IMAFAG Psychologie" -> Langform "Psychologie") und würde jedes
    Psychologie-Gremium treffen; sie bleibt deshalb außen vor."""
    forms = []
    for org in json.loads(Path(path).read_text(encoding="utf-8")):
        name, full = org.get("name") or "", org.get("full_name") or ""
        candidates = {name}
        if len(full.split()) > 1:
            candidates.add(full)
        for form in candidates:
            toks = [t for _, t in tokens(form)]
            if toks:
                forms.append((org["org_id"], toks, is_acronym(form)))
    return forms


def _acronym_ok(original):
    """Kürzel nur als Kürzel geschrieben: "RCDS", "AStA", "Asta", aber nicht
    "als" oder "Lust" - kurze Wörter brauchen zwei Großbuchstaben."""
    return sum(c.isupper() for c in original) >= 2 or len(original) >= 4


def resolve(surface, registry):
    """-> sortierte Liste der org_ids, die in der Schreibweise vorkommen."""
    toks = tokens(surface)
    words = [t for _, t in toks]
    hits = []
    for org_id, form, acronym in registry:
        n = len(form)
        for i in range(len(words) - n + 1):
            if words[i:i + n] != form:
                continue
            # a surface that is only the acronym is the group itself ("als")
            if acronym and len(words) > 1 and not _acronym_ok(toks[i][0]):
                continue
            hits.append((i, i + n, org_id))
    hits.sort(key=lambda h: h[0] - h[1])          # längste zuerst
    taken, found = set(), []
    for start, end, org_id in hits:
        span = set(range(start, end))
        if span & taken:
            continue
        taken |= span
        if org_id not in found:
            found.append(org_id)
    return sorted(found)


# Einträge der Normdatei, die an die Universität Regensburg gebunden sind: Der
# AStA Würzburg ist nicht "der AStA". Bundesweite Verbände (RCDS, SDS, LSD ...)
# bleiben dagegen dieselbe Organisation, auch mit Ortsangabe ("SDS Tübingen").
LOCAL_ORGS = {"asta", "linke_asta_fraktion", "studentenschaft",
              "studentenschaft_der_universit_t_regensburg", "studentenparlament",
              "fachschaften", "fachschaften_fachbereiche", "studentische_vertretung",
              "rektor", "kanzler", "studentenwerk", "studentenwerk_regensburg"}
OTHER_PLACE = re.compile(
    r"(?i)würzburg|münchen|muenchen|erlangen|nürnberg|bamberg|augsburg|passau|landshut|"
    r"bayreuth|eichstätt|tübingen|heidelberg|freiburg|frankfurt|marburg|gießen|göttingen|"
    r"hamburg|berlin|bonn|köln|münster|bochum|mainz|kiel|saarbrücken|konstanz|stuttgart|"
    r"mannheim|karlsruhe|hannover|bremen|aachen|darmstadt|kassel|"
    # universities named without their city (Würzburg, München, Erlangen)
    r"julius[- ]*maximilian|ludwig[- ]*maximilian|\blmu\b|friedrich[- ]*alexander|"
    r"polytechnikum|pädagogische[n]? hochschule|\bPH\b|fachhochschule|ingenieurschule")
# "Uni" allein meint in diesem Bestand die Universität Regensburg
# ("Studentenschaft Uni - PH - Poly-Technikum" ist ein gemeinsamer Auftritt).
OWN_UNIVERSITY = re.compile(r"(?i)universität regensburg|uni[- ]regensburg|univ\. regensburg|\buni\b")


def other_institution(iss):
    """Nennt Schreibweise oder Beleg eine andere Hochschule oder Stadt (und nicht
    zugleich die Universität Regensburg)?"""
    text = f"{iss.get('surface', '')} {iss.get('evidence', '')}"
    return bool(OTHER_PLACE.search(text)) and not OWN_UNIVERSITY.search(text)


def match_issuers(record, registry):
    """Setzt `org_ids` an jedem Herausgeber und legt Einträge zusammen, die auf
    dieselben Organisationen zeigen (Kopfleiste "RCDS" und Impressum
    "RCDS-Fachbereichsgruppe WiWi"). Behalten wird die längere, genauere
    Schreibweise; die anderen stehen in `_merged`. Unterzeichner bleiben, wie
    sie sind."""
    out, by_orgs = [], {}
    for iss in record.get("issuers") or []:
        if iss.get("role") != "issuer":
            out.append(iss)
            continue
        ids = resolve(iss.get("surface"), registry)
        if other_institution(iss) and set(ids) & LOCAL_ORGS:
            iss = dict(iss, _other_institution=sorted(set(ids) & LOCAL_ORGS))
            ids = [i for i in ids if i not in LOCAL_ORGS]
        iss = dict(iss, org_ids=ids)
        key = tuple(iss["org_ids"])
        if not key or key not in by_orgs:
            if key:
                by_orgs[key] = iss
            out.append(iss)
            continue
        kept = by_orgs[key]
        if len(iss["surface"]) > len(kept["surface"]):
            kept["_merged"] = kept.get("_merged", []) + [kept["surface"]]
            kept.update(surface=iss["surface"], evidence=iss["evidence"])
        else:
            kept.setdefault("_merged", []).append(iss["surface"])
        blocks = kept.setdefault("blocks", [])
        blocks += [b for b in iss.get("blocks") or [] if b not in blocks]
    record["issuers"] = out
    return record


def annotate(doc, registry):
    """Alle Segmente einer Ausgabe; -> Counter der nicht zugeordneten Schreibweisen."""
    unresolved = collections.Counter()
    for seg in doc.get("segments", []):
        match_issuers(seg, registry)
        for iss in seg["issuers"]:
            if iss.get("role") == "issuer" and not iss.get("org_ids"):
                unresolved[iss["surface"]] += 1
    return unresolved


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="org_ids an den Herausgebern ergänzen.")
    p.add_argument("files", nargs="+", type=Path, help="*.metadata.*.json")
    p.add_argument("--organizations", type=Path, default=DEFAULT_REGISTRY)
    args = p.parse_args()

    registry = load_registry(args.organizations)
    for path in args.files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        unresolved = annotate(doc, registry)
        doc["organizations"] = str(args.organizations.name)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        counts = collections.Counter(o for s in doc["segments"] for i in s["issuers"]
                                     for o in i.get("org_ids") or [])
        print(f"{path.name}: {sum(counts.values())} Zuordnungen, "
              f"häufigste {counts.most_common(5)}")
        for surface, n in unresolved.most_common():
            print(f"   nicht zugeordnet: {n}x {surface!r}")
