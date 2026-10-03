# Setup: Topic Modelling auf Flugblattebene

Anleitung für `leaflet_topics.py`, `topics_report.py` und `orgs_report.py`.
Hintergrund und Ergebnisse: [docs/korpus/topic-modelling.md](../../docs/korpus/topic-modelling.md).

## Voraussetzungen

- Python 3.10 (damit getestet)
- `data/raw/<Band>/` mit Datalab-OCR (`<stem>/<stem>.json`) und
  Segmentierung (`<stem>.segments.json`)
- ein OpenRouter-Key für die Embeddings (siehe unten)

## 1. Umgebung einrichten

Unter Windows die Umgebung unter einem **kurzen Pfad** anlegen. Sonst
scheitert spaCy an der Pfadlänge (`DLL load failed ... filename or
extension is too long`).

```powershell
py -3.10 -m venv C:\venvs\topics
C:\venvs\topics\Scripts\Activate.ps1
pip install bertopic umap-learn spacy stop-words openai python-dotenv numpy plotly
python -m spacy download de_core_news_lg
```

`bertopic` zieht `sentence-transformers` und PyTorch mit. Der erste
Download ist deshalb groß (etwa 1 GB mit dem spaCy-Modell).

## 2. OpenRouter-Key anlegen

Die Embeddings (`baai/bge-m3`) kommen über [OpenRouter](https://openrouter.ai).

1. Auf [openrouter.ai](https://openrouter.ai) ein Konto anlegen.
2. Unter [Credits](https://openrouter.ai/settings/credits) ein kleines
   Guthaben aufladen. Ein voller Lauf über das Korpus kostet etwa 2 Cent,
   danach kommen die Embeddings aus dem Cache.
3. Unter [Keys](https://openrouter.ai/settings/keys) einen Key erzeugen
   (beginnt mit `sk-or-v1-`). Optional ein Ausgabenlimit setzen.

## 3. Key hinterlegen

Im Repo-Hauptordner eine Datei `.env` anlegen oder ergänzen:

```
OPENROUTER_API_KEY=sk-or-v1-...
```

- `.env` steht in der `.gitignore` und wird nicht committet. **Den Key nie in
  Code, Notebooks oder Chat-Nachrichten einfügen.**
- Denselben Key nutzt auch `pipelines/02_ocr/openrouter_convert.py`.
- Alternativ nur für die aktuelle PowerShell-Sitzung:
  `$env:OPENROUTER_API_KEY = "sk-or-v1-..."`

## 4. Ausführen

Aus dem Repo-Hauptordner, mit aktivierter Umgebung:

```powershell
# Themen berechnen (Embeddings beim ersten Lauf ~1 min, danach aus dem Cache)
python pipelines\04_topic\leaflet_topics.py --num-topics 50

# Ausreisser nachtraeglich zuordnen; diese Zuordnungen bleiben im JSON markiert
python pipelines\04_topic\leaflet_topics.py --num-topics 50 --reduce-outliers

# Optionale LLM-Bezeichner; erzeugt nur fuer neue Themenfingerabdruecke API-Anfragen
python pipelines\04_topic\leaflet_topics.py --num-topics 50 --label-model openai/gpt-4.1-mini

# Heatmap Thema x Jahr, mit Titeln aus der Codierungstabelle
python pipelines\04_topic\topics_report.py data\topics\topics.baai__bge-m3.n50.json

# Organisationen nach Jahr und Thema
python pipelines\04_topic\orgs_report.py data\topics\topics.baai__bge-m3.n50.json

# Export für andere Anwendungen: jüngster --reduce-outliers-Lauf -> data/topics/topics.json
python pipelines\04_topic\export_topics.py
```

Ergebnisse liegen unter `data/topics/` (JSON, Heatmap, Dendrogramm,
Organisationsseite), der Embedding-Cache unter `data/cache/embeddings/`.
LLM-Labels liegen unter `data/cache/topic_labels/`. Diese Verzeichnisse sind
nicht in Git.

Weitere Optionen: `python pipelines\04_topic\leaflet_topics.py --help`,
z. B. `--model qwen/qwen3-embedding-8b` oder `--min-topic-size 8`.

Die Ergebnis-JSON enthaelt unter `quality` Dokumentzahl, Ausreisserquote,
Topic-Diversitaet und eine deterministisch gesampelte Cosine-Silhouette. Diese
Werte vergleichen Laeufe, ersetzen aber nicht die inhaltliche Themenpruefung.
Bei `--reduce-outliers` traegt jedes nachtraeglich zugeordnete Flugblatt den
Status `topic_assignment: "reassigned_uncertain"`.

Beim JSON-Export werden konfigurierte Stoppwörter zusätzlich geprüft: Auch
N-Gramme mit einem Stoppwort-Bestandteil erscheinen nicht in `top_words`.
Bestehende Ergebnisdateien behalten ihre bisherigen Themenwörter; dafür ist
ein erneuter Modelllauf erforderlich, die Embeddings bleiben dabei im Cache.
Jedes Thema erhält außerdem ein deterministisches `auto_label` aus bis zu drei
bereinigten Schlüsselwörtern; es dient nur als kompakter Fallback in der
HTML-Berichtansicht und wird nicht in den Anwendungs-Export übernommen.

`--label-model` aktiviert zusätzliche, kostenpflichtige Chat-Anfragen über
OpenRouter. Das Modell erhält je Thema die bereinigten Schlüsselwörter und
drei zentral gelegene Textauszüge. Seine JSON-Antwort wird validiert und als
`llm_label` gespeichert; der Cache-Schlüssel enthält Modell, Prompt-Version,
Schlüsselwörter und Auszüge. Bei einer fehlgeschlagenen Antwort bleibt der
deterministische Bezeichner als Fallback für den Bericht erhalten.

## Codierungstabellen

`topic_labels.<modell>.n<themen>.csv` enthält Titel und Kategorien zu genau
einem Lauf. Ändern sich Modell, Themenzahl, Text oder Seed, ändern sich die
Themen-IDs, und die Tabelle passt nicht mehr. Geprüfte Zeilen bekommen den
Status `geprüft` statt `KI-Entwurf`.

`export_topics.py` verwendet ausschließlich `llm_label` als `title`; das
redundante `auto_label` wird nicht exportiert. Bei einem reduced-Lauf werden Labels
aus der passenden Basis-JSON übernommen, sofern Modell, Seed, Themenzahl,
Mindestgröße und Themen-IDs übereinstimmen. Fehlen passende LLM-Labels, bricht
der Export ab. Flugblätter werden über Band und Seitenspanne identifiziert,
nicht über `segment_id`; Flugblätter ohne Thema haben `topic: null`.

## Häufige Fehler

| Meldung | Ursache |
|---|---|
| `OPENROUTER_API_KEY fehlt` | `.env` fehlt, liegt nicht im Repo-Hauptordner oder der Name ist falsch geschrieben |
| `401` / `Unauthorized` | Key ungültig oder widerrufen |
| `402` / `Insufficient credits` | Guthaben aufgebraucht |
| `DLL load failed ... too long` | Umgebung liegt unter einem zu langen Pfad, siehe Schritt 1 |
| `spaCy-Modell nicht verfügbar` | `python -m spacy download de_core_news_lg` fehlt; läuft trotzdem, aber mit unlemmatisierten Themenwörtern |
| Dendrogramm bleibt leer | braucht Internet, Plotly wird von einem CDN geladen |
