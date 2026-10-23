#!/usr/bin/env python3
"""Pro segmentiertem Flugblatt Titel, Datum und ausstellende Organisation aus dem
bereits vorhandenen OCR-Text ziehen - kein erneutes OCR, keine Seitenbilder.

Liest:
  - `<pdf-stem>.segments.json` neben der PDF (Format von flugblatt_splitter)
  - `<pdf-stem>/<pdf-stem>.json` neben der PDF (Datalab-Block-JSON, Seitentext
    als HTML in `children[i]["html"]`)

Schreibt:
  - `<pdf-stem>.metadata.<prompt>.json` - Sidecar, eine Zeile je Segment.
    Der Prompt-Name steckt im Dateinamen, damit zwei Läufe sich nie
    überschreiben und vergleichbar nebeneinander liegen (siehe compare_metadata.py).
  - `<pdf-stem>.metadata.<prompt>.partial.jsonl` - Checkpoint je Batch. Ein
    abgebrochener Lauf wird beim nächsten Start fortgesetzt, statt das
    Tageskontingent ein zweites Mal zu verbrauchen.

Prompt-Fassungen:
  v1  der ursprüngliche englische Prompt, ein Herausgeber als String, date_iso
      erzwungen auf YYYY-MM-DD. Nur noch zum Vergleich.
  v2  siehe prompt_v2.py: deutsch, Belegzitate je Feld, mehrere Herausgeber,
      unscharfe Daten, Unterscheidung Erscheinungs-/Veranstaltungsdatum. Wird
      nach dem Lauf automatisch gegen den Quelltext geprüft (Belegquote).

Beispiele:
    # billiger Probelauf: 20 Segmente, ein Request
    python pipelines/04_metadata/extract_metadata_v2.py "data/raw/Nr. 002 (1968)/0118_0002.pdf" --limit 20

    # derselbe Band mit dem alten Prompt, zum Vergleich
    python pipelines/04_metadata/extract_metadata_v2.py "data/raw/Nr. 002 (1968)/0118_0002.pdf" --limit 20 --prompt v1

    # vollständiger Lauf, große Batches gegen das Tageskontingent
    python pipelines/04_metadata/extract_metadata_v2.py "data/raw/Nr. 002 (1968)/0118_0002.pdf" --batch-size 50
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompt_v2 import (RESPONSE_SCHEMA as SCHEMA_V2, build_prompt, check_grounding,  # noqa: E402
                       missing_signatories)
import prompt_v3  # noqa: E402

# v2 = gewachsener Regelprompt, v3 = schlanker Gegenentwurf; gleiches Schema
BUILD_PROMPT = {"v2": build_prompt, "v3": prompt_v3.build_prompt}
import org_match  # noqa: E402

DEFAULT_MODELS = {"gemini": "gemini-3.5-flash", "openrouter": "google/gemini-2.5-flash"}
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_BATCH_SIZE = 20
MAX_RETRIES = 5
TAG_RE = re.compile(r"<[^>]+>")

# --------------------------------------------------------------- Prompt v1 (alt)

PROMPT_V1 = (
    "Below is the OCR text of several separate documents (German political "
    "flyers/leaflets, 'Flugblätter', from the 1960s-70s) that have already been "
    "split out of a larger scanned collection. Each is delimited by a "
    "'=== segment <id> ===' marker. For EACH segment, independently identify:\n"
    "- title: the flyer's own headline/caption (its main heading), not a summary you invent\n"
    "- issuing_org: the organization, party, committee, or group that issued it, "
    "as named in the text (empty string if genuinely not stated)\n"
    "- date_text: the date exactly as it appears in the text (empty string if none)\n"
    "- date_iso: that date normalized to YYYY-MM-DD if you can confidently resolve it "
    "(the flyers are known to be from the year given below), else empty string\n\n"
    "Return exactly one result per segment id given below - none merged, none skipped, "
    "any order - using that same id in your response.\n\n"
)

SCHEMA_V1 = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "issuing_org": {"type": "string"},
                    "date_text": {"type": "string"},
                    "date_iso": {"type": "string"},
                },
                "required": ["id", "title", "issuing_org", "date_text", "date_iso"],
            },
        },
    },
    "required": ["results"],
}

EMPTY_V1 = {"title": "", "issuing_org": "", "date_text": "", "date_iso": ""}
EMPTY_V2 = {"title_evidence": "", "title_blocks": [], "title": "", "title_type": "",
            "issuers": [], "date_evidence": "", "date_blocks": [], "date_text": "",
            "date_iso": "", "date_type": "undated", "doc_type": "unklar", "confidence": 0.0}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


def fmt_elapsed(seconds):
    return str(timedelta(seconds=round(seconds)))


def make_client(backend):
    """-> (client, backend). Der Schlüssel wird erst hier geprüft, damit ein
    fehlender Gemini-Key einen OpenRouter-Lauf nicht blockiert."""
    load_dotenv()
    import os
    if backend == "gemini":
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            sys.exit("GEMINI_API_KEY (oder GOOGLE_API_KEY) fehlt - in .env eintragen.")
        from google import genai
        return genai.Client()
    if not os.getenv("OPENROUTER_API_KEY"):
        sys.exit("OPENROUTER_API_KEY fehlt - in .env eintragen.")
    from openai import OpenAI
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=os.getenv("OPENROUTER_API_KEY"))


def strict_schema(schema):
    """Kopie des Schemas für den strict-Modus von OpenAI/OpenRouter: überall
    additionalProperties=false und alle Eigenschaften required. Ohne das lehnen
    manche Anbieter das Schema ab oder ignorieren es stillschweigend."""
    if isinstance(schema, dict):
        out = {k: strict_schema(v) for k, v in schema.items()}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out
    if isinstance(schema, list):
        return [strict_schema(x) for x in schema]
    return schema


def model_slug(model):
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def html_to_text(fragment_html):
    return html_lib.unescape(TAG_RE.sub("\n", fragment_html))


PICTURE_LABEL = "Abbildung, maschinell beschrieben - nicht Text des Blatts"
STAMP_LABEL = "Archivvermerk - kein Datum des Blatts"

# Eingangsstempel der Bibliothek ("UB Regensburg eingelaufen am: 1. FEB. 1973")
# und Ablagevermerke ("2, Ablage 12043", "z. K."). Das Stempeldatum ist das
# Eingangsdatum, oft mit falsch gelesenem Jahr.
STAMP_DATE = (r"\d{1,2}\s*\.?\s*(?:JAN|FEB|MRZ|MÄR|MÄRZ|APR|MAI|JUNI?|JULI?|AUG|"
              r"SEPT?|OKT|NOV|DEZ)\.?\s*19\d\d")
STAMP_INLINE = re.compile(
    rf"(?:eingeliefert|eingegangen|eingetroffen|eingelaufen)\s+am\s*:?\s*-?\s*{STAMP_DATE}"
    rf"|\bAblage\s*[\d\s()]{{2,8}}(?:{STAMP_DATE})?|\bz\.\s?K\.")
STAMP_ONLY = re.compile(rf"^\W*(?:am\s*:?\s*-?\s*)?{STAMP_DATE}\W*$")
STAMP_PICTURE = re.compile(
    r"stamp|stempel|eingeliefert|eingegangen|eingetroffen|eingelaufen", re.I)


def is_stamp_block(block_type, text):
    """Ganzer Block ist ein Archivvermerk: ein als Bild erkannter Stempel oder
    ein kurzer Textblock, der nur aus dem Stempeldatum besteht."""
    if block_type == "Picture":
        return bool(STAMP_PICTURE.search(text))
    return bool(STAMP_ONLY.match(" ".join(text.split())))


STAMP_DATE_PARTS = re.compile(
    r"(\d{1,2})\s*\.?\s*(JAN|FEB|MRZ|MÄR|MAR|APR|MAI|JUN|JUL|AUG|SEP|OKT|NOV|DEZ)[A-ZÄ]*\.?\s*(19\d\d)",
    re.I)
MONTH_NO = {"JAN": 1, "FEB": 2, "MRZ": 3, "MÄR": 3, "MAR": 3, "APR": 4, "MAI": 5, "JUN": 6,
            "JUL": 7, "AUG": 8, "SEP": 9, "OKT": 10, "NOV": 11, "DEZ": 12}


def stamp_dates(page_blocks, start_page, end_page):
    """Daten der Eingangsstempel eines Segments: [(iso, block_id, Stempeltext)].

    Gelesen ohne Sprachmodell aus Stempelblöcken, Stempel-Bildbeschreibungen
    und Stempelvermerken im Text. Ablagevermerke ohne Datum ("Ablage 12043")
    ergeben nichts."""
    found = []
    for p in range(start_page, end_page + 1):
        for block_id, block_type, text in page_blocks.get(p, []):
            if not text:
                continue
            if is_stamp_block(block_type, text):
                candidates = [text]
            elif block_type != "Picture":
                candidates = [m.group(0) for m in STAMP_INLINE.finditer(text)]
            else:
                continue
            for cand in candidates:
                m = STAMP_DATE_PARTS.search(cand)
                if not m:
                    continue
                day, month, year = int(m.group(1)), MONTH_NO[m.group(2).upper()[:3]], int(m.group(3))
                try:
                    iso = datetime(year, month, day).date().isoformat()
                except ValueError:
                    continue
                found.append((iso, block_id, " ".join(cand.split())))
    return found


def add_received_date(record, stamps, volume_year):
    """Eingangsdatum aus dem Stempel als eigenes Feld - der Tag, an dem das Blatt
    ins Archiv kam, und damit ein "spätestens am" für das Blatt.

    Das Jahr ist die Schwachstelle der OCR (8 statt 0 oder 3: "22. JUNI 1978"
    im Band 1970). Passt es nicht zum Jahrgang (±1), wird es nicht korrigiert,
    sondern als unsicher markiert. Hat das Modell trotz Prompt-Regel das
    Stempeldatum als Datum des Blatts genommen (Beleg aus einem Stempelblock),
    wird es dorthin verschoben statt gelöscht."""
    if not stamps:
        return record
    volume_year = int(volume_year) if str(volume_year or "").isdigit() else None
    plausible = [s for s in stamps if abs(int(s[0][:4]) - volume_year) <= 1] if volume_year else stamps
    iso, block_id, text = min(plausible or stamps)
    record.update(received_date=iso, received_evidence=text, received_blocks=[block_id],
                  received_year_uncertain=not plausible)

    stamp_ids = {s[1] for s in stamps}
    evidence = record.get("date_evidence") or ""
    from_stamp = bool(set(record.get("date_blocks") or []) & stamp_ids) or (
        evidence and any(evidence in s[2] for s in stamps))
    if record.get("date_iso") and from_stamp:
        record["_date_from_stamp"] = {k: record.get(k) for k in
                                      ("date_evidence", "date_blocks", "date_text", "date_iso", "date_type")}
        record.update(date_evidence="", date_blocks=[], date_text="", date_iso="", date_type="undated")
    return record


MONEY = re.compile(r"\bDM\s*[\d.,]|[\d.,]+\s*DM\b|satz\s+DM\b", re.I)
# Bildnachweise und Gestaltungsangaben nennen keine Herausgeber
# ("FOTOS: FOTOGRUPPE D. MSB SPARTAKUS", "GRAPHIK + DESIGN: ...")
CREDITS = re.compile(r"(?i)^\W*(fotos?|fotografie|graphik|grafik|design|zeichnung|druck|satz)\b")


def edge_orgs_without_issuer(record, page_blocks, seg, registry):
    """Kein Herausgeber im Ergebnis, aber in einem kurzen Block am Anfang oder
    Ende des Blatts steht eine Gruppe der Normdatei ("DEMOKRATISCHE MITTE",
    "RCDS - RCDS - RCDS", "Der Rektor teilt mit:")? -> [(block_id, Text)].

    Nur kurze Blöcke (Kopf, Kopfleiste, Schlusszeile): Im Fließtext wird eine
    Gruppe meist nur erwähnt. Geldbeträge ("DM 1.500") sind keine Gruppe."""
    if any(i.get("role") == "issuer" for i in record.get("issuers") or []):
        return []
    from prompt_v2 import unspace
    blocks = [(bid, unspace(" ".join(text.split())))
              for p in range(seg["start_page"], seg["end_page"] + 1)
              for bid, btype, text in page_blocks.get(p, [])
              if text and btype != "Picture" and not is_stamp_block(btype, text)]
    found, seen = [], set()
    for bid, text in blocks[:3] + blocks[-3:]:
        if len(text) > 70 or MONEY.search(text) or CREDITS.search(text) or bid in seen:
            continue
        if org_match.resolve(text, registry):
            found.append((bid, text))
            seen.add(bid)
    return found


def block_text(block):
    text = html_to_text(block.get("html", ""))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def load_page_blocks(ocr_json_path):
    """{Bandseite: [(block_id, block_type, text), ...]}, block_id = "Seite-Block".

    Seiten und Blöcke werden nach Array-Position gezählt, nicht nach Datalabs
    "id"-Feld: bei batchweiser Konvertierung über flugblatt_convert.py
    --batch-size beginnt die Zählung je Batch neu, die ids kollidieren also über
    Batchgrenzen hinweg. Dieselben Kennungen benutzt der Viewer in
    UR_LeafletArchive.
    """
    data = json.loads(ocr_json_path.read_text(encoding="utf-8"))
    pages = {}
    for p, page in enumerate(data["children"], start=1):
        pages[p] = [(f"{p}-{i}", b.get("block_type", "Text"), block_text(b))
                    for i, b in enumerate(page.get("children", []), start=1)]
    return pages


def segment_texts(page_blocks, start_page, end_page):
    """-> (Text fürs Modell mit Blockkennungen, Text für die Belegprüfung ohne
    Kennungen und ohne Bildbeschreibungen, {block_id: text} der Textblöcke).

    Bildbeschreibungen kommen von Datalabs Bildmodell, nicht vom Flugblatt. Das
    Modell sieht sie ausdrücklich als solche markiert; als Beleg taugen sie nicht.
    Archivvermerke ebenso: ganze Stempelblöcke werden markiert, Vermerke
    innerhalb eines Textblocks durch "[Archivvermerk]" ersetzt.
    """
    marked, plain, blocks = [], [], {}
    for p in range(start_page, end_page + 1):
        m_lines, p_lines = [], []
        for block_id, block_type, text in page_blocks.get(p, []):
            if not text:
                continue
            if is_stamp_block(block_type, text):
                m_lines.append(f"[{block_id}] [{STAMP_LABEL}: {' '.join(text.split())}]")
                continue
            if block_type != "Picture":
                text = STAMP_INLINE.sub("[Archivvermerk]", text)
            if block_type == "Picture":
                m_lines.append(f"[{block_id}] [{PICTURE_LABEL}: {' '.join(text.split())}]")
                continue
            m_lines.append(f"[{block_id}] {text}")
            p_lines.append(text)
            blocks[block_id] = text
        if m_lines:
            marked.append(f"--- Seite {p} ---\n" + "\n".join(m_lines))
        if p_lines:
            plain.append(f"--- Seite {p} ---\n" + "\n".join(p_lines))
    return "\n\n".join(marked), "\n\n".join(plain), blocks


def load_known_orgs(path):
    """Kurznamen aus organizations.json, falls vorhanden - gehen in den v2-Prompt
    und machen die Schreibweisen schon bei der Extraktion einheitlicher."""
    if not path or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [o["name"] for o in data if o.get("name")]
    except Exception as e:
        log(f"  ! organizations.json nicht lesbar ({e}) - ohne bekannte Gruppen weiter")
        return []


# ------------------------------------------------------------------ API-Aufruf

# Rückfallkette für OpenRouter. Nicht jedes Modell wird von einem Anbieter
# bedient, der strenge JSON-Schemata umsetzt; dann antwortet der Router mit
# 404 "No endpoints found that can handle the requested parameters". Statt das
# als Fehler zu behandeln, gehen wir eine Stufe zurück:
#   1. json_schema + strict + require_parameters  (beste Garantie)
#   2. json_schema ohne strict, ohne Anbieterfilter
#   3. json_object - das Schema steht dann nur noch im Prompt
OPENROUTER_MODES = ["schema_strict", "schema", "json_object"]
_ROUTING_ERROR = re.compile(r"No endpoints found|failed_routing_step|response_format", re.I)


def _schema_as_text(schema):
    return ("\n\nANTWORTFORM\nAntworte ausschließlich mit JSON, ohne Vorspann und ohne "
            "Markdown-Codezaun, nach genau diesem JSON-Schema:\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":")))


def _openrouter_call(client, model, prompt_text, schema, mode):
    kwargs = dict(model=model, temperature=0,
                  messages=[{"role": "user", "content": prompt_text}])
    if mode == "schema_strict":
        kwargs["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "flugblatt_metadaten",
                                                     "strict": True,
                                                     "schema": strict_schema(schema)}}
        kwargs["extra_body"] = {"provider": {"require_parameters": True}}
    elif mode == "schema":
        kwargs["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "flugblatt_metadaten",
                                                     "schema": schema}}
    else:
        kwargs["response_format"] = {"type": "json_object"}
        kwargs["messages"] = [{"role": "user", "content": prompt_text + _schema_as_text(schema)}]
    return client.chat.completions.create(**kwargs).choices[0].message.content


def _create(client, backend, model, prompt_text, schema, state):
    """Ein Request. -> Antworttext (JSON als String).

    `state` merkt sich die zuletzt funktionierende OpenRouter-Stufe, damit nicht
    jeder Batch die Kette von vorn durchprobiert."""
    if backend == "openrouter":
        start = OPENROUTER_MODES.index(state.get("mode", OPENROUTER_MODES[0]))
        last = None
        for mode in OPENROUTER_MODES[start:]:
            try:
                out = _openrouter_call(client, model, prompt_text, schema, mode)
                if state.get("mode") != mode:
                    log(f"    Antwortformat: {mode}")
                    state["mode"] = mode
                return out
            except Exception as e:                       # noqa: BLE001
                last = e
                if not _ROUTING_ERROR.search(str(e)):
                    raise                                # echter Fehler -> normaler Retry
                log(f"    Antwortformat {mode!r} vom Router abgelehnt, nächste Stufe ...")
        raise last

    kwargs = dict(
        model=model,
        input=[{"type": "text", "text": prompt_text}],
        response_format={"type": "text", "mime_type": "application/json", "schema": schema},
    )
    try:
        interaction = client.interactions.create(temperature=0, **kwargs)
    except TypeError:
        interaction = client.interactions.create(**kwargs)
    return interaction.output_text


class ParseError(ValueError):
    """Antwort kam an, hatte aber nicht die erwartete Form."""


def parse_results(raw):
    """Robust aus der Antwort die Record-Liste holen.

    In der Stufe `json_object` gibt es keine Schemagarantie, und die Modelle
    weichen ab: mal eine nackte Liste statt {"results": [...]}, mal ein anderer
    Schlüsselname, mal Zahlen zwischen den Objekten. Statt daran zu scheitern,
    nehmen wir, was brauchbar ist, und melden den Rest.
    """
    data = json.loads(raw)
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("results", "segments", "data", "records", "items"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        if items is None and "id" in data:
            items = [data]                       # ein einzelner Record ohne Huelle
    if items is None:
        raise ParseError(f"keine Ergebnisliste gefunden (Schluessel: {list(data)[:6] if isinstance(data, dict) else type(data).__name__})")

    good, junk = {}, 0
    for item in items:
        if isinstance(item, dict) and "id" in item:
            try:
                good[int(item["id"])] = item
                continue
            except (TypeError, ValueError):
                pass
        junk += 1
    if not good:
        raise ParseError(f"Ergebnisliste enthaelt keine verwertbaren Records ({junk} unbrauchbare Eintraege)")
    if junk:
        log(f"    ! {junk} unbrauchbare Eintraege in der Antwort uebersprungen")
    return good


def extract_batch(client, backend, model, year, batch, prompt_version, known_orgs, page_counts,
                  state, page_ranges=None, hints=None):
    """batch: Liste von (segment_id, text). -> {segment_id: record}
    hints: {segment_id: Hinweis} der maschinellen Prüfung (nur bei der Nachfrage)."""
    if prompt_version == "v1":
        body = "\n\n".join(f"=== segment {sid} ===\n{txt}" for sid, txt in batch)
        prompt_text = PROMPT_V1 + f"Collection year: {year}\n\n{body}"
        schema = SCHEMA_V1
    else:
        prompt_text = BUILD_PROMPT[prompt_version](year, batch, known_orgs=known_orgs,
                                                   page_counts=page_counts, page_ranges=page_ranges,
                                                   hints=hints)
        schema = SCHEMA_V2

    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = _create(client, backend, model, prompt_text, schema, state)
            raw = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw or "", flags=re.M).strip()
            return parse_results(raw)
        except (ParseError, json.JSONDecodeError) as e:
            # Formfehler sind bei temperature=0 deterministisch - ein zweiter
            # Versuch bringt dieselbe Antwort. Also hoechstens einmal wiederholen.
            last = e
            log(f"    ! Antwort unbrauchbar ({e})")
            if attempt >= 2:
                break
            time.sleep(2)
        except Exception as e:                       # Rate-Limit, 5xx, Netz
            last = e
            if attempt == MAX_RETRIES:
                break
            wait = min(60, 2 ** attempt) + random.uniform(0, 1)
            log(f"    ! Versuch {attempt}/{MAX_RETRIES} fehlgeschlagen ({type(e).__name__}: {e}); "
                f"neuer Versuch in {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError(f"Batch nach {MAX_RETRIES} Versuchen aufgegeben: {last}")


def normalize_record(record):
    """Bereinigt zwei Widersprüche, die das Modell gelegentlich liefert:

    - date_type "undated" mit Datumstext, meist das Datum eines im Text nur
      erwähnten Ereignisses ("Am 20. November veranstaltete der AStA ...").
      Das Datum wird geleert, der Originaltext bleibt in "_date_dropped" und
      wird im Log gemeldet: Manchmal ist nicht das Datum falsch, sondern die
      Art (Veranstaltungsdatum als "undated").
    - dieselbe Person oder Organisation mehrfach in derselben Rolle; die
      Belegblöcke werden zusammengeführt. Einträge ohne Namen fallen weg.
    """
    if record.get("date_type") == "undated" and record.get("date_text"):
        record["_date_dropped"] = record["date_text"]
        record.update(date_text="", date_iso="", date_evidence="", date_blocks=[])

    merged = {}
    for iss in record.get("issuers") or []:
        if not (iss.get("surface") or "").strip():
            continue
        key = (iss.get("surface", "").strip().lower(), iss.get("role"),
               (iss.get("function") or "").strip(), (iss.get("marker") or "").strip())
        if key in merged:
            blocks = merged[key].setdefault("blocks", [])
            blocks += [b for b in iss.get("blocks") or [] if b not in blocks]
        else:
            merged[key] = dict(iss)
    if record.get("issuers"):
        record["issuers"] = list(merged.values())
    return record


def cited_block_ids(record):
    ids = list(record.get("title_blocks") or []) + list(record.get("date_blocks") or [])
    for iss in record.get("issuers") or []:
        ids += iss.get("blocks") or []
    return ids


def foreign_block_ids(record, start_page, end_page):
    """Kennungen, die nicht auf den Seiten des eigenen Segments liegen - das
    Modell hat aus einem Nachbarblatt abgeschrieben (oder die Kennung erfunden)."""
    foreign = []
    for block_id in cited_block_ids(record):
        m = re.fullmatch(r"(\d+)-\d+", str(block_id))
        if not m or not start_page <= int(m.group(1)) <= end_page:
            foreign.append(block_id)
    return foreign


# "-2-", "- 2 -", "Seite 2", "2" als ganze Kopf-/Fußzeile
CONTINUATION_MARK = re.compile(r"^\s*(-\s*\d+\s*-|seite\s*\d+\s*-?|\d+)\s*$", re.I)


def segmentation_hints(seg, foreign_ids, page_blocks):
    """Zeigt eine fremde Kennung auf die direkt angrenzende Seite, fehlt dort
    womöglich ein Zusammenschnitt: das Modell hat das Blatt inhaltlich richtig
    gelesen, die Segmentgrenze liegt falsch. Eine Seitenzählung ("-2-") als
    Fußzeile der letzten bzw. Kopfzeile der folgenden Seite erhärtet das.
    Nicht angrenzende Seiten sind dagegen schlicht abgeschrieben.
    Bestätigte Fälle kommen nach docs/korpus/segmentierungsfehler.md."""
    hints = []
    pages = sorted({int(b.split("-")[0]) for b in foreign_ids
                    if re.fullmatch(r"\d+-\d+", str(b))})
    for p in pages:
        if p == seg["end_page"] + 1:
            last = page_blocks.get(seg["end_page"], [])
            nxt = page_blocks.get(p, [])
            mark = bool(
                (last and last[-1][1] == "PageFooter" and CONTINUATION_MARK.match(last[-1][2]))
                or (nxt and nxt[0][1] == "PageHeader" and CONTINUATION_MARK.match(nxt[0][2])))
            hints.append({"segment": seg["id"], "page": p, "relation": "folgende Seite",
                          "continuation_mark": mark})
        elif p == seg["start_page"] - 1:
            hints.append({"segment": seg["id"], "page": p, "relation": "vorige Seite",
                          "continuation_mark": False})
    return hints


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# ---------------------------------------------------------------- Checkpoints

def load_checkpoint(path):
    if not path.is_file():
        return {}
    done = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            done[rec["id"]] = rec
        except json.JSONDecodeError:
            continue                                  # halbe Zeile nach hartem Abbruch
    return done


def append_checkpoint(path, records):
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def backup_existing(path):
    if not path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.stem}.bak-{stamp}{path.suffix}")
    path.rename(backup_path)
    return backup_path


def guess_year(pdf_path):
    m = re.search(r"\((\d{4})\)", str(pdf_path))
    return m.group(1) if m else "unknown"


def parse_args():
    p = argparse.ArgumentParser(description="Titel, Datum und ausstellende Organisation je Segment per LLM.")
    p.add_argument("pdf", help="Pfad zur Jahrgangs-PDF (segments.json und OCR-JSON liegen daneben)")
    p.add_argument("--backend", choices=["gemini", "openrouter"], default="gemini",
                   help="gemini = Google-SDK direkt, openrouter = OpenAI-SDK gegen OpenRouter")
    p.add_argument("-m", "--model", default=None,
                   help=f"Modell-ID; Standard je Backend: {DEFAULT_MODELS}")
    p.add_argument("--tag", default=None,
                   help="Kennung im Dateinamen (Standard: <prompt>.<modell>) - trennt Vergleichsläufe")
    p.add_argument("--prompt", choices=["v1", "v2", "v3"], default="v2",
                   help="Prompt-Fassung (Standard: v2). v3 = schlanker Gegenentwurf "
                        "(prompt_v3.py), v1 nur noch zum Vergleich.")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, metavar="N",
                   help=f"Segmente je Request - gegen die Tageskontingente zählt die Zahl der "
                        f"Requests, nicht die Tokens (Standard: {DEFAULT_BATCH_SIZE})")
    p.add_argument("--limit", type=int, metavar="N",
                   help="nur die ersten N Segmente - für billige Probeläufe")
    p.add_argument("--fresh", action="store_true", help="vorhandene Checkpoints ignorieren")
    p.add_argument("--segments", type=Path, help="Pfad zu segments.json überschreiben")
    p.add_argument("--ocr-json", type=Path, help="Pfad zum Datalab-OCR-JSON überschreiben")
    p.add_argument("--organizations", type=Path, default=None,
                   help="organizations.json; ihre Kurznamen gehen in den v2-Prompt")
    p.add_argument("-o", "--output", type=Path, help="Ausgabepfad überschreiben")
    p.add_argument("--install", action="store_true",
                   help="Titel/Datum zusätzlich in segments.json zurückschreiben (nur v1; "
                        "für den Korpusbau nicht nötig und nicht empfohlen)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.is_file():
        sys.exit(f"Datei nicht gefunden: {pdf_path}")
    if args.install and args.prompt != "v1":
        sys.exit("--install gibt es nur für --prompt v1. Die v2-Felder gehören in den "
                 "Korpusbau, nicht in segments.json.")

    args.model = args.model or DEFAULT_MODELS[args.backend]
    tag = args.tag or f"{args.prompt}.{model_slug(args.model)}"

    segments_path = args.segments or pdf_path.with_name(pdf_path.stem + ".segments.json")
    ocr_json_path = args.ocr_json or pdf_path.with_name(pdf_path.stem) / (pdf_path.stem + ".json")
    if not segments_path.is_file():
        sys.exit(f"Keine segments.json gefunden: {segments_path}")
    if not ocr_json_path.is_file():
        sys.exit(f"Kein OCR-JSON gefunden: {ocr_json_path} (erst flugblatt_convert.py laufen lassen)")

    seg_doc = json.loads(segments_path.read_text(encoding="utf-8"))
    segments = sorted(seg_doc["segments"], key=lambda s: s["start_page"])
    if args.limit:
        segments = segments[:args.limit]
    page_blocks = load_page_blocks(ocr_json_path)
    year = guess_year(pdf_path)
    known_orgs = load_known_orgs(args.organizations) if args.prompt != "v1" else []
    empty = EMPTY_V1 if args.prompt == "v1" else EMPTY_V2

    out_path = args.output or pdf_path.with_name(f"{pdf_path.stem}.metadata.{tag}.json")
    ckpt_path = out_path.with_suffix(".partial.jsonl")
    if args.fresh and ckpt_path.is_file():
        backup_existing(ckpt_path)
        log(f"  vorhandenen Checkpoint beiseitegelegt (--fresh)")

    done = {} if args.fresh else load_checkpoint(ckpt_path)
    if done:
        log(f"Checkpoint gefunden: {len(done)} Segment(e) bereits extrahiert, "
            f"werden nicht erneut angefragt.")

    model_texts = {}
    plain_texts = {}                                 # für die Belegprüfung
    seg_blocks = {}
    page_counts = {}
    page_ranges = {}
    to_fetch = []
    for seg in segments:
        sid = seg["id"]
        marked, plain_texts[sid], seg_blocks[sid] = segment_texts(
            page_blocks, seg["start_page"], seg["end_page"])
        # v1 kennt keine Blockkennungen und bekommt den Text ohne sie
        model_texts[sid] = marked if args.prompt != "v1" else plain_texts[sid]
        page_counts[sid] = seg["end_page"] - seg["start_page"] + 1
        page_ranges[sid] = (seg["start_page"], seg["end_page"])
        if sid in done:
            continue
        if not marked:
            log(f"  ! Segment {sid} (S. {seg['start_page']}-{seg['end_page']}): kein OCR-Text, übersprungen")
            done[sid] = {"id": sid, **empty}
        else:
            to_fetch.append((sid, model_texts[sid]))

    batches = list(chunked(to_fetch, args.batch_size))
    log(f"{len(segments)} Segment(e), {len(to_fetch)} offen -> {len(batches)} Request(s) "
        f"à höchstens {args.batch_size} (Prompt {args.prompt}, {args.backend}:{args.model}, Jahrgang {year})"
        + (f", {len(known_orgs)} bekannte Gruppen im Prompt" if known_orgs else ""))

    client = make_client(args.backend)
    backend_state = {}
    failed_batches = 0
    run_start = time.monotonic()
    for i, batch in enumerate(batches, 1):
        log(f"  Batch {i}/{len(batches)}: Segmente {[sid for sid, _ in batch]} ...")
        try:
            batch_meta = extract_batch(client, args.backend, args.model, year, batch, args.prompt,
                                       known_orgs, page_counts, backend_state, page_ranges)
        except Exception as e:                       # noqa: BLE001
            failed_batches += 1
            log(f"  ! Batch {i} aufgegeben ({e}) - Lauf geht weiter, die Segmente bleiben offen. "
                f"Erneut starten holt sie nach (Checkpoint).")
            continue
        fresh_records = []
        for sid, _ in batch:
            meta = batch_meta.get(sid)
            if meta is None:
                log(f"    ! Segment {sid}: fehlt in der Antwort, wird einzeln nachgefragt")
                meta = {"id": sid, **empty, "_missing": True}
            meta.setdefault("id", sid)
            done[sid] = meta
            fresh_records.append(meta)
            org = (meta.get("issuing_org")
                   or ", ".join(x.get("surface", "") for x in meta.get("issuers") or []))
            log(f"    Segment {sid}: \"{meta.get('title', '')[:60]}\" / {org} / "
                f"{meta.get('date_iso') or meta.get('date_text') or '-'}")
        append_checkpoint(ckpt_path, fresh_records)     # erst schreiben, dann weiter

    # ------------------------------------ Nachfrage: fremde Kennungen, Lücken
    # Ein Ergebnis mit Kennungen außerhalb des eigenen Segments hat aus einem
    # Nachbarblatt abgeschrieben; ein fehlendes Ergebnis hat das Modell meist mit
    # einem Nachbarn zusammengelegt. Beide Segmente werden einzeln neu angefragt -
    # ohne Nachbarn im Kontext gibt es nichts abzuschreiben oder zusammenzulegen.
    # Die ursprünglichen fremden Kennungen bleiben als "_foreign_blocks" im
    # Record, weil sie auf eine falsche Segmentgrenze hinweisen können (siehe
    # segmentation_hints).
    # Ebenso Segmente, deren Verantwortlich-Zeile Personen nennt, die im
    # Ergebnis fehlen: Im großen Batch übersieht das Modell die letzte Zeile
    # eines Blatts leichter.
    # Ebenso Segmente ohne Herausgeber, bei denen im Kopf oder am Ende eine
    # Gruppe der Normdatei steht ("DEMOKRATISCHE MITTE", "RCDS - RCDS - RCDS").
    # Dort bekommt die Nachfrage einen neutralen Hinweis mit; das Modell
    # entscheidet mit Beleg, ob die Gruppe herausgibt oder nur erwähnt wird.
    seg_by_id = {s["id"]: s for s in segments}
    registry_path = args.organizations or org_match.DEFAULT_REGISTRY
    registry = org_match.load_registry(registry_path) if registry_path.is_file() else []
    if args.prompt != "v1":
        retry = []
        for sid, rec in done.items():
            s = seg_by_id.get(sid)
            if not s:
                continue
            asked = rec.get("_foreign_blocks") or rec.get("_retried_missing")
            foreign = [] if asked else foreign_block_ids(rec, s["start_page"], s["end_page"])
            unsigned = ([] if rec.get("_retried_signatory")
                        else missing_signatories(rec, plain_texts.get(sid, "")))
            edge = ([] if rec.get("_retried_issuer") or not registry
                    else edge_orgs_without_issuer(rec, page_blocks, s, registry))
            if foreign or (rec.get("_missing") and not asked) or unsigned or edge:
                retry.append((sid, foreign, unsigned, edge))
        if retry:
            log(f"Nachfrage: {len(retry)} Segment(e) mit fremden Kennungen, fehlenden "
                f"Unterzeichnern/Herausgebern oder ohne Ergebnis werden einzeln neu angefragt.")
        for sid, foreign, unsigned, edge in retry:
            hint = []
            if unsigned:
                hint.append(f"Die Verantwortlich-Zeile nennt {', '.join(unsigned)} - "
                            "fehlen diese Personen als signatory?")
            if edge:
                where = "; ".join(f"„{text}“ (Block {bid})" for bid, text in edge)
                hint.append(f"Am Anfang oder Ende des Blatts steht {where}. Prüfe, ob diese Gruppe "
                            "das Blatt herausgibt (issuer) oder nur erwähnt, zitiert oder "
                            "angesprochen wird.")
            try:
                meta = extract_batch(client, args.backend, args.model, year,
                                     [(sid, model_texts[sid])], args.prompt, known_orgs,
                                     page_counts, backend_state, page_ranges,
                                     hints={sid: " ".join(hint)} if hint else None).get(sid)
            except Exception as e:                   # noqa: BLE001
                log(f"  ! Segment {sid}: Nachfrage fehlgeschlagen ({e}), altes Ergebnis bleibt")
                continue
            if meta is None:
                log(f"  ! Segment {sid}: fehlt in der Nachfrage-Antwort, altes Ergebnis bleibt")
                continue
            meta["id"] = sid
            old = done[sid]
            if foreign:
                meta["_foreign_blocks"] = foreign
            elif unsigned or edge:
                # Nur übernehmen, wenn die Nachfrage die Lücke schließt, ohne
                # anderes zu verlieren; sonst bleibt das alte Ergebnis.
                gained_sig = unsigned and (len(missing_signatories(meta, plain_texts.get(sid, "")))
                                           < len(unsigned))
                gained_iss = edge and any(i.get("role") == "issuer" for i in meta.get("issuers") or [])
                if not (gained_sig or gained_iss):
                    meta = dict(old)
                for flag in ("_foreign_blocks", "_retried_missing"):
                    if old.get(flag):
                        meta[flag] = old[flag]
                if unsigned:
                    meta["_retried_signatory"] = True
                if edge:
                    meta["_retried_issuer"] = [text for _, text in edge]
            else:
                meta["_retried_missing"] = True
            done[sid] = meta
            append_checkpoint(ckpt_path, [meta])
            why = (f"vorher fremd: {', '.join(foreign)}" if foreign
                   else "; ".join(filter(None, [
                       f"Unterzeichner fehlten: {', '.join(unsigned)}" if unsigned else "",
                       f"Gruppe am Rand: {', '.join(t for _, t in edge)}" if edge else ""]))
                   or "fehlte in der Antwort")
            issuers = [i.get("surface") for i in meta.get("issuers") or [] if i.get("role") == "issuer"]
            log(f"    Segment {sid} ({why}): \"{meta.get('title', '')[:50]}\" -> "
                f"Herausgeber {', '.join(issuers) or '-'}")

    log(f"Fertig in {fmt_elapsed(time.monotonic() - run_start)}."
        + (f" {failed_batches} Batch(es) ohne Ergebnis." if failed_batches else ""))

    hints = []
    for sid, rec in done.items():
        if rec.get("_foreign_blocks") and sid in seg_by_id:
            hints += segmentation_hints(seg_by_id[sid], rec["_foreign_blocks"], page_blocks)
    for h in hints:
        log(f"  Segmentierung prüfen: Segment {h['segment']} bezog sich auf die {h['relation']} "
            f"{h['page']}" + (" (mit Seitenzählung - vermutlich dasselbe Blatt)"
                              if h["continuation_mark"] else ""))

    results = []
    for seg in segments:
        meta = dict(done.get(seg["id"], {"id": seg["id"], **empty}))
        meta.pop("id", None)
        if args.prompt != "v1":
            meta = normalize_record(meta)
            if meta.get("_date_dropped"):
                log(f"  Datum prüfen: Segment {seg['id']} hatte \"{meta['_date_dropped']}\" "
                    f"ohne Datumsart, verworfen (Ereignis im Text oder falsche Art?)")
            meta = add_received_date(meta, stamp_dates(page_blocks, seg["start_page"], seg["end_page"]),
                                     year)
            if meta.get("_date_from_stamp"):
                log(f"  Segment {seg['id']}: Stempeldatum {meta['_date_from_stamp']['date_iso']} "
                    f"war als Datum des Blatts eingetragen - jetzt Eingangsdatum")
        results.append({**seg, **meta})
    received = [r for r in results if r.get("received_date")]
    if received:
        log(f"Eingangsdatum aus Stempel: {len(received)} von {len(results)} Segmenten"
            + (f", davon {sum(r['received_year_uncertain'] for r in received)} mit unsicherem Jahr"
               if any(r["received_year_uncertain"] for r in received) else ""))

    # ------------------------------------------------------------ Belegprüfung
    grounding = None
    if args.prompt != "v1":
        checked = 0
        flagged = []
        for r in results:
            probs = check_grounding(r, plain_texts.get(r["id"], ""), collection_year=year,
                                    blocks=seg_blocks.get(r["id"], {}))
            checked += 1
            if probs:
                flagged.append({"id": r["id"], "problems": probs})
            r["_grounding"] = probs
        rate = 100 * (checked - len(flagged)) / checked if checked else 0
        grounding = {"checked": checked, "flagged": len(flagged), "rate_percent": round(rate, 1)}
        log(f"Belegprüfung: {checked - len(flagged)}/{checked} Records ohne Beanstandung "
            f"({rate:.1f} %).")
        for f in flagged[:15]:
            log(f"  ! Segment {f['id']}: {'; '.join(f['problems'])}")
        if len(flagged) > 15:
            log(f"  ... und {len(flagged) - 15} weitere, vollständig in der Ausgabedatei")

    # ------------------------------------------------- Zuordnung zur Normdatei
    # Erst nach der Belegprüfung: Das Zusammenlegen von Kopfleiste und Impressum
    # derselben Organisation vereinigt deren Belegblöcke.
    if args.prompt != "v1" and registry_path.is_file():
        doc = {"segments": results}
        unresolved = org_match.annotate(doc, registry)
        if unresolved:
            log(f"Normdatei: {len(unresolved)} Herausgeber-Schreibweise(n) ohne Eintrag: "
                + "; ".join(unresolved))

    out_doc = {
        "source_pdf": pdf_path.name,
        "created": datetime.now().isoformat(),
        "model": args.model,
        "backend": args.backend,
        "tag": tag,
        "prompt_version": args.prompt,
        "batch_size": args.batch_size,
        "grounding": grounding,
        "organizations": registry_path.name if registry_path.is_file() else None,
        "segmentation_hints": hints,
        "segments": results,
    }
    if out_path.is_file():
        backup_existing(out_path)
    out_path.write_text(json.dumps(out_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Gespeichert: {out_path}")
    log(f"  Checkpoint bleibt liegen: {ckpt_path.name} (für --fresh oder zum Löschen von Hand)")

    if args.install:
        backup_path = backup_existing(segments_path)
        if backup_path:
            log(f"  bestehende {segments_path.name} gesichert -> {backup_path.name}")
        installed = []
        for r in results:
            title = f"{r['issuing_org']} - {r['title']}" if r.get("issuing_org") else r.get("title", "")
            installed.append({"id": r["id"], "title": title,
                              "date": r.get("date_iso") or r.get("date_text", ""),
                              "start_page": r["start_page"], "end_page": r["end_page"],
                              "confirmed": r.get("confirmed", False)})
        seg_doc["segments"] = installed
        segments_path.write_text(json.dumps(seg_doc, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"  in {segments_path} eingetragen")
