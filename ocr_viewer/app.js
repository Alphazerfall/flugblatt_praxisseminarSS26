import * as pdfjsLib from "/ocr_viewer/vendor/pdf.min.mjs";
import { normalize, normalizeMarkdown, normalizeTextPages, colorFor, legendEntries } from "/ocr_viewer/adapters.js";
import { sanitizeHtml } from "/ocr_viewer/sanitize.js";
import { pageText, wordDiffHtml, htmlToText, alignBlocks } from "/ocr_viewer/diff.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/ocr_viewer/vendor/pdf.worker.min.mjs";

const RENDER_SCALE = 2; // fixed internal resolution; CSS scales the canvas to fit the pane

// Presentation-only — model.name itself (the raw output folder/file name,
// e.g. "jsonQwen") stays untouched everywhere it's used as an identifier
// (matching, deep-link ?model=/&modelB= params); this only prettifies what's
// shown to the user in the Model/Compare-with dropdowns and the row labels.
const MODEL_DISPLAY_NAMES = {
  jsonDatalab: "Datalab API (JSON)",
  markdownDatalab: "Datalab API (Markdown)",
  jsonQwen: "Qwen3-VL",
  jsonClaude: "Claude Sonnet 5",
  jsonMistral: "Mistral OCR 4",
  jsonGemini: "Gemini 2.5 Pro",
  markdownMistral: "Mistral OCR 4 (Markdown)",
  PaddleOCR: "PaddleOCR-VL-1.5",
  MinerU: "MinerU2.5-Pro",
};

function displayNameFor(model) {
  return (model && MODEL_DISPLAY_NAMES[model.name]) || model?.name || "";
}

const el = {
  docSelect: document.getElementById("doc-select"),
  modelSelect: document.getElementById("model-select"),
  modelSelectB: document.getElementById("model-select-b"),
  modelBField: document.getElementById("model-b-field"),
  annotatorField: document.getElementById("annotator-field"),
  annotatorInput: document.getElementById("annotator-input"),
  annotatorProgress: document.getElementById("annotator-progress"),
  correctSidebar: document.getElementById("correct-sidebar"),
  correctProgress: document.getElementById("correct-progress"),
  pageCompleteStatus: document.getElementById("page-complete-status"),
  insertAllOcr: document.getElementById("insert-all-ocr"),
  showGoldDiff: document.getElementById("show-gold-diff"),
  showAllBoxes: document.getElementById("show-all-boxes"),
  readingOrderCorrect: document.getElementById("reading-order-correct"),
  layoutHasErrors: document.getElementById("layout-has-errors"),
  layoutErrorNote: document.getElementById("layout-error-note"),
  layoutReviewed: document.getElementById("layout-reviewed"),
  pageNote: document.getElementById("page-note"),
  correctSave: document.getElementById("correct-save"),
  compareMode: document.getElementById("compare-mode"),
  prevPage: document.getElementById("prev-page"),
  nextPage: document.getElementById("next-page"),
  pageInput: document.getElementById("page-input"),
  pageTotal: document.getElementById("page-total"),
  toggleBoxes: document.getElementById("toggle-boxes"),
  toggleBoxesField: document.getElementById("toggle-boxes-field"),
  themeToggle: document.getElementById("theme-toggle"),
  status: document.getElementById("status"),
  typeLegend: document.getElementById("type-legend"),
  main: document.getElementById("main"),
  rowB: document.getElementById("row-b"),
  rowResizer: document.getElementById("row-resizer"),
  rowLabelA: document.getElementById("row-label-a"),
  rowLabelB: document.getElementById("row-label-b"),
  contentPaneA: document.getElementById("content-pane-a"),
  diffPane: document.getElementById("diff-pane"),
  diffLegend: document.getElementById("diff-legend"),
  diffContent: document.getElementById("diff-content"),
  canvasA: document.getElementById("pdf-canvas-a"),
  overlayA: document.getElementById("overlay-a"),
  contentListA: document.getElementById("content-list-a"),
  canvasB: document.getElementById("pdf-canvas-b"),
  overlayB: document.getElementById("overlay-b"),
  contentListB: document.getElementById("content-list-b"),
};

// Two independent render "slots" — A is always shown, B only in side-by-side
// mode. Each pane tracks its own overlay-box/content-item elements so hover
// sync (setActive) doesn't cross-wire between the two.
const panes = {
  a: { key: "a", canvas: el.canvasA, ctx: el.canvasA.getContext("2d"), overlay: el.overlayA, contentList: el.contentListA, boxEls: [], itemEls: [], correctItems: [], renderTask: null },
  b: { key: "b", canvas: el.canvasB, ctx: el.canvasB.getContext("2d"), overlay: el.overlayB, contentList: el.contentListB, boxEls: [], itemEls: [], correctItems: [], renderTask: null },
};

const state = {
  manifest: null,
  doc: null, // current manifest document entry
  pdf: null, // pdfjs document proxy
  pageNum: 1, // 1-indexed, matches pdfjs
  numPages: 0,
  pdfPageSizes: [], // [{width,height}, ...] in PDF points, 0-indexed; fallback reference for formats without their own page size
  compareMode: "single", // "single" | "side" | "diff" | "diff-struct" | "correct"
  a: { model: null, data: null, baseUrl: "" },
  b: { model: null, data: null, baseUrl: "" },
  renderToken: 0, // guards against races when switching pages/models fast
  // --- correction / gold-standard mode ---
  annotator: "", // whose gold this is; goes into the save path/filename
  annotation: null, // the current page's editable annotation JSON (source of truth in memory)
  focusedBlock: -1, // index of the block whose textarea has focus (for keyboard shortcuts)
  showGoldDiff: false, // whole-page word diff of raw OCR vs correction instead of the editable list
  showAllBoxes: false, // Layout section override: show every box instead of just the selected one
};

// ---------- correction mode constants ----------
const ANNOTATOR_KEY = "ocr-annotator";
const AUTOSAVE_DELAY = 800; // ms of idle after the last keystroke before POSTing
const DATALAB_MODEL_NAME = "jsonDatalab"; // Correct mode is locked to this output
const DIFF_RAW_COLOR = "#c17b7b"; // raw OCR (removed) — matches .diff-del
const DIFF_GOLD_COLOR = "#72a396"; // correction (added) — matches .diff-ins
let saveTimer = null;

function setStatus(msg) {
  el.status.textContent = msg || "";
}

// ---------- theme ----------
// index.html applies the stored/system theme synchronously (before paint)
// via an inline <script> so there's no flash of the wrong theme; this just
// syncs the toggle's checked state to whatever was already applied and
// handles switching it afterward.
const THEME_KEY = "ocr-compare-theme";
el.themeToggle.checked = document.documentElement.dataset.theme === "light";
el.themeToggle.addEventListener("change", () => {
  const theme = el.themeToggle.checked ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
});

// ---------- pane resizer ----------
// Draggable split between the PDF pane and its content/diff pane, shared
// (via the --pane-split CSS variable on #main) across both compare rows so
// dragging either row's handle keeps both rows' PDF panes the same width —
// useful since side-by-side mode is meant for lining the two up visually.
// Persisted so it survives a reload, same pattern as the theme toggle above.
const PANE_SPLIT_KEY = "ocr-compare-pane-split";
const PANE_SPLIT_MIN = 0.2;
const PANE_SPLIT_MAX = 0.8;

function applyPaneSplit(fraction) {
  el.main.style.setProperty("--pane-split", `${fraction * 100}%`);
}

function setupPaneResizer() {
  const stored = Number(localStorage.getItem(PANE_SPLIT_KEY));
  applyPaneSplit(stored > 0 && stored < 1 ? stored : 0.5);

  for (const resizer of document.querySelectorAll(".pane-resizer")) {
    resizer.addEventListener("mousedown", (event) => {
      event.preventDefault();
      resizer.classList.add("dragging");
      const rowRect = resizer.closest(".compare-row").getBoundingClientRect();

      function onMove(moveEvent) {
        const fraction = (moveEvent.clientX - rowRect.left) / rowRect.width;
        applyPaneSplit(Math.min(PANE_SPLIT_MAX, Math.max(PANE_SPLIT_MIN, fraction)));
      }
      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        resizer.classList.remove("dragging");
        const fraction = parseFloat(getComputedStyle(el.main).getPropertyValue("--pane-split")) / 100;
        localStorage.setItem(PANE_SPLIT_KEY, String(fraction));
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }
}
setupPaneResizer();

// ---------- row resizer ----------
// Draggable split between row-a and row-b's heights, side-by-side mode only
// (the resizer and row-a's fixed flex-basis are both only active while
// #main has .split-rows — see updateLayout()). Persisted the same way as
// the pane resizer above.
const ROW_SPLIT_KEY = "ocr-compare-row-split";
const ROW_SPLIT_MIN = 0.2;
const ROW_SPLIT_MAX = 0.8;

function applyRowSplit(fraction) {
  el.main.style.setProperty("--row-split", `${fraction * 100}%`);
}

function setupRowResizer() {
  const stored = Number(localStorage.getItem(ROW_SPLIT_KEY));
  applyRowSplit(stored > 0 && stored < 1 ? stored : 0.5);

  el.rowResizer.addEventListener("mousedown", (event) => {
    event.preventDefault();
    el.rowResizer.classList.add("dragging");
    const mainRect = el.main.getBoundingClientRect();

    function onMove(moveEvent) {
      const fraction = (moveEvent.clientY - mainRect.top) / mainRect.height;
      applyRowSplit(Math.min(ROW_SPLIT_MAX, Math.max(ROW_SPLIT_MIN, fraction)));
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      el.rowResizer.classList.remove("dragging");
      const fraction = parseFloat(getComputedStyle(el.main).getPropertyValue("--row-split")) / 100;
      localStorage.setItem(ROW_SPLIT_KEY, String(fraction));
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}
setupRowResizer();

// ---------- type legend ----------
// Built once — legendEntries() is a fixed type->color mapping, the same for
// every model/page, so it belongs in the topbar rather than being rebuilt
// (identically, twice over in side-by-side mode) inside each content pane
// on every render.
function buildTypeLegend() {
  el.typeLegend.innerHTML = "";
  for (const [type, color] of legendEntries()) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `<span class="swatch" style="--c:${color}"></span>${type}`;
    el.typeLegend.appendChild(chip);
  }
}
buildTypeLegend();

// Last-resort net: data/ is rewritten live by external pipeline scripts
// while this app is open, so requests can fail in places that are awkward
// to individually guard (e.g. mid-write file reads). Without this, such a
// rejection is silent — console-only — and the UI is left looking "empty"
// with no clue why.
window.addEventListener("unhandledrejection", (event) => {
  setStatus(`Unexpected error: ${event.reason?.message || event.reason}`);
  console.error(event.reason);
});

async function loadManifest() {
  const res = await fetch("/api/manifest");
  if (!res.ok) throw new Error(`manifest request failed: ${res.status}`);
  state.manifest = await res.json();

  el.docSelect.innerHTML = "";
  const byDataset = new Map();
  for (const doc of state.manifest.documents) {
    if (!byDataset.has(doc.dataset)) byDataset.set(doc.dataset, []);
    byDataset.get(doc.dataset).push(doc);
  }
  for (const [dataset, docs] of [...byDataset.entries()].sort()) {
    const group = document.createElement("optgroup");
    group.label = dataset;
    for (const doc of docs) {
      const opt = document.createElement("option");
      opt.value = `${doc.dataset}/${doc.id}`;
      opt.textContent = `${doc.id}${doc.models.length ? "" : "  (no OCR output)"}`;
      group.appendChild(opt);
    }
    el.docSelect.appendChild(group);
  }
}

function findDoc(key) {
  return state.manifest.documents.find((d) => `${d.dataset}/${d.id}` === key);
}

function populateModelSelect(selectEl, models) {
  selectEl.innerHTML = "";
  if (models.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "(no OCR output for this document)";
    selectEl.appendChild(opt);
    selectEl.disabled = true;
    return;
  }
  selectEl.disabled = false;
  models.forEach((m, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = displayNameFor(m);
    selectEl.appendChild(opt);
  });
}

// opts.modelName / opts.modelBName let a caller (deep-link restore) pick the
// actual wanted models up front, instead of loading the defaults first and
// immediately discarding that work — for per-page formats (GLM-OCR,
// PaddleOCR) a discarded default load means dozens of wasted requests.
async function selectDocument(key, opts = {}) {
  const doc = findDoc(key);
  if (!doc) return;
  state.doc = doc;
  state.annotation = null;
  state.focusedBlock = -1;

  // Alphabetical by display name (not raw folder name, and not manifest.py's
  // filesystem scan order) — sorted in place so every other lookup that
  // indexes into doc.models (dropdown value <-> array index, deep-link
  // restore, the "pick any other model" default for slot B) stays consistent
  // with what the dropdown shows, with no separate index mapping to track.
  doc.models.sort((a, b) => displayNameFor(a).localeCompare(displayNameFor(b)));

  populateModelSelect(el.modelSelect, doc.models);
  populateModelSelect(el.modelSelectB, doc.models);

  setStatus(`Loading ${doc.id}.pdf ...`);
  state.pdf = null;
  state.numPages = 0;
  try {
    // data/ can be actively rewritten by external OCR pipeline scripts
    // while this runs, so a PDF read can transiently fail mid-write; one
    // retry after a beat is usually enough for that to have settled.
    state.pdf = await loadPdfWithRetry(doc.pdf_url);
  } catch (err) {
    setStatus(`Failed to load ${doc.id}.pdf: ${err.message}`);
    return;
  }
  state.numPages = state.pdf.numPages;
  state.pageNum = 1;
  state.pdfPageSizes = await getPdfPageSizes(state.pdf);
  setStatus("");

  const byName = (name) => name && doc.models.find((m) => m.name === name);
  // Correct mode is pinned to the Datalab output — pick it up front so we
  // don't load a different default model only to immediately swap it.
  const modelA = (state.compareMode === "correct" && datalabModel())
    || byName(opts.modelName) || doc.models[0] || null;
  const modelB = byName(opts.modelBName) || doc.models.find((m) => m !== modelA) || doc.models[0] || null;
  await setSlotModel("a", modelA);
  await setSlotModel("b", modelB);

  const idxA = doc.models.indexOf(state.a.model);
  const idxB = doc.models.indexOf(state.b.model);
  if (idxA >= 0) el.modelSelect.value = idxA;
  if (idxB >= 0) el.modelSelectB.value = idxB;

  updateLayout(); // re-assert per-mode field visibility/disabled now that models are loaded
  await renderAll();
}

async function loadPdfWithRetry(url) {
  try {
    return await pdfjsLib.getDocument({ url }).promise;
  } catch (err) {
    await new Promise((r) => setTimeout(r, 700));
    return await pdfjsLib.getDocument({ url }).promise; // let this one's rejection propagate if it also fails
  }
}

async function getPdfPageSizes(pdf) {
  const sizes = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const viewport = page.getViewport({ scale: 1 });
    sizes.push({ width: viewport.width, height: viewport.height });
  }
  return sizes;
}

async function loadModelOutput(model) {
  if (model.kind === "markdown") {
    const res = await fetch(model.md_url);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return normalizeMarkdown(await res.text(), state.numPages);
  }
  if (model.kind === "text_pages") {
    const texts = await Promise.all(model.txt_urls.map(async (url) => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
      return res.text();
    }));
    return normalizeTextPages(texts);
  }
  if (model.kind === "json_pages") {
    const jsons = await Promise.all(model.json_urls.map(async (url) => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
      return res.json();
    }));
    return normalize(jsons, state.pdfPageSizes).data;
  }
  const res = await fetch(model.json_url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return normalize(await res.json(), state.pdfPageSizes).data;
}

async function setSlotModel(slot, model) {
  const s = state[slot];
  s.model = model;
  if (!model) {
    s.data = null;
    s.baseUrl = "";
    return;
  }
  setStatus(`Loading ${displayNameFor(model)} output ...`);
  try {
    s.data = await loadModelOutput(model);
    s.baseUrl = model.base_url;
    setStatus("");
  } catch (err) {
    s.data = null;
    s.baseUrl = "";
    setStatus(`Failed to load/parse ${displayNameFor(model)} output: ${err.message}`);
  }
}

async function renderAll() {
  const token = ++state.renderToken;
  updateRowLabels();
  if (!state.pdf) return;

  try {
    await renderPanePdf(panes.a, token);
    if (token !== state.renderToken) return;
    const pageDataA = state.a.data ? state.a.data.pages[state.pageNum - 1] : null;
    renderOverlay(panes.a, pageDataA);

    if (state.compareMode === "side") {
      renderContentList(panes.a, pageDataA, state.a.baseUrl);
      await renderPanePdf(panes.b, token);
      if (token !== state.renderToken) return;
      renderPaneOverlayAndContent(panes.b, state.b.data, state.b.baseUrl);
    } else if (state.compareMode === "diff") {
      renderDiff();
    } else if (state.compareMode === "diff-struct") {
      renderStructuredDiffContent(panes.a, pageDataA, state.b.data, state.a.baseUrl, state.b.baseUrl);
    } else if (state.compareMode === "correct") {
      await ensureAnnotationForCurrentPage(pageDataA);
      if (token !== state.renderToken) return;
      renderCorrectMode(panes.a, pageDataA);
    } else {
      renderContentList(panes.a, pageDataA, state.a.baseUrl);
    }
  } catch (err) {
    // most likely the PDF page failed mid-render (e.g. data/ was being
    // rewritten by an external pipeline at the exact moment we read it) —
    // report it instead of leaving the canvas in a half-drawn state with no
    // explanation.
    setStatus(`Render failed: ${err.message}`);
    console.error(err);
    return;
  }
  if (token !== state.renderToken) return;

  el.pageInput.value = state.pageNum;
  el.pageInput.max = state.numPages;
  el.pageTotal.textContent = `/ ${state.numPages}`;
}

async function renderPanePdf(pane, token) {
  const page = await state.pdf.getPage(state.pageNum);
  if (token !== state.renderToken) return;

  // goToPage()'s click/keydown handlers fire renderAll() without awaiting
  // it, so a fast prev/next click (or Enter in the page box) can start a
  // second render on this same canvas before the first one finishes — pdf.js
  // rejects that outright ("Cannot use the same canvas during multiple
  // render() operations"). Cancel whatever's in flight on this pane first.
  if (pane.renderTask) {
    pane.renderTask.cancel();
    try {
      await pane.renderTask.promise;
    } catch {
      // expected: cancelling a RenderTask rejects its promise
    }
  }
  if (token !== state.renderToken) return; // superseded again while we waited for the cancel

  const viewport = page.getViewport({ scale: RENDER_SCALE });
  pane.canvas.width = viewport.width;
  pane.canvas.height = viewport.height;
  const task = page.render({ canvasContext: pane.ctx, viewport });
  pane.renderTask = task;
  try {
    await task.promise;
  } catch (err) {
    if (err?.name === "RenderingCancelledException") return; // a newer render took over; not a real failure
    throw err;
  } finally {
    if (pane.renderTask === task) pane.renderTask = null;
  }
}

function renderPaneOverlayAndContent(pane, modelData, baseUrl) {
  const pageData = modelData ? modelData.pages[state.pageNum - 1] : null;
  renderOverlay(pane, pageData);
  renderContentList(pane, pageData, baseUrl);
}

function setActive(pane, idx) {
  pane.boxEls.forEach((b, i) => b.classList.toggle("active", i === idx));
  pane.itemEls.forEach((c, i) => c.classList.toggle("active", i === idx));
}

function renderOverlay(pane, pageData) {
  pane.overlay.innerHTML = "";
  pane.boxEls = [];
  // Correct mode: ~20 overlapping boxes make the scan hard to read while
  // transcribing, so only the selected block's box is shown by default (see
  // .boxes-solo in style.css) — everything else stays clickable/hoverable,
  // just visually hidden until it's the active one. The Layout section's
  // "Show all boxes" override lets annotators see the whole layout at once
  // to audit it for errors. Other compare modes always show every box, since
  // that's the point of comparing detections.
  pane.overlay.classList.toggle("boxes-solo", state.compareMode === "correct" && !state.showAllBoxes);
  if (!pageData) return;

  pageData.blocks.forEach((block, i) => {
    const [x0, y0, x1, y1] = block.bbox;
    const color = colorFor(block.type);
    const box = document.createElement("div");
    box.className = "box";
    box.style.setProperty("--box-color", color);
    box.style.left = `${(x0 / pageData.width) * 100}%`;
    box.style.top = `${(y0 / pageData.height) * 100}%`;
    box.style.width = `${((x1 - x0) / pageData.width) * 100}%`;
    box.style.height = `${((y1 - y0) / pageData.height) * 100}%`;

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = i + 1;
    box.appendChild(badge);

    box.addEventListener("mouseenter", () => setActive(pane, i));
    box.addEventListener("mouseleave", () => setActive(pane, -1));
    box.addEventListener("click", () => {
      setActive(pane, i);
      pane.itemEls[i]?.scrollIntoView({ behavior: "smooth", block: "center" });
    });

    pane.overlay.appendChild(box);
    pane.boxEls.push(box);
  });
}

function renderContentList(pane, pageData, baseUrl) {
  pane.itemEls = [];
  pane.contentList.innerHTML = "";

  if (!pageData) {
    const msg = document.createElement("div");
    msg.className = "empty-msg";
    msg.textContent = state.doc && state.doc.models.length === 0
      ? "No OCR output found for this document yet."
      : "No content detected on this page.";
    pane.contentList.appendChild(msg);
    return;
  }

  pageData.blocks.forEach((block, i) => {
    const item = document.createElement("div");
    item.className = "content-item";

    const num = document.createElement("div");
    num.className = "num";
    num.style.setProperty("--box-color", colorFor(block.type));
    num.textContent = i + 1;

    const body = document.createElement("div");
    body.className = "body";
    const tag = document.createElement("div");
    tag.className = "type-tag";
    tag.textContent = block.type;
    const html = document.createElement("div");
    html.className = "html-content";
    html.innerHTML = sanitizeHtml(block.html, baseUrl);

    body.appendChild(tag);
    body.appendChild(html);
    item.appendChild(num);
    item.appendChild(body);

    item.addEventListener("mouseenter", () => setActive(pane, i));
    item.addEventListener("mouseleave", () => setActive(pane, -1));

    pane.contentList.appendChild(item);
    pane.itemEls.push(item);
  });
}

// ---------- word diff (view: diff) ----------
function diffChip(color, label) {
  const chip = document.createElement("span");
  chip.className = "chip";
  const swatch = document.createElement("span");
  swatch.className = "swatch";
  swatch.style.setProperty("--c", color);
  chip.appendChild(swatch);
  chip.append(label);
  return chip;
}

function renderDiff() {
  const pageIdx = state.pageNum - 1;
  const textA = pageText(state.a.data, pageIdx);
  const textB = pageText(state.b.data, pageIdx);

  el.diffLegend.innerHTML = "";
  el.diffLegend.appendChild(diffChip("#c17b7b", `${displayNameFor(state.a.model) || "A"} only`));
  el.diffLegend.appendChild(diffChip("#72a396", `${displayNameFor(state.b.model) || "B"} only`));

  el.diffContent.innerHTML = wordDiffHtml(textA, textB);
}

// ---------- structured diff (view: diff-struct) ----------
// Same word-level diff as renderDiff(), but keeping block structure (bbox
// overlay, type tags, per-block layout) instead of flattening the whole
// page to one text blob first. Blocks are aligned first (alignBlocks —
// block-level *similarity*, not exact match, since two models' output for
// the same paragraph is essentially never byte-identical), then each
// matched pair is word-diffed; a block that only exists in one model shows
// as a whole-block insertion/deletion instead.
//
// pane.itemEls is kept indexed by pageDataA's block index — matching
// pane.boxEls, which the ordinary renderOverlay() call in renderAll()
// already built from the same pageDataA — so hover/click sync with the
// already-drawn A-side overlay boxes keeps working completely unchanged.
// Inserted (B-only) blocks have no box to sync to, so they're appended to
// the content list's DOM but simply left out of that index.
function renderStructuredDiffContent(pane, pageDataA, modelDataB, baseUrlA, baseUrlB) {
  pane.itemEls = [];
  pane.contentList.innerHTML = "";

  const pageDataB = modelDataB ? modelDataB.pages[state.pageNum - 1] : null;
  const blocksA = pageDataA ? pageDataA.blocks : [];
  const blocksB = pageDataB ? pageDataB.blocks : [];

  if (blocksA.length === 0 && blocksB.length === 0) {
    const msg = document.createElement("div");
    msg.className = "empty-msg";
    msg.textContent = "No content detected on this page.";
    pane.contentList.appendChild(msg);
    return;
  }

  const textsA = blocksA.map((b) => htmlToText(b.html));
  const textsB = blocksB.map((b) => htmlToText(b.html));

  for (const op of alignBlocks(textsA, textsB)) {
    const item = document.createElement("div");
    item.className = "content-item";

    const num = document.createElement("div");
    num.className = "num";
    const body = document.createElement("div");
    body.className = "body";
    const tag = document.createElement("div");
    tag.className = "type-tag";
    const html = document.createElement("div");
    html.className = "html-content";
    body.appendChild(tag);
    body.appendChild(html);
    item.appendChild(num);
    item.appendChild(body);

    if (op.type === "match") {
      const blockA = blocksA[op.a];
      num.style.setProperty("--box-color", colorFor(blockA.type));
      num.textContent = op.a + 1;
      tag.textContent = blockA.type;
      html.innerHTML = wordDiffHtml(textsA[op.a], textsB[op.b]);
      item.addEventListener("mouseenter", () => setActive(pane, op.a));
      item.addEventListener("mouseleave", () => setActive(pane, -1));
      pane.itemEls[op.a] = item;
    } else if (op.type === "del") {
      const blockA = blocksA[op.a];
      item.classList.add("diff-struct-del");
      num.style.setProperty("--box-color", colorFor(blockA.type));
      num.textContent = op.a + 1;
      tag.textContent = blockA.type;
      html.innerHTML = sanitizeHtml(blockA.html, baseUrlA);
      item.addEventListener("mouseenter", () => setActive(pane, op.a));
      item.addEventListener("mouseleave", () => setActive(pane, -1));
      pane.itemEls[op.a] = item;
    } else {
      // ins — only in B, so there's no box in A's (the only PDF shown)
      // overlay for it to sync to.
      const blockB = blocksB[op.b];
      item.classList.add("diff-struct-ins");
      num.style.setProperty("--box-color", colorFor(blockB.type));
      num.textContent = "+";
      tag.textContent = blockB.type;
      html.innerHTML = sanitizeHtml(blockB.html, baseUrlB);
    }

    pane.contentList.appendChild(item);
  }
}

// ---------- correction / gold-standard mode ----------
// A new "Correct" compare mode that turns the (Datalab-only) content pane into
// an editable transcription surface, producing the gold standard we score CER
// against. Each block is a textarea seeded from the OCR text (or, in blind
// mode, empty); edits, per-block status/flags/review-state/notes, and a page
// note autosave to data/<dataset>/gold/annotations/<annotator>/page_<NNN>.json
// via the server's /api/save-annotation endpoint. Block ids are preserved 1:1
// with the OCR so scoring is a dictionary lookup, not geometric matching.
// Every per-block action (the 3-state toggle, Illegible, Insert OCR text,
// Note, Remove for added blocks) lives inline on the block itself, in its
// header row and just below its text — see renderEditableList.

function datalabModel() {
  return (state.doc && state.doc.models.find((m) => m.name === DATALAB_MODEL_NAME)) || null;
}

// Block types that aren't transcribable text (their "OCR text" is an AI image
// description, not something to correct). These get the image + an optional
// note instead of a transcription field, and are excluded from CER scoring —
// keep this list in sync with NON_TEXT_TYPES in
// pipelines/03_eval/build_dinglehopper_inputs.py.
const NON_TEXT_TYPES = new Set(["Picture", "Figure"]);
function isTextBlock(block) {
  return !NON_TEXT_TYPES.has(block.type);
}

// The bare <img> filename from a Picture block's html (which also carries an AI
// description blurb we don't want). Returned as-is; the caller prepends baseUrl.
function firstImgSrc(html) {
  const img = new DOMParser().parseFromString(html || "", "text/html").querySelector("img");
  return img?.getAttribute("src") || null;
}

function annotationUrl(annotator, page) {
  const nnn = String(page).padStart(3, "0");
  // dataset can contain spaces/parens (e.g. "raw/Nr. 001 (1967)") — encode it.
  return encodeURI(`/data/${state.doc.dataset}/gold/annotations/${annotator}/page_${nnn}.json`);
}

// The "N/M complete" counter next to the Annotator field — how many of this
// annotator's saved pages (for the current document) are marked complete.
// Refreshed on annotator change, entering Correct mode, and after each save
// (since a save is what flips a page's complete status).
async function fetchAnnotatorProgress() {
  if (!state.annotator || !state.doc) {
    el.annotatorProgress.textContent = "";
    return;
  }
  try {
    const url = `/api/annotator-progress?dataset=${encodeURIComponent(state.doc.dataset)}&annotator=${encodeURIComponent(state.annotator)}`;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(await res.text());
    const { completed } = await res.json();
    el.annotatorProgress.textContent = `${completed}/${state.numPages} complete`;
  } catch {
    el.annotatorProgress.textContent = ""; // non-essential — fail quietly
  }
}

// Three-state workflow per text block:
//   "editing" — never confirmed since it was last empty/untyped. Diff hidden
//               (so a first-time blind read isn't spoiled by the answer).
//   "pending" — confirmed at least once and has text ("Under review"); diff
//               shown and updates live. Reaching this is always automatic —
//               matching the OCR exactly is a good sign, not proof, so it's
//               never enough on its own to call something reviewed.
//   "done"    — "Reviewed": only ever set by the annotator's explicit
//               3-state toggle (sidebar) or the Reviewed control, i.e. a
//               deliberate human decision, never automatically.
// Once a block has left "editing", further edits keep it at "pending" (never
// snap back to "editing") so the diff stays visible and live while refining —
// see the textarea's `input` handler in renderEditableList.
function evaluateReview(block) {
  if (block.status === "illegible") return; // color comes from status instead; leave review as-is
  block.review = block.gt_text.trim() ? "pending" : "editing";
}

// A fresh annotation seeded from the Datalab page: every text block starts
// empty, so the annotator transcribes from the scan unanchored by the OCR
// text — that's the whole point of post-editing being post-editing rather
// than retyping. Each block's "Insert OCR text" button (and the page-level
// "Insert all OCR text") is the opt-in way to pull the OCR text in instead,
// per block or for the whole page, if that's faster for a given page.
// ocr_text is always the OCR text, derived with the *same* htmlToText the
// scoring export uses, so a block left untouched contributes zero CER rather
// than HTML-stripping noise.
function seedAnnotation(pageDataA) {
  const blocks = (pageDataA ? pageDataA.blocks : []).map((b, i) => {
    // Non-text blocks (Picture/Figure) aren't transcribed — no gt/ocr text,
    // no review workflow, just an optional note; they never enter scoring.
    if (NON_TEXT_TYPES.has(b.type)) {
      return { id: b.id, order: i, type: b.type, ocr_text: "", gt_text: "", status: "unchanged", flags: [], added: false, review: "done", note: "" };
    }
    const text = htmlToText(b.html).trim();
    return {
      id: b.id, order: i, type: b.type, ocr_text: text, gt_text: "",
      status: text ? "corrected" : "unchanged", // matches recomputeStatus's gt-vs-ocr logic, just pre-typing
      flags: [], added: false, note: "", review: "editing",
    };
  });
  return {
    annotator: state.annotator,
    dataset: state.doc.dataset,
    doc_id: state.doc.id,
    source: DATALAB_MODEL_NAME,
    page: state.pageNum,
    complete: false,
    page_note: "",
    // Layout section (sidebar): whole-page structural signals, distinct from
    // per-block text corrections — assumed fine (true/false defaults below)
    // unless the annotator flags otherwise while auditing the full layout
    // with "Show all boxes". layout_reviewed is different: it starts false
    // regardless, and is the explicit "I looked" confirmation that gates
    // page completion (see computePageComplete) — the other two fields
    // already default to "looks fine", so leaving them untouched can't be
    // told apart from having actually checked them.
    reading_order_correct: true,
    layout_has_errors: false,
    layout_error_note: "",
    layout_reviewed: false,
    updated_at: null,
    blocks,
  };
}

async function loadAnnotationForCurrentPage(pageDataA) {
  const seed = seedAnnotation(pageDataA);
  if (!state.annotator) {
    state.annotation = seed; // shown read-only until an annotator is set
    return;
  }
  try {
    const res = await fetch(annotationUrl(state.annotator, state.pageNum), { cache: "no-store" });
    if (res.ok) {
      const saved = await res.json();
      // Trust the saved gold (gt_text/status/flags/added/page_note/complete);
      // it's the source of truth for a resumed page. Guard only against an
      // empty/garbage file by falling back to the seed.
      if (saved && Array.isArray(saved.blocks) && saved.blocks.length) {
        // ocr_text is a derived baseline, not user data — refresh it from the
        // current extraction (by block id) so pages saved before an
        // htmlToText fix pick it up too. Never touches gt_text/status/flags.
        const ocrById = new Map((pageDataA?.blocks || []).map((b) => [b.id, htmlToText(b.html).trim()]));
        for (const b of saved.blocks) {
          if (!Array.isArray(b.flags)) b.flags = [];
          if (typeof b.note !== "string") b.note = "";
          if (NON_TEXT_TYPES.has(b.type)) {
            b.ocr_text = "";
            b.review = "done";
            continue;
          }
          if (!b.added && ocrById.has(b.id)) b.ocr_text = ocrById.get(b.id);
          // Migrate files saved before the review-state model (which had a
          // `confirmed` boolean instead of a 3-state `review`) — evaluateReview
          // derives it purely from whether there's text, so it's a safe default.
          if (!b.review) evaluateReview(b);
          delete b.confirmed;
        }
        // Layout fields didn't exist in older saved files — default them in
        // rather than leaving them undefined (undefined reads as unchecked
        // for the two booleans, which happens to be the wrong default for
        // reading_order_correct).
        if (typeof saved.reading_order_correct !== "boolean") saved.reading_order_correct = true;
        if (typeof saved.layout_has_errors !== "boolean") saved.layout_has_errors = false;
        if (typeof saved.layout_error_note !== "string") saved.layout_error_note = "";
        if (typeof saved.layout_reviewed !== "boolean") saved.layout_reviewed = false;
        state.annotation = saved;
      } else {
        state.annotation = seed;
      }
    } else {
      state.annotation = seed; // 404 = not started yet
    }
  } catch {
    state.annotation = seed;
  }
}

// Avoid re-fetching (and discarding unsaved in-memory edits) on renders that
// don't change the page — e.g. toggling the whole-page diff. Only (re)load when
// the loaded annotation doesn't match the current doc/annotator/page.
async function ensureAnnotationForCurrentPage(pageDataA) {
  const a = state.annotation;
  if (a && a.page === state.pageNum && a.annotator === state.annotator && a.dataset === state.doc.dataset) return;
  await loadAnnotationForCurrentPage(pageDataA);
}

function recomputeStatus(block) {
  if (block.status === "illegible") return; // sticky until explicitly cleared
  block.status = block.gt_text.trim() === block.ocr_text.trim() ? "unchanged" : "corrected";
}

// Blocks joined in reading order, for the whole-page raw-vs-gold word diff.
// Mirrors the scoring export: raw = every non-added, non-illegible block's OCR
// text; gold = every non-illegible, non-spurious block's corrected text
// (added/missed blocks included). So missed regions show as insertions,
// spurious as deletions, and illegible regions drop out of both.
function correctPageTexts() {
  const blocks = state.annotation ? [...state.annotation.blocks].sort((x, y) => x.order - y.order) : [];
  const raw = blocks.filter((b) => !b.added && b.status !== "illegible").map((b) => b.ocr_text.trim()).filter(Boolean).join("\n\n");
  const gold = blocks
    .filter((b) => b.status !== "illegible" && !b.flags.includes("spurious_region"))
    .map((b) => b.gt_text.trim())
    .filter(Boolean)
    .join("\n\n");
  return { raw, gold };
}

function renderCorrectMode(pane, pageDataA) {
  updateCorrectSidebar();
  if (!datalabModel()) {
    renderCorrectMessage(pane, `Correct mode needs the Datalab ("${DATALAB_MODEL_NAME}") output for this document.`);
    state.focusedBlock = -1; // this document has nothing to show
    return;
  }
  if (state.showGoldDiff) {
    renderGoldDiff();
  } else {
    renderEditableList(pane, pageDataA);
  }
}

function renderCorrectMessage(pane, text) {
  pane.itemEls = [];
  pane.contentList.innerHTML = "";
  const msg = document.createElement("div");
  msg.className = "empty-msg";
  msg.textContent = text;
  pane.contentList.appendChild(msg);
}

function renderGoldDiff() {
  const { raw, gold } = correctPageTexts();
  el.diffLegend.innerHTML = "";
  el.diffLegend.appendChild(diffChip(DIFF_RAW_COLOR, "raw OCR (removed)"));
  el.diffLegend.appendChild(diffChip(DIFF_GOLD_COLOR, "correction (added)"));
  el.diffContent.innerHTML = wordDiffHtml(raw, gold);
}

// The editable list is rendered in reading order (block.order), with any
// annotator-added blocks interleaved among the original Datalab ones. Two
// indices are kept, because those two orders diverge once a block is added:
//   - pane.itemEls[boxIndex]     — sparse, only original blocks; parallels
//     pane.boxEls so hover/click sync with the overlay (via setActive) stays
//     correct even with added blocks in between.
//   - pane.correctItems[readingPos] — every item in DOM order, for keyboard
//     navigation and "add after focused".
function renderEditableList(pane, pageDataA) {
  pane.itemEls = [];
  pane.correctItems = [];
  pane.contentList.innerHTML = "";
  const editable = Boolean(state.annotator);
  const blocks = state.annotation ? state.annotation.blocks : [];

  if (blocks.length === 0) {
    renderCorrectMessage(pane, "No content detected on this page by Datalab.");
    return;
  }

  let boxCounter = 0; // original blocks are 0,1,2,… in reading order == their box index
  blocks.forEach((block) => {
    const boxIndex = block.added ? -1 : boxCounter++;
    const readingPos = pane.correctItems.length;

    const item = document.createElement("div");
    item.className = "content-item correct-item";
    item.dataset.status = block.status;
    if (isTextBlock(block)) item.dataset.review = block.review;
    item.style.setProperty("--box-color", colorFor(block.type));

    const num = document.createElement("div");
    num.className = "num";
    num.style.setProperty("--box-color", colorFor(block.type));
    num.textContent = block.added ? "+" : boxIndex + 1;

    const body = document.createElement("div");
    body.className = "body";

    // Header row: type, the 3-state toggle + Illegible, and (pushed to the
    // far right) the Insert-OCR-text button — all in one line per block, so
    // every control for a block lives right on it instead of requiring a
    // trip to the sidebar.
    const header = document.createElement("div");
    header.className = "block-header";

    const tag = document.createElement("div");
    tag.className = "type-tag";
    tag.textContent = block.added ? `${block.type} · added` : block.type;
    header.appendChild(tag);

    body.appendChild(header);

    // Focusing any field in a block highlights its box and marks this block
    // as the current one — same idea as flugblatt_splitter's "current page"
    // indicator: scrolled to the top of the list, no DOM reordering, just
    // scroll position + a highlight (here, the review-color outline).
    const syncOnFocus = () => {
      state.focusedBlock = readingPos;
      if (boxIndex >= 0) {
        setActive(pane, boxIndex);
        scrollBoxIntoView(pane, boxIndex);
      } else {
        setActive(pane, -1); // added block has no box to sync to
      }
      for (const el of pane.contentList.querySelectorAll(".current-block")) el.classList.remove("current-block");
      item.classList.add("current-block");
      item.scrollIntoView({ behavior: "smooth", block: "start" });
    };

    let navField; // where Tab / Ctrl+Enter keyboard nav lands for this block
    // Reassigned inside the text-block branch; a no-op default for non-text
    // blocks (they have no toggle/illegible UI to refresh).
    let refresh = () => {};

    if (isTextBlock(block)) {
      const textarea = document.createElement("textarea");
      textarea.className = "gt-input";
      textarea.value = block.gt_text;
      textarea.rows = 1; // real height set by autoGrow() once it's in the DOM
      textarea.spellcheck = false;

      const diffStrip = document.createElement("div");
      diffStrip.className = "gt-diff";

      // The 3-state toggle (Editing / Under review / Reviewed) + Illegible,
      // inline in the header so every control for a block lives on the block
      // itself. Clicking either does a surgical DOM update via refresh()
      // below — never a full renderAll() — so the list doesn't reshuffle or
      // reset scroll position just because one block's state changed.
      // tabIndex = -1 on every small control below (toggle, illegible, insert,
      // remove, note) keeps them mouse-clickable but out of the Tab sequence,
      // so Tab/Shift+Tab jump straight from one block's main field to the
      // next's, as advertised, instead of first stepping through each
      // block's handful of buttons.
      const reviewToggle = document.createElement("div");
      reviewToggle.className = "review-toggle inline";
      const reviewButtons = ["editing", "pending", "done"].map((value) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.tabIndex = -1;
        btn.dataset.value = value;
        btn.textContent = REVIEW_LABELS[value];
        btn.addEventListener("click", () => {
          if (btn.disabled) return;
          setReviewState(block, value);
          refresh();
        });
        reviewToggle.appendChild(btn);
        return btn;
      });

      const illegibleBtn = document.createElement("button");
      illegibleBtn.type = "button";
      illegibleBtn.tabIndex = -1;
      illegibleBtn.className = "illegible-btn";
      illegibleBtn.textContent = "Illegible";
      illegibleBtn.title = "Source can't be read — excluded from scoring";
      illegibleBtn.addEventListener("click", () => {
        toggleIllegible(block);
        refresh();
      });

      // Single source of truth for this block's DOM state, called after
      // every mutation (typing, blur, toggle clicks) instead of duplicating
      // the same handful of updates in each handler.
      refresh = function () {
        item.dataset.status = block.status;
        item.dataset.review = block.review;
        const disabled = !editable || block.status === "illegible";
        textarea.disabled = disabled;
        for (const btn of reviewButtons) {
          btn.classList.toggle("active", btn.dataset.value === block.review);
          btn.disabled = disabled;
        }
        illegibleBtn.classList.toggle("active", block.status === "illegible");
        illegibleBtn.disabled = !editable;
        if (importBtn) importBtn.disabled = disabled;
        updateDiffStrip(item, block);
        updateCorrectSidebar(); // progress counts / completion status depend on review states
      }

      // Only re-evaluate on blur if something was actually typed during this
      // focus session. Otherwise merely passing through an untouched block —
      // e.g. Ctrl+Enter repeating while held, or landing on it and tabbing
      // straight past — would blur it too, and unconditionally evaluating on
      // every blur would wrongly flag an untouched blind field as "needs
      // review" just because focus visited it, not because it was confirmed.
      let dirty = false;
      textarea.addEventListener("focus", () => {
        dirty = false;
        syncOnFocus();
      });
      textarea.addEventListener("input", () => {
        dirty = true;
        block.gt_text = textarea.value;
        recomputeStatus(block);
        // Once a block has left "editing" (confirmed at least once), further
        // edits keep it at "pending" rather than snapping back to "editing" —
        // that's what keeps the diff visible and live-updating while
        // refining an already-reviewed-ish block. Only a still-pristine,
        // never-confirmed block (still "editing") stays there, so a first
        // blind read isn't spoiled by the diff appearing mid-keystroke.
        if (block.status !== "illegible" && block.review !== "editing") block.review = "pending";
        autoGrow(textarea);
        refresh();
        scheduleSave();
      });
      textarea.addEventListener("blur", () => {
        if (dirty) {
          // Finishing a block for the first time confirms it — moves it from
          // "editing" to "pending" ("Under review") and reveals the diff.
          // Never auto-promotes to "Reviewed": matching the OCR exactly is a
          // good sign, not proof, so only the 3-state toggle can mark
          // something Reviewed.
          evaluateReview(block);
          refresh();
          scheduleSave();
        }
        flushSave();
      });

      // One-click accept: copies the OCR text in as-is (useful when it's
      // already correct — no need to retype it). Same as confirming any
      // other edit: moves to "Under review", not straight to "Reviewed" —
      // still requires the explicit toggle.
      let importBtn = null;
      if (!block.added && block.ocr_text) {
        importBtn = document.createElement("button");
        importBtn.type = "button";
        importBtn.tabIndex = -1;
        importBtn.className = "import-ocr-btn";
        importBtn.textContent = "Insert OCR text";
        importBtn.title = "Copy the OCR text into this field";
        importBtn.addEventListener("click", () => {
          textarea.value = block.ocr_text;
          block.gt_text = block.ocr_text;
          recomputeStatus(block);
          evaluateReview(block);
          autoGrow(textarea);
          refresh();
          scheduleSave();
          textarea.focus();
        });
      }

      // Only annotator-added (missed) blocks can be removed — mutually
      // exclusive with importBtn (an added block has no OCR text to insert),
      // so both share the same pushed-right slot.
      let removeBlockBtn = null;
      if (block.added) {
        removeBlockBtn = document.createElement("button");
        removeBlockBtn.type = "button";
        removeBlockBtn.tabIndex = -1;
        removeBlockBtn.className = "remove-block-btn";
        removeBlockBtn.textContent = "✕ Remove block";
        removeBlockBtn.addEventListener("click", () => {
          const idx = state.annotation.blocks.indexOf(block);
          if (idx >= 0) state.annotation.blocks.splice(idx, 1);
          state.focusedBlock = -1;
          scheduleSave();
          renderAll();
        });
      }

      header.appendChild(reviewToggle);
      header.appendChild(illegibleBtn);
      if (importBtn) header.appendChild(importBtn);
      if (removeBlockBtn) header.appendChild(removeBlockBtn);

      refresh(); // set initial disabled/active states from the block's current data

      body.appendChild(textarea);
      body.appendChild(diffStrip);
      navField = textarea;
    } else {
      // Non-text block (Picture/Figure): show the image itself instead of a
      // transcription field. Not scored. Only the <img> is rendered — not
      // Datalab's AI alt-text description blurb, which isn't useful here.
      // Its Note (added below, same as text blocks) is its only annotation.
      const media = document.createElement("div");
      media.className = "gt-media";
      media.tabIndex = 0; // focusable: selects the block so the sidebar shows/edits its note
      const pd = boxIndex >= 0 ? pageDataA?.blocks?.[boxIndex] : null;
      const src = pd ? firstImgSrc(pd.html) : null;
      if (src) {
        const img = document.createElement("img");
        img.src = state.a.baseUrl + src;
        img.alt = "";
        media.appendChild(img);
      } else {
        media.classList.add("empty-msg");
        media.textContent = "(no image)";
      }
      media.addEventListener("focus", syncOnFocus);

      body.appendChild(media);
      navField = media;
    }

    // Note: collapsed behind a small "+ Add note" button unless it already
    // has content (e.g. a resumed page) or the annotator explicitly opens
    // it; "✕" clears and collapses it again. Shared by both branches above.
    const addNoteBtn = document.createElement("button");
    addNoteBtn.type = "button";
    addNoteBtn.tabIndex = -1;
    addNoteBtn.className = "add-note-btn";
    addNoteBtn.textContent = "+ Add note";

    const noteField = document.createElement("div");
    noteField.className = "block-note-field";
    const noteInput = document.createElement("textarea");
    noteInput.className = "block-note-input";
    noteInput.tabIndex = -1;
    noteInput.placeholder = "optional note about this block";
    noteInput.value = block.note || "";
    noteInput.rows = 1;
    noteInput.spellcheck = false;
    noteInput.addEventListener("focus", syncOnFocus);
    noteInput.addEventListener("input", () => {
      block.note = noteInput.value;
      autoGrow(noteInput);
      scheduleSave();
    });
    noteInput.addEventListener("blur", () => flushSave());

    const removeNoteBtn = document.createElement("button");
    removeNoteBtn.type = "button";
    removeNoteBtn.tabIndex = -1;
    removeNoteBtn.className = "remove-note-btn";
    removeNoteBtn.textContent = "✕";
    removeNoteBtn.title = "Remove note";
    removeNoteBtn.addEventListener("click", () => {
      block.note = "";
      noteInput.value = "";
      noteField.hidden = true;
      addNoteBtn.hidden = false;
      scheduleSave();
    });
    noteField.appendChild(noteInput);
    noteField.appendChild(removeNoteBtn);

    addNoteBtn.addEventListener("click", () => {
      addNoteBtn.hidden = true;
      noteField.hidden = false;
      autoGrow(noteInput);
      noteInput.focus();
    });

    const hasNote = Boolean(block.note);
    addNoteBtn.hidden = hasNote;
    noteField.hidden = !hasNote;

    body.appendChild(addNoteBtn);
    body.appendChild(noteField);

    item.appendChild(num);
    item.appendChild(body);
    pane.contentList.appendChild(item);
    if (navField.tagName === "TEXTAREA") autoGrow(navField); // size to content now it's laid out
    if (hasNote) autoGrow(noteInput); // same reason — needs to be attached first to measure scrollHeight
    if (boxIndex >= 0) pane.itemEls[boxIndex] = item;
    pane.correctItems.push({ block, textarea: navField, boxIndex, refresh });
    updateDiffStrip(item, block); // no-op for non-text blocks (no .gt-diff)
  });
}

// Helpers shared by the per-block controls built inline in renderEditableList
// (the 3-state toggle, Illegible, Insert OCR text, Note, Remove).

const REVIEW_LABELS = { editing: "Editing", pending: "Under review", done: "Reviewed" };
// Alt+1/2/3 jump the focused block to a review state directly.
const REVIEW_KEYS = { 1: "editing", 2: "pending", 3: "done" };

// Every block resolved — reviewed (or illegible, which excludes it from
// scoring rather than requiring review). No manual toggle for this half:
// each block already has to be confirmed on its own.
function blocksAllReviewed(annotation) {
  if (!annotation) return false;
  return annotation.blocks
    .filter(isTextBlock)
    .every((b) => b.status === "illegible" || b.review === "done");
}

// A page is complete once every block is resolved *and* the annotator has
// explicitly confirmed they checked the page's reading order and layout.
// That second half is a deliberate, forced gate — reading_order_correct and
// layout_has_errors already default to "looks fine", so leaving them
// untouched can't be told apart from having actually checked; layout_reviewed
// starts false and only the annotator ticking it moves it to true.
function computePageComplete(annotation) {
  return Boolean(annotation) && blocksAllReviewed(annotation) && annotation.layout_reviewed === true;
}

function toggleIllegible(block) {
  if (block.status === "illegible") {
    recomputeStatusForce(block);
    evaluateReview(block);
  } else {
    block.status = "illegible";
  }
  scheduleSave();
}

// Manual override for a "pending" block once the annotator has looked at the
// diff and is satisfied — flips it to "done" (or back, if they change their
// mind). Only meaningful once a block has been confirmed at least once.
// The 3-state toggle in the sidebar (Editing / Under review / Reviewed) sets
// the review state directly — a deliberate manual override, not a checkbox
// toggle, so the annotator can jump to any of the three states at any time
// (e.g. force something Reviewed without editing it, or send a mistakenly
// Reviewed block back to Under review).
function setReviewState(block, value) {
  if (block.status === "illegible") return; // illegible is a separate, sticky override
  block.review = value;
  scheduleSave();
}

function recomputeStatusForce(block) {
  block.status = block.gt_text.trim() === block.ocr_text.trim() ? "unchanged" : "corrected";
}

function updateDiffStrip(item, block) {
  const strip = item.querySelector(".gt-diff");
  if (!strip) return;
  // Revealed once the block leaves "editing", i.e. after the annotator
  // finishes typing it for the first time, so the OCR text isn't shown while
  // they're still transcribing. Shown even on an exact match — the OCR text
  // reads back plain (all-equal), confirming the transcription agrees.
  const show = !block.added && block.review !== "editing" && block.status !== "illegible";
  strip.hidden = !show;
  strip.classList.toggle("matched", block.gt_text.trim() === block.ocr_text.trim());
  strip.innerHTML = show ? wordDiffHtml(block.ocr_text, block.gt_text) : "";
}

function autoGrow(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function scrollBoxIntoView(pane, i) {
  pane.boxEls[i]?.scrollIntoView({ block: "center", inline: "nearest" });
}

// Bulk version of the per-block "Insert OCR text" button: overwrites every
// original (non-added), non-illegible text block's gt_text with its OCR
// text. A quick way to seed a whole page from the OCR baseline (e.g. to
// switch a mostly-correct page from blind to post-editing) rather than
// clicking through each block individually — deliberately overwrites
// whatever's already there, same as the per-block button does.
function insertAllOcrText() {
  if (!state.annotation || !state.annotator) return;
  for (const block of state.annotation.blocks) {
    if (!isTextBlock(block) || block.added || block.status === "illegible") continue;
    block.gt_text = block.ocr_text;
    recomputeStatus(block);
    evaluateReview(block);
  }
  scheduleSave();
  renderAll();
}

function updateCorrectSidebar() {
  const a = state.annotation;
  const blocks = a ? a.blocks : [];
  const textBlocks = blocks.filter(isTextBlock);
  const done = textBlocks.filter((b) => b.status !== "illegible" && b.review === "done").length;
  const pending = textBlocks.filter((b) => b.status !== "illegible" && b.review === "pending").length;
  const editing = textBlocks.filter((b) => b.status !== "illegible" && b.review === "editing").length;
  const illegible = blocks.filter((b) => b.status === "illegible").length;
  const added = blocks.filter((b) => b.added).length;
  // Each count is its own chip (not one string joined with " · ") so
  // wrapping in the narrow sidebar breaks between whole counts, never
  // mid-phrase — a dot color-codes each to match its review state.
  el.correctProgress.innerHTML = "";
  const chips = [
    ["done", done, "reviewed"],
    ["pending", pending, "under review"],
    ["editing", editing, "editing"],
  ];
  if (illegible) chips.push(["illegible", illegible, "illegible"]);
  if (added) chips.push([null, added, "added"]);
  for (const [reviewValue, count, label] of chips) {
    const chip = document.createElement("span");
    chip.className = "progress-chip";
    if (reviewValue) {
      const dot = document.createElement("span");
      dot.className = "progress-dot";
      dot.dataset.review = reviewValue;
      chip.appendChild(dot);
    }
    chip.append(`${count} ${label}`);
    el.correctProgress.appendChild(chip);
  }

  // Read-only, derived — no manual toggle for the block half; the layout
  // half is gated on the explicit "I've checked..." checkbox below. The
  // message says *which* half is still open, since "not complete" alone
  // doesn't explain why once there are two independent conditions.
  const blocksOk = blocksAllReviewed(a);
  const layoutOk = Boolean(a && a.layout_reviewed);
  const complete = blocksOk && layoutOk;
  let statusText = "";
  if (a && blocks.length) {
    if (complete) statusText = "Page complete";
    else if (!blocksOk && !layoutOk) statusText = "Not complete — blocks + layout review pending";
    else if (!blocksOk) statusText = "Not complete — blocks pending";
    else statusText = "Not complete — layout review pending";
  }
  el.pageCompleteStatus.textContent = statusText;
  el.pageCompleteStatus.dataset.complete = complete ? "yes" : "no";

  el.pageNote.value = a ? a.page_note || "" : "";
  el.pageNote.disabled = !state.annotator;
  el.insertAllOcr.disabled = !state.annotator;
  el.showGoldDiff.checked = state.showGoldDiff;

  el.showAllBoxes.checked = state.showAllBoxes;
  el.readingOrderCorrect.checked = a ? a.reading_order_correct !== false : true;
  el.readingOrderCorrect.disabled = !state.annotator;
  el.layoutHasErrors.checked = Boolean(a && a.layout_has_errors);
  el.layoutHasErrors.disabled = !state.annotator;
  el.layoutErrorNote.value = a ? a.layout_error_note || "" : "";
  el.layoutErrorNote.disabled = !state.annotator;
  el.layoutReviewed.checked = layoutOk;
  el.layoutReviewed.disabled = !state.annotator;

  if (!state.annotator) setSaveState("no-annotator");
  else if (!el.correctSave.dataset.state) setSaveState("idle");
}

function setSaveState(kind, detail) {
  const labels = {
    idle: "",
    saving: "Saving…",
    saved: "Saved",
    error: `Save failed: ${detail || ""}`,
    "no-annotator": "Enter an annotator name to begin.",
  };
  el.correctSave.dataset.state = kind;
  el.correctSave.textContent = labels[kind] ?? "";
}

function scheduleSave() {
  if (!state.annotation) return;
  state.annotation.complete = computePageComplete(state.annotation);
  state.annotation.updated_at = new Date().toISOString();
  if (!state.annotator) {
    setSaveState("no-annotator");
    return;
  }
  setSaveState("saving");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, AUTOSAVE_DELAY);
}

async function saveNow() {
  clearTimeout(saveTimer);
  saveTimer = null;
  if (!state.annotator || !state.annotation) return;
  try {
    const res = await fetch("/api/save-annotation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.annotation),
    });
    if (!res.ok) throw new Error(await res.text());
    setSaveState("saved");
    fetchAnnotatorProgress(); // a save is what can flip a page's complete status
  } catch (err) {
    setSaveState("error", err.message);
  }
}

// Force a pending debounced save to happen now — on blur, page/annotator
// switch, and before unload, so nothing in flight is lost.
function flushSave() {
  if (saveTimer) saveNow();
}

async function enterCorrectMode() {
  const dl = datalabModel();
  if (dl && state.a.model !== dl) {
    await setSlotModel("a", dl);
    const idx = state.doc.models.indexOf(dl);
    if (idx >= 0) el.modelSelect.value = idx;
  }
  state.annotation = null; // force a fresh load for the current page
  state.focusedBlock = -1;
  fetchAnnotatorProgress();
}

// ---------- view mode ----------
function updateLayout() {
  const mode = state.compareMode;
  const correct = mode === "correct";
  // In Correct mode the middle pane is either the editable block list
  // (content-pane-a) or, when "Show diff vs raw OCR" is on, the flat word-diff
  // pane (diff-pane) — same two panes the diff modes already use.
  const showDiffPane = mode === "diff" || (correct && state.showGoldDiff);
  el.rowB.hidden = mode !== "side";
  el.rowResizer.hidden = mode !== "side";
  el.main.classList.toggle("split-rows", mode === "side");
  el.diffPane.hidden = !showDiffPane;
  el.contentPaneA.hidden = showDiffPane;
  el.modelBField.hidden = mode === "single" || correct;
  el.annotatorField.hidden = !correct;
  el.correctSidebar.hidden = !correct;
  // Model A is pinned to Datalab in Correct mode; re-enable otherwise unless
  // the current document simply has no OCR output.
  el.modelSelect.disabled = correct || !(state.doc && state.doc.models.length);
  // Extra bottom padding so the last block can be scrolled up to the top of
  // the pane instead of being stuck at the bottom with nothing left to
  // scroll past it.
  el.contentListA.classList.toggle("scroll-pad", correct);
  // "Show all boxes" (Layout section) is the only box toggle in Correct mode —
  // hide the topbar's and force the overlay on so it can't be left blank.
  el.toggleBoxesField.hidden = correct;
  if (correct) {
    el.overlayA.style.display = "";
    el.overlayB.style.display = "";
  } else {
    el.overlayA.style.display = el.toggleBoxes.checked ? "" : "none";
    el.overlayB.style.display = el.toggleBoxes.checked ? "" : "none";
  }
}

// row-a is always model A; row-b (side-by-side only) is always model B —
// labelled so it's clear which is which without cross-checking the Model /
// Compare-with dropdowns.
function updateRowLabels() {
  el.rowLabelA.textContent = state.a.model ? `A: ${displayNameFor(state.a.model)}` : "";
  el.rowLabelB.textContent = state.b.model ? `B: ${displayNameFor(state.b.model)}` : "";
}

// ---------- deep-linking (?doc=<dataset>/<id>&model=<name>&mode=<m>&modelB=<name>&page=<n>) ----------
function updateUrl() {
  const params = new URLSearchParams();
  if (state.doc) params.set("doc", `${state.doc.dataset}/${state.doc.id}`);
  if (state.a.model) params.set("model", state.a.model.name);
  if (state.compareMode !== "single") {
    params.set("mode", state.compareMode);
    if (state.b.model) params.set("modelB", state.b.model.name);
  }
  if (state.pageNum) params.set("page", state.pageNum);
  history.replaceState(null, "", `?${params.toString()}`);
}

// ---------- wiring ----------
el.docSelect.addEventListener("change", async () => {
  await selectDocument(el.docSelect.value);
  if (state.compareMode === "correct") fetchAnnotatorProgress(); // scoped per document/dataset
  updateUrl();
});
el.modelSelect.addEventListener("change", async () => {
  await setSlotModel("a", state.doc?.models[Number(el.modelSelect.value)]);
  await renderAll();
  updateUrl();
});
el.modelSelectB.addEventListener("change", async () => {
  await setSlotModel("b", state.doc?.models[Number(el.modelSelectB.value)]);
  await renderAll();
  updateUrl();
});
el.compareMode.addEventListener("change", async () => {
  flushSave(); // may be leaving Correct mode with an edit still pending
  state.compareMode = el.compareMode.value;
  if (state.compareMode === "correct") await enterCorrectMode();
  updateLayout();
  await renderAll();
  updateUrl();
});

// ---------- correction-mode wiring ----------
state.annotator = (localStorage.getItem(ANNOTATOR_KEY) || "").trim();
el.annotatorInput.value = state.annotator;
el.annotatorInput.addEventListener("change", async () => {
  flushSave();
  state.annotator = el.annotatorInput.value.trim();
  localStorage.setItem(ANNOTATOR_KEY, state.annotator);
  state.annotation = null; // reload this page's gold under the new annotator
  state.focusedBlock = -1;
  fetchAnnotatorProgress();
  if (state.compareMode === "correct") await renderAll();
});
el.insertAllOcr.addEventListener("click", () => insertAllOcrText());

// ---------- Layout section ----------
// "Show all boxes" is a viewing preference, not part of the gold standard —
// not persisted into the annotation JSON, just localStorage.
const SHOW_ALL_BOXES_KEY = "ocr-show-all-boxes";
state.showAllBoxes = localStorage.getItem(SHOW_ALL_BOXES_KEY) === "1";
el.showAllBoxes.checked = state.showAllBoxes;
el.showAllBoxes.addEventListener("change", async () => {
  state.showAllBoxes = el.showAllBoxes.checked;
  localStorage.setItem(SHOW_ALL_BOXES_KEY, state.showAllBoxes ? "1" : "0");
  await renderAll();
});
// reading_order_correct / layout_has_errors / layout_error_note *are* part of
// the gold standard (whole-page structural signals, not tied to one block) —
// persisted the same way as page_note.
el.readingOrderCorrect.addEventListener("change", () => {
  if (!state.annotation) return;
  state.annotation.reading_order_correct = el.readingOrderCorrect.checked;
  scheduleSave();
});
el.layoutHasErrors.addEventListener("change", () => {
  if (!state.annotation) return;
  state.annotation.layout_has_errors = el.layoutHasErrors.checked;
  scheduleSave();
});
el.layoutErrorNote.addEventListener("input", () => {
  if (!state.annotation) return;
  state.annotation.layout_error_note = el.layoutErrorNote.value;
  scheduleSave();
});
el.layoutErrorNote.addEventListener("blur", () => flushSave());
el.layoutReviewed.addEventListener("change", () => {
  if (!state.annotation) return;
  state.annotation.layout_reviewed = el.layoutReviewed.checked;
  scheduleSave();
  updateCorrectSidebar(); // the completion status message depends on this
});

el.showGoldDiff.addEventListener("change", async () => {
  state.showGoldDiff = el.showGoldDiff.checked;
  updateLayout();
  await renderAll();
});
el.pageNote.addEventListener("input", () => {
  if (!state.annotation) return;
  state.annotation.page_note = el.pageNote.value;
  scheduleSave();
});

// Keyboard shortcuts, active only in Correct mode. Tab/Shift+Tab are handled
// here (not left to native tab order) so focus uses preventScroll — avoids a
// double-scroll fight with our own smooth scrollIntoView in syncOnFocus.
document.addEventListener("keydown", (e) => {
  if (state.compareMode !== "correct") return;
  if (e.key === "Tab" && !e.ctrlKey && !e.altKey && !e.metaKey) {
    const items = panes.a.correctItems || [];
    if (!items.some((it) => it.textarea === document.activeElement)) return; // native tab elsewhere
    const dir = e.shiftKey ? -1 : 1;
    let next = state.focusedBlock + dir;
    while (next >= 0 && next < items.length && (!items[next].textarea || items[next].textarea.disabled)) {
      next += dir;
    }
    if (next >= 0 && next < items.length) {
      e.preventDefault();
      focusBlockTextarea(next);
    } // else: out of range — fall through to native tab (leaves the block list)
  } else if (e.ctrlKey && e.key === "Enter") {
    e.preventDefault();
    focusBlockTextarea(state.focusedBlock + 1);
  } else if (e.altKey && (e.key === "d" || e.key === "D")) {
    e.preventDefault();
    el.showGoldDiff.checked = !el.showGoldDiff.checked;
    el.showGoldDiff.dispatchEvent(new Event("change"));
  } else if (e.altKey && REVIEW_KEYS[e.key]) {
    e.preventDefault();
    const item = panes.a.correctItems?.[state.focusedBlock];
    if (item && isTextBlock(item.block)) {
      setReviewState(item.block, REVIEW_KEYS[e.key]);
      item.refresh();
    }
  }
});

function focusBlockTextarea(readingPos) {
  const textarea = panes.a.correctItems?.[readingPos]?.textarea;
  if (textarea && !textarea.disabled) textarea.focus({ preventScroll: true });
}

// Don't lose a debounced save if the tab is closed mid-edit.
window.addEventListener("beforeunload", () => flushSave());

function goToPage(n) {
  n = Math.min(Math.max(Math.trunc(n) || 1, 1), state.numPages || 1);
  if (n === state.pageNum) {
    el.pageInput.value = state.pageNum; // snap back if the typed value got clamped
    return;
  }
  flushSave(); // persist the page we're leaving before its annotation is replaced
  state.pageNum = n;
  state.focusedBlock = -1; // last page's block index doesn't mean anything on the new page
  renderAll();
  updateUrl();
}
el.prevPage.addEventListener("click", () => goToPage(state.pageNum - 1));
el.nextPage.addEventListener("click", () => goToPage(state.pageNum + 1));
el.pageInput.addEventListener("change", () => goToPage(Number(el.pageInput.value)));
el.pageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    goToPage(Number(el.pageInput.value));
    el.pageInput.blur();
  }
});
el.toggleBoxes.addEventListener("change", () => {
  const show = el.toggleBoxes.checked;
  el.overlayA.style.display = show ? "" : "none";
  el.overlayB.style.display = show ? "" : "none";
});

(async function init() {
  try {
    setStatus("Loading document list ...");
    await loadManifest();
    setStatus("");
    if (state.manifest.documents.length === 0) return;

    const params = new URLSearchParams(location.search);
    const requestedDoc = params.get("doc");
    const hasDoc = requestedDoc && findDoc(requestedDoc);
    const defaultDoc = state.manifest.documents.find((d) => d.id === "test_set") || state.manifest.documents[0];
    const target = hasDoc ? requestedDoc : `${defaultDoc.dataset}/${defaultDoc.id}`;
    el.docSelect.value = target;

    const requestedMode = params.get("mode");
    if (["side", "diff", "diff-struct", "correct"].includes(requestedMode)) {
      state.compareMode = requestedMode;
      el.compareMode.value = requestedMode;
    }
    updateLayout();

    // pass the requested models straight in so a deep link doesn't first
    // load the default model(s) only to immediately discard that work
    await selectDocument(target, { modelName: params.get("model"), modelBName: params.get("modelB") });

    const requestedPage = parseInt(params.get("page"), 10);
    if (requestedPage >= 1 && requestedPage <= state.numPages) {
      state.pageNum = requestedPage;
      await renderAll();
    }
    if (state.compareMode === "correct") fetchAnnotatorProgress(); // deep-linked straight into Correct mode

    updateUrl();
  } catch (err) {
    setStatus(`Error: ${err.message}`);
    console.error(err);
  }
})();
