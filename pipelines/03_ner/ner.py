#!/usr/bin/env python3
"""Named-entity recognition over OCR'd leaflet text blocks.

Reads a datalab-format OCR JSON tree (`<id>.json`, produced by
pipelines/02_ocr/datalab_convert.py) and writes a sibling `<id>.ner.json`
with one entry per text block: {block_id, page, text, entities}.

Entities are tagged with four leaflet-specific categories:
    ACTOR      - authors, issuers, organisations, printers and publishers
    LOC        - places and geographic references
    TIME       - dates, deadlines and times
    PERSON     - named public figures

PERSON/LOC/ACTOR come from a German spaCy NER model; all four categories
are additionally boosted by the term files, and TIME is detected with
regexes, since the stock German models don't ship a DATE/TIME label.
Requires the optional "ner" dependency group:
  pip install -e ".[ner]"
    python -m spacy download de_core_news_lg
"""

import argparse
import glob
import html
import json
import os
from pathlib import Path
import re
import sys

try:
    import spacy
except ImportError:
    spacy = None

# Genutztes SpaCy-Modell
DEFAULT_MODEL = "de_core_news_lg"

# Das Modell liefert andere Labels als die Pipeline.
SPACY_LABEL_MAP = {
    "PER": "PERSON",
    "LOC": "LOC",
    "ORG": "ACTOR",
}

SKIP_BLOCK_TYPES = {"Picture", "Figure", "PictureGroup", "FigureGroup"}
TERMS_DIR = Path(__file__).with_name("terms")


def log(message):
    print(message, file=sys.stderr)


# Lädt Begriffe; ein führendes ! markiert einen Blacklist-Eintrag.
def load_terms(filename):
    path = TERMS_DIR / filename
    terms = []
    blacklist = []
    try:
        with path.open(encoding="utf-8") as terms_file:
            for line in terms_file:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("!") and line[1:].strip():
                    blacklist.append(line[1:].strip())
                else:
                    terms.append(line)
    except OSError:
        log(f"Term file not found: {path}")
    return terms, blacklist


TERM_GROUPS = {}
for label, filename in (
    ("ACTOR", "actors.txt"),
    ("LOC", "places.txt"),
    ("TIME", "times.txt"),
    ("PERSON", "persons.txt"),
):
    terms, blacklist = load_terms(filename)
    TERM_GROUPS[label] = {
        "whitelist": terms,
        "blacklist": blacklist,
    }

_WEEKDAYS = (
    r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)"
)
_MONTHS = (
    r"(?:Januar|Februar|M\u00e4rz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)"
)
_NUMERIC_DATE = (
    # Deutsches Datum, optional mit Jahr und Datumsbereich.
    r"\b(?:\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?|\d{4}[./-]\d{1,2}[./-]\d{1,2})\.?"
    r"(?:\s*(?:[-–—]|bis)\s*"
    r"(?:\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?|\d{4}[./-]\d{1,2}[./-]\d{1,2})\.?)?(?!\w)"
)
# Erkennt Uhrzeiten mit Doppelpunkt, Punkt oder OCR-Leerzeichen.
_CLOCK_TIME = r"\b\d{1,2}\s*(?:[:.]\s*|\s+)\d{2}\s*(?:Uhr)?\b"
TIME_PATTERNS = [
    re.compile(_CLOCK_TIME, re.IGNORECASE),
    re.compile(
        rf"(?<!\w){_WEEKDAYS}\s*,?\s*(?:den\s*)?{_NUMERIC_DATE}(?!\w)",
        re.IGNORECASE,
    ),
    re.compile(rf"(?<!\w){_NUMERIC_DATE}(?!\w)", re.IGNORECASE),
    re.compile(
        rf"(?<!\w)\d{{1,2}}\s*\.?\s*{_MONTHS}(?:\s+\d{{2,4}})?(?!\w)",
        re.IGNORECASE,
    ),
    re.compile(rf"(?<!\w){_WEEKDAYS}(?!\w)", re.IGNORECASE),
    re.compile(r"(?<!\w)\d{1,2}\s*Uhr(?!\w)", re.IGNORECASE),
]

# Erkennt HTML-Tags, normalisiert Leerzeichen und entfernt sie aus OCR-Fragmenten.
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# Filtert kurze Abkürzungen, die spaCy gelegentlich als Personen markiert.
JUNK_PERSON_RE = re.compile(r"^[A-ZÄÖÜ][a-zäöüß]{0,3}\.$")


# Entfernt HTML-Tags, decodiert Entities und normalisiert Leerzeichen.
def strip_html(fragment):
    text = TAG_RE.sub(" ", fragment or "")
    text = html.unescape(text)
    return WS_RE.sub(" ", text).strip()


def iter_blocks(node):
    children = node.get("children")
    if children:
        for child in children:
            yield from iter_blocks(child)
        return
    if node.get("block_type") in SKIP_BLOCK_TYPES:
        return
    text = strip_html(node.get("html"))
    if not text:
        return
    yield {"block_id": node.get("id"), "page": node.get("page"), "text": text}


def make_patterns(label, terms):
    """Erzeugt spaCy-Muster für mehrteilige Begriffe."""
    return [
        {"label": label, "pattern": [{"LOWER": tok.lower()} for tok in term.split()]}
        for term in terms
    ]


def build_nlp(model_name):
    if spacy is None:
        log("spaCy is not installed; only term files and TIME rules will run.")
        return None
    try:
        nlp = spacy.load(
            model_name,
            disable=["parser", "morphologizer", "attribute_ruler", "lemmatizer"],
        )
    except OSError:
        log(
            f"spaCy model '{model_name}' is not installed "
            f"(run: python -m spacy download {model_name}); "
            "falling back to gazetteer/regex rules only."
        )
        return None
    ruler = nlp.add_pipe("entity_ruler", before="ner")
    term_patterns = []
    for label, group in TERM_GROUPS.items():
        term_patterns.extend(make_patterns(label, group["whitelist"]))
    ruler.add_patterns(term_patterns)
    return nlp

# Findet Zeitangaben und verwirft kürzere überlappende Treffer.
def find_time_spans(text):
    matches = [match.span() for pattern in TIME_PATTERNS for match in pattern.finditer(text)]
    matches.sort(key=lambda span: (-(span[1] - span[0]), span[0]))
    selected = []
    for start, end in matches:
        if not any(start < other_end and other_start < end for other_start, other_end in selected):
            selected.append((start, end))
    return sorted(selected)


# Findet Zeitangaben und Begriffe aus den Term-Dateien.
def find_gazetteer_spans(text):
    spans = []
    for start, end in find_time_spans(text):
        spans.append((start, end, "TIME"))
    for label, group in TERM_GROUPS.items():
        for term in group["whitelist"]:
            for match in re.finditer(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
                spans.append((match.start(), match.end(), label))
    return spans


# Findet gesperrte Textbereiche getrennt nach Entity-Label.
def find_blacklist_spans(text):
    spans = []
    for label, group in TERM_GROUPS.items():
        for term in group["blacklist"]:
            pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
            spans.extend(
                (match.start(), match.end(), label)
                for match in re.finditer(pattern, text, re.IGNORECASE)
            )
    return spans


# Filtert zu kurze Treffer und typische Abkürzungs-Fehler aus.
def is_junk(label, text):
    if len(text) < 2:
        return True
    if label == "PERSON" and JUNK_PERSON_RE.match(text):
        return True
    return False


# Kombiniert Regeln und Modell, entfernt Überlappungen und sortiert Treffer.
def extract_entities(text, nlp):
    spans = find_gazetteer_spans(text)
    blacklist_spans = find_blacklist_spans(text)

    if nlp is not None:
        doc = nlp(text)
        model_ents = [e for e in doc.ents if e.label_ in SPACY_LABEL_MAP]
        for ent in model_ents:
            spans.append((ent.start_char, ent.end_char, SPACY_LABEL_MAP[ent.label_]))

    label_priority = {"TIME": 0, "ACTOR": 1, "PERSON": 2, "LOC": 3}
    spans.sort(
        key=lambda span: (
            span[0],
            -(span[1] - span[0]),
            label_priority.get(span[2], 99),
        )
    )
    entities = []
    occupied = []
    for start, end, label in spans:
        if any(
            label == blocked_label
            and start < blocked_end
            and blocked_start < end
            for blocked_start, blocked_end, blocked_label in blacklist_spans
        ):
            continue
        if any(start < e and s < end for s, e in occupied):
            continue
        occupied.append((start, end))
        entity_text = text[start:end]
        if is_junk(label, entity_text):
            continue
        entities.append({"text": entity_text, "label": label, "start": start, "end": end})

    entities.sort(key=lambda e: e["start"])
    return entities


def process_file(path, nlp):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    results = []
    for block in iter_blocks(data):
        results.append(
            {
                "block_id": block["block_id"],
                "page": block["page"],
                "text": block["text"],
                "entities": extract_entities(block["text"], nlp),
            }
        )
    return results


def resolve_inputs(paths):
    files = []
    for path in paths:
        if os.path.isdir(path):
            for candidate in glob.glob(os.path.join(path, "**", "*.json"), recursive=True):
                base = os.path.basename(candidate)
                if base.endswith((".ner.json", ".segments.json", ".topics.json", ".segments.auto.json")):
                    continue
                files.append(candidate)
        else:
            files.append(path)
    return files


def default_output_path(path):
    stem, _ = os.path.splitext(path)
    return stem + ".ner.json"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+", help="datalab JSON file(s) or directories to scan recursively")
    p.add_argument("-o", "--output", help="output path (only valid for a single input file)")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"spaCy model to use (default: {DEFAULT_MODEL})")
    return p.parse_args()


def main():
    args = parse_args()
    files = resolve_inputs(args.inputs)
    if not files:
        sys.exit("No input files found.")
    if args.output and len(files) > 1:
        sys.exit("--output can only be used with a single input file.")

    nlp = build_nlp(args.model)

    for path in files:
        out_path = args.output or default_output_path(path)
        results = process_file(path, nlp)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        n_entities = sum(len(r["entities"]) for r in results)
        log(f"{path} -> {out_path} ({len(results)} blocks, {n_entities} entities)")


if __name__ == "__main__":
    main()
