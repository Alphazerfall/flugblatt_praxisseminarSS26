#!/usr/bin/env python3
"""Organisationen je Jahr und je Thema, als eigenständige HTML-Seite.

Herausgeber aus den LLM-Metadaten gibt es bisher nur für wenige Bände. Diese
Auswertung sucht die Organisationen der Normdatei deshalb direkt im Text:

  - Kürzel (RCDS, SHB ...) mit Groß-/Kleinschreibung, ausgeschriebene Namen
    ohne. Kürzel, die auch gewöhnliche Wörter in Versalien sein können
    (ALS, DM, alle zweibuchstabigen), zählen nur über den ausgeschriebenen
    Namen.
  - "Absender-Näherung": Nennung in den ersten 300 oder letzten 400 Zeichen,
    wo Kopfleiste und Unterschrift stehen. "Irgendwo genannt" zählt auch
    Erwähnungen im Fließtext, etwa Angriffe auf andere Gruppen.

Beides ist eine Heuristik, keine Herausgeberangabe.

    python pipelines/04_topic/orgs_report.py data/topics/topics.baai__bge-m3.json

Schreibt <json>.orgs.html daneben.
"""

import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import leaflet_topics as lt  # noqa: E402

HEAD, TAIL = 300, 400
AMBIGUOUS = {"ALS", "DM", "LUST", "DAB"}
MIN_LEAFLETS = 8


def org_patterns():
    patterns = {}
    for org in json.loads(lt.ORGS_PATH.read_text(encoding="utf-8")):
        name, full = org["name"], org.get("full_name", "")
        regexes = []
        if (re.fullmatch(r"[A-ZÄÖÜ][A-Za-zÄÖÜ]{2,6}", name)
                and sum(c.isupper() for c in name) >= 2 and name not in AMBIGUOUS):
            flags = re.I if not name.isupper() else 0   # AStA auch als ASTA
            regexes.append(re.compile(rf"\b{re.escape(name)}\b", flags))
        for long_name in [full] + [name] * (" " in name):
            if len(long_name.split()) >= 2:
                words = r"\s+".join(re.escape(w) for w in long_name.split())
                regexes.append(re.compile(words, re.I))
        if regexes:
            patterns[org["org_id"]] = (name, regexes)
    return patterns


def find_orgs(text, patterns):
    edges = text[:HEAD] + " \n " + text[-TAIL:]
    anywhere, sender = set(), set()
    for org_id, (_, regexes) in patterns.items():
        if any(r.search(text) for r in regexes):
            anywhere.add(org_id)
            if any(r.search(edges) for r in regexes):
                sender.add(org_id)
    return anywhere, sender


def heat_table(rows, cols, counts, totals, col_label, names):
    max_share = max((counts[r][c] / totals[c] for r in rows for c in cols
                     if totals[c]), default=1) or 1
    head = "".join(f"<th>{html.escape(col_label(c))}</th>" for c in cols)
    body = []
    for r in rows:
        cells = []
        for c in cols:
            share = counts[r][c] / totals[c] if totals[c] else 0
            alpha = share / max_share
            color = "#fff" if alpha > 0.55 else "#1f2937"
            cells.append(f"<td class='cell' style='background: rgba(37,99,235,{alpha:.2f});"
                         f" color: {color}' title='{counts[r][c]} von {totals[c]}'>"
                         f"{round(100 * share) or ''}</td>")
        total = sum(counts[r].values())
        body.append(f"<tr><td class='label'>{html.escape(names[r])}"
                    f"<span class='count'>{total}</span></td>{''.join(cells)}</tr>")
    return f"<table><tr><th></th>{head}</tr>{''.join(body)}</table>"


CSS = """
body { margin: 0; padding: 24px; font: 14px/1.45 system-ui, sans-serif; color: #1f2937; background: #fff; }
h1 { font-size: 1.4rem; margin: 0 0 4px; } h2 { font-size: 1.1rem; margin: 32px 0 4px; }
.sub { color: #6b7280; margin: 0 0 12px; max-width: 900px; }
table { border-collapse: collapse; }
th { font-weight: 600; color: #6b7280; padding: 4px 6px; font-size: 12px; max-width: 90px; }
td.cell { width: 52px; height: 26px; text-align: center; font-size: 12px; border: 2px solid #fff; border-radius: 4px; }
td.label { padding-right: 12px; white-space: nowrap; }
.count { color: #9ca3af; font-size: 12px; margin-left: 6px; }
"""


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/topics/topics.baai__bge-m3.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    topic_of = {(lf["stem"], lf["segment_id"]): lf["topic"] for lf in data["leaflets"]}
    labels = {}
    label_path = Path(__file__).parent / (
        f"topic_labels.{data['model'].replace('/', '__')}.n{data.get('num_topics')}.csv")
    if label_path.is_file():
        for line in label_path.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split(";")
            labels[int(parts[0])] = parts[1]

    patterns = org_patterns()
    names = {org_id: name for org_id, (name, _) in patterns.items()}
    # Kopf- und Fußzeilen bleiben hier drin: dort stehen die Absenderleisten
    leaflets = lt.load_leaflets(skip={"Picture", "Figure", "PictureGroup", "FigureGroup"})
    years = sorted({lf["year"] for lf in leaflets})
    per_year = Counter(lf["year"] for lf in leaflets)
    topics = [t["id"] for t in data["topics"]]
    per_topic = Counter(topic_of.get((lf["stem"], lf["segment_id"])) for lf in leaflets)

    by_year = {"sender": defaultdict(Counter), "anywhere": defaultdict(Counter)}
    by_topic = defaultdict(Counter)
    for lf in leaflets:
        anywhere, sender = find_orgs(lf["text"], patterns)
        topic = topic_of.get((lf["stem"], lf["segment_id"]))
        for org_id in anywhere:
            by_year["anywhere"][org_id][lf["year"]] += 1
        for org_id in sender:
            by_year["sender"][org_id][lf["year"]] += 1
            by_topic[org_id][topic] += 1

    def top_orgs(counts):
        return sorted((o for o in counts if sum(counts[o].values()) >= MIN_LEAFLETS),
                      key=lambda o: -sum(counts[o].values()))

    sender_orgs = top_orgs(by_year["sender"])
    sections = [
        ("Absender-Näherung je Jahr",
         "Anteil der Flugblätter eines Jahrgangs, die die Organisation in Kopf "
         "oder Schluss nennen.",
         heat_table(sender_orgs, years, by_year["sender"], per_year,
                    lambda y: f"{y} (n={per_year[y]})", names)),
        ("Irgendwo genannt je Jahr",
         "Auch Erwähnungen im Fließtext, etwa Kritik an anderen Gruppen.",
         heat_table(top_orgs(by_year["anywhere"]), years, by_year["anywhere"],
                    per_year, lambda y: f"{y} (n={per_year[y]})", names)),
        ("Absender-Näherung je Thema",
         "Anteil der Flugblätter eines Themas, die die Organisation in Kopf "
         "oder Schluss nennen.",
         heat_table(sender_orgs, topics, by_topic, per_topic,
                    lambda t: labels.get(t, f"Thema {t}"), names)),
    ]
    page = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Organisationen</title>
<style>{CSS}</style></head><body>
<h1>Organisationen nach Jahr und Thema</h1>
<p class="sub">{len(leaflets)} Flugblätter, Organisationen aus der Normdatei per
Textsuche (Heuristik, keine Herausgeberangabe). Gezeigt werden Organisationen mit
mindestens {MIN_LEAFLETS} Flugblättern. Zahlen = Anteil in %, Maus über eine Zelle
zeigt die absoluten Zahlen.</p>
{''.join(f"<h2>{h}</h2><p class='sub'>{s}</p>{t}" for h, s, t in sections)}
</body></html>"""
    out = src.with_suffix(".orgs.html")
    out.write_text(page, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
