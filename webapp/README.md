# OCR model comparison webapp

Local tool for visually comparing OCR model output (Datalab, MinerU,
PaddleOCR, GLM-OCR, ...) against the source PDF: page on the left with
detected boxes overlaid, extracted content on the right, numbered and synced
by hover/click — same idea as Datalab's own playground UI.

The **View** dropdown switches between three ways of comparing the current
document's models, all sharing the same document/page navigation:
- **Single** — one model, the layout described above.
- **Side-by-side** — two full model rows (PDF+boxes | content) stacked, model
  A on top and "Compare with" (model B) below, so misaligned/missed regions
  are visible at a glance without flipping the dropdown back and forth.
- **Word diff** — model A's PDF+boxes on the left; on the right, a word-level
  diff of the two models' extracted text for the current page (LCS-based,
  `diff.js`), red/struck-through for text only in A, green for text only in
  B, unstyled where they agree.

The **Light mode** checkbox toggles the theme; the choice is remembered
(`localStorage`) and otherwise defaults to the OS's `prefers-color-scheme`.
Applied via a `data-theme` attribute on `<html>` — see the inline `<script>`
at the top of `index.html` (sets it synchronously, before first paint, so
there's no flash of the wrong theme) and the `:root[data-theme="light"]`
overrides in `style.css`.

## Run

```bash
python webapp/server.py           # defaults to port 8000
```

Open http://127.0.0.1:8000/. The document list is built by scanning `data/`
fresh on every page load, so newly generated OCR output shows up on refresh
with no restart needed. `test_set` loads by default if present (falls back to
the first document found otherwise); the model dropdown always shows the raw
output-directory name (e.g. "jsonMistral", "MinerU") so it's obvious which
folder on disk a given entry came from.

## Adding a model's output

Drop the model's output next to the existing ones for a document — any of
these layouts are picked up automatically (see `manifest.py` for the exact
rules):

```
data/<dataset>/<doc_id>.pdf
data/<dataset>/<doc_id>/<model>.json        # e.g. glm.json
data/<dataset>/<doc_id>/<doc_id>.json       # datalab_convert.py's default output -> shown as "datalab"
data/<dataset>/MinerU/<doc_id>_middle.json  # MinerU's output dir, as-is
data/<dataset>/PaddleOCR/<doc_id>_<page>_res.json  # PaddleOCR's per-page output dir, as-is
data/<dataset>/markdownDatalab/<doc_id>.md  # markdown-only output (no boxes), as-is
data/<dataset>/GLM-OCR/ergebnisse/<anything>_<page>.txt  # any tool's plain-text-per-page output (no boxes), as-is
```

All but the first two match a given tool's own default output folder/file
names verbatim — just point the tool at `data/<dataset>/` and nothing needs
renaming. The last (numbered `.txt` files) works for any per-page
plain-text output, not just GLM-OCR's `ergebnisse/seite_NNN.txt`, since it's
matched by "2+ files ending in digits.txt", one level deep, not by tool name.

Images referenced from a block's `html` (`<img src="...">`) are resolved
relative to that model's own output directory, so keep them alongside the
JSON/markdown (all of the above tools already do this).

## Adding a model's JSON format

The frontend normalizes every model's output into a common shape before
rendering: `{ pages: [{ width, height, blocks: [{ id, type,
bbox: [x0,y0,x1,y1], html }] }] }` (bbox is in the same coordinate space as
the page's width/height — only the ratio matters, not the unit).

- **Single JSON file per document** (Datalab, MinerU, Mistral, Gemini): add
  an adapter in `adapters.js` — implement `matches(data)` and
  `normalize(data, pdfPageSizes)` — and register it in the `ADAPTERS` list.
  `normalize` is tried against whatever `JSON.parse` of the fetched file
  produces; auto-detected by `matches()`, no manifest changes needed as long
  as the file is named `<doc_id>.json` (or `<doc_id>/<model>.json`).
  - Mistral (`{ pages: [{ index, markdown, blocks?, dimensions? }] }`) uses
    real per-block boxes (`blocks[].top_left_x/y, bottom_right_x/y` in the
    coordinate space given by `dimensions.{width,height}`) when a page has
    them, falling back to the whole-page `markdown` blob (no boxes) for
    pages/runs that don't — the format has grown richer between runs, this
    adapter still handles the earlier markdown-only shape.
  - Gemini (`{ model, text }`) is one markdown blob for the whole document
    with `### Page N` / `# Seite N` headings as page separators — matched
    loosely (any heading level, "Page" or "Seite") since the exact wording
    has already varied between runs. No boxes; reuses `markdownToHtml()`,
    same as the markdown-only formats below, just JSON-wrapped.
- **One JSON file per page** (PaddleOCR): `matches(data)` receives the array
  of all per-page files' parsed JSON instead of a single object. Wire the
  folder up in `manifest.py`'s `_scan_dir` the way PaddleOCR's
  `<doc_id>_<page>_res.json` pattern is handled.
- **No JSON at all, one blob for the whole document** (markdownDatalab):
  bypasses adapter auto-detection entirely — see `normalizeMarkdown()` and
  the `kind: "markdown"` handling in `app.js`'s `selectModel()`. Renders as a
  single full-page block on page 1 with no boxes, since plain markdown/text
  doesn't carry per-page or per-block structure.
- **No JSON at all, one file per page** (GLM-OCR): same idea but per page —
  see `normalizeTextPages()` and `kind: "text_pages"`. Each page becomes one
  full-page block, no boxes.
- **No page-size field in the format itself** (PaddleOCR): `pdfPageSizes[i]`
  (the PDF's own page size in points, from pdf.js) is passed into
  `normalize()` as a fallback reference — see `normalizePaddleOcrPages` for
  the pattern (it also documents the empirically-derived 2x render-scale
  assumption; re-derive that constant if a different tool's output doesn't
  match it).

## Files

- `server.py` — static file server + `/api/manifest` endpoint
- `manifest.py` — scans `data/` for documents and their per-model JSON outputs
- `index.html` / `style.css` / `app.js` — the frontend
- `adapters.js` — per-model JSON → common shape normalization
- `diff.js` — word-level LCS diff between two models' extracted page text
- `sanitize.js` — whitelist HTML sanitizer for rendering block content
- `vendor/` — vendored pdf.js (ESM build)
