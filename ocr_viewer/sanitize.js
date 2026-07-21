// Minimal whitelist HTML sanitizer for rendering OCR block content.
// Strips all attributes except img[src] (rewritten to be relative to
// baseUrl) and drops any tag not in ALLOWED (content included, to be safe
// against script/style injection from untrusted JSON).

const ALLOWED = new Set([
  "P", "H1", "H2", "H3", "H4", "H5", "B", "I", "STRONG", "EM", "BR", "DIV",
  "SPAN", "TABLE", "THEAD", "TBODY", "TR", "TD", "TH", "UL", "OL", "LI",
  "IMG", "SUB", "SUP", "U",
]);

export function sanitizeHtml(html, baseUrl) {
  const doc = new DOMParser().parseFromString(html || "", "text/html");

  function clean(node) {
    for (const child of [...node.childNodes]) {
      if (child.nodeType === Node.ELEMENT_NODE) {
        if (!ALLOWED.has(child.tagName)) {
          child.remove();
          continue;
        }
        for (const attr of [...child.attributes]) {
          if (child.tagName === "IMG" && attr.name === "src") continue;
          if (child.tagName === "IMG" && attr.name === "alt") continue;
          child.removeAttribute(attr.name);
        }
        if (child.tagName === "IMG") {
          const src = child.getAttribute("src");
          if (src) child.setAttribute("src", baseUrl + src);
        }
        clean(child);
      } else if (child.nodeType !== Node.TEXT_NODE) {
        child.remove();
      }
    }
  }

  clean(doc.body);
  return doc.body.innerHTML;
}
