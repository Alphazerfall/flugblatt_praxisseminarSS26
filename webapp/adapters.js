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
    if (!line || line === "---") {
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
