# Flugblatt Splitter

A local tool for manually splitting a large yearly PDF of political flyers
("Flugblätter") into individual documents. Renders every page as a thumbnail
and lets you click through them to mark and confirm cuts, then saves a
segmentation JSON. Purely manual and visual — no text extraction, no AI, no
external dependencies beyond rendering the PDF itself.

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

```sh
uvicorn flugblatt_splitter.backend.main:app --reload --port 8020
```

Then open <http://127.0.0.1:8020/> in a browser. (Port 8020 is just a
suggestion — pick any free port; `ocr_viewer/` in this repo commonly runs on
8000/8010.)

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
