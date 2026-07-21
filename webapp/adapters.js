// Normalizes different OCR models' JSON output into a common shape:
//
//   { pages: [ { width, height, blocks: [ { id, order, type, bbox: [x0,y0,x1,y1], html } ] } ] }
//
// bbox is in the same coordinate space as the page's width/height (i.e. use
// bbox[i] / width or / height to get a 0..1 fraction, independent of DPI).
//
// normalize(data, pdfPageSizes) is used for anything fetched as JSON (a
// single object, or an array for paged formats like PaddleOCR); it tries
// each adapter's matches() in turn. pdfPageSizes (index = 0-based PDF page)
// is the PDF's own page size in points, from pdf.js — a fallback reference
// for formats (PaddleOCR) that don't carry page dimensions themselves.
//
// Markdown-only output (no boxes) goes through normalizeMarkdown() instead,
// called directly by app.js since it isn't JSON.

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ---------- Datalab ----------
function isDatalabJson(json) {
  return (
    json &&
    typeof json === "object" &&
    Array.isArray(json.children) &&
    json.children.some((c) => c && c.block_type === "Page")
  );
}

function normalizeDatalab(json) {
  const pages = [];
  for (const pageNode of json.children || []) {
    if (pageNode.block_type !== "Page") continue;
    const [x0, y0, x1, y1] = pageNode.bbox || [0, 0, 0, 0];
    const width = x1 - x0;
    const height = y1 - y0;
    const blocks = (pageNode.children || []).map((b, i) => ({
      id: b.id || `${pageNode.id}/${i}`,
      order: i,
      type: b.block_type || "Unknown",
      bbox: b.bbox || [0, 0, 0, 0],
      html: b.html || (b.markdown ? `<p>${b.markdown}</p>` : ""),
    }));
    pages.push({ width, height, blocks });
  }
  return { pages };
}

// ---------- MinerU (test_set_middle.json) ----------
// para_blocks nest either directly as { bbox, lines: [{ spans }] } for leaf
// blocks (text/title/...), or as { bbox, blocks: [ {..leaf..} ] } for
// container blocks (image/table, wrapping an image_body/table_body etc).
function isMinerUJson(json) {
  return json && typeof json === "object" && Array.isArray(json.pdf_info);
}

const MINERU_TYPE_MAP = {
  text: "Text",
  title: "SectionHeader",
  image: "Picture",
  chart: "Picture",
  table: "Table",
  interline_equation: "Equation",
  list: "ListGroup",
  code: "Text",
  abstract: "Text",
  index: "ListGroup",
};

function collectSpans(node, out) {
  if (node.blocks) for (const b of node.blocks) collectSpans(b, out);
  if (node.lines) for (const line of node.lines) for (const span of line.spans || []) out.push(span);
  return out;
}

function minerUBlockHtml(block) {
  const spans = collectSpans(block, []);
  if (block.type === "table") {
    const tableSpan = spans.find((s) => s.type === "table" && s.html);
    if (tableSpan) return tableSpan.html;
  }
  if (block.type === "image" || block.type === "chart") {
    const imgSpan = spans.find((s) => s.type === "image" && s.image_path);
    if (imgSpan) return `<img alt="" src="images/${imgSpan.image_path}">`;
  }
  const text = spans.filter((s) => s.type === "text" && s.content).map((s) => s.content).join(" ");
  const esc = escapeHtml(text);
  if (!esc) return "";
  if (block.type === "title") return `<h2>${esc}</h2>`;
  if (block.type === "interline_equation") return `<p><i>${esc}</i></p>`;
  return `<p>${esc}</p>`;
}

function normalizeMinerU(json) {
  const pages = (json.pdf_info || []).map((p) => {
    const [width, height] = p.page_size || [0, 0];
    const blocks = (p.para_blocks || []).map((b, i) => ({
      id: `mineru/${p.page_idx}/${i}`,
      order: i,
      type: MINERU_TYPE_MAP[b.type] || b.type || "Unknown",
      bbox: b.bbox || [0, 0, 0, 0],
      html: minerUBlockHtml(b),
    }));
    return { width, height, blocks };
  });
  return { pages };
}

// ---------- PaddleOCR (array of per-page *_res.json files) ----------
// General OCR only: text regions with no layout classification, and no
// page-size field. rec_boxes empirically line up with the PDF page rendered
// at 2x (i.e. the box coordinate space is ~double the PDF's point size) —
// used as the primary reference; the boxes' own bounding envelope is the
// fallback if the PDF's page size isn't available for some reason.
const PADDLEOCR_ASSUMED_RENDER_SCALE = 2;

function isPaddleOcrPages(data) {
  return Array.isArray(data) && data.length > 0 && data.every((d) => d && Array.isArray(d.rec_texts) && Array.isArray(d.rec_boxes));
}

function normalizePaddleOcrPages(data, pdfPageSizes) {
  const pages = [];
  for (const d of data) {
    const pageIdx = d.page_index ?? 0;
    const pdfSize = pdfPageSizes && pdfPageSizes[pageIdx];
    let width, height;
    if (pdfSize) {
      width = pdfSize.width * PADDLEOCR_ASSUMED_RENDER_SCALE;
      height = pdfSize.height * PADDLEOCR_ASSUMED_RENDER_SCALE;
    } else {
      width = Math.max(1, ...d.rec_boxes.map((b) => b[2]));
      height = Math.max(1, ...d.rec_boxes.map((b) => b[3]));
    }
    const blocks = d.rec_texts.map((text, i) => ({
      id: `paddle/${pageIdx}/${i}`,
      order: i,
      type: "Text",
      bbox: d.rec_boxes[i] || [0, 0, 0, 0],
      html: `<p>${escapeHtml(text)}</p>`,
    }));
    pages[pageIdx] = { width, height, blocks };
  }
  return { pages };
}

// ---------- Mistral (jsonMistral/test_set.json: { pages: [{ index, markdown, ... }] }) ----------
// Each page always has a plain `markdown` blob (no boxes); newer runs also
// carry `blocks` (with pixel bboxes, markdown-flavored `content` per block)
// and `dimensions` (the reference width/height those bboxes are in) — real
// per-block boxes are used when present, falling back to the whole-page
// markdown blob (no boxes) for pages/runs that only have that.
function isMistralJson(data) {
  return data && typeof data === "object" && Array.isArray(data.pages) && data.pages.every((p) => p && typeof p.markdown === "string");
}

const MISTRAL_TYPE_MAP = {
  header: "PageHeader",
  footer: "PageHeader",
  title: "SectionHeader",
  text: "Text",
  aside_text: "Text",
  signature: "Text",
  list: "ListGroup",
  image: "Picture",
  table: "Table",
  caption: "Caption",
};

// minimal GFM pipe-table -> <table>; drops the `---` alignment row, treats
// the first remaining row as a header (harmless even where that's not
// semantically accurate — it's just a visual grouping cue).
function mistralTableToHtml(md) {
  const rows = (md || "")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !/^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$/.test(l))
    .map((l) => l.replace(/^\||\|$/g, "").split("|").map((c) => escapeHtml(c.trim())));
  if (!rows.length) return "";
  const [head, ...body] = rows;
  const thead = `<tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  const tbody = body.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("");
  return `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

function mistralBlockHtml(b) {
  if (b.type === "table") return mistralTableToHtml(b.content);
  if (b.type === "image") return `<img alt="" src="${b.image_id || ""}">`;
  return markdownToHtml(b.content || "");
}

function normalizeMistral(json) {
  const pages = [];
  (json.pages || []).forEach((p, i) => {
    const idx = typeof p.index === "number" ? p.index : i;
    const dims = p.dimensions;
    if (Array.isArray(p.blocks) && p.blocks.length && dims && dims.width && dims.height) {
      pages[idx] = {
        width: dims.width,
        height: dims.height,
        blocks: p.blocks.map((b, j) => ({
          id: `mistral/${idx}/${j}`,
          order: j,
          type: MISTRAL_TYPE_MAP[b.type] || b.type || "Unknown",
          bbox: [b.top_left_x, b.top_left_y, b.bottom_right_x, b.bottom_right_y],
          html: mistralBlockHtml(b),
        })),
      };
    } else {
      pages[idx] = {
        width: 1,
        height: 1,
        blocks: [{ id: `mistral/${idx}`, order: 0, type: "Text", bbox: [0, 0, 1, 1], html: markdownToHtml(p.markdown) }],
      };
    }
  });
  return { pages };
}

// ---------- Qwen (jsonQwen/test_set.json: { model, pages: [{ page, text }] }) ----------
// Plain markdown per page (no boxes), 0-indexed `page`. Qwen wraps its
// answer in a ```markdown fenced code block almost always but not always
// (a few pages come back without one, or without the closing fence if the
// response got cut off) — stripped where present, left alone otherwise.
function isQwenJson(data) {
  return data && typeof data === "object" && Array.isArray(data.pages) && data.pages.every((p) => p && typeof p.text === "string" && typeof p.page === "number");
}

function stripCodeFence(text) {
  const t = (text || "").trim();
  // some pages append a trailing note *after* the closing fence (e.g. "Note:
  // archival markings omitted..."), so a matched pair must be extracted
  // (non-greedy, stops at the first close) rather than just trimmed off the
  // end — otherwise that trailing text drags the closing ``` along with it
  // into what's shown.
  const fenced = t.match(/^```[\w-]*\n([\s\S]*?)\n```/);
  if (fenced) return fenced[1];
  return t.replace(/^```[\w-]*\n/, ""); // opening fence with no matching close (truncated output)
}

function normalizeQwen(json) {
  const pages = [];
  for (const p of json.pages || []) {
    pages[p.page] = {
      width: 1,
      height: 1,
      blocks: [{ id: `qwen/${p.page}`, order: 0, type: "Text", bbox: [0, 0, 1, 1], html: markdownToHtml(stripCodeFence(p.text)) }],
    };
  }
  return { pages };
}

// ---------- Gemini (jsonGemini/test_set.json: { model, text }) ----------
// One markdown blob for the whole document, pages delimited by a heading
// like "### Page N" or "# Seite N" — Gemini's own convention, which has
// already been observed to vary (heading level and Page/Seite wording), so
// match loosely rather than lock onto one exact run's formatting. No boxes.
// Content contains a mix of markdown syntax and raw inline HTML (<u>,
// <p align="...">, <b>); the latter gets escaped by markdownToHtml like any
// other text, so it shows up as literal tag text rather than rendering — a
// known cosmetic gap, not a data-loss one.
const GEMINI_PAGE_HEADING_RE = /^#{1,6}\s*(?:Page|Seite)\s+(\d+)\s*$/gim;

function isGeminiJson(data) {
  return data && typeof data === "object" && !Array.isArray(data) && typeof data.text === "string";
}

function splitGeminiPages(text) {
  const matches = [...text.matchAll(GEMINI_PAGE_HEADING_RE)];
  if (matches.length === 0) return [{ pageIdx: 0, content: text }];
  return matches.map((m, i) => ({
    pageIdx: parseInt(m[1], 10) - 1,
    content: text.slice(m.index + m[0].length, i + 1 < matches.length ? matches[i + 1].index : text.length),
  }));
}

function normalizeGemini(json) {
  const pages = [];
  for (const { pageIdx, content } of splitGeminiPages(json.text || "")) {
    if (pageIdx < 0) continue;
    pages[pageIdx] = {
      width: 1,
      height: 1,
      blocks: [{ id: `gemini/${pageIdx}`, order: 0, type: "Text", bbox: [0, 0, 1, 1], html: markdownToHtml(content) }],
    };
  }
  return { pages };
}

// ---------- Markdown-only output (no boxes) ----------
function inlineMarkdown(s) {
  let html = escapeHtml(s);
  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => `<img alt="${alt}" src="${src}">`);
  html = html.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<i>$1</i>");
  return html;
}

function markdownToHtml(md) {
  const out = [];
  let paragraph = [];
  const flush = () => {
    if (paragraph.length) {
      out.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  };
  for (const raw of (md || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^[-=]{3,}$/.test(line)) {
      flush();
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flush();
      const level = Math.min(heading[1].length, 3);
      out.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    paragraph.push(line);
  }
  flush();
  return out.join("\n");
}

export function normalizeMarkdown(text) {
  return {
    pages: [{
      width: 1,
      height: 1,
      blocks: [{ id: "md/0", order: 0, type: "Text", bbox: [0, 0, 1, 1], html: markdownToHtml(text) }],
    }],
  };
}

// ---------- Plain-text-per-page output, no boxes (e.g. GLM-OCR) ----------
// Each page's raw text becomes one full-page block; paragraphs are split on
// blank lines since that's the only structure plain OCR text output has.
function textToHtml(text) {
  return (text || "")
    .split(/\r?\n\s*\r?\n/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => `<p>${escapeHtml(p.replace(/\r?\n/g, " "))}</p>`)
    .join("\n");
}

// texts: array of raw page text, in page order (index = page_idx)
export function normalizeTextPages(texts) {
  return {
    pages: texts.map((text, i) => ({
      width: 1,
      height: 1,
      blocks: [{ id: `text/${i}`, order: 0, type: "Text", bbox: [0, 0, 1, 1], html: textToHtml(text) }],
    })),
  };
}

// ---------- dispatch ----------
const ADAPTERS = [
  { name: "datalab", matches: isDatalabJson, normalize: normalizeDatalab },
  { name: "mineru", matches: isMinerUJson, normalize: normalizeMinerU },
  { name: "paddleocr", matches: isPaddleOcrPages, normalize: normalizePaddleOcrPages },
  { name: "mistral", matches: isMistralJson, normalize: normalizeMistral },
  { name: "qwen", matches: isQwenJson, normalize: normalizeQwen },
  { name: "gemini", matches: isGeminiJson, normalize: normalizeGemini },
];

export function normalize(data, pdfPageSizes) {
  for (const adapter of ADAPTERS) {
    if (adapter.matches(data)) return { model: adapter.name, data: adapter.normalize(data, pdfPageSizes) };
  }
  throw new Error("No adapter recognizes this JSON's structure.");
}

const PALETTE = {
  Text: "#7a9cc2",
  SectionHeader: "#c17b7b",
  PageHeader: "#bd9868",
  Picture: "#8d84b0",
  Caption: "#72a396",
  Table: "#b3a25a",
  TableCell: "#b3a25a",
  ListGroup: "#b088a0",
  ListItem: "#b088a0",
  Footnote: "#7fa0ac",
  Equation: "#9884ab",
};
const DEFAULT_COLOR = "#9a9ba0";

export function colorFor(type) {
  return PALETTE[type] || DEFAULT_COLOR;
}

export function legendEntries() {
  return Object.entries(PALETTE);
}
