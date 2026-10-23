# 03_eval — measuring Datalab OCR accuracy (CER)

We report the character error rate (CER) of the Datalab OCR output on the
100-page `test_set.pdf` by post-editing Datalab's own output into a gold
standard, then scoring gold vs. raw with
[dinglehopper](https://github.com/qurator-spk/dinglehopper).

## 1. Produce the gold standard (in the OCR viewer)

```bash
python ocr_viewer/server.py
```

Open <http://127.0.0.1:8000/?doc=test_set/test_set&mode=correct>, type your
initials in the **Annotator** box, and correct each block's text against the
scan. See [ocr_viewer/README.md](../../ocr_viewer/README.md) → "Correct mode"
for the editing workflow, shortcuts, status/flags, and where the annotation
JSON is autosaved:

    data/test_set/gold/annotations/<annotator>/page_<NNN>.json

A page counts as **complete** once every block is Reviewed/Illegible and
**both** layout ratings have been set — only complete pages are scored by
default.

### Migrating older annotations

Pages saved before the current layout schema carry the v1 fields
(`reading_order_correct` / `layout_has_errors` / `layout_error_note` /
`layout_reviewed`), an earlier cut (v2) that rated segmentation,
classification and reading order as three separate dimensions, or another
(v3) that combined everything into one rating. The viewer lifts any of them
to the current shape when it opens a page, so this script is only needed to
convert everything in one go rather than page by page. Run it with the
viewer closed:

```bash
python pipelines/03_eval/migrate_layout_annotations.py            # dry run
python pipelines/03_eval/migrate_layout_annotations.py --apply
```

The current schema has two ratings — `general` (layout) and `reading_order`
— sharing one note, mirroring the two-checkbox-plus-note structure ("Layout
has errors" / "Reading order correct") the annotators who didn't use this
tool actually worked with:

- **From v1**: `layout_error_note` carries over verbatim as the shared note.
  `general` is `error` if `layout_has_errors` was; `reading_order` is `error`
  if `reading_order_correct` was `false`; either is `ok` only where
  `layout_reviewed` explicitly confirmed a clean page (an untouched `true`
  was just the old default and means nothing), else `unrated`. The script's
  `READING_ORDER_OVERRIDE` table corrects the two pages found where a note
  contradicted its own flag (the annotator apparently forgot to also flip
  the checkbox) — read it before `--apply`. The old values are kept verbatim
  under `layout_legacy` either way.
- **From v2**: `general` is `error` if segmentation or classification was,
  `ok` only if both were, else `unrated`; `reading_order` carries over as its
  own dimension already was. Notes from all three, deduplicated and joined
  with " · ".
- **From v3**: if the file has `layout_legacy` (i.e. it went through v1
  first), both ratings are *re-derived* from the real v1 flags rather than
  guessed from the single combined rating — that rating alone can't say
  which aspect was the problem. Otherwise (a page created natively while v3
  was current) the single rating is mirrored onto both.

## 2. Build the dinglehopper inputs

```bash
python pipelines/03_eval/build_dinglehopper_inputs.py            # all annotators, complete pages only
python pipelines/03_eval/build_dinglehopper_inputs.py --annotator fw
python pipelines/03_eval/build_dinglehopper_inputs.py --all      # include in-progress pages too
```

This writes, per annotator, under `data/test_set/gold/eval/<annotator>/`:

- `page/gt/page_NNN.txt` + `page/ocr/page_NNN.txt` — full-page reading-order
  text. GT = non-illegible, non-spurious blocks (missed blocks included); OCR =
  non-added, non-illegible blocks. Missed regions therefore count as OCR-side
  errors and spurious regions as GT-side errors; illegible regions are dropped
  from both sides.
- `block/gt/page_NNN_bII.txt` + `block/ocr/…` — one pair per *matched* block
  (present in both), for a per-block CER distribution.
- `structural_report.csv` — one row per page: the block-level counts
  (added / missed_region / spurious_region / illegible / merge / split) plus
  the whole-page layout review: `general_rating` and `reading_order_rating`
  (each `unrated`/`ok`/`error`), `layout_note` (the shared free-text
  description, for reading rather than parsing), then `layout_schema`. The
  countable part is the ratings — `df["general_rating"].value_counts()` and
  `df["reading_order_rating"].value_counts()`, independently: a page whose
  reading order is fine but whose regions were mis-split shows up as exactly
  that, instead of one undifferentiated "layout has errors".

## 3. Score

```bash
pip install -e ".[eval]"        # installs dinglehopper (optional dep)

# one page:
dinglehopper data/test_set/gold/eval/fw/page/gt/page_001.txt \
             data/test_set/gold/eval/fw/page/ocr/page_001.txt report_001

# or let the build script run + aggregate every page pair for you:
python pipelines/03_eval/build_dinglehopper_inputs.py --score
```

`--score` runs `dinglehopper` on each page pair (reports under
`…/page/reports/`) and, if `dinglehopper-summarize` is available, aggregates
them into a single CER/WER figure — the headline number for the report.

## Whitespace

Line breaks are not recognition errors, so by default the export **collapses
runs of whitespace (incl. newlines) to a single space** in both gt and ocr
before scoring — a soft line break the OCR rendered as `<br/>` and the
annotator typed as a space contributes zero CER. (The viewer's text extraction
also turns `<br/>`/paragraph breaks into spaces, so in post-editing mode the
seeded field is already correct and needs no edit.) Pass `--keep-whitespace` to
score whitespace strictly instead.

## Calibration (inter-annotator agreement)

Three annotators independently correct the same ~5 calibration pages; because
the annotator is part of the save path, their versions coexist
(`gold/annotations/fw/…`, `gold/annotations/js/…`, …). Build/score each and
compare page CERs across annotators to sanity-check the guidelines before
splitting the remaining pages one-per-annotator.

## Further material

- `testkorpus-seiten.csv`: volume and page of each of the 100 test pages, reconstructed afterwards (report, section 3.3).
- `ocr-modelle-uebersicht.md`: the OCR candidates with benchmarks, licences and sources as of 17.08.2026 (report, section 3.4).
