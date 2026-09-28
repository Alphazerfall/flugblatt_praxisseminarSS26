// Flugblatt Splitter frontend. No build step — loaded directly as an ES module.
//
// Pure manual, visual splitting tool: no text/header extraction and no AI
// boundary suggestions — thumbnails and page images are the only signal.
// The user reviews thumbnails and clicks a thumbnail's corner cut (or the
// segment confirmed button) to build up the segmentation themselves.
//
// Title/date input fields are intentionally not rendered right now (the
// segment data model still carries them, round-tripped on save/load) for
// possible future manual entry.

const PREVIEW_DPI = 60

const el = {
  pdfSelect: document.getElementById('pdf-select'),
  btnSave: document.getElementById('btn-save'),
  btnLoadJson: document.getElementById('btn-load-json'),
  themeToggle: document.getElementById('theme-toggle'),
  metadataToggle: document.getElementById('metadata-toggle'),
  status: document.getElementById('status'),
  app: document.getElementById('app'),
  panelResizer: document.getElementById('panel-resizer'),
  previewPanel: document.getElementById('preview-panel'),
  previewList: document.getElementById('preview-list'),
  docSummary: document.getElementById('doc-summary'),
  pagesPanel: document.getElementById('pages-panel'),
  pagesList: document.getElementById('pages-list'),
  tplSegmentBox: document.getElementById('tpl-segment-box'),
  tplPreviewThumb: document.getElementById('tpl-preview-thumb'),
  tplPage: document.getElementById('tpl-page'),
}

// index.html applies the stored/system theme synchronously (before paint)
// via an inline <script> so there's no flash of the wrong theme; this just
// keeps the toggle in sync and persists changes.
const THEME_KEY = 'flugblatt-splitter-theme'
el.themeToggle.checked = document.documentElement.dataset.theme === 'light'
el.themeToggle.addEventListener('change', () => {
  const theme = el.themeToggle.checked ? 'light' : 'dark'
  document.documentElement.dataset.theme = theme
  localStorage.setItem(THEME_KEY, theme)
})

// Off by default (extracted metadata is a review aid, not the primary view) -
// only shown once explicitly turned on, then remembered like the theme.
const METADATA_VISIBLE_KEY = 'flugblatt-splitter-metadata-visible'
function applyMetadataVisibility(visible) {
  document.body.classList.toggle('metadata-hidden', !visible)
}
const metadataVisible = localStorage.getItem(METADATA_VISIBLE_KEY) === 'true'
el.metadataToggle.checked = metadataVisible
applyMetadataVisibility(metadataVisible)
el.metadataToggle.addEventListener('change', () => {
  applyMetadataVisibility(el.metadataToggle.checked)
  localStorage.setItem(METADATA_VISIBLE_KEY, String(el.metadataToggle.checked))
})

// Draggable split between the two panes — the right-hand detailed view can
// otherwise be too wide to comfortably read a full scan at once, with no
// way to give it less (or more) of the screen. Persisted so it survives a
// reload, same pattern as the theme toggle above.
const PANEL_SPLIT_KEY = 'flugblatt-splitter-panel-split'
const PANEL_SPLIT_MIN = 0.2
const PANEL_SPLIT_MAX = 0.8

function applyPanelSplit(fraction) {
  // fr tracks share only the space left over after the fixed 6px resizer
  // track — using percentages for both sides summed to 100% + 6px, always
  // overflowing the container by exactly the resizer's width and producing
  // a permanent few-pixel horizontal scrollbar.
  el.app.style.gridTemplateColumns = `${fraction}fr 6px ${1 - fraction}fr`
}

function setupPanelResizer() {
  const stored = Number(localStorage.getItem(PANEL_SPLIT_KEY))
  applyPanelSplit(stored > 0 && stored < 1 ? stored : 0.5)

  el.panelResizer.addEventListener('mousedown', (event) => {
    event.preventDefault()
    el.panelResizer.classList.add('dragging')
    const appRect = el.app.getBoundingClientRect()

    function onMove(moveEvent) {
      const fraction = (moveEvent.clientX - appRect.left) / appRect.width
      applyPanelSplit(Math.min(PANEL_SPLIT_MAX, Math.max(PANEL_SPLIT_MIN, fraction)))
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      el.panelResizer.classList.remove('dragging')
      const fraction = el.previewPanel.getBoundingClientRect().width / appRect.width
      localStorage.setItem(PANEL_SPLIT_KEY, String(fraction))
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  })
}
setupPanelResizer()

const state = {
  pdf: null,
  pageCount: 0,
  pages: [],                 // [{pageNumber, width, height}]
  cuts: new Set(),           // human-confirmed cut points ("cut after page N")
  segmentMeta: new Map(),    // startPage -> {title, date, confirmed} — title/date not editable in the UI yet
  extractedMeta: new Map(),  // "startPage_endPage" -> {title, issuers: [{surface, role}], dateText, dateIso} from extract_metadata_v2.py, read-only
  knownOrgKeys: new Set(),   // normalized names/acronyms from organizations.draft.json, for canonical-match highlighting
  pageEls: new Map(),        // pageNumber -> page element (right-hand detailed list)
  currentVisiblePage: null,  // page currently scrolled into view on the right — mirrored as a highlight on the left
}

let scrollSpyHandler = null
let scrollSpyRaf = null

// `flash` re-triggers a brief highlight animation even if the text is
// identical to what's already shown (e.g. saving twice in a row to the same
// path) — otherwise a repeat save looks like nothing happened at all.
function setStatus(text, { flash = false } = {}) {
  el.status.textContent = text
  if (flash) {
    el.status.classList.remove('flash')
    // Two rAFs (not just a forced-reflow read) guarantee the browser has
    // actually painted the class-removed state before it's re-added —
    // a single synchronous reflow can still get coalesced away, silently
    // skipping the animation restart.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => el.status.classList.add('flash'))
    })
  }
}

async function fetchJSON(url, options) {
  const res = await fetch(url, options)
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch { /* not JSON */ }
    throw new Error(detail)
  }
  return res.json()
}

// Derives contiguous [{startPage, endPage}] segments from the cut-point set.
// Pure function — mirrors the backend's segmentation.validate_segments logic
// client-side so every divider click can recompute instantly with no round-trip.
function computeSegments(pageCount, cuts) {
  const sortedCuts = [...cuts].filter((c) => c >= 1 && c < pageCount).sort((a, b) => a - b)
  const segments = []
  let start = 1
  for (const cut of sortedCuts) {
    segments.push({ startPage: start, endPage: cut })
    start = cut + 1
  }
  segments.push({ startPage: start, endPage: pageCount })
  return segments
}

// Creates blank segmentMeta entries for newly-appeared segment start pages
// (never overwrites data the user, or a saved file, already provided).
// title/date still aren't shown in the UI (possible future manual entry),
// but round-trip through save/load so nothing is lost.
function ensureSegmentMeta(segments) {
  for (const seg of segments) {
    if (!state.segmentMeta.has(seg.startPage)) {
      state.segmentMeta.set(seg.startPage, { title: '', date: '', confirmed: false, noContent: false, note: '' })
    }
  }
}

async function loadPdfList() {
  const { pdfs } = await fetchJSON('/api/pdfs')
  for (const pdf of pdfs) {
    const opt = document.createElement('option')
    opt.value = pdf
    opt.textContent = pdf
    el.pdfSelect.appendChild(opt)
  }
}

async function onSelectPdf() {
  const pdf = el.pdfSelect.value
  if (!pdf) return
  setStatus('Seiten werden geladen…')
  el.btnSave.disabled = true
  el.btnLoadJson.disabled = true

  state.pdf = pdf
  state.cuts = new Set()
  state.segmentMeta = new Map()
  state.extractedMeta = new Map()
  state.pageEls = new Map()

  const doc = await fetchJSON(`/api/document?pdf=${encodeURIComponent(pdf)}`)
  state.pageCount = doc.page_count
  const { pages } = await fetchJSON(`/api/pages?pdf=${encodeURIComponent(pdf)}`)
  // Normalize the API's snake_case fields to camelCase once, here, so the
  // rest of the frontend can consistently use page.pageNumber.
  state.pages = pages.map((p) => ({ pageNumber: p.page_number, width: p.width, height: p.height }))

  buildPagesList()
  setupScrollSpy()

  // Best-effort: restore a previously saved segmentation for this PDF.
  try {
    await loadSegmentationFromServer(pdf, { silent: true })
    setStatus('Gespeicherte Segmentierung geladen.')
  } catch {
    setStatus(`${state.pageCount} Seiten geladen.`)
  }

  // Best-effort: overlay any LLM-extracted metadata (title/org/date), purely
  // for display — silently absent if extract_metadata.py hasn't run yet.
  await loadExtractedMetadata(pdf)

  renderSegments()
  el.btnSave.disabled = false
  el.btnLoadJson.disabled = false
}

// Highlights, in the left-half overview, whichever page is currently
// scrolled into view in the right-hand detailed list. Driven directly off
// scroll position (rAF-throttled) rather than IntersectionObserver ratios —
// ratio comparisons flicker between adjacent pages right around their shared
// boundary (especially scrolling up), which made the left-hand highlight and
// its auto-scroll jump around and occasionally not match what's actually
// shown on the right.
function setupScrollSpy() {
  if (scrollSpyHandler) el.pagesPanel.removeEventListener('scroll', scrollSpyHandler)
  state.currentVisiblePage = null

  scrollSpyHandler = () => {
    if (scrollSpyRaf != null) return
    scrollSpyRaf = requestAnimationFrame(() => {
      scrollSpyRaf = null
      updateCurrentPageFromScroll()
    })
  }
  el.pagesPanel.addEventListener('scroll', scrollSpyHandler, { passive: true })
  updateCurrentPageFromScroll()
}

// The "current" page is the last one whose top has scrolled up to (or past)
// a reference line near the top of the right-hand panel — i.e. whichever
// page a real reader would say they're looking at. Unlike intersection
// ratios, this changes exactly once per boundary crossed, in either scroll
// direction.
function updateCurrentPageFromScroll() {
  // While a programmatic jump (jumpToPage) is animating the scroll, the
  // scroll events it generates would otherwise race our own explicit
  // "current page" update: this recompute reads the in-between scroll
  // position, briefly reporting the old page again before the animation
  // finishes and it corrects itself — visible as the highlight jumping to
  // the target, back to the old page, then to the target a second time.
  if (suppressScrollSpy) return
  const referenceLine = el.pagesPanel.getBoundingClientRect().top + 16
  let current = null
  for (const [pageNumber, pageEl] of state.pageEls) {
    if (pageEl.getBoundingClientRect().top <= referenceLine) {
      if (current == null || pageNumber > current) current = pageNumber
    }
  }
  if (current == null && state.pages.length > 0) current = state.pages[0].pageNumber
  if (current === state.currentVisiblePage) return
  state.currentVisiblePage = current
  updateCurrentIndicator()
}

// Keeps the left-hand overview following the right-hand detailed list —
// whichever thumbnail matches the currently-visible page is both highlighted
// and scrolled into view, so the user doesn't have to separately mouse-wheel
// the left pane to keep up with where they are on the right.
function updateCurrentIndicator() {
  for (const thumb of el.previewList.querySelectorAll('.preview-thumb.current')) {
    thumb.classList.remove('current')
  }
  if (state.currentVisiblePage == null) return
  const thumb = el.previewList.querySelector(`.preview-thumb[data-page-number="${state.currentVisiblePage}"]`)
  if (!thumb) return
  thumb.classList.add('current')
  // Extra top clearance (vs. the plain 8px default) — the "current" thumb's
  // own border/glow grows beyond a normal thumbnail's box (see
  // .preview-thumb.current img in style.css), so when it lands right at the
  // scrollable panel's own top edge, the default gap isn't enough and the
  // glow reads as clipped by the panel itself. Deliberately generous (not
  // just enough for the glow) so part of the previous row stays visible
  // above it too, for context on where you scrolled from. Always prioritizes
  // the thumb itself being clearly in view; if that pushes its segment box's
  // own header above the fold, that's fine.
  scrollToElement(el.previewPanel, thumb, { offset: 50 })
}

// Native scrollIntoView({behavior: 'smooth'}) has no speed control and feels
// sluggish over the distance of a ~100-page list — animate scrollTop
// directly instead, over a short fixed duration regardless of distance.
function scrollToElement(container, target, { duration = 220, offset = 8, onDone } = {}) {
  const containerRect = container.getBoundingClientRect()
  const targetRect = target.getBoundingClientRect()
  const startTop = container.scrollTop
  const delta = targetRect.top - containerRect.top - offset
  const startTime = performance.now()

  function step(now) {
    const t = Math.min(1, (now - startTime) / duration)
    const eased = 1 - Math.pow(1 - t, 3) // ease-out cubic
    container.scrollTop = startTop + delta * eased
    if (t < 1) requestAnimationFrame(step)
    else onDone?.()
  }
  requestAnimationFrame(step)
}

// See the comment in updateCurrentPageFromScroll — set for the duration of a
// jumpToPage animation so its own scroll events don't fight the "current
// page" value the jump itself is setting.
let suppressScrollSpy = false

function jumpToPage(pageNumber) {
  const pageEl = state.pageEls.get(pageNumber)
  if (!pageEl) return
  suppressScrollSpy = true
  scrollToElement(el.pagesPanel, pageEl, { onDone: () => { suppressScrollSpy = false } })
}

function buildPagesList() {
  el.pagesList.innerHTML = ''
  state.pageEls = new Map()

  state.pages.forEach((page) => {
    const pageEl = buildPageEl(page)
    state.pageEls.set(page.pageNumber, pageEl)
    el.pagesList.appendChild(pageEl)
  })
}

function buildPageEl(page) {
  const frag = el.tplPage.content.cloneNode(true)
  const root = frag.querySelector('.page')
  root.dataset.pageNumber = String(page.pageNumber)
  root.querySelector('.page-number-badge').textContent = `Seite ${page.pageNumber}`

  const img = root.querySelector('.thumb')
  // Reserve the image's real aspect ratio up front — otherwise the box
  // starts at 0 height and grows once the (lazy-loaded) image arrives,
  // shifting every page below it and throwing off any in-flight
  // scroll-to-page animation targeting one of those later pages.
  if (page.width && page.height) img.style.aspectRatio = `${page.width} / ${page.height}`
  img.src = `/api/thumbnail?pdf=${encodeURIComponent(state.pdf)}&page=${page.pageNumber}`
  img.alt = `Seite ${page.pageNumber}`

  // Clicking anywhere on the card snaps it fully into view at the top —
  // handy when a click lands on a page that's only partially scrolled into
  // view.
  root.addEventListener('click', () => scrollToElement(el.pagesPanel, root))

  return root
}

function toggleCut(afterPage) {
  if (state.cuts.has(afterPage)) {
    state.cuts.delete(afterPage)
  } else {
    state.cuts.add(afterPage)
  }
  renderSegments()
}

// --- Left-half overview: one bordered box per segment containing a
// responsive grid of that segment's (large) thumbnails. Rebuilt on every
// renderSegments() call since box membership changes whenever cuts change.
// Each thumbnail (except the document's last page) carries its own small
// "cut after this page" corner toggle — the only way to add/remove a cut,
// since the right-hand detailed list has no divider control of its own. ---

function buildPreviewPanel(segments) {
  el.previewList.innerHTML = ''
  segments.forEach((seg) => {
    el.previewList.appendChild(buildSegmentBoxEl(seg))
  })
  updateCurrentIndicator()
}

function buildSegmentBoxEl(seg) {
  const meta = state.segmentMeta.get(seg.startPage)
  const frag = el.tplSegmentBox.content.cloneNode(true)
  const root = frag.querySelector('.segment-box')

  root.querySelector('.segment-range').textContent =
    seg.startPage === seg.endPage ? `Seite ${seg.startPage}` : `Seiten ${seg.startPage}–${seg.endPage}`

  const confirmBtn = root.querySelector('.segment-confirm-btn')
  const applyConfirmedStyle = () => {
    root.classList.toggle('confirmed', meta.confirmed)
    confirmBtn.classList.toggle('confirmed', meta.confirmed)
    confirmBtn.textContent = meta.confirmed ? 'Bestätigt' : 'Bestätigen'
  }
  applyConfirmedStyle()
  confirmBtn.addEventListener('click', () => {
    meta.confirmed = !meta.confirmed
    applyConfirmedStyle()
  })

  // "Kein Inhalt" — marks a range as a divider/blank page (incl. a blank
  // back side)/cover etc. rather than an actual document, so it can be
  // visually skipped and later excluded from metadata extraction.
  // Orthogonal to "Bestätigen": a range can be both reviewed and confirmed
  // to have no content.
  const noContentCheckbox = root.querySelector('.segment-no-content-checkbox')
  noContentCheckbox.checked = meta.noContent
  root.classList.toggle('no-content', meta.noContent)
  noContentCheckbox.addEventListener('change', () => {
    meta.noContent = noContentCheckbox.checked
    root.classList.toggle('no-content', meta.noContent)
  })

  // Free-text problem flag, e.g. "Seite fehlt" — rides along with the
  // segment, no separate save step.
  const noteInput = root.querySelector('.segment-note-input')
  noteInput.value = meta.note
  noteInput.addEventListener('input', () => {
    meta.note = noteInput.value
  })

  const extractedEl = root.querySelector('.segment-extracted-meta')
  const extracted = state.extractedMeta.get(`${seg.startPage}_${seg.endPage}`)
  const issuers = (extracted?.issuers || []).filter((i) => i.role === 'issuer')
  const signatories = (extracted?.issuers || []).filter((i) => i.role === 'signatory')
  if (extracted && (extracted.title || issuers.length || signatories.length || extracted.dateText)) {
    extractedEl.replaceChildren()
    const titleEl = document.createElement('strong')
    titleEl.textContent = extracted.title || '(kein Titel)'
    extractedEl.appendChild(titleEl)

    if (issuers.length) {
      extractedEl.appendChild(document.createTextNode(' — '))
      issuers.forEach((org, i) => {
        if (i > 0) extractedEl.appendChild(document.createTextNode(', '))
        const orgEl = document.createElement('span')
        orgEl.textContent = org.surface
        const known = isKnownOrg(org.surface)
        orgEl.className = 'org-tag ' + (known ? 'org-known' : 'org-unknown')
        orgEl.title = known ? 'in der Normdatei (organizations.draft.json)' : 'nicht in der Normdatei — noch unaufgelöst'
        extractedEl.appendChild(orgEl)
      })
    }
    if (signatories.length) {
      extractedEl.appendChild(document.createTextNode(
        (issuers.length ? '; ' : ' — ') + 'Unterzeichner: ' + signatories.map((s) => s.surface).join(', ')))
    }
    const dateDisplay = extracted.dateIso ? `${extracted.dateText} (iso: ${extracted.dateIso})` : extracted.dateText
    if (dateDisplay) extractedEl.appendChild(document.createTextNode(' · ' + dateDisplay))
  } else {
    extractedEl.remove()
  }

  const gridEl = root.querySelector('.segment-box-grid')
  for (let p = seg.startPage; p <= seg.endPage; p++) {
    gridEl.appendChild(buildPreviewThumbEl(state.pages[p - 1]))
  }

  return root
}

function buildPreviewThumbEl(page) {
  const frag = el.tplPreviewThumb.content.cloneNode(true)
  const root = frag.querySelector('.preview-thumb')
  root.dataset.pageNumber = String(page.pageNumber)

  const img = root.querySelector('img')
  img.src = `/api/thumbnail?pdf=${encodeURIComponent(state.pdf)}&page=${page.pageNumber}&dpi=${PREVIEW_DPI}`
  img.alt = `Seite ${page.pageNumber}`
  root.querySelector('.preview-thumb-label').textContent = `Seite ${page.pageNumber}`
  root.addEventListener('click', () => jumpToPage(page.pageNumber))

  const cutBtn = root.querySelector('.preview-thumb-cut')
  if (page.pageNumber >= state.pageCount) {
    // no valid "cut after" position past the last page
    cutBtn.remove()
  } else {
    updatePreviewCutButton(cutBtn, page.pageNumber)
    cutBtn.addEventListener('click', (event) => {
      event.stopPropagation() // don't also trigger the thumbnail's jump-to-page click
      toggleCut(page.pageNumber)
    })
  }

  return root
}

// afterPage here is always a page number (the cut sits right after it),
// rendered as the folded-corner triangle overlaid on the thumbnail.
function updatePreviewCutButton(cutBtn, afterPage) {
  const confirmed = state.cuts.has(afterPage)
  cutBtn.classList.toggle('confirmed', confirmed)
  cutBtn.title = confirmed ? 'Schnitt entfernen' : 'Schnitt nach dieser Seite hinzufügen'
}

function renderSegments() {
  const segments = computeSegments(state.pageCount, state.cuts)
  ensureSegmentMeta(segments)

  el.docSummary.textContent = `${state.pageCount} Seiten · ${segments.length} Segmente`
  buildPreviewPanel(segments)
}

async function saveJson() {
  const segments = computeSegments(state.pageCount, state.cuts).map((seg, i) => {
    const meta = state.segmentMeta.get(seg.startPage)
    return {
      id: i + 1,
      title: meta.title,
      date: meta.date,
      start_page: seg.startPage,
      end_page: seg.endPage,
      confirmed: meta.confirmed,
      no_content: meta.noContent,
      note: meta.note,
    }
  })
  try {
    const result = await fetchJSON('/api/segmentation/save', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pdf: state.pdf, segments }),
    })
    setStatus(`Gespeichert ${new Date().toLocaleTimeString()} — ${result.saved_to}`, { flash: true })
  } catch (err) {
    setStatus(`Fehler beim Speichern: ${err.message}`)
  }
}

async function loadSegmentationFromServer(pdf, { silent = false } = {}) {
  const doc = await fetchJSON(`/api/segmentation/load?pdf=${encodeURIComponent(pdf)}`)
  state.cuts = new Set(doc.segments.slice(0, -1).map((s) => s.end_page))
  state.segmentMeta = new Map(
    doc.segments.map((s) => [s.start_page, {
      title: s.title,
      date: s.date || '',
      confirmed: s.confirmed,
      noContent: s.no_content || false,
      note: s.note || '',
    }]),
  )
  if (!silent) renderSegments()
}

// Mirrors compare_metadata.py's norm()/org_keys(): a normalized full-string
// key plus every ALL-CAPS token of plausible acronym length, so "SDS" and
// "Sozialistischer Deutscher Studentenbund (SDS)" resolve to the same key.
function normOrg(s) {
  return (s || '').normalize('NFC').replace(/\s+/g, ' ').trim().toLowerCase()
}

function orgKeys(name) {
  const keys = new Set([normOrg(name)])
  for (const token of (name || '').split(/[^A-ZÄÖÜ]+/)) {
    if (token.length >= 2 && token.length <= 6) keys.add(token.toLowerCase())
  }
  keys.delete('')
  return keys
}

// The normdatei is corpus-wide, not per-PDF, so this is loaded once at
// startup (see bottom of file) rather than on every onSelectPdf().
async function loadOrganizations() {
  state.knownOrgKeys = new Set()
  try {
    const orgs = await fetchJSON('/api/organizations/load')
    for (const org of orgs) {
      for (const key of orgKeys(org.name)) state.knownOrgKeys.add(key)
      for (const key of orgKeys(org.full_name)) state.knownOrgKeys.add(key)
      for (const variant of org.variants || []) {
        for (const key of orgKeys(variant)) state.knownOrgKeys.add(key)
      }
    }
  } catch {
    // no normdatei published yet — every org then just shows as "unknown"
  }
}

function isKnownOrg(surface) {
  for (const key of orgKeys(surface)) {
    if (state.knownOrgKeys.has(key)) return true
  }
  return false
}

// Keyed by exact "startPage_endPage" so it only ever attaches to a segment
// whose boundaries match what extract_metadata_v2.py actually saw — a range
// re-cut since then just shows nothing rather than a stale/wrong match.
async function loadExtractedMetadata(pdf) {
  state.extractedMeta = new Map()
  try {
    const doc = await fetchJSON(`/api/metadata/load?pdf=${encodeURIComponent(pdf)}`)
    for (const s of doc.segments) {
      state.extractedMeta.set(`${s.start_page}_${s.end_page}`, {
        title: s.title || '',
        issuers: s.issuers || [],
        dateText: s.date_text || '',
        dateIso: s.date_iso || '',
      })
    }
  } catch {
    // no extracted metadata for this pdf yet — leave the map empty
  }
}

async function loadJsonButtonClicked() {
  try {
    await loadSegmentationFromServer(state.pdf)
    renderSegments()
    setStatus('Segmentierung geladen.')
  } catch (err) {
    setStatus(`Keine gespeicherte Segmentierung gefunden: ${err.message}`)
  }
}

el.pdfSelect.addEventListener('change', onSelectPdf)
el.btnSave.addEventListener('click', saveJson)
el.btnLoadJson.addEventListener('click', loadJsonButtonClicked)

// --- Keyboard-only first pass: ↑/↓ (or ←/→) step through the PDF list,
// Arrow keys step through pages (no cut, just look); Space/Enter marks a cut
// after the currently-visible page and advances to the next one — so a full
// first pass can be done without touching the mouse. Ignored while an actual
// form control has focus so typing (e.g. a future title/date field) isn't
// hijacked.

function isTypingTarget(target) {
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

// Jumps to `target` and updates our own tracked "current page" immediately,
// rather than waiting for the scroll-spy to notice it via scroll events.
// The animated scroll only takes ~220ms, but late-loading (lazy) thumbnails
// below the fold can shift the list's layout underneath it, so scroll-spy
// convergence lags well behind a rapid key-repeat pass — without this, fast
// presses would double up on the same page instead of moving on each time.
function setCurrentPage(target) {
  jumpToPage(target)
  state.currentVisiblePage = target
  updateCurrentIndicator()
}

function movePage(delta) {
  if (!state.pdf) return
  const current = state.currentVisiblePage
  if (current == null) return
  const target = Math.min(state.pageCount, Math.max(1, current + delta))
  if (target === current) return
  setCurrentPage(target)
}

// "Current page" here is the same one the scroll-spy already tracks as
// visible in the right-hand detailed list — the natural page to be adding a
// cut after during a top-to-bottom pass.
function addSplitAndAdvance() {
  if (!state.pdf) return
  const current = state.currentVisiblePage
  if (current == null || current >= state.pageCount) return
  if (!state.cuts.has(current)) {
    state.cuts.add(current)
    renderSegments()
  }
  setCurrentPage(current + 1)
}

document.addEventListener('keydown', (event) => {
  if (event.ctrlKey || event.altKey || event.metaKey) return
  if (isTypingTarget(event.target)) return

  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    event.preventDefault()
    movePage(1)
  } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    event.preventDefault()
    movePage(-1)
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    addSplitAndAdvance()
  }
})

loadPdfList().catch((err) => setStatus(`Fehler beim Laden der PDF-Liste: ${err.message}`))
loadOrganizations()
