Topic-Modelling-Pipeline
========================

Die Pipeline erkennt Themen in Datalab-OCR-JSON-Dateien und schreibt die
Ergebnisse in eine gemeinsame `data/topics/topics.json`.

Funktionsweise
--------------

Aus jeder `<id>.json`-OCR-Datei werden die Textblöcke extrahiert (HTML wird
entfernt, Picture-/Figure-Blöcke werden übersprungen). Statt pro Flugblatt zu
modellieren (zu wenige Dokumente für stabile Cluster), wird EIN gemeinsames
BERTopic-Modell über alle Textblöcke aller Flugblätter zusammen trainiert.

- Die Cluster-Bildung nutzt Satz-Embeddings (sentence-transformers,
  sprachunabhängig, semantisch).
- Die menschenlesbaren Themenwörter stammen aus einer separat lemmatisierten
  Version desselben Texts (spaCy, optional) über einen deutschen
  Stoppwort-Vektorisierer (c-TF-IDF).
- Das Hauptthema eines Flugblatts ist das Thema, dem die meisten seiner
  Blöcke zugeordnet wurden; die `weights` sind die normalisierte Verteilung
  seiner Blöcke über alle Themen (Ausreißer-Blöcke, HDBSCAN-Topic -1, werden
  ausgeschlossen, außer wenn *jeder* Block eines Flugblatts ein Ausreißer ist).

Installation
-------------

Optionale Abhängigkeitsgruppe "topics" in `pyproject.toml`
(bertopic, sentence-transformers, stop-words, spacy):

```powershell
pip install -e ".[topics]"
python -m spacy download de_core_news_lg
```

Ohne spaCy-Modell funktioniert die Pipeline weiterhin, die Themenwörter
verwenden dann aber unlemmatisierte Wortformen.

Aufruf
------

```powershell
.venv\Scripts\python.exe pipelines\04_topic\topic_modelling.py data\raw
```

Als Eingabe sind auch mehrere JSON-Dateien oder Verzeichnisse möglich
(Standard: `data/raw`). Weitere Optionen:

- `-o`: Ausgabepfad (Standard: `data/topics/topics.json`)
- `--num-topics`: feste Anzahl an Themen (Standard: automatische Reduktion durch BERTopic)
- `--min-topic-size`: minimale Anzahl an Blöcken pro Themen-Cluster (Standard: 20)
- `--embedding-model`: sentence-transformers-Modell (Standard: paraphrase-multilingual-MiniLM-L12-v2)
- `--lemma-model`: spaCy-Modell für die Lemmatisierung der Themenwörter (Standard: de_core_news_lg)

Ausgabeformat
-------------

```json
{
  "topics": [{"id": 0, "label": "wort1_wort2_wort3", "top_words": ["..."], "count": 123}],
  "documents": [
    {"id": "0118_0001", "path": "data/raw/.../0118_0001.json", "dataset": "Nr. 001 (1967)",
     "dominant_topic": 0, "weights": {"0": 0.8, "1": 0.2}}
  ]
}
```

Hinweise
--------

Jeder Lauf berechnet die Embeddings neu (kein Caching), ein voller Lauf über
`data/raw` dauert daher mehrere Minuten. Feintuning der Parameter
`min_topic_size`, `min_df` und `max_df` beeinflusst die Qualität der
erkannten Themen.
