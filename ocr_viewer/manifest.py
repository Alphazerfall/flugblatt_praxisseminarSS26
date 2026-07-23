"""Scans the data/ folder for PDFs and their per-model OCR JSON outputs.

For each `<dataset>/<doc_id>.pdf`, outputs are looked for directly beside it
and in any immediate subdirectory of its parent folder (one level deep).
Search is scoped per-PDF (parent dir + its immediate subdirs only) so that
documents sharing the same id across different dataset folders don't get
their outputs cross-matched.

Recognized layouts, checked per candidate directory in this order:

  1. `<doc_id>.json` (a single JSON file named after the doc id)
       data/<dataset>/<doc_id>/<doc_id>.json     # datalab_convert.py default
       data/<dataset>/output/<doc_id>.json
       data/<dataset>/jsonDatalab/<doc_id>.json
     Model name is always the containing folder name verbatim (e.g.
     "jsonDatalab", "output", or the doc id itself for the first layout
     above) — this stays a stable, unambiguous identifier ("which folder is
     this"), used for matching and deep-link URLs. The frontend applies a
     separate, purely cosmetic prettification on top for display (see
     MODEL_DISPLAY_NAMES in app.js) — it doesn't change what's sent here.

  2. `<doc_id>/<model>.json` (explicit multi-model layout, stem != doc id)
       data/<dataset>/<doc_id>/glm.json          -> model "glm"

  3. `<doc_id>_middle.json` (MinerU's richest single-file output: layout
     blocks + per-page pixel dimensions in one place)
       data/<dataset>/MinerU/<doc_id>_middle.json -> model "MinerU"
     MinerU also writes content_list*.json/model.json siblings; those are
     ignored since middle.json alone has everything the frontend needs.

  4. `<doc_id>_<page>_res.json` (PaddleOCR: one JSON per page, no layout
     classification or page-size field)
       data/<dataset>/PaddleOCR/<doc_id>_0_res.json, ..._1_res.json, ...
     These are grouped into a single model (the folder name) whose
     `json_urls` list is ordered by page number.

  5. `<doc_id>.md` (markdown-only output, no per-block boxes)
       data/<dataset>/markdownDatalab/<doc_id>.md -> model "markdownDatalab"
     Only used if the directory didn't already produce a JSON-based model.

  6. a folder of numbered `*<N>.txt` files, one page per file, filenames
     not necessarily related to the doc id (GLM-OCR: plain-text-only output,
     no boxes, no page-size field) - checked in the candidate directory
     itself and one level of its subdirectories, since tools like GLM-OCR's
     script nest their output a folder deeper (e.g. `GLM-OCR/ergebnisse/`)
       data/<dataset>/GLM-OCR/ergebnisse/seite_001.txt, seite_002.txt, ...
     Requires at least 2 matching files to avoid false positives from a
     stray single .txt file (e.g. a README).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PAGED_JSON_RE = re.compile(r"^(?P<stem>.+)_(?P<page>\d+)_.*\.json$")
PAGED_TXT_RE = re.compile(r"^.*?(?P<page>\d+)\.txt$", re.IGNORECASE)


@dataclass
class ModelOutput:
    name: str
    kind: str  # "json" | "json_pages" | "markdown" | "text_pages"
    base_dir: Path  # directory used to resolve relative image src
    json_path: Path | None = None
    json_paths: list[Path] | None = None  # kind == "json_pages", ordered by page
    md_path: Path | None = None
    txt_paths: list[Path] | None = None  # kind == "text_pages", ordered by page


@dataclass
class Document:
    id: str
    dataset: str  # dataset folder, relative to data/, used for grouping/display
    pdf_path: Path
    models: list[ModelOutput] = field(default_factory=list)


def _candidate_dirs(pdf_path: Path) -> list[Path]:
    parent = pdf_path.parent
    dirs = [parent]
    dirs.extend(p for p in parent.iterdir() if p.is_dir() and not p.name.startswith("."))
    return dirs


def _numbered_txt_files(directory: Path) -> list[tuple[int, Path]]:
    pages = []
    for txt_path in directory.glob("*.txt"):
        m = PAGED_TXT_RE.match(txt_path.name)
        if m:
            pages.append((int(m.group("page")), txt_path))
    return pages


def _scan_dir(directory: Path, doc_id: str) -> list[ModelOutput]:
    models: list[ModelOutput] = []
    found_json = False

    # 1. <doc_id>.json
    for json_path in sorted(directory.glob(f"{doc_id}.json")):
        models.append(ModelOutput(
            name=directory.name, kind="json",
            base_dir=json_path.parent, json_path=json_path,
        ))
        found_json = True

    # 2. explicit model-named files inside the doc's own same-name folder
    if directory.name == doc_id:
        for json_path in sorted(directory.glob("*.json")):
            if json_path.stem == doc_id:
                continue
            models.append(ModelOutput(
                name=json_path.stem, kind="json",
                base_dir=json_path.parent, json_path=json_path,
            ))
            found_json = True

    # 3. <doc_id>_middle.json (MinerU)
    middle_path = directory / f"{doc_id}_middle.json"
    if middle_path.is_file():
        models.append(ModelOutput(
            name=directory.name, kind="json",
            base_dir=directory, json_path=middle_path,
        ))
        found_json = True

    # 4. <doc_id>_<page>_res.json (PaddleOCR, one file per page)
    paged = []
    for json_path in directory.glob(f"{doc_id}_*.json"):
        m = PAGED_JSON_RE.match(json_path.name)
        if m and m.group("stem") == doc_id:
            paged.append((int(m.group("page")), json_path))
    if paged:
        paged.sort(key=lambda t: t[0])
        models.append(ModelOutput(
            name=directory.name, kind="json_pages",
            base_dir=directory, json_paths=[p for _, p in paged],
        ))
        found_json = True

    # 5. <doc_id>.md, only if this directory didn't already yield JSON output
    md_path = directory / f"{doc_id}.md"
    if not found_json and md_path.is_file():
        models.append(ModelOutput(
            name=directory.name, kind="markdown",
            base_dir=directory, md_path=md_path,
        ))
        found_json = True

    # 6. a folder of numbered *.txt files, checked here and one level deeper
    # (e.g. GLM-OCR/ergebnisse/seite_001.txt)
    if not found_json:
        for txt_dir in [directory, *(p for p in directory.iterdir() if p.is_dir() and not p.name.startswith("."))]:
            pages = _numbered_txt_files(txt_dir)
            if len(pages) >= 2:
                pages.sort(key=lambda t: t[0])
                models.append(ModelOutput(
                    name=directory.name, kind="text_pages",
                    base_dir=txt_dir, txt_paths=[p for _, p in pages],
                ))
                break

    return models


def scan(data_root: Path) -> list[Document]:
    documents: dict[str, Document] = {}

    for pdf_path in sorted(data_root.rglob("*.pdf")):
        doc_id = pdf_path.stem
        dataset = str(pdf_path.parent.relative_to(data_root)).replace("\\", "/")
        if dataset == ".":
            dataset = "(root)"

        doc = Document(id=doc_id, dataset=dataset, pdf_path=pdf_path)
        try:
            for directory in _candidate_dirs(pdf_path):
                doc.models.extend(_scan_dir(directory, doc_id))
        except OSError:
            # data/ is being actively written by external OCR pipeline
            # scripts while this scan runs; a directory can vanish or be
            # mid-rename between the rglob() above and here. Show the
            # document with whatever models were already found rather than
            # failing the whole /api/manifest request over one bad path.
            pass

        # de-dupe by document id; if the same id appears in two dataset
        # folders (shouldn't normally happen), keep the first and skip.
        key = f"{dataset}/{doc_id}"
        if key not in documents:
            documents[key] = doc

    return sorted(documents.values(), key=lambda d: (d.dataset, d.id))


def to_manifest_json(data_root: Path) -> dict:
    repo_root = data_root.parent

    def url_for(p: Path) -> str:
        return f"/{p.relative_to(repo_root).as_posix()}"

    docs = scan(data_root)
    out = []
    for doc in docs:
        models = []
        for m in doc.models:
            entry = {"name": m.name, "kind": m.kind, "base_url": f"{url_for(m.base_dir)}/"}
            if m.kind == "json":
                entry["json_url"] = url_for(m.json_path)
            elif m.kind == "json_pages":
                entry["json_urls"] = [url_for(p) for p in m.json_paths]
            elif m.kind == "markdown":
                entry["md_url"] = url_for(m.md_path)
            elif m.kind == "text_pages":
                entry["txt_urls"] = [url_for(p) for p in m.txt_paths]
            models.append(entry)
        out.append({
            "id": doc.id,
            "dataset": doc.dataset,
            "pdf_url": url_for(doc.pdf_path),
            "models": models,
        })
    return {"documents": out}


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent / "data"
    print(json.dumps(to_manifest_json(root), indent=2, ensure_ascii=False))
