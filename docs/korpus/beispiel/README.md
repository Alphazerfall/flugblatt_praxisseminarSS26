# Beispieldaten

Alle Records stammen aus **Nr. 002 (1968)**, `0118_0002.pdf`. Texte, Zeichen-/Wortzahlen, `content_hash` und `boundary_signals` sind aus dem vorhandenen Datalab-OCR errechnet, nicht ausgedacht. Titel, Datumsdeutung und Organisationszuordnung sind von Hand gesetzt, um die Feldsemantik zu zeigen.

| Datei | Inhalt |
|---|---|
| `documents.jsonl` | zwei geprüfte Flugblätter (S. 1 und S. 6–7) |
| `documents.flagged.jsonl` | ein automatisch geschnittenes Segment mit Verdachtssignalen (S. 1–23 aus `segments.auto.json`) |
| `pages.jsonl` | vier Seiten-Records (S. 1, 3, 6, 7) |
| `organizations.json` | Startbestand der Normdatei, sieben Einträge |

## Was die Beispiele zeigen sollen

**`documents.jsonl`, Record 1 (S. 1, Streikaufruf).** Der Fall „kein gedrucktes Datum, aber ein Datum im Text": Der Streik ist für den 29.5.1968 angekündigt, das Blatt muss also *vorher* verteilt worden sein. Deshalb `type: "event"`, `latest: "1968-05-29"` und `precision: "month"` — mit einem einfachen `date: "1968-05-29"` wäre diese Unterscheidung verloren. `verified_fields: ["date"]` hält fest, dass ein Mensch genau dieses Feld geprüft hat, während Titel und Herausgeber noch LLM-Ausgabe sind.

**`documents.jsonl`, Record 2 (S. 6–7, LSD).** Der einfache Fall: Datum steht als `PageHeader` auf der Seite (`23. 7. 68`), der Herausgeber ergibt sich aus der Sigel-Leiste darunter. `surface` bewahrt die gedruckte Form `LSD- LSD - LSD-LSD- ...`, `org_id: "lsd"` macht sie zählbar.

**`documents.flagged.jsonl`.** Dasselbe Blatt wie Record 1, aber so, wie die Datalab-Auto-Segmentierung es sieht: als 23-Seiten-Block, der in Wahrheit zehn Flugblätter enthält. Vier Flags stehen im Record, `status: "flagged"`, `boundary_confidence: 0.15`, `doc_type: "unklar"`. Der Punkt: **so ein Fehler ist im Korpus sichtbar und filterbar, statt still zu einer falschen Zahl in einer Auswertung zu werden.**

Beide Records in `documents.jsonl` tragen dessen `doc_uid` in `supersedes` — so sieht die Übertragungsregel aus Abschnitt 7.4 in der Praxis aus: Der 23-Seiten-Block zerfällt, keines der Teilstücke erreicht eine Seitenüberlappung von 0,5, also bekommen alle neue UUIDs und der Vorgänger bleibt als Herkunft dokumentiert.

**`pages.jsonl`.** S. 3 trägt den Kopf `- Seite 2 -` → `header_page_number: 2`, `start_score: 0.02`: Hier darf kein Dokument beginnen. S. 6 trägt ein Datum im Kopf → `start_score: 0.9`. Diese Werte kommen aus vorhandenen OCR-Blöcken und kosten keinen zusätzlichen API-Aufruf.

## Validieren

```bash
pip install jsonschema
python - <<'PY'
import json, jsonschema
doc = json.load(open("docs/korpus/schema/document.schema.json"))
page = json.load(open("docs/korpus/schema/page.schema.json"))
org  = json.load(open("docs/korpus/schema/organizations.schema.json"))
for f, s in [("documents.jsonl", doc), ("documents.flagged.jsonl", doc), ("pages.jsonl", page)]:
    for i, line in enumerate(open(f"docs/korpus/beispiel/{f}", encoding="utf-8"), 1):
        jsonschema.validate(json.loads(line), s)
        print(f"{f}:{i} ok")
jsonschema.validate(json.load(open("docs/korpus/beispiel/organizations.json", encoding="utf-8")), org)
print("organizations.json ok")
PY
```
