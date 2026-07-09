import * as pdfjsLib from "/webapp/vendor/pdf.min.mjs";
import { normalize, normalizeMarkdown, normalizeTextPages, colorFor, legendEntries } from "/webapp/adapters.js";
import { sanitizeHtml } from "/webapp/sanitize.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/webapp/vendor/pdf.worker.min.mjs";

const RENDER_SCALE = 2; // fixed internal resolution; CSS scales the canvas to fit the pane

const el = {
  docSelect: document.getElementById("doc-select"),
  modelSelect: document.getElementById("model-select"),
  prevPage: document.getElementById("prev-page"),
  nextPage: document.getElementById("next-page"),
  pageInput: document.getElementById("page-input"),
  pageTotal: document.getElementById("page-total"),
  toggleBoxes: document.getElementById("toggle-boxes"),
  status: document.getElementById("status"),
  canvas: document.getElementById("pdf-canvas"),
  overlay: document.getElementById("overlay"),
  contentList: document.getElementById("content-list"),
};

const ctx = el.canvas.getContext("2d");

const state = {
  manifest: null,
  doc: null, // current manifest document entry
  pdf: null, // pdfjs document proxy
  pageNum: 1, // 1-indexed, matches pdfjs
  numPages: 0,
  pdfPageSizes: [], // [{width,height}, ...] in PDF points, 0-indexed; fallback reference for formats without their own page size
  modelData: null, // normalized { pages: [...] } for the selected model
  baseUrl: "", // directory the current model's output lives in (for image src)
  renderToken: 0, // guards against races when switching pages/models fast
};

function setStatus(msg) {
  el.status.textContent = msg || "";
}

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

async function selectDocument(key) {
  const doc = findDoc(key);
  if (!doc) return;
  state.doc = doc;
  state.modelData = null;
  state.baseUrl = "";

  el.modelSelect.innerHTML = "";
  if (doc.models.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "(no OCR output for this document)";
    el.modelSelect.appendChild(opt);
    el.modelSelect.disabled = true;
  } else {
    el.modelSelect.disabled = false;
    doc.models.forEach((m, i) => {
      const opt = document.createElement("option");
      opt.value = i;
      opt.textContent = m.name;
      el.modelSelect.appendChild(opt);
    });
  }

  setStatus(`Loading ${doc.id}.pdf ...`);
  const loadingTask = pdfjsLib.getDocument({ url: doc.pdf_url });
  state.pdf = await loadingTask.promise;
  state.numPages = state.pdf.numPages;
  state.pageNum = 1;
  state.pdfPageSizes = await getPdfPageSizes(state.pdf);
  setStatus("");

  if (doc.models.length > 0) {
    await selectModel(doc.models[0]);
  } else {
    await renderPage();
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

async function selectModel(model) {
  if (!model) {
    state.modelData = null;
    state.baseUrl = "";
    await renderPage();
    return;
  }
  setStatus(`Loading ${model.name} output ...`);
  try {
    let data;
    if (model.kind === "markdown") {
      const res = await fetch(model.md_url);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      data = normalizeMarkdown(await res.text());
    } else if (model.kind === "text_pages") {
      const texts = await Promise.all(model.txt_urls.map(async (url) => {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
        return res.text();
      }));
      data = normalizeTextPages(texts);
    } else if (model.kind === "json_pages") {
      const jsons = await Promise.all(model.json_urls.map(async (url) => {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
        return res.json();
      }));
      data = normalize(jsons, state.pdfPageSizes).data;
    } else {
      const res = await fetch(model.json_url);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      data = normalize(await res.json(), state.pdfPageSizes).data;
    }
    state.modelData = data;
    state.baseUrl = model.base_url;
    setStatus("");
  } catch (err) {
    state.modelData = null;
    state.baseUrl = "";
    setStatus(`Failed to load/parse ${model.name} output: ${err.message}`);
  }
  await renderPage();
}

async function renderPage() {
  const token = ++state.renderToken;
  if (!state.pdf) return;

  const page = await state.pdf.getPage(state.pageNum);
  if (token !== state.renderToken) return;

  const viewport = page.getViewport({ scale: RENDER_SCALE });
  el.canvas.width = viewport.width;
  el.canvas.height = viewport.height;

  await page.render({ canvasContext: ctx, viewport }).promise;
  if (token !== state.renderToken) return;

  el.pageInput.value = state.pageNum;
  el.pageInput.max = state.numPages;
  el.pageTotal.textContent = `/ ${state.numPages}`;

  const pageData = state.modelData ? state.modelData.pages[state.pageNum - 1] : null;
  renderOverlay(pageData);
  renderContentList(pageData);
}

function renderOverlay(pageData) {
  el.overlay.innerHTML = "";
  boxEls = [];
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

    box.addEventListener("mouseenter", () => setActive(i));
    box.addEventListener("mouseleave", () => setActive(-1));
    box.addEventListener("click", () => {
      setActive(i);
      itemEls[i]?.scrollIntoView({ behavior: "smooth", block: "center" });
    });

    el.overlay.appendChild(box);
    boxEls.push(box);
  });
}

let boxEls = [];
let itemEls = [];

function setActive(idx) {
  boxEls.forEach((b, i) => b.classList.toggle("active", i === idx));
  itemEls.forEach((c, i) => c.classList.toggle("active", i === idx));
}

function renderContentList(pageData) {
  itemEls = [];
  el.contentList.innerHTML = "";

  if (!pageData) {
    const msg = document.createElement("div");
    msg.className = "empty-msg";
    msg.textContent = state.doc && state.doc.models.length === 0
      ? "No OCR output found for this document yet."
      : "No content detected on this page.";
    el.contentList.appendChild(msg);
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
  el.contentList.appendChild(legend);

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
    html.innerHTML = sanitizeHtml(block.html, state.baseUrl);

    body.appendChild(tag);
    body.appendChild(html);
    item.appendChild(num);
    item.appendChild(body);

    item.addEventListener("mouseenter", () => setActive(i));
    item.addEventListener("mouseleave", () => setActive(-1));

    el.contentList.appendChild(item);
    itemEls.push(item);
  });
}

// ---------- deep-linking (?doc=<dataset>/<id>&model=<name>&page=<n>) ----------
function updateUrl() {
  const params = new URLSearchParams();
  if (state.doc) params.set("doc", `${state.doc.dataset}/${state.doc.id}`);
  if (el.modelSelect.value) params.set("model", el.modelSelect.selectedOptions[0]?.textContent || "");
  if (state.pageNum) params.set("page", state.pageNum);
  history.replaceState(null, "", `?${params.toString()}`);
}

// ---------- wiring ----------
el.docSelect.addEventListener("change", async () => {
  await selectDocument(el.docSelect.value);
  updateUrl();
});
el.modelSelect.addEventListener("change", async () => {
  await selectModel(state.doc?.models[Number(el.modelSelect.value)]);
  updateUrl();
});
function goToPage(n) {
  n = Math.min(Math.max(Math.trunc(n) || 1, 1), state.numPages || 1);
  if (n === state.pageNum) {
    el.pageInput.value = state.pageNum; // snap back if the typed value got clamped
    return;
  }
  state.pageNum = n;
  renderPage();
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
  el.overlay.style.display = el.toggleBoxes.checked ? "" : "none";
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
    const target = hasDoc ? requestedDoc : `${state.manifest.documents[0].dataset}/${state.manifest.documents[0].id}`;
    el.docSelect.value = target;
    await selectDocument(target);

    const requestedModel = params.get("model");
    if (requestedModel) {
      const idx = state.doc?.models.findIndex((m) => m.name === requestedModel);
      if (idx >= 0) {
        el.modelSelect.value = idx;
        await selectModel(state.doc.models[idx]);
      }
    }

    const requestedPage = parseInt(params.get("page"), 10);
    if (requestedPage >= 1 && requestedPage <= state.numPages) {
      state.pageNum = requestedPage;
      await renderPage();
    }

    updateUrl();
  } catch (err) {
    setStatus(`Error: ${err.message}`);
    console.error(err);
  }
})();
