#!/usr/bin/env python3
"""Topic modelling over OCR'd leaflet text using BERTopic.

Reads datalab-format OCR JSON trees (`<id>.json`, produced by
pipelines/02_ocr/datalab_convert.py) from one or more folders (default
data/raw), strips HTML per text block (skips Picture/Figure blocks, same
rule as ner.py) and fits ONE shared BERTopic model over every leaflet's
text blocks together (block-level, not leaflet-level - a corpus of only a
dozen leaflets is too few documents for stable topic clusters, but the
thousands of individual text blocks inside them are plenty).

Each leaflet's main topic is simply the topic most of its blocks were
assigned to; a leaflet's "weights" are the normalized distribution of its
blocks over topics (outlier blocks, HDBSCAN topic -1, are excluded unless
*every* block in a leaflet is an outlier).

Sentence embeddings drive the clustering (semantic, language-agnostic),
while the human-readable topic words come from a separately lemmatized
version of the same text (spaCy, optional - degrades to raw word forms
without it) run through a German-stopword-aware c-TF-IDF vectorizer.

Requires the optional "topics" dependency group:
    pip install -e ".[topics]"
    python -m spacy download de_core_news_lg   # optional, for lemmatized topic words

A single scanned PDF can contain several distinct leaflets glued together;
`<doc_id>.segments.json` next to the OCR output (written by an earlier,
manual splitting step) records each leaflet's page range, including
multi-page leaflets. When present, blocks are also aggregated per segment
so each actually-distinct leaflet gets its own topic weights, in addition
to the whole-scan aggregate (kept for backward compatibility with
ocr_viewer, which still matches documents by the scanned PDF's id).

If a `<doc_id>.ner.json` sidecar exists (written by pipelines/03_ner/
ner.py), PERSON/LOC/ACTOR entities recognized in a block are appended as
normalized pseudo-words (e.g. "person_rudi_dutschke") to that block's text
before c-TF-IDF vectorization only - embeddings still use the raw text -
so named actors/places surface directly as topic words instead of being
diluted among generic vocabulary. TIME entities are left alone since dates
aren't a useful "topic". A missing sidecar degrades gracefully to plain
topic modelling, same as a missing segments.json.

Output: a single data/topics/topics.json:
    {
      "topics": [{"id": int, "label": str, "top_words": [str, ...], "count": int}, ...],
      "documents": [
        {"id": str, "path": str, "dataset": str,
         "dominant_topic": int | null, "weights": {"<topic_id>": float, ...},
         "segments": [                                  # only if segments.json exists
           {"segment_id": int, "start_page": int, "end_page": int,
            "dominant_topic": int | null, "weights": {"<topic_id>": float, ...}}, ...
         ]}, ...
      ]
    }

CLI:
    python pipelines/04_topic/topic_modelling.py [folder/file ...]
        [-o data/topics/topics.json] [--num-topics N] [--min-topic-size N]
        [--embedding-model NAME] [--lemma-model NAME]
"""

# Finetuning notwendig, um ideale Ergebnisse bei der Themenmodellierung zu erzielen.
# Finetuning durch Anpassung der Parameter min_topic_size, min_df und max_df

import argparse
import glob
import html
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from umap import UMAP 
from sklearn.cluster import HDBSCAN

try:
    from bertopic import BERTopic
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import CountVectorizer
except ImportError:
    BERTopic = None
    SentenceTransformer = None
    CountVectorizer = None

try:
    import stop_words
except ImportError:
    stop_words = None

try:
    import spacy
except ImportError:
    spacy = None

from huggingface_hub import login

HF_LOGIN_TOKEN = "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"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_LEMMA_MODEL = "de_core_news_lg" #Anpassbar, aber wrsl. beste Option

SKIP_BLOCK_TYPES = {"Picture", "Figure", "PictureGroup", "FigureGroup"}
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# Zusätzliche Stoppwörter, die nicht von der Standardliste abgedeckt werden.
EXTRA_STOPWORDS = [
    "daß"
]


def log(message):
    print(message, file=sys.stderr)


# Normalisierte Gewichte + dominantes Topic fuer eine Liste von Block-Topic-IDs (-1 = Ausreisser).
def topic_summary(topic_ids):
    counts = Counter(t for t in topic_ids if t != -1)
    total = sum(counts.values())
    weights = {str(t): c / total for t, c in counts.items()} if total else {}
    dominant = max(counts.items(), key=lambda kv: kv[1])[0] if total else None
    return dominant, weights


# Entfernt HTML-Tags, decodiert Entities und normalisiert Leerzeichen.
def strip_html(fragment):
    text = TAG_RE.sub(" ", fragment or "")
    text = html.unescape(text)
    return WS_RE.sub(" ", text).strip()


# Liefert (page, block_id, text) statt nur text - die Seitenzahl wird gebraucht, um
# Bloecke anhand von segments.json den einzelnen (bereits getrennten) Flugblaettern
# innerhalb eines mehrseitigen Scans zuzuordnen, die block_id, um Entities aus
# der passenden .ner.json dem richtigen Block zuzuordnen.
def iter_blocks(node):
    children = node.get("children")
    if children:
        for child in children:
            yield from iter_blocks(child)
        return
    if node.get("block_type") in SKIP_BLOCK_TYPES:
        return
    text = strip_html(node.get("html"))
    if text:
        yield node.get("page"), node.get("id"), text


def resolve_inputs(paths):
    files = []
    for path in paths:
        if os.path.isdir(path):
            for candidate in glob.glob(os.path.join(path, "**", "*.json"), recursive=True):
                base = os.path.basename(candidate)
                if base.endswith((".ner.json", ".segments.json", ".topics.json", ".segments.auto.json")):
                    continue
                files.append(candidate)
        else:
            files.append(path)
    return sorted(files)


# Der oberste Ordnername unter dem Datensatz-Root, z.B. "Nr. 001 (1967)" -
# funktioniert sowohl fuer Geschwister- als auch fuer <id>/<id>.json-Layouts.
def dataset_for(path):
    doc_id = Path(path).stem
    parent = Path(path).parent
    if parent.name == doc_id:
        parent = parent.parent
    return parent.name


def rel_path(path):
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


# Manche Scans (data/raw/<Nr. X>/<doc_id>.pdf) enthalten mehrere eigenstaendige
# Flugblaetter; <doc_id>.segments.json (neben dem OCR-Ordner, gleiche Ebene wie
# dataset_for()) haelt die bereits von Hand bestaetigten Seitenbereiche fest
# (start_page/end_page, 1-basiert, ein Segment kann mehrere Seiten umfassen).
# Gibt None zurueck, wenn keine Datei existiert (z.B. test_set) - dann bleibt
# der ganze Scan wie bisher ein einziges Leaflet.
def load_segments(path, doc_id):
    parent = Path(path).parent
    if parent.name == doc_id:
        parent = parent.parent
    seg_path = parent / f"{doc_id}.segments.json"
    if not seg_path.is_file():
        return None
    try:
        with seg_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        log(f"Skipping segments file {seg_path}: {exc}")
        return None
    segments = []
    for seg in data.get("segments", []):
        if seg.get("no_content"):
            continue
        start_page, end_page = seg.get("start_page"), seg.get("end_page")
        if start_page is None or end_page is None:
            continue
        segments.append({"segment_id": seg.get("id"), "start_page": start_page, "end_page": end_page})
    return segments or None


# Laedt die von ner.py erzeugte <doc_id>.ner.json (falls vorhanden) und baut eine
# block_id -> entities Zuordnung. Anders als segments.json liegt sie NEBEN der
# Quelldatei selbst (default_output_path() in ner.py), nicht eine Ebene hoeher.
def load_ner(path, doc_id):
    ner_path = Path(path).parent / f"{doc_id}.ner.json"
    if not ner_path.is_file():
        return None
    try:
        with ner_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        log(f"Skipping NER file {ner_path}: {exc}")
        return None
    return {block.get("block_id"): block.get("entities", []) for block in data}


BOOST_ENTITY_LABELS = {"PERSON", "LOC", "ACTOR"}  # TIME entities aren't a useful "topic"
ENTITY_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


# Baut aus einer Entity ein rein alphabetisches Pseudo-Wort (Ziffern/Satzzeichen entfernt),
# damit benannte Akteure/Orte im c-TF-IDF-Vokabular als eigenes Token auftauchen.
def entity_token(label, text):
    slug = "_".join(ENTITY_WORD_RE.findall(text.lower()))
    return f"{label.lower()}_{slug}" if slug else None


# Alle PERSON/LOC/ACTOR-Entities eines Blocks als leerzeichengetrennte Pseudo-Woerter.
def block_entity_tokens(entities):
    tokens = (
        entity_token(e.get("label"), e.get("text", ""))
        for e in entities
        if e.get("label") in BOOST_ENTITY_LABELS
    )
    return " ".join(t for t in tokens if t)


def build_leaflets(files):
    leaflets = []
    seen_keys = set()
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            log(f"Skipping {path}: {exc}")
            continue
        doc_id = Path(path).stem
        dataset = dataset_for(path)
        key = f"{dataset}/{doc_id}"
        if key in seen_keys:
            log(f"Skipping duplicate leaflet id {key}: {path}")
            continue
        seen_keys.add(key)

        blocks_with_page = list(iter_blocks(data))
        segments = []
        for seg in load_segments(path, doc_id) or []:
            lo, hi = seg["start_page"] - 1, seg["end_page"] - 1  # 0-basiert, wie das "page"-Feld der OCR-Bloecke
            block_indices = [i for i, (page, _bid, _text) in enumerate(blocks_with_page) if page is not None and lo <= page <= hi]
            if block_indices:
                segments.append({**seg, "block_indices": block_indices})

        ner_by_block = load_ner(path, doc_id) or {}
        entity_tokens = [block_entity_tokens(ner_by_block.get(block_id, [])) for _page, block_id, _text in blocks_with_page]

        leaflets.append({
            "id": doc_id,
            "path": rel_path(path),
            "dataset": dataset,
            "blocks": [text for _page, _bid, text in blocks_with_page],
            "entity_tokens": entity_tokens,
            "segments": segments,
        })
    return leaflets


def build_nlp(model_name):
    if spacy is None:
        log("spaCy is not installed; topic words will use raw (non-lemmatized) word forms.")
        return None
    try:
        return spacy.load(model_name, disable=["ner", "parser"])
    except OSError:
        log(
            f"spaCy model '{model_name}' is not installed "
            f"(run: python -m spacy download {model_name}); "
            "topic words will use raw (non-lemmatized) word forms."
        )
        return None


# Lemmatisiert fuer die Themen-Repraesentation; die Embeddings nutzen weiterhin den Rohtext.
def lemmatize_texts(texts, nlp):
    if nlp is None:
        return texts
    lemmatized = []
    for doc in nlp.pipe(texts, batch_size=64):
        lemmatized.append(" ".join(tok.lemma_.lower() for tok in doc if tok.is_alpha and len(tok) >= 3))
    return lemmatized


GARBAGE_RUN_RE = re.compile(r"(.)\1{3,}")  # entfernt z.B. "aaaaaaa"/"ssssss" Noise von schlechten OCR-Seiten


# Kleinschreibung + Entfernen von Zeichenwiederholungen (OCR-Artefakte), vor der Tokenisierung.
def clean_preprocessor(doc):
    return GARBAGE_RUN_RE.sub(" ", doc.lower())


def build_vectorizer():
    german_stopwords = set(w.lower() for w in stop_words.get_stop_words("german")) if stop_words else set()
    stopwords = sorted(german_stopwords | set(EXTRA_STOPWORDS))
    return CountVectorizer(
        preprocessor=clean_preprocessor,
        stop_words=stopwords,
        ngram_range=(1, 2),
        # underscore allowed (not just letters) so entity_token()'s "label_multi_word" pseudo-words stay one token
        token_pattern=r"(?u)\b[^\W\d]{3,}\b",
        min_df=5,
        max_df=0.9,
    )


ENTITY_TOKEN_RE = re.compile(r"^(?:person|loc|actor)_(.+)$")


# Zeigt ein Entity-Pseudo-Wort wieder als lesbaren Namen an ("person_rudi_dutschke" -> "Rudi Dutschke").
def humanize_word(word):
    match = ENTITY_TOKEN_RE.match(word)
    if not match:
        return word
    return match.group(1).replace("_", " ").title()


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="*", default=["data/raw"], help="OCR JSON file(s)/folder(s) to scan (default: data/raw)")
    p.add_argument("-o", "--output", default="data/topics/topics.json", help="output path (default: data/topics/topics.json)")
    p.add_argument("--num-topics", type=int, default=None, help="fix the number of topics (default: BERTopic's automatic reduction)")
    p.add_argument("--min-topic-size", type=int, default=20, help="minimum blocks per topic cluster (default: 20)")
    p.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help=f"sentence-transformers model name (default: {DEFAULT_EMBEDDING_MODEL})")
    p.add_argument("--lemma-model", default=DEFAULT_LEMMA_MODEL, help=f"spaCy model for lemmatizing topic words (default: {DEFAULT_LEMMA_MODEL})")
    return p.parse_args()

def build_hdbscan_model():
    return HDBSCAN(
        min_cluster_size=25,
        min_samples=5,
        metric="euclidean",
        cluster_selection_method="eom"
    )

def build_umap_model():
    return UMAP(
        n_neighbors=30,
        min_dist=0.0,
        n_components=5,
        metric="cosine",
    )

def main():
    login(token=HF_LOGIN_TOKEN)
    args = parse_args()
    if BERTopic is None or SentenceTransformer is None:
        sys.exit(
            "bertopic/sentence-transformers are not installed. Run:\n"
            '  pip install -e ".[topics]"'
        )

    files = resolve_inputs(args.inputs)
    if not files:
        sys.exit("No input files found.")

    leaflets = build_leaflets(files)
    raw_blocks = [block for leaflet in leaflets for block in leaflet["blocks"]]
    entity_tokens = [tokens for leaflet in leaflets for tokens in leaflet["entity_tokens"]]
    if len(raw_blocks) < 2:
        sys.exit(f"Only {len(raw_blocks)} text block(s) found across {len(leaflets)} leaflet(s); need more to fit a topic model.")
    log(f"{len(leaflets)} leaflets, {len(raw_blocks)} text blocks")
    n_boosted = sum(1 for t in entity_tokens if t)
    if n_boosted:
        log(f"NER boosting: {n_boosted}/{len(raw_blocks)} blocks have PERSON/LOC/ACTOR entity tokens from .ner.json sidecars")

    nlp = build_nlp(args.lemma_model)
    lemmatized_blocks = lemmatize_texts(raw_blocks, nlp)
    # append entity pseudo-words to the c-TF-IDF input only; embeddings below stay on raw_blocks
    augmented_blocks = [f"{lemma} {tokens}".strip() if tokens else lemma for lemma, tokens in zip(lemmatized_blocks, entity_tokens)]

    log(f"Embedding {len(raw_blocks)} blocks with '{args.embedding_model}' ...")
    embedder = SentenceTransformer(args.embedding_model)
    embeddings = embedder.encode(raw_blocks, show_progress_bar=True, batch_size=64)

    topic_model = BERTopic(
        umap_model=build_umap_model(),
        hdbscan_model=build_hdbscan_model(),
        vectorizer_model=build_vectorizer(),
        calculate_probabilities=False,
        min_topic_size=args.min_topic_size,
        nr_topics=args.num_topics or "auto",
        # BERTopic's default language="english" strips everything but
        # [A-Za-z0-9 ] before computing topic words (see _preprocess_text in
        # its source) - fatal for German umlauts/ß; "multilingual" skips that.
        language="multilingual",
        verbose=True,
    )
    log("Fitting BERTopic ...")
    topics, _ = topic_model.fit_transform(augmented_blocks, embeddings=embeddings)

    topic_ids = sorted(t for t in set(topics) if t != -1)
    topics_out = []
    empty_topic_ids = set()
    for topic_id in topic_ids:
        words = topic_model.get_topic(topic_id) or []
        top_words = [humanize_word(w) for w, _score in words[:10] if w]
        if not top_words:
            empty_topic_ids.add(topic_id)
            continue
        topics_out.append({
            "id": topic_id,
            "label": "_".join(top_words[:3]),
            "top_words": top_words,
            "count": sum(1 for t in topics if t == topic_id),
        })

    # blocks in an uninterpretable topic can't meaningfully be a leaflet's "topic" - treat like outliers (-1)
    topics = [-1 if t in empty_topic_ids else t for t in topics]

    documents_out = []
    idx = 0
    for leaflet in leaflets:
        n = len(leaflet["blocks"])
        leaflet_topics = topics[idx:idx + n]
        idx += n
        dominant, weights = topic_summary(leaflet_topics)
        doc_out = {
            "id": leaflet["id"],
            "path": leaflet["path"],
            "dataset": leaflet["dataset"],
            "dominant_topic": dominant,
            "weights": weights,
        }
        # scans already split (via segments.json) into several actual leaflets get a
        # finer per-leaflet breakdown too, without changing the whole-scan entry above
        # (which ocr_viewer still matches by the scan/PDF's own id).
        if leaflet["segments"]:
            doc_out["segments"] = []
            for seg in leaflet["segments"]:
                seg_dominant, seg_weights = topic_summary([leaflet_topics[i] for i in seg["block_indices"]])
                doc_out["segments"].append({
                    "segment_id": seg["segment_id"],
                    "start_page": seg["start_page"],
                    "end_page": seg["end_page"],
                    "dominant_topic": seg_dominant,
                    "weights": seg_weights,
                })
        documents_out.append(doc_out)
    documents_out.sort(key=lambda d: d["id"])

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump({"topics": topics_out, "documents": documents_out}, f, ensure_ascii=False, indent=2)

    n_outliers = sum(1 for t in topics if t == -1)
    log(f"-> {output_path} ({len(topics_out)} topics, {len(documents_out)} leaflets, {n_outliers}/{len(topics)} outlier blocks)")


if __name__ == "__main__":
    main()
