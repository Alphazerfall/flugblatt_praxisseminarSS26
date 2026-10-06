#!/usr/bin/env python3
"""Erzeugt aus einer Ausgabe von leaflet_topics.py eine eigenständige HTML-Seite.

Heatmap Thema x Jahr (Anteil an allen Flugblättern des Jahrgangs, damit die
kleinen frühen Jahrgänge vergleichbar bleiben); ein Klick auf ein Thema
klappt die zugehörigen Flugblätter mit Band, Seiten und Textanfang auf.

    python pipelines/04_topic/topics_report.py data/topics/topics.baai__bge-m3.json

Schreibt die Seite neben die JSON (gleicher Name, .html). Gibt es zum Lauf
eine Codierungstabelle (topic_labels.<modell>.n<themen>.csv neben diesem
Skript), zeigt die Seite deren Titel und Kategorien statt der Schlagworte.
"""

import csv
import html
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

CSS = """
body { margin: 0; padding: 24px; font: 14px/1.45 system-ui, sans-serif; color: #1f2937; background: #fff; }
h1 { font-size: 1.4rem; margin: 0 0 4px; }
.sub { color: #6b7280; margin: 0 0 20px; }
table { border-collapse: collapse; }
th { font-weight: 600; color: #6b7280; padding: 4px 6px; text-align: right; }
th.topic { text-align: left; }
td { padding: 0; }
td.cell { width: 64px; height: 30px; text-align: center; font-size: 12px; border: 2px solid #fff; border-radius: 4px; }
td.label { padding: 0 12px 0 0; max-width: 520px; }
details summary { cursor: pointer; list-style: none; padding: 5px 0; }
details summary::-webkit-details-marker { display: none; }
details summary:hover { color: #2563eb; }
.count { color: #9ca3af; font-size: 12px; margin-left: 6px; }
ul { margin: 4px 0 10px; padding-left: 18px; color: #4b5563; font-size: 13px; }
li { margin: 3px 0; }
.meta { color: #9ca3af; }
.words { display: block; color: #9ca3af; font-size: 12px; }
.badge { margin-left: 6px; padding: 1px 6px; border-radius: 9px; font-size: 11px; background: #f3f4f6; color: #4b5563; }
.badge.Sachthema { background: #dcfce7; color: #166534; }
.badge.gemischt { background: #fef9c3; color: #854d0e; }
.uncertain { color: #854d0e; font-size: 12px; }
"""


def load_labels(data):
    if not data.get("num_topics"):
        return {}
    path = Path(__file__).parent / (
        f"topic_labels.{data['model'].replace('/', '__')}.n{data['num_topics']}.csv")
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        return {int(row["thema"]): row for row in csv.DictReader(f, delimiter=";")}


def cell_style(share, max_share):
    alpha = share / max_share if max_share else 0
    color = "#fff" if alpha > 0.55 else "#1f2937"
    return f"background: rgba(37, 99, 235, {alpha:.2f}); color: {color}"


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/topics/topics.baai__bge-m3.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    leaflets = data["leaflets"]
    years = sorted({lf["year"] for lf in leaflets})
    per_year = Counter(lf["year"] for lf in leaflets)
    by_topic = defaultdict(list)
    for lf in leaflets:
        by_topic[lf["topic"]].append(lf)

    counts = defaultdict(Counter)
    for lf in leaflets:
        counts[lf["topic"]][lf["year"]] += 1
    max_share = max(counts[t["id"]][y] / per_year[y]
                    for t in data["topics"] for y in years)

    labels = load_labels(data)
    rows = []
    for t in data["topics"]:
        words = html.escape(', '.join(t['top_words'][:5]))
        generated_label = html.escape(t.get(
            "llm_label", t.get("auto_label", ', '.join(t['top_words'][:3]))))
        lab = labels.get(t["id"])
        if lab:
            kat = html.escape(lab["kategorie"])
            badge = f"<span class='badge {kat.split()[0]}'>{kat}</span>" if kat else ""
            heading = (f"<strong>{html.escape(lab['titel'])}</strong>{badge}"
                       f"<span class='count'>{t['count']}</span>"
                       f"<span class='words'>{words}</span>")
        else:
            heading = (f"<strong>{generated_label}</strong>"
                       f"<span class='count'>{t['count']}</span>"
                       f"<span class='words'>{words}</span>")
        items = "".join(
            f"<li>{html.escape(lf['incipit'][:110])}… "
            f"<span class='meta'>{html.escape(lf['volume'])}, S. {lf['start_page']}"
            f"{'–' + str(lf['end_page']) if lf['end_page'] != lf['start_page'] else ''}</span>"
            f"<span class='uncertain'>{' nachträglich zugeordnet' if lf.get('topic_assignment') == 'reassigned_uncertain' else ''}</span></li>"
            for lf in sorted(by_topic[t["id"]], key=lambda x: (x["stem"], x["start_page"])))
        label = f"<details><summary>{heading}</summary><ul>{items}</ul></details>"
        cells = "".join(
            f"<td class='cell' style='{cell_style(counts[t['id']][y] / per_year[y], max_share)}' "
            f"title='{counts[t['id']][y]} von {per_year[y]} Flugblättern {y}'>"
            f"{round(100 * counts[t['id']][y] / per_year[y]) or ''}</td>"
            for y in years)
        rows.append(f"<tr><td class='label'>{label}</td>{cells}</tr>")

    n_out = len(by_topic.get(-1, []))
    n_reassigned = sum(lf.get("topic_assignment") == "reassigned_uncertain"
                       for lf in leaflets)
    hierarchy = src.with_suffix(".hierarchy.html")
    link = (f" · <a href='{hierarchy.name}'>Dendrogramm</a>"
            if hierarchy.is_file() else "")
    if labels:
        drafts = sum(r["status"] == "KI-Entwurf" for r in labels.values())
        link += f" · Titel: {len(labels) - drafts} geprüft, {drafts} KI-Entwurf"
    head = "".join(f"<th>{y}<br><span class='count'>n={per_year[y]}</span></th>" for y in years)
    page = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Themen im Zeitverlauf</title>
<style>{CSS}</style></head><body>
<h1>Themen im Zeitverlauf</h1>
<p class="sub">{len(leaflets)} Flugblätter, {len(data['topics'])} Themen, {n_out} ohne Thema,
{n_reassigned} nachträglich zugeordnet ·
Modell {html.escape(data['model'])} · Zahlen = Anteil am Jahrgang in % · Thema anklicken für die Flugblätter{link}</p>
<table><tr><th class="topic">Thema</th>{head}</tr>{''.join(rows)}</table>
</body></html>"""

    out = src.with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
