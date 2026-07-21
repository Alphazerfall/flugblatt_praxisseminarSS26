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
export function htmlToText(html) {
  const doc = new DOMParser().parseFromString(html || "", "text/html");
  return doc.body.textContent || "";
}

export function pageText(modelData, pageIdx) {
  const page = modelData && modelData.pages[pageIdx];
  if (!page) return "";
  return page.blocks.map((b) => htmlToText(b.html)).join("\n\n");
}

function tokenize(text) {
  return (text || "").split(/\s+/).filter(Boolean);
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
export function wordDiffHtml(textA, textB) {
  const a = tokenize(textA);
  const b = tokenize(textB);
  if (a.length === 0 && b.length === 0) {
    return '<div class="empty-msg">No text to compare on this page.</div>';
  }
  if (a.length * b.length > MAX_DIFF_CELLS) {
    return `<div class="empty-msg">Page too large for a word diff (${a.length} vs ${b.length} words).</div>`;
  }
  const ops = diffTokens(a, b);
  return ops.map((op) => `<span class="diff-${op.type}">${escapeHtml(op.value)}</span>`).join(" ");
}
