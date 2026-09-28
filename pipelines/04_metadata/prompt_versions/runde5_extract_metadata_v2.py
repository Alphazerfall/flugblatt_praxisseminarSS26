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
from prompt_v2 import RESPONSE_SCHEMA as SCHEMA_V2, build_prompt, check_grounding  # noqa: E402

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
EMPTY_V2 = {"title_evidence": "", "title": "", "title_type": "", "issuers": [],
            "date_evidence": "", "date_text": "", "date_iso": "", "date_type": "undated",
            "doc_type": "unklar", "confidence": 0.0}


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


def load_page_texts(ocr_json_path):
    # Array-Position, nicht das "id"-Feld: bei batchweiser Konvertierung über
    # flugblatt_convert.py --batch-size beginnt die Seitenzählung je Batch neu,
    # die ids kollidieren also über Batchgrenzen hinweg.
    data = json.loads(ocr_json_path.read_text(encoding="utf-8"))
    return {i + 1: html_to_text(child.get("html", "")) for i, child in enumerate(data["children"])}


def segment_text(page_texts, start_page, end_page):
    parts = []
    for p in range(start_page, end_page + 1):
        text = page_texts.get(p, "").strip()
        if text:
            parts.append(f"--- Seite {p} ---\n{text}")
    return "\n\n".join(parts)


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
                  state):
    """batch: Liste von (segment_id, text). -> {segment_id: record}"""
    if prompt_version == "v1":
        body = "\n\n".join(f"=== segment {sid} ===\n{txt}" for sid, txt in batch)
        prompt_text = PROMPT_V1 + f"Collection year: {year}\n\n{body}"
        schema = SCHEMA_V1
    else:
        prompt_text = build_prompt(year, batch, known_orgs=known_orgs, page_counts=page_counts)
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
    p.add_argument("--prompt", choices=["v1", "v2"], default="v2",
                   help="Prompt-Fassung (Standard: v2). v1 nur noch zum Vergleich.")
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
    page_texts = load_page_texts(ocr_json_path)
    year = guess_year(pdf_path)
    known_orgs = load_known_orgs(args.organizations) if args.prompt == "v2" else []
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

    texts = {}
    page_counts = {}
    to_fetch = []
    for seg in segments:
        sid = seg["id"]
        texts[sid] = segment_text(page_texts, seg["start_page"], seg["end_page"])
        page_counts[sid] = seg["end_page"] - seg["start_page"] + 1
        if sid in done:
            continue
        if not texts[sid]:
            log(f"  ! Segment {sid} (S. {seg['start_page']}-{seg['end_page']}): kein OCR-Text, übersprungen")
            done[sid] = {"id": sid, **empty}
        else:
            to_fetch.append((sid, texts[sid]))

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
                                       known_orgs, page_counts, backend_state)
        except Exception as e:                       # noqa: BLE001
            failed_batches += 1
            log(f"  ! Batch {i} aufgegeben ({e}) - Lauf geht weiter, die Segmente bleiben offen. "
                f"Erneut starten holt sie nach (Checkpoint).")
            continue
        fresh_records = []
        for sid, _ in batch:
            meta = batch_meta.get(sid)
            if meta is None:
                log(f"    ! Segment {sid}: fehlt in der Antwort, bleibt leer")
                meta = {"id": sid, **empty}
            meta.setdefault("id", sid)
            done[sid] = meta
            fresh_records.append(meta)
            org = (meta.get("issuing_org")
                   or ", ".join(x.get("surface", "") for x in meta.get("issuers") or []))
            log(f"    Segment {sid}: \"{meta.get('title', '')[:60]}\" / {org} / "
                f"{meta.get('date_iso') or meta.get('date_text') or '-'}")
        append_checkpoint(ckpt_path, fresh_records)     # erst schreiben, dann weiter

    log(f"Fertig in {fmt_elapsed(time.monotonic() - run_start)}."
        + (f" {failed_batches} Batch(es) ohne Ergebnis." if failed_batches else ""))

    results = []
    for seg in segments:
        meta = dict(done.get(seg["id"], {"id": seg["id"], **empty}))
        meta.pop("id", None)
        results.append({**seg, **meta})

    # ------------------------------------------------------------ Belegprüfung
    grounding = None
    if args.prompt == "v2":
        checked = 0
        flagged = []
        for r in results:
            probs = check_grounding(r, texts.get(r["id"], ""), collection_year=year)
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

    out_doc = {
        "source_pdf": pdf_path.name,
        "created": datetime.now().isoformat(),
        "model": args.model,
        "backend": args.backend,
        "tag": tag,
        "prompt_version": args.prompt,
        "batch_size": args.batch_size,
        "grounding": grounding,
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
