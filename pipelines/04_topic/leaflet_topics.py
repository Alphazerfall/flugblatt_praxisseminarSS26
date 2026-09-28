#!/usr/bin/env python3
"""Topic Modelling auf Flugblattebene mit Embeddings über OpenRouter.

Ergänzung zu topic_modelling.py (Branch dev-ner), das auf Blockebene mit
einem lokalen MiniLM arbeitet. Hier ist ein Dokument ein Flugblatt, also ein
Segment aus `<stem>.segments.json`, und die Embeddings kommen von einem
aktuellen Modell mit langem Kontext (Standard: baai/bge-m3).

Ablauf:
  1. Text je Segment aus der Datalab-OCR-JSON (ohne Bilder, Kopf-/Fußzeilen
     und Archivvermerke wie "Ablage 12043").
  2. Embeddings über OpenRouter, zwischengespeichert unter
     data/cache/embeddings/<modell>.npz, Schlüssel ist der Hash des Textes.
     Nur neue oder geänderte Texte werden angefragt; Parameter von UMAP,
     HDBSCAN und Vektorisierer lassen sich danach ohne Kosten variieren.
  3. BERTopic mit festem Seed, dazu Themenverteilung je Jahr
     (topics_over_time). Die Themenwörter bestehen nur aus Substantiven
     (spaCy, optional); Eigennamen und Organisationskürzel aus der
     Normdatei sind ausgeschlossen, weil sie als typischste Wörter eines
     Clusters sonst die Sachbegriffe verdrängen. Die Cluster selbst bleiben
     davon unberührt.

Schreibt data/topics/topics.<modell>[.n<themen>].json und .hierarchy.html
(Dendrogramm der Themen, Grundlage für die Entscheidung über --num-topics).

Beispiele:
    python pipelines/04_topic/leaflet_topics.py
    python pipelines/04_topic/leaflet_topics.py --model qwen/qwen3-embedding-8b --min-topic-size 8

Braucht OPENROUTER_API_KEY in der Umgebung oder in .env.
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "embeddings"
OUT_DIR = REPO_ROOT / "data" / "topics"
ORGS_PATH = REPO_ROOT / "docs" / "korpus" / "findmittel" / "organizations.draft.json"
BASE_URL = "https://openrouter.ai/api/v1"

SKIP_BLOCK_TYPES = {"Picture", "Figure", "PictureGroup", "FigureGroup",
                    "PageHeader", "PageFooter"}
MAX_CHARS = 16000          # bleibt sicher unter 8k Tokens (bge-m3)

# Bearbeitungsvermerke des Archivs, kein Inhalt der Flugblätter:
# "2, Ablage 12043 27. NOV. 1972" (Ablagenummer mit Eingangsstempel), "z. K."
ARCHIVE_STAMPS = re.compile(
    r"\bAblage\s*[\d\s()]{2,8}(?:\d{1,2}\.?\s*[A-ZÄ]{3,5}\.?\s*19\d\d)?"
    r"|\bz\.\s?K\.|\bErbitte Rückgabe")

EXTRA_STOPWORDS = [
    "daß", "dass", "wurde", "worden", "sowie", "bzw", "xxx",
    # Allerweltswörter im Hochschulkontext
    "student", "studenten", "studentin", "kommilitone", "universität", "uni",
    "regensburg", "studentenschaft",
    # Füllsubstantive
    "zeit", "jahr", "herr", "frage", "seite", "fall", "punkt", "teil", "art",
    "weise", "grund", "beispiel",
    # Termine
    "uhr", "januar", "februar", "märz", "april", "mai", "juni", "juli",
    "august", "september", "oktober", "november", "dezember", "montag",
    "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag",
    # Archiv und Impressum
    "ablage", "anlage", "eigendruck", "selbstverlag", "druck", "presserecht",
    # Kürzel aus Wahllisten
    "sem", "gesch", "soz", "mitgl", "theol", "phil", "päd", "stud", "abs",
]


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def strip_html(fragment):
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))
    return re.sub(r"\s+", " ", text).strip()


def load_leaflets(skip=SKIP_BLOCK_TYPES):
    leaflets = []
    for seg_path in sorted(RAW_DIR.glob("*/*.segments.json")):
        volume = seg_path.parent.name
        stem = seg_path.name.removesuffix(".segments.json")
        ocr_path = seg_path.parent / stem / f"{stem}.json"
        if not ocr_path.is_file():
            log(f"  ! keine OCR für {volume}, übersprungen")
            continue
        year = int(re.search(r"\((\d{4})\)", volume).group(1))
        pages = json.loads(ocr_path.read_text(encoding="utf-8"))["children"]
        segments = json.loads(seg_path.read_text(encoding="utf-8"))["segments"]
        for seg in segments:
            if seg.get("no_content"):
                continue
            parts = [strip_html(b.get("html"))
                     for page in pages[seg["start_page"] - 1:seg["end_page"]]
                     for b in page.get("children", [])
                     if b.get("block_type") not in skip]
            text = ARCHIVE_STAMPS.sub(" ", " ".join(p for p in parts if p))
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 50:
                continue
            leaflets.append({"volume": volume, "stem": stem, "year": year,
                             "segment_id": seg["id"],
                             "start_page": seg["start_page"],
                             "end_page": seg["end_page"],
                             "text": text})
    return leaflets


def text_key(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_cache(path):
    if not path.is_file():
        return {}
    data = np.load(path)
    return dict(zip(data["keys"].tolist(), data["vectors"]))


def save_cache(path, cache):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(cache)
    np.savez(path, keys=np.array(keys), vectors=np.stack([cache[k] for k in keys]))


def embed(texts, model, batch_size):
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("OPENROUTER_API_KEY fehlt (Umgebung oder .env).")
    client = OpenAI(base_url=BASE_URL, api_key=api_key)

    cache_path = CACHE_DIR / f"{model.replace('/', '__')}.npz"
    cache = load_cache(cache_path)
    keys = [text_key(t) for t in texts]
    unique = dict(zip(keys, texts))
    missing = [(k, t) for k, t in unique.items() if k not in cache]
    log(f"Embeddings: {len(unique)} verschiedene Texte, {len(unique) - len(missing)} "
        f"aus dem Cache, {len(missing)} neu ({model})")

    for i in range(0, len(missing), batch_size):
        batch = missing[i:i + batch_size]
        for attempt in range(5):
            try:
                resp = client.embeddings.create(
                    model=model, input=[t[:MAX_CHARS] for _, t in batch])
                break
            except Exception as exc:
                wait = 2 ** attempt * 5
                log(f"  Fehler ({exc}), neuer Versuch in {wait}s")
                time.sleep(wait)
        else:
            save_cache(cache_path, cache)
            sys.exit("Abbruch nach 5 Fehlversuchen; bisherige Embeddings sind gespeichert.")
        for (k, _), item in zip(batch, resp.data):
            cache[k] = np.asarray(item.embedding, dtype=np.float32)
        save_cache(cache_path, cache)
        log(f"  {min(i + batch_size, len(missing))}/{len(missing)}")

    return np.stack([cache[k] for k in keys])


def lemmatize(texts, model_name):
    try:
        import spacy
        nlp = spacy.load(model_name, disable=["ner", "parser"])
    except (ImportError, OSError):
        log("spaCy-Modell nicht verfügbar, Themenwörter bleiben unlemmatisiert.")
        return texts
    nlp.max_length = MAX_CHARS * 2
    log(f"Lemmatisiere {len(texts)} Flugblätter (nur Substantive) ...")
    return [" ".join(t.lemma_.lower() for t in doc
                     if t.pos_ == "NOUN" and t.is_alpha and len(t) >= 3)
            for doc in nlp.pipe((t[:MAX_CHARS] for t in texts), batch_size=16)]


# Hochschulgesetz, Mark: Sache, nicht Absender; Wörter aus Namen in Versalien
NOT_ORG_ACRONYMS = {"bhg", "dm", "liste", "mitte"}


def org_stopwords():
    """Organisationskürzel aus der Normdatei (bis 5 Buchstaben, mind. zwei
    Großbuchstaben, z. B. rcds, shb, msb). Ausgeschriebene Namen bleiben
    drin, sonst fielen Sachbegriffe wie "Studentenwerk" oder "Rektor" mit
    heraus; Eigennamen wie "Spartakus" filtert schon die Wortart."""
    if not ORGS_PATH.is_file():
        return set()
    words = set()
    for org in json.loads(ORGS_PATH.read_text(encoding="utf-8")):
        for name in [org["name"], *org.get("variants", [])]:
            words |= {t.lower() for t in re.findall(r"[^\W\d_]+", name)
                      if len(t) <= 5 and sum(c.isupper() for c in t) >= 2}
    return words - NOT_ORG_ACRONYMS


def build_topic_model(args):
    from bertopic import BERTopic
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    try:
        import stop_words
        german = stop_words.get_stop_words("german")
    except ImportError:
        german = []
    stopwords = {w.lower() for w in german} | set(EXTRA_STOPWORDS) | org_stopwords()
    vectorizer = CountVectorizer(
        stop_words=sorted(stopwords),
        token_pattern=r"(?u)\b[^\W\d_]{3,}\b",
        ngram_range=(1, 2), min_df=3, max_df=0.9)
    umap_model = UMAP(n_neighbors=15, n_components=5, min_dist=0.0,
                      metric="cosine", random_state=args.seed)
    return BERTopic(umap_model=umap_model, vectorizer_model=vectorizer,
                    min_topic_size=args.min_topic_size,
                    nr_topics=args.num_topics or None,
                    language="multilingual", verbose=True)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="baai/bge-m3", help="OpenRouter-Embedding-Modell")
    p.add_argument("--min-topic-size", type=int, default=10)
    p.add_argument("--num-topics", type=int, default=None,
                   help="Themen nachträglich auf N zusammenfassen")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lemma-model", default="de_core_news_lg")
    p.add_argument("--embed-only", action="store_true",
                   help="nur Embeddings berechnen und cachen")
    return p.parse_args()


def main():
    args = parse_args()
    leaflets = load_leaflets()
    texts = [lf["text"] for lf in leaflets]
    n_long = sum(len(t) > MAX_CHARS for t in texts)
    log(f"{len(leaflets)} Flugblätter aus {len({lf['stem'] for lf in leaflets})} Bänden"
        f" ({n_long} auf {MAX_CHARS} Zeichen gekürzt)")

    embeddings = embed(texts, args.model, args.batch_size)
    if args.embed_only:
        return

    topic_model = build_topic_model(args)
    docs = lemmatize(texts, args.lemma_model)
    topics, _ = topic_model.fit_transform(docs, embeddings=embeddings)

    info = topic_model.get_topic_info()
    topics_out = [{"id": int(row.Topic), "count": int(row.Count),
                   "top_words": [w for w, _ in topic_model.get_topic(row.Topic)[:10]]}
                  for row in info.itertuples() if row.Topic != -1]

    years = [lf["year"] for lf in leaflets]
    over_time = topic_model.topics_over_time(docs, years)
    by_year = [{"topic": int(r.Topic), "year": int(round(r.Timestamp)),
                "count": int(r.Frequency)}
               for r in over_time.itertuples() if r.Topic != -1]

    leaflets_out = [{k: lf[k] for k in ("volume", "stem", "year", "segment_id",
                                        "start_page", "end_page")}
                    | {"topic": int(t), "incipit": lf["text"][:120]}
                    for lf, t in zip(leaflets, topics)]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = args.model.replace('/', '__') + (f".n{args.num_topics}" if args.num_topics else "")
    out_path = OUT_DIR / f"topics.{run}.json"
    out_path.write_text(json.dumps({
        "model": args.model, "min_topic_size": args.min_topic_size,
        "num_topics": args.num_topics, "seed": args.seed,
        "topics": topics_out, "topics_by_year": by_year, "leaflets": leaflets_out,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    hierarchy = topic_model.hierarchical_topics(docs)
    fig = topic_model.visualize_hierarchy(hierarchical_topics=hierarchy,
                                          width=1100, height=40 + 22 * len(topics_out))
    fig.write_html(out_path.with_suffix(".hierarchy.html"), include_plotlyjs="cdn")

    n_out = sum(t == -1 for t in topics)
    log(f"-> {out_path.relative_to(REPO_ROOT)}: {len(topics_out)} Themen, "
        f"{n_out}/{len(topics)} Flugblätter ohne Thema (Ausreißer)")
    for t in topics_out[:15]:
        log(f"  {t['id']:>3} ({t['count']:>3})  {', '.join(t['top_words'][:6])}")


if __name__ == "__main__":
    main()
