#!/usr/bin/env python3
"""Einfache N-Gramm-Analysen auf den OCR-Volltexten der Flugblattsammlung.

Nur Standardbibliothek - kein pandas, kein nltk, keine Modelle. Gedacht als
erster Zugriff auf das Material und als Referenz dafuer, welche Vorverarbeitung
bei diesen Scans noetig ist (siehe --raw, um den Unterschied zu sehen).

Liest die Datalab-OCR-Jsons direkt aus data/raw/**, filtert Kopf-/Fusszeilen
ueber die Blocktypen und legt den Plaintext in data/cache/ngram_txt/ ab, damit
nur der erste Lauf die grossen Jsons parsen muss.

Beispiele:
    python pipelines/06_analysis/ngrams.py size
    python pipelines/06_analysis/ngrams.py top -n 2 --top 25
    python pipelines/06_analysis/ngrams.py top -n 3 --raw          # ohne Bereinigung
    python pipelines/06_analysis/ngrams.py trend notstand vietnam streik berufsverbot
    python pipelines/06_analysis/ngrams.py trend "numerus clausus" "kampf gegen"
    python pipelines/06_analysis/ngrams.py keyness --min-count 25
    python pipelines/06_analysis/ngrams.py collocates spd --year 1972
    python pipelines/06_analysis/ngrams.py collocates "verfaßten studentenschaft" --measure dice
    python pipelines/06_analysis/ngrams.py kwic Berufsverbot --limit 12
    python pipelines/06_analysis/ngrams.py hyphens -o docs/korpus/dehyphenierung.tsv
"""

from __future__ import annotations

import argparse
import collections
import html as html_lib
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "data" / "raw"
CACHE = REPO_ROOT / "data" / "cache" / "ngram_txt"

# Band -> Erscheinungsjahr. Mehrere Baende koennen dasselbe Jahr haben.
YEARS = {
    "0118_0001": 1967, "0118_0002": 1968, "0118_0003": 1969, "0118_0004": 1970,
    "0118_0005": 1971, "0118_0006": 1972, "0118_0007": 1972, "0118_0008": 1972,
    "0118_0009": 1972, "0118_0010": 1973, "0118_0011": 1973, "0118_0012": 1973,
    "0118_0013": 1973, "0118_0014": 1973,
}

# Blocktypen, die nicht in die Analyse gehoeren: Kopfleisten ("LSD - LSD - LSD"),
# Seitenzahlen, Bildunterschriften. Kostet nichts, weil Datalab sie ohnehin labelt.
DROP_BLOCKS = {"PageHeader", "PageFooter", "PageNumber", "Picture", "Figure"}

STOPWORD_FILE = Path(__file__).with_name("stopwords_de.txt")

# Notliste, falls stopwords_de.txt fehlt. Bewusst knapp - die gepflegte Liste
# steht in der Datei daneben, versioniert und mit Quellenangabe.
FALLBACK_STOPWORDS = set("""
aber als am an auch auf aus bei bin bis bist da damit dann das dass daß dazu dem den denn der des die diese dieser
dir doch du durch ein eine einem einen einer eines er es für gegen hat hatte hier ich ihm ihn ihnen ihr ihre im in
ist ja kann kein man mit nach nicht noch nun nur ob oder ohne sein sich sie sind so um und uns unter vom von vor war
waren was weil wenn wer werden wie wir wird wo zu zum zur zwischen
""".split())


def load_stopwords(path: Path | None = None) -> set[str]:
    """Eine Zeile = ein Wort; '#' leitet Kommentare ein, '## projekt' trennt die
    projektspezifischen Ergaenzungen ab (wird als Kommentar mitgelesen)."""
    path = path or STOPWORD_FILE
    if not path.is_file():
        print(f"[warn] {path.name} nicht gefunden - benutze die kurze Notliste "
              f"({len(FALLBACK_STOPWORDS)} Woerter)", file=sys.stderr)
        return set(FALLBACK_STOPWORDS)
    words = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            words.add(line)
    return words


STOPWORDS = load_stopwords()

TAG_RE = re.compile(r"<[^>]+>")
# Kein Token endet auf einem Bindestrich: 'Sprach- und' ergibt 'sprach', nicht
# 'sprach-'. Binnenbindestriche bleiben erhalten ('christlich-demokratisch').
WORD_RE = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")


# --------------------------------------------------------------------------- laden

def ocr_json_path(stem: str) -> Path:
    matches = [d for d in RAW.iterdir() if d.is_dir() and d.name.startswith(f"Nr. {stem[-3:]}")]
    if not matches:
        raise FileNotFoundError(f"Kein Ordner 'Nr. {stem[-3:]} (...)' unter {RAW}")
    return matches[0] / stem / f"{stem}.json"


def block_text(block: dict) -> str:
    return html_lib.unescape(TAG_RE.sub("\n", block.get("html", "")))


def extract_plaintext(stem: str, keep_headers: bool) -> str:
    """Seiten durch \\f getrennt; Kopf-/Fusszeilen je nach Flag mit oder ohne."""
    data = json.loads(ocr_json_path(stem).read_text(encoding="utf-8"))
    pages = []
    for page in data["children"]:
        parts = []
        for block in page.get("children", []):
            if not keep_headers and block.get("block_type") in DROP_BLOCKS:
                continue
            parts.append(block_text(block))
        text = "\n".join(parts)
        pages.append("\n".join(line.strip() for line in text.split("\n") if line.strip()))
    return "\n\f\n".join(pages)


def load_text(stem: str, keep_headers: bool = False) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{stem}{'.full' if keep_headers else ''}.txt"
    if not cached.is_file():
        cached.write_text(extract_plaintext(stem, keep_headers), encoding="utf-8")
    return cached.read_text(encoding="utf-8")


# --------------------------------------------------------------- vorverarbeitung

HYPHEN_BREAK = re.compile(r"([^\W\d_]+)-\n([^\W\d_]+)")

# Nach diesen Woertern ist der Bindestrich ein Ergaenzungsstrich und gehoert
# nicht weg: "Sprach-\nund Literaturwissenschaften" -> "Sprach- und ...".
ELLIPSIS_NEXT = {"und", "oder", "bzw", "beziehungsweise", "sowie", "resp"}

INLINE_WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
_VOCAB_CACHE: dict[str, collections.Counter] = {}


def inline_vocab(stems) -> collections.Counter:
    """Wortschatz aus Tokens, die vollstaendig INNERHALB einer Zeile stehen.

    Zeilenuebergreifende Trennungen bleiben aussen vor - sonst wuerde die
    Entscheidung, ob 'Hilfskammer-\\nmensch' zusammengehoert, mit sich selbst
    begruendet. So ist sie durch andere Textstellen belegt."""
    key = ",".join(sorted(stems))
    if key not in _VOCAB_CACHE:
        vocab = collections.Counter()
        for stem in stems:
            for line in load_text(stem).split("\n"):
                for w in INLINE_WORD.findall(line):
                    vocab[w.lower()] += 1
        _VOCAB_CACHE[key] = vocab
    return _VOCAB_CACHE[key]


def hyphen_decision(a: str, b: str, vocab: collections.Counter | None) -> tuple[str, str]:
    """-> (entscheidung, begruendung). Drei Ausgaenge, nicht zwei:

      join     'Hilfskammer-\\nmensch'  -> 'Hilfskammermensch'  (Worttrennung)
      hyphen   'AStA-\\nFraktion'       -> 'AStA-Fraktion'      (Kompositum, das
                                                                zufaellig an seinem
                                                                eigenen Strich umbricht)
      ellipsis 'Sprach-\\nund'          -> 'Sprach- und'        (Ergaenzungsstrich)

    Reihenfolge: Ergaenzungsstrich zuerst, dann der Korpusbeleg, dann die Form.
    """
    if b.lower() in ELLIPSIS_NEXT:
        return "ellipsis", "ergaenzungsstrich"
    if vocab is not None:
        joined = vocab[(a + b).lower()]
        hyphened = vocab[f"{a}-{b}".lower()]
        if joined and not hyphened:
            return "join", f"beleg_joined({joined})"
        if hyphened and not joined:
            return "hyphen", f"beleg_hyph({hyphened})"
        if joined and hyphened:
            return ("join" if joined >= hyphened else "hyphen",
                    f"beleg_beide(j={joined},h={hyphened})")
    # Kein Beleg: Grossschreibung beider Teile spricht fuer ein echtes Kompositum
    # ("Christlich-Demokratischer"), ausser der Text ist durchgaengig VERSAL -
    # dann ist die Grossschreibung kein Signal ("HOCH-\nSCHULPOLITISCHEN").
    both_caps = a[:1].isupper() and b[:1].isupper()
    all_caps = a.isupper() and b.isupper()
    if both_caps and not all_caps:
        return "hyphen", "form_kompositum"
    return "join", "form_trennung"


def apply_decision(a: str, b: str, decision: str) -> str:
    if decision == "join":
        return a + b
    if decision == "hyphen":
        return f"{a}-{b}"
    return f"{a}- {b}"


def dehyphenate(text: str, vocab: collections.Counter | None = None) -> str:
    """'Hilfskammer-\\nmensch' -> 'Hilfskammermensch'. Ohne diesen Schritt zerfaellt
    jedes am Zeilenende getrennte Wort in zwei Nicht-Woerter.

    Mit `vocab` (siehe inline_vocab) wird jeder Fall am uebrigen Korpus geprueft,
    statt blind zusammenzuziehen; ohne entscheidet nur die Form."""
    def repl(m):
        a, b = m.group(1), m.group(2)
        decision, _ = hyphen_decision(a, b, vocab)
        return apply_decision(a, b, decision)
    return HYPHEN_BREAK.sub(repl, text)


def tokenize(text: str, dehyph: bool = True, min_len: int = 3,
             vocab: collections.Counter | None = None) -> list[str]:
    if dehyph:
        text = dehyphenate(text, vocab)
    text = unicodedata.normalize("NFC", text)
    return [t.lower() for t in WORD_RE.findall(text) if len(t) >= min_len]


def collapse_runs(tokens: list[str], k: int = 3) -> list[str]:
    """Sigel-Leisten ('LSD - LSD - LSD - ...') stauchen: Laeufe desselben Tokens
    ab Laenge k auf ein Vorkommen. Ohne das dominieren sie jede Trigramm-Liste."""
    out, run = [], 1
    for i, w in enumerate(tokens):
        run = run + 1 if i and w == tokens[i - 1] else 1
        if run < k:
            out.append(w)
    return out


# Wird in main() gesetzt: der Korpus-Wortschatz, an dem Trennungen geprueft
# werden. None = nur Formregeln (siehe --no-vocab).
VOCAB: collections.Counter | None = None


def prepare(stem: str, raw: bool = False, vocab: collections.Counter | None = None) -> list[str]:
    tokens = tokenize(load_text(stem, keep_headers=raw), dehyph=not raw,
                      vocab=VOCAB if vocab is None else vocab)
    return tokens if raw else collapse_runs(tokens)


def prepare_pages(stem: str) -> list[list[str]]:
    """Wie prepare(), aber eine Tokenliste pro Seite - Grundlage fuer Streuungs-
    masse ('auf wie vielen Seiten?') statt reiner Tokenzaehlung."""
    return [collapse_runs(tokenize(page, vocab=VOCAB))
            for page in load_text(stem).split("\f")]


# ------------------------------------------------------------------- ngramme

def ngram_counts(tokens: list[str], n: int, min_content: int = 1) -> collections.Counter:
    """N-Gramme mit mindestens min_content Nicht-Stoppwoertern."""
    counts = collections.Counter()
    if n == 1:
        for w in tokens:
            if min_content == 0 or w not in STOPWORDS:
                counts[w] += 1
        return counts
    grams = zip(*[tokens[i:] for i in range(n)])
    for g in grams:
        if sum(1 for w in g if w not in STOPWORDS) >= min_content:
            counts[" ".join(g)] += 1
    return counts


def log_likelihood(a: int, b: int, size_a: int, size_b: int) -> float:
    """Dunnings G2, signiert: positiv = im Teilkorpus ueberrepraesentiert."""
    e1 = size_a * (a + b) / (size_a + size_b)
    e2 = size_b * (a + b) / (size_a + size_b)
    g2 = 0.0
    if a:
        g2 += a * math.log(a / e1)
    if b:
        g2 += b * math.log(b / e2)
    return 2 * g2 * (1 if a / size_a > b / size_b else -1)


def log_dice(a: int, f_node: int, f_coll: int) -> float:
    """logDice (Rychly 2008): 14 + log2(2a / (f_node + f_coll)).

    Anders als G2 waechst logDice nicht mit der Korpusgroesse und bevorzugt
    keine Hochfrequenzwoerter - deshalb in der Korpuslinguistik der uebliche
    Wert fuer Kollokationslisten. Skala grob: > 9 sehr stark, 7-9 stark,
    unter 5 kaum bemerkenswert."""
    if a == 0 or f_node + f_coll == 0:
        return float("-inf")
    return 14 + math.log2(2 * a / (f_node + f_coll))


def find_term(tokens: list[str], term: list[str]) -> list[int]:
    """Startpositionen des (ggf. mehrwortigen) Suchausdrucks."""
    n = len(term)
    return [i for i in range(len(tokens) - n + 1) if tokens[i:i + n] == term]


def collocates(pages: list[list[str]], term: list[str], window: int
               ) -> tuple[collections.Counter, int, int, list[int]]:
    """-> (Kollokat-Zaehler, Treffer gesamt, Seiten mit Treffer, Treffer je Seite)"""
    coll = collections.Counter()
    hits = 0
    per_page = []
    for tokens in pages:
        positions = find_term(tokens, term)
        per_page.append(len(positions))
        hits += len(positions)
        for i in positions:
            lo, hi = max(0, i - window), min(len(tokens), i + len(term) + window)
            for j in range(lo, hi):
                if i <= j < i + len(term):
                    continue
                coll[tokens[j]] += 1
    return coll, hits, sum(1 for n in per_page if n), per_page


def kwic(text: str, term: str, width: int = 45, limit: int = 10) -> list[tuple[int, str]]:
    """-> [(seite, fundstelle), ...]. Seite ist 1-basiert (text.split('\\f'))."""
    hits = []
    for page_num, page in enumerate(text.split("\f"), start=1):
        flat = re.sub(r"\s+", " ", dehyphenate(page))
        for m in re.finditer(re.escape(term), flat, re.IGNORECASE):
            s, e = max(0, m.start() - width), min(len(flat), m.end() + width)
            hits.append((page_num, f"…{flat[s:m.start()]}[{flat[m.start():m.end()]}]{flat[m.end():e]}…"))
            if len(hits) >= limit:
                return hits
    return hits


# ------------------------------------------------------------------ kommandos

def by_year(stems, raw=False):
    buckets = collections.defaultdict(list)
    for stem in stems:
        buckets[YEARS[stem]] += prepare(stem, raw)
    return dict(sorted(buckets.items()))


def cmd_size(args):
    print(f"{'Jahr':<6}{'Seiten':>8}{'Token':>10}  Baende")
    total_t = total_p = 0
    for year in sorted(set(YEARS.values())):
        stems = [s for s in args.stems if YEARS[s] == year]
        if not stems:
            continue
        pages = sum(load_text(s).count("\f") + 1 for s in stems)
        toks = sum(len(prepare(s)) for s in stems)
        total_p += pages
        total_t += toks
        print(f"{year:<6}{pages:>8}{toks:>10}  {', '.join(stems)}")
    print(f"{'Summe':<6}{total_p:>8}{total_t:>10}")


def cmd_top(args):
    tokens = []
    for stem in args.stems:
        tokens += prepare(stem, args.raw)
    if args.n == 1:
        min_content = 0 if args.with_stopwords else 1
    else:
        min_content = 2 if args.n >= 3 else 1
    counts = ngram_counts(tokens, args.n, min_content)
    label = "roh" if args.raw else "bereinigt"
    print(f"Top-{args.top} {args.n}-Gramme ({label}, {len(tokens)} Token):")
    for gram, n in counts.most_common(args.top):
        print(f"  {n:>6}  {gram}")


def cmd_trend(args):
    buckets = by_year(args.stems)
    years = list(buckets)
    sizes = {y: len(t) for y, t in buckets.items()}
    max_n = max(len(t.split()) for t in args.terms)
    counts = {y: {n: ngram_counts(buckets[y], n, 0 if n == 1 else 1) for n in range(1, max_n + 1)}
              for y in years}
    print("Relative Frequenz pro 10.000 Token")
    print(f"{'':<26}" + "".join(f"{y:>8}" for y in years))
    for term in args.terms:
        t = term.lower()
        n = len(t.split())
        row = [1e4 * counts[y][n][t] / sizes[y] for y in years]
        print(f"  {term:<24}" + "".join(f"{v:>8.1f}" for v in row))
    print(f"\n  Basis (Token je Jahr):    " + "".join(f"{sizes[y]:>8}" for y in years))


def cmd_keyness(args):
    buckets = by_year(args.stems)
    sizes = {y: len(t) for y, t in buckets.items()}
    counts = {y: ngram_counts(buckets[y], args.n, 1) for y in buckets}
    total = collections.Counter()
    for c in counts.values():
        total += c
    n_all = sum(sizes.values())
    print(f"Distinktive {args.n}-Gramme je Jahr (G2 gegen alle uebrigen Jahre, "
          f"mind. {args.min_count} Treffer)")
    for year in buckets:
        scored = []
        for gram, a in counts[year].items():
            if a < args.min_count:
                continue
            scored.append((log_likelihood(a, total[gram] - a, sizes[year], n_all - sizes[year]), gram, a))
        scored.sort(reverse=True)
        print(f"  {year}: " + ", ".join(f"{g} ({a})" for _, g, a in scored[:args.top]))


def cmd_collocates(args):
    term = [w.lower() for w in args.term.lower().split()]
    stems = args.stems
    if args.year:
        wanted = {int(y) for y in args.year.split(",")}
        stems = [s for s in stems if YEARS[s] in wanted]
        if not stems:
            sys.exit(f"Keine Baende fuer Jahr(e) {sorted(wanted)}")

    pages = []
    for stem in stems:
        pages += prepare_pages(stem)
    corpus = collections.Counter()
    for p in pages:
        corpus.update(p)
    n_tokens = sum(corpus.values())

    coll, hits, hit_pages, per_page = collocates(pages, term, args.window)
    if not hits:
        sys.exit(f"'{args.term}' kommt in {', '.join(stems)} nicht vor.")

    scope = f"Jahr(e) {args.year}" if args.year else f"{len(stems)} Band/Baende"
    print(f"'{args.term}' — {scope}: {hits} Treffer auf {hit_pages} von {len(pages)} Seiten "
          f"({1e4 * hits / n_tokens:.2f} pro 10.000 Token)")

    # Streuung: liegt alles in wenigen Dokumenten, ist der Befund ein Artefakt
    top = sorted(per_page, reverse=True)[:10]
    print(f"  Streuung: die 10 stärksten Seiten stellen {100 * sum(top) / hits:.0f} % der Treffer"
          f"{'  ← Vorsicht, stark konzentriert' if sum(top) / hits > 0.5 else ''}")

    n_coll = sum(coll.values())
    scored = []
    for w, a in coll.items():
        if a < args.min_count or w in STOPWORDS or w in term:
            continue
        if args.measure == "dice":
            score = log_dice(a, hits, corpus[w])
        else:
            score = log_likelihood(a, max(corpus[w] - a, 0), n_coll, n_tokens)
        scored.append((score, w, a, corpus[w]))
    scored.sort(reverse=True)

    label = "logDice" if args.measure == "dice" else "G2"
    print(f"\n  Kollokate im Fenster ±{args.window} (mind. {args.min_count} gemeinsame Treffer), "
          f"nach {label}:")
    print(f"    {'Kollokat':<28}{'gem.':>6}{'gesamt':>8}{label:>9}")
    for score, w, a, total in scored[:args.top]:
        print(f"    {w:<28}{a:>6}{total:>8}{score:>9.1f}")
    if not scored:
        print("    (nichts oberhalb der Mindesthäufigkeit)")


def cmd_hyphens(args):
    """Alle Zeilenend-Trennungen auflisten, mit Entscheidung und Begruendung."""
    vocab = None if args.no_vocab else inline_vocab(args.stems)
    rows = {}
    for stem in args.stems:
        text = load_text(stem)
        for m in HYPHEN_BREAK.finditer(text):
            a, b = m.group(1), m.group(2)
            key = (a, b)
            row = rows.setdefault(key, {"n": 0, "bands": set(), "context": ""})
            row["n"] += 1
            row["bands"].add(stem)
            if not row["context"]:
                s = max(0, m.start() - 40)
                row["context"] = re.sub(r"\s+", " ", text[s:m.end() + 40])

    counts = collections.Counter()
    out = []
    for (a, b), row in rows.items():
        decision, reason = hyphen_decision(a, b, vocab)
        counts[(decision, reason.split("(")[0])] += row["n"]
        out.append({
            "n": row["n"], "a": a, "b": b,
            "ergebnis": apply_decision(a, b, decision),
            "entscheidung": decision, "begruendung": reason,
            "vok_joined": vocab[(a + b).lower()] if vocab else "",
            "vok_hyph": vocab[f"{a}-{b}".lower()] if vocab else "",
            "baende": " ".join(sorted(row["bands"])), "kontext": row["context"],
        })
    out.sort(key=lambda r: (r["entscheidung"], -r["n"], r["a"].lower()))

    total = sum(r["n"] for r in out)
    print(f"{total} Trennungen an Zeilenenden, {len(out)} verschiedene Paare "
          f"({'mit' if vocab else 'ohne'} Korpusbeleg)")
    for (decision, reason), n in counts.most_common():
        print(f"  {n:>5}  {decision:<8} {reason}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        import csv
        with args.out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0]), delimiter="\t")
            w.writeheader()
            w.writerows(out)
        print(f"\nVollstaendige Liste: {args.out}  ({len(out)} Zeilen)")
    else:
        print()
        for r in out[:args.top]:
            print(f"  {r['n']:>3}  {r['a']}-{r['b']:<28} -> {r['ergebnis']:<32} "
                  f"{r['entscheidung']:<8} {r['begruendung']}")


def cmd_kwic(args):
    for stem in args.stems:
        text = load_text(stem)
        for page_num, line in kwic(text, args.term, args.width, args.limit):
            print(f"  [{YEARS[stem]} {stem} p{page_num}] {line}")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bands", default=",".join(YEARS),
                   help="kommaseparierte Band-Stems (Standard: alle)")
    p.add_argument("--stopwords", type=Path, default=None, metavar="PATH",
                   help=f"alternative Stoppwortliste (Standard: {STOPWORD_FILE.name} neben diesem Skript)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("size", help="Korpusgroesse je Jahr")
    s.set_defaults(func=cmd_size)

    s = sub.add_parser("top", help="haeufigste N-Gramme")
    s.add_argument("-n", type=int, default=2, help="N (1=Unigramme, 2=Bigramme, ...)")
    s.add_argument("--top", type=int, default=20)
    s.add_argument("--raw", action="store_true",
                   help="ohne Bereinigung: mit Kopfzeilen, ohne Dehyphenierung, ohne Sigel-Kollaps")
    s.add_argument("--with-stopwords", action="store_true",
                   help="nur bei -n 1: Stoppwoerter mitzaehlen (zeigt, warum man sie sonst entfernt)")
    s.set_defaults(func=cmd_top)

    s = sub.add_parser("trend", help="relative Frequenz je Jahr fuer einzelne Terme")
    s.add_argument("terms", nargs="+", help="Woerter oder Mehrwortausdruecke in Anfuehrungszeichen")
    s.set_defaults(func=cmd_trend)

    s = sub.add_parser("keyness", help="distinktive N-Gramme je Jahr (Dunnings G2)")
    s.add_argument("-n", type=int, default=1)
    s.add_argument("--min-count", type=int, default=25)
    s.add_argument("--top", type=int, default=10)
    s.set_defaults(func=cmd_keyness)

    s = sub.add_parser("collocates", help="Kollokate eines Ausdrucks, mit Streuungspruefung")
    s.add_argument("term", help="Wort oder Mehrwortausdruck in Anfuehrungszeichen")
    s.add_argument("--year", metavar="JAHR[,JAHR]", help="auf diese Jahre einschraenken")
    s.add_argument("-w", "--window", type=int, default=5, help="Fenstergroesse in Token (Standard: 5)")
    s.add_argument("--measure", choices=["ll", "dice"], default="ll",
                   help="ll = Dunnings G2 (Standard), dice = logDice (frequenzrobuster)")
    s.add_argument("--min-count", type=int, default=4, help="Mindestzahl gemeinsamer Treffer")
    s.add_argument("--top", type=int, default=20)
    s.set_defaults(func=cmd_collocates)

    s = sub.add_parser("hyphens", help="alle Zeilenend-Trennungen mit Entscheidung auflisten")
    s.add_argument("-o", "--out", type=Path, metavar="PATH",
                   help="vollstaendige Liste als TSV schreiben (sonst nur die haeufigsten auf stdout)")
    s.add_argument("--top", type=int, default=40, help="Zeilen auf stdout, wenn kein --out")
    s.add_argument("--no-vocab", action="store_true",
                   help="nur Formregeln, ohne Abgleich mit dem uebrigen Korpus")
    s.set_defaults(func=cmd_hyphens)

    s = sub.add_parser("kwic", help="Konkordanz (keyword in context)")
    s.add_argument("term")
    s.add_argument("--width", type=int, default=45)
    s.add_argument("--limit", type=int, default=10, help="Belege je Band")
    s.set_defaults(func=cmd_kwic)

    args = p.parse_args(argv)
    if args.stopwords:
        global STOPWORDS
        STOPWORDS = load_stopwords(args.stopwords)
    args.stems = [b.strip() for b in args.bands.split(",") if b.strip()]
    unknown = [b for b in args.stems if b not in YEARS]
    if unknown:
        sys.exit(f"Unbekannte Baende: {unknown}")
    if args.cmd != "hyphens" and not getattr(args, "raw", False):
        global VOCAB
        VOCAB = inline_vocab(args.stems)
    return args


if __name__ == "__main__":
    a = parse_args()
    a.func(a)
