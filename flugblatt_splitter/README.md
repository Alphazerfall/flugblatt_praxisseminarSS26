# Flugblatt Splitter

A local tool for manually splitting a large yearly PDF of political flyers
("Flugblätter") into individual documents. Renders every page as a thumbnail
and lets you click through them to mark and confirm cuts, then saves a
segmentation JSON. The cuts themselves are always set by hand; a review mode
walks through suspicious boundaries found by `pipelines/01_pdf/check_boundaries.py`
(see "Prüfmodus" below).

## Project structure

```
flugblatt_splitter/
  backend/
    main.py          # FastAPI app + routes
    config.py         # DATA_ROOT, thumbnail DPI — tune here
    pdf_service.py     # PyMuPDF: page count + thumbnail rendering
    segmentation.py      # segmentation JSON validation + save/load
    models.py             # Pydantic request/response schemas
  frontend/
    index.html / style.css / app.js   # plain JS, no build step
  requirements.txt
```

## Setup

From this directory (`flugblatt_splitter/`), ideally in a virtual environment:

```sh
python -m venv .venv
.venv/Scripts/activate      # Windows
# source .venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
```

## Run

Run from the **repo root** (not from inside `flugblatt_splitter/`), using the
venv's own Python so it doesn't matter whether that venv is activated:

```sh
# PowerShell / bash / Git Bash (forward slashes)
flugblatt_splitter/.venv/Scripts/python.exe -m uvicorn flugblatt_splitter.backend.main:app --reload --port 8020
```

```bat
:: cmd.exe (needs backslashes — it won't resolve a relative exe path with /)
flugblatt_splitter\.venv\Scripts\python.exe -m uvicorn flugblatt_splitter.backend.main:app --reload --port 8020
```

Then open <http://127.0.0.1:8020/> in a browser. (Port 8020 is just a
suggestion — pick any free port; `ocr_viewer/` in this repo commonly runs on
8000/8010.) `--reload` picks up backend code changes automatically;
`frontend/` files are served fresh on every request regardless, so a browser
refresh is enough to see those.

## Using it

1. Pick a PDF from the dropdown. Any `*.pdf` under this repo's `data/` folder
   is listed automatically (re-scanned on every page load, no restart
   needed). For a first smoke test, use one of the small existing samples —
   `data/test/0118_0001.pdf` or `data/test_set/test_set.pdf`. For a real
   yearly collection, drop the big PDF into `data/per_year/` (e.g.
   `data/per_year/flugblaetter_1969.pdf`).
2. The left panel is a whole-document overview, grouped into boxed sections —
   one per segment — each containing that segment's page thumbnails. Click
   any thumbnail to jump straight to that page in the detailed view on the
   right; click a page there to snap it fully into view.
3. Click the folded-corner triangle on the bottom-right of any thumbnail
   (except the document's last page) to add or remove a cut after that page.
   Segments recompute instantly as you do this — no cut is ever applied
   automatically.
4. Click **Confirm** on a segment box once you're happy with it (turns green).
5. Drag the vertical bar between the two panels to resize them — handy for
   giving the detailed view more or less width; the split is remembered
   across reloads.
6. Click **"Save JSON"** to save the segmentation next to the source PDF as
   `<pdf-name>.segments.json`. **"Load JSON"** reloads a previously saved
   segmentation for the current PDF.

## Modus „Grenzen prüfen“: verdächtige Grenzen abarbeiten

Oben links schaltet man zwischen **Schneiden** (wie bisher, ohne
Markierungen) und **Grenzen prüfen** um; die Wahl bleibt gespeichert. Im
Prüfmodus zeigt eine Leiste unter der Topbar die Verdachtsfälle des Bandes aus
`docs/korpus/segmentgrenzen.tsv` (erzeugt von
`python pipelines/01_pdf/check_boundaries.py`):

| Bedienelement | Wirkung |
|---|---|
| ▶ | nächster offener Fall; springt so, dass die Seite vor dem Übergang oben steht und die fragliche Seite darunter |
| ◀ | voriger Fall, auch ein schon entschiedener (zum Korrigieren) |
| Vorschlag, z. B. „Schnitt nach S. 215 setzen“ | übernehmen: **speichert sofort** und geht weiter |
| „Keinen Schnitt setzen“ bzw. „Schnitt behalten“ | Vorschlag ablehnen, weiter |
| „Unklar“ | Richtlinienfrage, weiter |
| „Zurücknehmen“ | Entscheidung zum aktuellen Fall zurücknehmen |

Buchstaben-Kürzel gibt es bewusst nicht, damit man ungestört Notizen tippen
kann; Pfeiltasten, <kbd>Enter</kbd> und <kbd>Strg</kbd>+<kbd>S</kbd>
funktionieren wie bisher. Die Zählung „Fall 3 von 13 · 10 offen“ bezieht sich
auf die gewählten Stufen und bleibt beim Abarbeiten stabil.

- **Markierungen:** Eine bernsteinfarbene Ecke an einer Vorschau schlägt einen
  Schnitt nach dieser Seite vor; eine leuchtende rote Ecke ist ein vermutlich
  überflüssiger Schnitt. Das Fähnchen (✂? bzw. ⇅?) sitzt auf der Seite, um deren
  Anfang es geht; Segment-Hinweise (Findmittel, „enthält anderes Blatt“) stehen
  als Chip im Kopf der Segmentbox. In der großen Ansicht steht der Beleg direkt
  über der Seite. Farbe je Stufe: rot sicher, bernstein wahrscheinlich, grau
  prüfen; Erledigtes wird blass.
- **Filter:** Standard sind die Stufen „sicher“ und „wahrscheinlich“, nur
  offene Fälle.
- **Von Hand korrigieren** geht genauso: Wer im Prüfmodus links den
  vorgeschlagenen Schnitt setzt oder entfernt (bei Segment-Hinweisen:
  irgendeinen Schnitt innerhalb des Segments), erledigt den Fall. Er wird als
  „übernommen“ festgehalten, die Segmentierung gespeichert und die Leiste
  springt zum nächsten Fall; wird der Schnitt wieder zurückgenommen, auch die
  Entscheidung. Bei Segment-Hinweisen ist das der einzige Weg, denn das
  Skript weiß nicht, an welcher Seite der Schnitt fehlt.
- **Entscheidungen** landen in `<pdf-stem>.boundary_review.json` neben dem
  PDF. Sie sind zugleich ein geprüfter Datensatz, an dem sich
  `check_boundaries.py` messen lässt.
- Nach Korrekturen in einem Band: Metadaten mit `--fresh` neu extrahieren
  (siehe `docs/korpus/segmentierungsfehler.md`).

## Segmentation JSON format

```json
{
  "source_pdf": "flugblaetter_1969.pdf",
  "created": "2026-07-21T14:10:51.032806+00:00",
  "segments": [
    { "id": 1, "title": "", "date": "", "start_page": 1, "end_page": 3, "confirmed": true }
  ]
}
```

`title`/`date` are carried through save/load for possible future manual
entry, but there's no UI to edit them yet — they're always empty unless a
previously saved file already set them.

## Tuning

- **Thumbnail DPI**: `THUMBNAIL_DPI` in `backend/config.py`.
