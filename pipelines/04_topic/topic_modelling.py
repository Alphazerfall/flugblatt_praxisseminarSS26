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

Output: a single data/topics/topics.json:
    {
      "topics": [{"id": int, "label": str, "top_words": [str, ...], "count": int}, ...],
      "documents": [
        {"id": str, "path": str, "dataset": str,
         "dominant_topic": int | null, "weights": {"<topic_id>": float, ...}}, ...
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


# Entfernt HTML-Tags, decodiert Entities und normalisiert Leerzeichen.
def strip_html(fragment):
    text = TAG_RE.sub(" ", fragment or "")
    text = html.unescape(text)
    return WS_RE.sub(" ", text).strip()


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
        yield text


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
        leaflets.append({
            "id": doc_id,
            "path": rel_path(path),
            "dataset": dataset,
            "blocks": list(iter_blocks(data)),
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
        token_pattern=r"(?u)\b[^\W\d_]{3,}\b",
        min_df=5,
        max_df=0.9,
    )


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="*", default=["data/raw"], help="OCR JSON file(s)/folder(s) to scan (default: data/raw)")
    p.add_argument("-o", "--output", default="data/topics/topics.json", help="output path (default: data/topics/topics.json)")
    p.add_argument("--num-topics", type=int, default=None, help="fix the number of topics (default: BERTopic's automatic reduction)")
    p.add_argument("--min-topic-size", type=int, default=20, help="minimum blocks per topic cluster (default: 20)")
    p.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help=f"sentence-transformers model name (default: {DEFAULT_EMBEDDING_MODEL})")
    p.add_argument("--lemma-model", default=DEFAULT_LEMMA_MODEL, help=f"spaCy model for lemmatizing topic words (default: {DEFAULT_LEMMA_MODEL})")
    return p.parse_args()


def main():
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
    if len(raw_blocks) < 2:
        sys.exit(f"Only {len(raw_blocks)} text block(s) found across {len(leaflets)} leaflet(s); need more to fit a topic model.")
    log(f"{len(leaflets)} leaflets, {len(raw_blocks)} text blocks")

    nlp = build_nlp(args.lemma_model)
    lemmatized_blocks = lemmatize_texts(raw_blocks, nlp)

    log(f"Embedding {len(raw_blocks)} blocks with '{args.embedding_model}' ...")
    embedder = SentenceTransformer(args.embedding_model)
    embeddings = embedder.encode(raw_blocks, show_progress_bar=True, batch_size=64)

    topic_model = BERTopic(
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
    topics, _ = topic_model.fit_transform(lemmatized_blocks, embeddings=embeddings)

    topic_ids = sorted(t for t in set(topics) if t != -1)
    topics_out = []
    empty_topic_ids = set()
    for topic_id in topic_ids:
        words = topic_model.get_topic(topic_id) or []
        top_words = [w for w, _score in words[:10] if w]
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
        counts = Counter(t for t in leaflet_topics if t != -1)
        total = sum(counts.values())
        weights = {str(t): c / total for t, c in counts.items()} if total else {}
        dominant = max(counts.items(), key=lambda kv: kv[1])[0] if total else None
        documents_out.append({
            "id": leaflet["id"],
            "path": leaflet["path"],
            "dataset": leaflet["dataset"],
            "dominant_topic": dominant,
            "weights": weights,
        })
    documents_out.sort(key=lambda d: d["id"])

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump({"topics": topics_out, "documents": documents_out}, f, ensure_ascii=False, indent=2)

    n_outliers = sum(1 for t in topics if t == -1)
    log(f"-> {output_path} ({len(topics_out)} topics, {len(documents_out)} leaflets, {n_outliers}/{len(topics)} outlier blocks)")


if __name__ == "__main__":
    main()
