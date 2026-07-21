import * as pdfjsLib from "/webapp/vendor/pdf.min.mjs";
import { normalize, normalizeMarkdown, normalizeTextPages, colorFor, legendEntries } from "/webapp/adapters.js";
import { sanitizeHtml } from "/webapp/sanitize.js";
import { pageText, wordDiffHtml } from "/webapp/diff.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/webapp/vendor/pdf.worker.min.mjs";

const RENDER_SCALE = 2; // fixed internal resolution; CSS scales the canvas to fit the pane

const el = {
  docSelect: document.getElementById("doc-select"),
  modelSelect: document.getElementById("model-select"),
  modelSelectB: document.getElementById("model-select-b"),
  modelBField: document.getElementById("model-b-field"),
  compareMode: document.getElementById("compare-mode"),
  prevPage: document.getElementById("prev-page"),
  nextPage: document.getElementById("next-page"),
  pageInput: document.getElementById("page-input"),
  pageTotal: document.getElementById("page-total"),
  toggleBoxes: document.getElementById("toggle-boxes"),
  themeToggle: document.getElementById("theme-toggle"),
  status: document.getElementById("status"),
  rowB: document.getElementById("row-b"),
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
  a: { key: "a", canvas: el.canvasA, ctx: el.canvasA.getContext("2d"), overlay: el.overlayA, contentList: el.contentListA, boxEls: [], itemEls: [] },
  b: { key: "b", canvas: el.canvasB, ctx: el.canvasB.getContext("2d"), overlay: el.overlayB, contentList: el.contentListB, boxEls: [], itemEls: [] },
};

const state = {
  manifest: null,
  doc: null, // current manifest document entry
  pdf: null, // pdfjs document proxy
  pageNum: 1, // 1-indexed, matches pdfjs
  numPages: 0,
  pdfPageSizes: [], // [{width,height}, ...] in PDF points, 0-indexed; fallback reference for formats without their own page size
  compareMode: "single", // "single" | "side" | "diff"
  a: { model: null, data: null, baseUrl: "" },
  b: { model: null, data: null, baseUrl: "" },
  renderToken: 0, // guards against races when switching pages/models fast
};

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
    opt.textContent = m.name;
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
  const modelA = byName(opts.modelName) || doc.models[0] || null;
  const modelB = byName(opts.modelBName) || doc.models.find((m) => m !== modelA) || doc.models[0] || null;
  await setSlotModel("a", modelA);
  await setSlotModel("b", modelB);

  const idxA = doc.models.indexOf(state.a.model);
  const idxB = doc.models.indexOf(state.b.model);
  if (idxA >= 0) el.modelSelect.value = idxA;
  if (idxB >= 0) el.modelSelectB.value = idxB;

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
    return normalizeMarkdown(await res.text());
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
  setStatus(`Loading ${model.name} output ...`);
  try {
    s.data = await loadModelOutput(model);
    s.baseUrl = model.base_url;
    setStatus("");
  } catch (err) {
    s.data = null;
    s.baseUrl = "";
    setStatus(`Failed to load/parse ${model.name} output: ${err.message}`);
  }
}

async function renderAll() {
  const token = ++state.renderToken;
  if (!state.pdf) return;

  try {
    await renderPanePdf(panes.a, token);
    if (token !== state.renderToken) return;
    renderPaneOverlayAndContent(panes.a, state.a.data, state.a.baseUrl);

    if (state.compareMode === "side") {
      await renderPanePdf(panes.b, token);
      if (token !== state.renderToken) return;
      renderPaneOverlayAndContent(panes.b, state.b.data, state.b.baseUrl);
    } else if (state.compareMode === "diff") {
      renderDiff();
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
  const viewport = page.getViewport({ scale: RENDER_SCALE });
  pane.canvas.width = viewport.width;
  pane.canvas.height = viewport.height;
  await page.render({ canvasContext: pane.ctx, viewport }).promise;
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

  const legend = document.createElement("div");
  legend.className = "legend";
  for (const [type, color] of legendEntries()) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `<span class="swatch" style="--c:${color}"></span>${type}`;
    legend.appendChild(chip);
  }
  pane.contentList.appendChild(legend);

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
  el.diffLegend.appendChild(diffChip("#c17b7b", `${state.a.model?.name || "A"} only`));
  el.diffLegend.appendChild(diffChip("#72a396", `${state.b.model?.name || "B"} only`));

  el.diffContent.innerHTML = wordDiffHtml(textA, textB);
}

// ---------- view mode ----------
function updateLayout() {
  const mode = state.compareMode;
  el.rowB.hidden = mode !== "side";
  el.diffPane.hidden = mode !== "diff";
  el.contentPaneA.hidden = mode === "diff";
  el.modelBField.hidden = mode === "single";
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
  state.compareMode = el.compareMode.value;
  updateLayout();
  await renderAll();
  updateUrl();
});

function goToPage(n) {
  n = Math.min(Math.max(Math.trunc(n) || 1, 1), state.numPages || 1);
  if (n === state.pageNum) {
    el.pageInput.value = state.pageNum; // snap back if the typed value got clamped
    return;
  }
  state.pageNum = n;
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
    if (requestedMode === "side" || requestedMode === "diff") {
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

    updateUrl();
  } catch (err) {
    setStatus(`Error: ${err.message}`);
    console.error(err);
  }
})();
