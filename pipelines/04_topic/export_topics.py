#!/usr/bin/env python3
"""Wandelt ein Ergebnis von leaflet_topics.py in eine topics.json für andere Anwendungen um.

    python pipelines/04_topic/export_topics.py [data/topics/topics.baai__bge-m3.n50.reduced.json]

Ohne Argument gilt die jüngste *.reduced.json in data/topics (Lauf mit
--reduce-outliers). Schreibt standardmäßig data/topics/topics.json. Der Titel eines Themas ist das
llm_label des Laufs (--label-model), sonst das auto_label. Beides stammt aus
derselben Ergebnisdatei, passt also immer zu den Themen-IDs dieses Laufs.

Flugblätter werden über Band und Seitenspanne identifiziert, nicht über die
segment_id: Verschiebt sich eine Segmentgrenze, fällt die Zuordnung weg, statt
beim falschen Blatt zu landen.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "data" / "topics" / "topics.json"
REDUCED_PATTERN = "topics.*.reduced.json"
OUTLIER_TOPIC = -1
UNCERTAIN_ASSIGNMENT = "reassigned_uncertain"


class ExportError(Exception):
    """Der Export ist nicht möglich oder würde unvollständige Daten liefern."""


def topic_title(topic: dict[str, Any]) -> tuple[str, str]:
    """Gibt Titel und Herkunft zurück; das LLM-Label hat Vorrang."""
    for source in ("llm_label", "auto_label"):
        if topic.get(source):
            return topic[source], source
    raise ExportError(
        f"Thema {topic['id']} hat kein llm_label oder auto_label; "
        "Lauf mit der aktuellen leaflet_topics.py wiederholen.")


def build_topics(run_topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Verbindet Themenwörter des Laufs mit ihrem Titel."""
    topics: list[dict[str, Any]] = []
    for topic in sorted(run_topics, key=lambda item: item["id"]):
        title, title_source = topic_title(topic)
        topics.append({"id": topic["id"], "title": title,
                       "title_source": title_source, "words": topic["top_words"]})
    return topics


def build_leaflets(run_leaflets: list[dict[str, Any]],
                   known_topic_ids: set[int]) -> list[dict[str, Any]]:
    """Identifiziert Flugblätter über Band und Seitenspanne."""
    leaflets: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for leaflet in run_leaflets:
        key = (leaflet["stem"], leaflet["start_page"], leaflet["end_page"])
        if key in seen:
            raise ExportError(f"Band und Seitenspanne sind nicht eindeutig: {key}")
        seen.add(key)
        topic_id = leaflet["topic"]
        if topic_id != OUTLIER_TOPIC and topic_id not in known_topic_ids:
            raise ExportError(f"Flugblatt {key} verweist auf unbekanntes Thema {topic_id}")
        leaflets.append({
            "volume": leaflet["stem"],
            "start_page": leaflet["start_page"],
            "end_page": leaflet["end_page"],
            "topic": None if topic_id == OUTLIER_TOPIC else topic_id,
            "uncertain": leaflet.get("topic_assignment") == UNCERTAIN_ASSIGNMENT,
        })
    return sorted(leaflets, key=lambda item: (item["volume"], item["start_page"]))


def describe_run(run: dict[str, Any], source: Path) -> str:
    """Kurzbeschreibung des Laufs; das Datum ist der Änderungszeitpunkt der Datei."""
    date = datetime.fromtimestamp(source.stat().st_mtime).date().isoformat()
    return f"{run['model']}, {len(run['topics'])} Themen, seed {run['seed']}, {date}"


def build_export(run: dict[str, Any], source: Path) -> dict[str, Any]:
    """Erzeugt den vollständigen Export für einen Lauf."""
    run_topic_ids = {topic["id"] for topic in run["topics"]}
    return {"run": describe_run(run, source),
            "topics": build_topics(run["topics"]),
            "leaflets": build_leaflets(run["leaflets"], run_topic_ids)}


def load_run(source: Path) -> dict[str, Any]:
    """Liest ein Ergebnis von leaflet_topics.py und prüft die Pflichtfelder."""
    try:
        run = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"{source} nicht lesbar: {exc}") from exc
    missing_keys = {"model", "seed", "topics", "leaflets"} - run.keys()
    if missing_keys:
        raise ExportError(f"{source.name}: Felder fehlen: {', '.join(sorted(missing_keys))}")
    return run


def latest_reduced_run(directory: Path) -> Path:
    """Findet die jüngste Ergebnisdatei eines Laufs mit --reduce-outliers."""
    candidates = sorted(directory.glob(REDUCED_PATTERN), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise ExportError(
            f"Kein Lauf mit --reduce-outliers in {directory} ({REDUCED_PATTERN}).")
    return candidates[-1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, nargs="?",
                        help="Ergebnis-JSON von leaflet_topics.py (Standard: jüngster *.reduced.json-Lauf)")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        source = args.source or latest_reduced_run(DEFAULT_OUTPUT.parent)
        export = build_export(load_run(source), source)
    except ExportError as exc:
        sys.exit(f"Export abgebrochen: {exc}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(export, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"{source.name} -> {args.output}: {len(export['topics'])} Themen, "
          f"{len(export['leaflets'])} Flugblätter")


if __name__ == "__main__":
    main()
