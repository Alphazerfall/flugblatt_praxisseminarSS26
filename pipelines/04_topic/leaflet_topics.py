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
import csv
import hashlib
import html
import json
import os
import re
import sys
import time
import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "embeddings"
LABEL_CACHE_DIR = REPO_ROOT / "data" / "cache" / "topic_labels"
OUT_DIR = REPO_ROOT / "data" / "topics"
ORGS_PATH = REPO_ROOT / "docs" / "korpus" / "findmittel" / "organizations.draft.json"
DUPLICATE_PAGES_PATH = REPO_ROOT / "docs" / "korpus" / "seiten_duplikate.tsv"
BASE_URL = "https://openrouter.ai/api/v1"

SKIP_BLOCK_TYPES = {"Picture", "Figure", "PictureGroup", "FigureGroup",
                    "PageHeader", "PageFooter"}
MAX_CHARS = 16000          # bleibt sicher unter 8k Tokens (bge-m3)
LABEL_PROMPT_VERSION = 3
MAX_LABEL_LENGTH = 120
MAX_WORD_AMT = 5
MAX_LABEL_EXCERPT_CHARS = 700

# Bearbeitungsvermerke des Archivs, kein Inhalt der Flugblätter:
# "2, Ablage 12043 27. NOV. 1972" (Ablagenummer mit Eingangsstempel), "z. K."
ARCHIVE_STAMPS = re.compile(
    r"\bAblage\s*[\d\s()]{2,8}(?:\d{1,2}\.?\s*[A-ZÄ]{3,5}\.?\s*19\d\d)?"
    r"|\bz\.\s?K\.|\bErbitte Rückgabe")

EXTRA_STOPWORDS = [
    "daß", "dass", "wurde", "worden", "sowie", "bzw", "xxx",
    # Allerweltswörter im Hochschulkontext
    "student", "studenten", "studentin", "kommilitone", "universität", "uni",
    "regensburg", "studentenschaft", "herr", "hochschule", "professor", "interesse",
    "interessenvertretung",
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


def load_duplicate_page_map(path=DUPLICATE_PAGES_PATH):
    """Map each duplicate page to the first occurrence in its page group."""
    if not path.is_file():
        log(f"  ! Duplikat-Tabelle fehlt: {path}")
        return {}
    duplicate_pages = {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            pages = [int(page) for page in row["alle_seiten"].split(",")]
            canonical_page = min(pages)
            page_map = duplicate_pages.setdefault(row["stem"], {})
            page_map.update({page: canonical_page for page in pages})
    return duplicate_pages


def is_complete_duplicate_segment(segment, duplicate_pages):
    """Return whether every page is a non-canonical documented duplicate."""
    page_map = duplicate_pages.get(segment["stem"], {})
    pages = range(segment["start_page"], segment["end_page"] + 1)
    return all(page_map.get(page) not in (None, page) for page in pages)


def load_leaflets(skip=SKIP_BLOCK_TYPES):
    leaflets = []
    duplicate_pages = load_duplicate_page_map()
    skipped_duplicates = 0
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
            if is_complete_duplicate_segment({"stem": stem, **seg}, duplicate_pages):
                skipped_duplicates += 1
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
    if skipped_duplicates:
        log(f"  {skipped_duplicates} vollstaendig duplizierte Flugblaetter uebersprungen")
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


def openrouter_client() -> Any:
    """Create an authenticated OpenRouter client from the local environment."""
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        sys.exit("OPENROUTER_API_KEY fehlt (Umgebung oder .env).")
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def embed(texts, model, batch_size):
    client = openrouter_client()

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


def topic_stopwords() -> set[str]:
    """Return the complete normalized stopword set for topic representations."""
    try:
        import stop_words
        german = stop_words.get_stop_words("german")
    except ImportError:
        german = []
    return {word.lower() for word in german} | set(EXTRA_STOPWORDS) | org_stopwords()


def is_stopword_topic_term(term: str, stopwords: set[str]) -> bool:
    """Return whether a topic term contains an excluded word."""
    tokens = re.findall(r"(?u)[^\W\d_]{3,}", term.lower())
    return not tokens or any(token in stopwords for token in tokens)


def export_topic_words(topic_terms: Iterable[tuple[str, float]], stopwords: set[str],
                       limit: int = 10) -> list[str]:
    """Keep only displayable topic terms that contain no configured stopwords."""
    return [term for term, _ in topic_terms
            if not is_stopword_topic_term(term, stopwords)][:limit]


def automatic_topic_label(topic_words: list[str], limit: int = 3) -> str:
    """Create a compact, deterministic descriptor from representative unigrams."""
    unigrams = [word for word in topic_words if " " not in word]
    terms = (unigrams or topic_words)[:limit]
    return " / ".join(term.capitalize() for term in terms) or "Unbenanntes Thema"


def label_cache_path(model: str) -> Path:
    """Return the cache location for labels created by an OpenRouter model."""
    return LABEL_CACHE_DIR / f"{model.replace('/', '__')}.json"


def load_label_cache(path: Path) -> dict[str, str]:
    """Load validated labels from a previous run."""
    if not path.is_file():
        return {}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ungültiger Label-Cache: {path}") from exc
    if not isinstance(cache, dict) or not all(
            isinstance(key, str) and isinstance(label, str)
            for key, label in cache.items()):
        raise ValueError(f"Ungültiges Format im Label-Cache: {path}")
    return cache


def save_label_cache(path: Path, cache: dict[str, str]) -> None:
    """Persist labels atomically so interrupted runs retain valid cache data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def topic_label_fingerprint(model: str, topic_words: list[str], excerpts: list[str]) -> str:
    """Fingerprint all label inputs to prevent stale cached labels."""
    payload = json.dumps({"version": LABEL_PROMPT_VERSION, "model": model,
                          "words": topic_words, "excerpts": excerpts},
                         ensure_ascii=False, sort_keys=True)
    return text_key(payload)


def representative_excerpts(texts: list[str], topics: list[int], embeddings: np.ndarray,
                            topic_id: int, limit: int = 3) -> list[str]:
    """Select central documents in a topic by cosine similarity to its centroid."""
    indices = [index for index, topic in enumerate(topics) if topic == topic_id]
    if not indices:
        return []
    vectors = embeddings[indices]
    norms = np.linalg.norm(vectors, axis=1)
    nonzero = norms > 0
    ranked_indices = np.asarray(indices[:limit])
    if np.any(nonzero):
        normalized_vectors = vectors[nonzero] / norms[nonzero, np.newaxis]
        normalized_indices = np.asarray(indices)[nonzero]
        centroid = normalized_vectors.mean(axis=0)
        centroid_norm = np.linalg.norm(centroid)
        if centroid_norm > 0:
            scores = normalized_vectors @ (centroid / centroid_norm)
            ranked_indices = normalized_indices[np.argsort(scores)[::-1][:limit]]
    return [re.sub(r"\s+", " ", texts[index]).strip()[:MAX_LABEL_EXCERPT_CHARS]
            for index in ranked_indices if texts[index].strip()]


def label_prompt(topic_words: list[str], excerpts: list[str]) -> str:
    """Build a constrained prompt for concise, evidence-based topic names."""
    evidence = "\n\n".join(
        f"Auszug {index}: {excerpt}" for index, excerpt in enumerate(excerpts, start=1))
    return (
        "Du benennst Themen-Cluster historischer deutscher Flugblätter. Erstelle "
        "für das Cluster einen kurzen, präzisen und sachlichen deutschen Titel, "
        "der das zentrale Sachthema beschreibt.\n"
        "Regeln:\n"
        "- Formuliere einen verständlichen Titel statt einer Liste von Stichwörtern.\n"
        "- Benenne Anliegen, Konflikt, Forderung oder Gegenstand der Flugblätter; "
        "nicht Absender, Organisation, Textsorte oder Schreibstil.\n"
        "- Nutze Schlüsselwörter und Textauszüge gemeinsam. Die Auszüge sind die "
        "inhaltlichen Belege; Schlüsselwörter sind nur Hinweise.\n"
        "- Erfinde oder ergänze keine Akteure, Orte, Daten, Ereignisse oder "
        "Zusammenhänge, die aus den Belegen nicht hervorgehen.\n"
        "- Vermeide nichtssagende Titel wie „Verschiedenes“ oder „Politik“. "
        "Wenn die Belege mehrere Aspekte zeigen, wähle einen passenden "
        "gemeinsamen Oberbegriff.\n"
        "- Nenne immer ein Thema. Lehne die Aufgabe nicht ab und antworte nicht "
        "mit „unbekannt“, „unklar“ oder „kein Thema“. Wenn die Belege wenig "
        "hergeben, formuliere den engsten durch Schlüsselwörter und Auszüge "
        "gestützten Oberbegriff.\n"
        "- Nutze möglichst neutrale und unwertende Formulierungen.\n"
        "- Ignoriere offensichtliche OCR-Fehler und übernimm sie nicht in den Titel.\n"
        "- Schreibe knapp und ohne Anführungszeichen; verwende höchstens "
        f"{MAX_LABEL_LENGTH} Zeichen und möglichst nur {MAX_WORD_AMT} Wörter.\n"
        'Antworte ausschließlich als JSON-Objekt im Format {"label":"..."}.\n\n'
        f"Schlüsselwörter: {', '.join(topic_words) or '(keine verfügbar)'}\n\n"
        f"{evidence or 'Keine repräsentativen Textauszüge verfügbar.'}")


def parse_llm_label(content: str) -> str:
    """Validate a model response before it can enter analysis output."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM-Antwort ist kein JSON-Objekt") from exc
    label = payload.get("label") if isinstance(payload, dict) else None
    if not isinstance(label, str):
        raise ValueError("LLM-Antwort enthält kein Textfeld 'label'")
    label = re.sub(r"\s+", " ", label).strip()
    if not label or len(label) > MAX_LABEL_LENGTH:
        raise ValueError("LLM-Label ist leer oder zu lang")
    return label


def request_llm_label(client: Any, model: str, topic_words: list[str],
                      excerpts: list[str]) -> str:
    """Request a validated label, retrying once if the model misses the format."""
    from openai import OpenAIError

    prompt = label_prompt(topic_words, excerpts)
    for attempt in range(2):
        messages = [{"role": "user", "content": prompt}]
        if attempt:
            messages.append({
                "role": "user",
                "content": 'Erstelle jetzt einen Titel und gib ausschließlich gültiges '
                           'JSON im Format {"label":"..."} zurück. Nenne immer ein '
                           "Thema; bei Unsicherheit den engsten belegten Oberbegriff.",
            })
        request = {
            "model": model,
            "temperature": 0,
            "messages": messages,
        }
        if not attempt:
            request["response_format"] = {"type": "json_object"}
        try:
            response = client.chat.completions.create(**request)
            if not response.choices:
                raise ValueError("LLM-Antwort enthält keine Auswahl")
            content = response.choices[0].message.content
            if not isinstance(content, str):
                raise ValueError("LLM-Antwort enthält keinen Text")
            return parse_llm_label(content)
        except (OpenAIError, ValueError) as exc:
            if attempt:
                raise
            log(f"  ! LLM-Label: strukturierte Antwort fehlgeschlagen ({exc}); "
                "wiederhole ohne JSON-Modus")
    raise RuntimeError("LLM-Label fehlgeschlagen, obwohl beide Versuche beendet sind")


def add_llm_labels(topics_out: list[dict[str, Any]], texts: list[str], topics: list[int],
                   embeddings: np.ndarray, model: str) -> None:
    """Add cached, validated LLM labels to topic records in place."""
    from openai import OpenAIError

    client = openrouter_client()
    cache_path = label_cache_path(model)
    cache = load_label_cache(cache_path)
    cached_count = 0
    created_count = 0
    failed_count = 0
    failed_topics = []

    for topic in topics_out:
        excerpts = representative_excerpts(texts, topics, embeddings, topic["id"])
        if not excerpts:
            log(f"  ! Thema {topic['id']}: keine repräsentativen Texte; "
                "LLM-Label nur anhand der Schlüsselwörter")
        cache_key = topic_label_fingerprint(model, topic["top_words"], excerpts)
        if cache_key in cache:
            topic["llm_label"] = cache[cache_key]
            cached_count += 1
            continue
        try:
            label = request_llm_label(client, model, topic["top_words"], excerpts)
        except (OpenAIError, ValueError) as exc:
            log(f"  ! Thema {topic['id']}: LLM-Label fehlgeschlagen: {exc}")
            failed_count += 1
            failed_topics.append(topic["id"])
            continue
        cache[cache_key] = label
        save_label_cache(cache_path, cache)
        topic["llm_label"] = label
        created_count += 1

    log(f"LLM-Labels ({model}): {created_count} neu, {cached_count} aus Cache, "
        f"{failed_count} fehlgeschlagen")
    if failed_topics:
        raise RuntimeError(
            f"Keine vollständige Themenbenennung möglich; fehlgeschlagen für "
            f"Themen {', '.join(map(str, failed_topics))}. Erfolgreiche Labels "
            "sind gecacht; starte den Lauf erneut.")


def build_topic_model(args):
    from bertopic import BERTopic
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    stopwords = topic_stopwords()
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


def quality_metrics(embeddings, topics, topics_out, seed):
    """Return reproducible indicators for comparing modelling runs."""
    assigned_indices = [index for index, topic in enumerate(topics) if topic != -1]
    assigned_topics = [topics[index] for index in assigned_indices]
    top_words = [word for topic in topics_out for word in topic["top_words"]]
    silhouette = None
    if len(set(assigned_topics)) >= 2:
        from sklearn.metrics import silhouette_score

        sample_size = min(1000, len(assigned_indices))
        generator = np.random.default_rng(seed)
        sample = generator.choice(assigned_indices, size=sample_size, replace=False)
        try:
            silhouette = float(silhouette_score(
                embeddings[sample], [topics[index] for index in sample], metric="cosine"))
        except ValueError as exc:
            log(f"  ! Silhouette konnte nicht berechnet werden: {exc}")

    total = len(topics)
    return {
        "document_count": total,
        "assigned_document_count": len(assigned_indices),
        "outlier_count": total - len(assigned_indices),
        "outlier_share": (total - len(assigned_indices)) / total if total else 0.0,
        "topic_count": len(topics_out),
        "topic_diversity": len(set(top_words)) / len(top_words) if top_words else None,
        "silhouette_cosine": silhouette,
    }


def hierarchical_topics(topic_model: Any, documents: list[str]):
    """Generate a hierarchy without BERTopic's known pandas slice warning."""
    from pandas.errors import SettingWithCopyWarning

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=SettingWithCopyWarning,
                                module=r"bertopic\._bertopic")
        return topic_model.hierarchical_topics(documents)


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
    p.add_argument("--reduce-outliers", action="store_true",
                   help="Ausreisser nachtraeglich und als unsicher zuordnen")
    p.add_argument("--label-model", metavar="MODEL",
                   help="OpenRouter-Chatmodell für optionale Themenbezeichner")
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
    assignment_sources = ["clustered" if topic != -1 else "outlier" for topic in topics]
    if args.reduce_outliers and -1 in topics:
        reassigned_topics = topic_model.reduce_outliers(
            docs, topics, strategy="distributions", embeddings=embeddings)
        assignment_sources = [
            "reassigned_uncertain" if old == -1 and new != -1 else source
            for old, new, source in zip(topics, reassigned_topics, assignment_sources)
        ]
        topics = [int(topic) for topic in reassigned_topics]
        topic_model.update_topics(docs, topics=topics)

    info = topic_model.get_topic_info()
    stopwords = topic_stopwords()
    topics_out = []
    for row in info.itertuples():
        if row.Topic == -1:
            continue
        top_words = export_topic_words(topic_model.get_topic(row.Topic), stopwords)
        topics_out.append({"id": int(row.Topic), "count": int(row.Count),
                           "auto_label": automatic_topic_label(top_words),
                           "top_words": top_words})

    if args.label_model:
        add_llm_labels(topics_out, texts, topics, embeddings, args.label_model)

    years = [lf["year"] for lf in leaflets]
    over_time = topic_model.topics_over_time(docs, years, topics=topics)
    by_year = [{"topic": int(r.Topic), "year": int(round(r.Timestamp)),
                "count": int(r.Frequency)}
               for r in over_time.itertuples() if r.Topic != -1]
    quality = quality_metrics(embeddings, topics, topics_out, args.seed)
    quality["reassigned_document_count"] = assignment_sources.count("reassigned_uncertain")

    leaflets_out = [{k: lf[k] for k in ("volume", "stem", "year", "segment_id",
                                        "start_page", "end_page")}
                          | {"topic": int(topic), "topic_assignment": source,
                              "incipit": lf["text"][:120]}
                          for lf, topic, source in zip(leaflets, topics, assignment_sources)]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = (args.model.replace('/', '__')
           + (f".n{args.num_topics}" if args.num_topics else "")
           + (".reduced" if args.reduce_outliers else ""))
    out_path = OUT_DIR / f"topics.{run}.json"
    out_path.write_text(json.dumps({
        "model": args.model, "min_topic_size": args.min_topic_size,
        "num_topics": args.num_topics, "seed": args.seed,
        "reduce_outliers": args.reduce_outliers,
        "label_model": args.label_model,
        "quality": quality, "topics": topics_out, "topics_by_year": by_year,
        "leaflets": leaflets_out,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    hierarchy = hierarchical_topics(topic_model, docs)
    fig = topic_model.visualize_hierarchy(hierarchical_topics=hierarchy,
                                          width=1100, height=40 + 22 * len(topics_out))
    fig.write_html(out_path.with_suffix(".hierarchy.html"), include_plotlyjs="cdn")

    topic_model.visualize_topics().write_html(
        out_path.with_suffix(".intertopic.html"), include_plotlyjs="cdn")
    topic_model.visualize_barchart(top_n_topics=15).write_html(
        out_path.with_suffix(".barchart.html"), include_plotlyjs="cdn")

    n_out = sum(t == -1 for t in topics)
    log(f"->  {out_path.relative_to(REPO_ROOT)}: {len(topics_out)} Themen, "
        f"{n_out}/{len(topics)} Flugblätter ohne Thema (Ausreißer)")
    for t in topics_out[:15]:
        log(f"  {t['id']:>3} ({t['count']:>3})  {', '.join(t['top_words'][:6])}")


if __name__ == "__main__":
    main()
