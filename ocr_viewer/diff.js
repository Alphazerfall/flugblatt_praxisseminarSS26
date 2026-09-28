// Word-level diff between two models' extracted text for the same page.

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Blocks' `html` is real markup (from Datalab, or built by other adapters);
// strip it down to plain text via a detached DOM parse (doesn't execute
// scripts/styles, just walks the tree) rather than regexing tags out.
//
// Line and paragraph breaks carry whitespace that `textContent` alone drops,
// gluing words together across lines: Datalab uses soft `<br/>`s inside a
// paragraph ("bestimmen;<br/>das" -> "bestimmen;das", "Regensburger<br/>AStA"
// -> "RegensburgerAStA"), which then reads as a real change the moment an
// annotator types the natural space. So insert whitespace for <br> and around
// block-level elements before extracting, then collapse runs to single spaces —
// soft line breaks become ordinary word separators, which is what both the
// word diff (token-based) and character-level CER want.
const BLOCK_TAGS = "p,div,li,h1,h2,h3,h4,h5,h6,blockquote,tr";

export function htmlToText(html) {
  const doc = new DOMParser().parseFromString(html || "", "text/html");
  for (const br of doc.body.querySelectorAll("br,hr")) br.replaceWith(" ");
  for (const node of doc.body.querySelectorAll(BLOCK_TAGS)) node.append(" ");
  return (doc.body.textContent || "").replace(/\s+/g, " ").trim();
}

export function pageText(modelData, pageIdx) {
  const page = modelData && modelData.pages[pageIdx];
  if (!page) return "";
  return page.blocks.map((b) => htmlToText(b.html)).join("\n\n");
}

function tokenize(text) {
  return (text || "").split(/\s+/).filter(Boolean);
}

// Datalab flattens a list's own numbering ("1.", "II.", "-") into each <li>'s
// text rather than expressing it as real list markup (see the ListGroup note
// in style.css) — which is exactly what htmlToText/dinglehopper need (a
// list read start-to-finish is just running text, and a real newline there
// would cost CER for nothing), but it leaves the OCR read-back as one
// unbroken paragraph, which is hard to scan against a 5-item list on the
// scan. This finds, display-only, where each item *starts* — the block's
// ocr_text/gt_text used for scoring are never touched.
const LIST_MARKER_RE = /^(\d{1,3}[.)]|[ivxlcdm]{1,4}[.)]|[a-z][.)]|[-–—])$/i;

// Returns each <li>'s leading marker token ("1.", "II.", …), in order, or
// null if this isn't a marked list (fewer than two items, or any item
// doesn't start with a recognizable marker) — callers should fall back to
// the plain unbroken text rather than break some items and not others.
export function listItemMarkers(html) {
  const doc = new DOMParser().parseFromString(html || "", "text/html");
  const items = doc.body.querySelectorAll("li");
  if (items.length < 2) return null;
  const markers = [];
  for (const li of items) {
    const first = (li.textContent || "").trim().split(/\s+/)[0] || "";
    if (!LIST_MARKER_RE.test(first)) return null;
    markers.push(first);
  }
  return markers;
}

// Standard LCS-based diff over the two token arrays. O(n*m) time and space,
// fine for a page's worth of words; callers should guard against pathologically
// large inputs (see MAX_DIFF_CELLS below).
function diffTokens(a, b) {
  const n = a.length;
  const m = b.length;
  const dp = new Array(n + 1);
  for (let i = 0; i <= n; i++) dp[i] = new Uint32Array(m + 1);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ type: "eq", value: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: "del", value: a[i] });
      i++;
    } else {
      ops.push({ type: "ins", value: b[j] });
      j++;
    }
  }
  while (i < n) ops.push({ type: "del", value: a[i++] });
  while (j < m) ops.push({ type: "ins", value: b[j++] });
  return ops;
}

const MAX_DIFF_CELLS = 4_000_000; // ~2000x2000 words; keeps the DP table under ~16MB and fast

// Returns sanitized HTML: words wrapped in spans classed diff-eq/diff-ins/diff-del.
// `breakMarkers` (optional, from listItemMarkers) inserts a <br> before each
// marker token in order — display formatting on top of the same diff, not a
// second alignment. Matching looks ahead in the marker list (not just the
// very next one) so one marker OCR garbled badly enough to never appear as
// its own token costs only its own break, not every one after it. Only
// "eq"/"del" ops are checked (tokens that came from textA, the OCR reading
// the markers were extracted from) — matching "ins" tokens too would let a
// marker the annotator *typed* (but OCR misread) pull the break onto the
// wrong side of that same edit, splitting e.g. a garbled "1"/"1." pair onto
// two lines right at the top of the list.
export function wordDiffHtml(textA, textB, breakMarkers) {
  const a = tokenize(textA);
  const b = tokenize(textB);
  if (a.length === 0 && b.length === 0) {
    return '<div class="empty-msg">No text to compare on this page.</div>';
  }
  if (a.length * b.length > MAX_DIFF_CELLS) {
    return `<div class="empty-msg">Page too large for a word diff (${a.length} vs ${b.length} words).</div>`;
  }
  const ops = diffTokens(a, b);
  const parts = [];
  let markerIdx = 0;
  for (const op of ops) {
    if (breakMarkers && op.type !== "ins") {
      for (let look = markerIdx; look < breakMarkers.length; look++) {
        if (op.value === breakMarkers[look]) {
          if (parts.length > 0) parts.push("<br>");
          markerIdx = look + 1;
          break;
        }
      }
    }
    parts.push(`<span class="diff-${op.type}">${escapeHtml(op.value)}</span>`);
  }
  return parts.join(" ");
}

// ---------- block-level alignment (structured diff) ----------
// Order-independent word-set overlap (Jaccard) between two blocks' text —
// cheap, and robust to word reordering within a block, which plain word-LCS
// isn't. Blocks are basically never byte-identical across two different
// models even when they really do correspond to the same content, so this
// is a similarity *score*, not an equality check.
function similarity(textA, textB) {
  const setA = new Set(tokenize(textA));
  const setB = new Set(tokenize(textB));
  if (setA.size === 0 && setB.size === 0) return 1;
  if (setA.size === 0 || setB.size === 0) return 0;
  let intersection = 0;
  for (const w of setA) if (setB.has(w)) intersection++;
  return intersection / (setA.size + setB.size - intersection);
}

// Below this, two blocks are treated as unrelated rather than "the same
// paragraph, OCR'd differently" — tuned loosely; false matches are more
// confusing than a same-content pair occasionally showing as del+ins.
const MIN_BLOCK_SIMILARITY = 0.15;

const MAX_ALIGN_CELLS = 4_000_000; // same budget/rationale as MAX_DIFF_CELLS, in block-count terms

// Needleman-Wunsch-style sequence alignment (not plain LCS — LCS only has
// an equal/unequal test, but block text is graded similarity) over two
// blocks' text arrays. Returns an ordered list of
// {type:"match", a, b} | {type:"del", a} | {type:"ins", b}, `a`/`b` being
// indices into textsA/textsB, in reading order.
export function alignBlocks(textsA, textsB) {
  const n = textsA.length;
  const m = textsB.length;
  if (n * m > MAX_ALIGN_CELLS) {
    // Pathological case (shouldn't happen for a single page) — fall back to
    // "nothing matches" so the caller still gets a usable, if unhelpful, result.
    const ops = [];
    for (let i = 0; i < n; i++) ops.push({ type: "del", a: i });
    for (let j = 0; j < m; j++) ops.push({ type: "ins", b: j });
    return ops;
  }

  const sim = Array.from({ length: n }, () => new Float64Array(m));
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < m; j++) sim[i][j] = similarity(textsA[i], textsB[j]);
  }

  const score = Array.from({ length: n + 1 }, () => new Float64Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      const s = sim[i][j];
      const matchScore = s >= MIN_BLOCK_SIMILARITY ? score[i + 1][j + 1] + s : -Infinity;
      score[i][j] = Math.max(matchScore, score[i + 1][j], score[i][j + 1]);
    }
  }

  const ops = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    const s = sim[i][j];
    const matchScore = s >= MIN_BLOCK_SIMILARITY ? score[i + 1][j + 1] + s : -Infinity;
    if (matchScore >= score[i + 1][j] && matchScore >= score[i][j + 1]) {
      ops.push({ type: "match", a: i, b: j });
      i++;
      j++;
    } else if (score[i + 1][j] >= score[i][j + 1]) {
      ops.push({ type: "del", a: i });
      i++;
    } else {
      ops.push({ type: "ins", b: j });
      j++;
    }
  }
  while (i < n) ops.push({ type: "del", a: i++ });
  while (j < m) ops.push({ type: "ins", b: j++ });
  return ops;
}
