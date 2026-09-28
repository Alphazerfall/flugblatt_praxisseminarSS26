# Topic Modelling: Stand und Vorgehen

> Arbeitsdokument für das Team, Stand 28.09.2026. Mit KI-Unterstützung (Claude)
> erstellt; Zahlen stammen aus den beschriebenen Läufen, Bewertungen sind zur
> Diskussion gedacht.

## Kurzfassung

- Ausgangspunkt ist die Topic-Modelling-Pipeline auf dem Branch `dev-ner`
  (BERTopic auf Blockebene mit einem kleinen Embedding-Modell). Sie liefert
  viele kleine, oft formale Themen.
- Wir haben eine zweite Variante gebaut, die **ganze Flugblätter** (Segmente)
  modelliert, ein **aktuelles Embedding-Modell mit langem Kontext** nutzt und
  die Themen **von Hand beschriftet**, angelehnt an Achmann & Wolff (2023).
- Ergebnis nach Zusammenfassung: **24 Themen** über 1 911 Flugblätter, davon
  14 Sachthemen. Die Beschriftungen sind ein KI-Entwurf und müssen geprüft
  werden.

## 1. Ausgangsstand: Branch `dev-ner`

`pipelines/04_topic/topic_modelling.py` (Stand Commit `0b64f74`):

- Ein BERTopic-Modell über **alle Textblöcke aller Bände** (48 443 Blöcke);
  Thema eines Flugblatts = häufigstes Thema seiner Blöcke.
- Embeddings: `paraphrase-multilingual-MiniLM-L12-v2` (lokal).
- Themenwörter aus spaCy-lemmatisiertem Text, deutsche Stoppwörter,
  optional NER-Entitäten als Zusatzwörter.

**Testlauf** (lokal, CPU, ohne NER-Dateien): rund 70 Minuten,
234 Themen, **42 % der Blöcke ohne Thema**. Größtes Thema ist das Impressum
(„presserechtlich verantwortlich …“); viele Themen sind formal (Wochentage,
Monatsnamen, Wahllisten). Es gibt aber auch klare Inhaltsthemen (Vietnam,
Marxismus, Lehrerausbildung, Streik).

**Befunde aus der Code-Durchsicht**

| Punkt | Folge |
|---|---|
| Hugging-Face-Token im Klartext, auf GitHub gepusht | muss widerrufen werden; der Login ist unnötig, das Modell ist öffentlich |
| `--min-topic-size` wirkt nicht (eigenes HDBSCAN mit festem Wert) | Parameter im README stimmt nicht |
| liest alle `*.json` unter `data/raw` | Metadaten-Dateien landen als leere „Flugblätter“ im Ergebnis |
| Kopf- und Fußzeilen werden mitmodelliert | bilden eigene Themen („LSD - LSD - LSD“, „-2-“) |
| UMAP ohne `random_state` | jeder Lauf liefert andere Themen |
| ungeschützte Importe, scikit-learn ≥ 1.3 fehlt in `pyproject.toml` | Installationsprobleme |
| MiniLM liest nur ~128 Tokens | lange Blöcke gehen nur mit dem Anfang ein |
| Blöcke als Dokumente | kurze Blöcke („Wir fordern:“) tragen kein Thema |

## 2. Einordnung: Achmann & Wolff (2023)

Achmann, M.; Wolff, C. (2023): *Policy Issues vs. Documentation: Using
BERTopic to Gain Insight in the Political Communication in Instagram Stories
and Posts during the 2021 German Federal Election Campaign.* DHNB2023
Conference Proceedings, S. 11–28.

Vorgehen der Autoren: BERTopic mit demselben MiniLM-Modell, qualitative
Prüfung über Dendrogramm und Themenkarte, Reduktion auf eine feste Zahl
(62 → 25), **Beschriftung von Hand** und Zuordnung zu einer groben Kategorie
(Sachthema / kein Sachthema / gemischt). Ausgewertet wird über diese
Kategorie. Ihr Hauptproblem: Parteinamen, Slogans und Hashtags bildeten
eigene Themen; Lösung war, Hashtags und Erwähnungen zu entfernen. Als
Ausblick nennen sie Guided Topic Modeling.

**Übertragbar:** der Ablauf mit menschlicher Prüfung; das Entfernen der
Absender-Merkmale (bei uns Organisationskürzel statt Hashtags); die grobe
Kategorie über den Themen.

**Unterschied:** Instagram-Texte haben im Schnitt ~15 Wörter, dafür genügt
MiniLM. Unsere Flugblätter sind oft seitenlang; deshalb ein Modell mit langem
Kontext und Flugblätter statt Blöcke als Dokumente.

## 3. Unser Ansatz

Skript: `pipelines/04_topic/leaflet_topics.py` (neben dem Branch-Code, ändert
ihn nicht).

| Schritt | Umsetzung |
|---|---|
| Dokumente | ein Flugblatt = ein Segment aus `<stem>.segments.json`; 1 911 Flugblätter aus 14 Bänden (Segmente ohne Inhalt oder unter 50 Zeichen entfallen) |
| Text | Datalab-OCR ohne Bild-, Kopf- und Fußzeilenblöcke; auf 16 000 Zeichen gekürzt (betrifft 79 Flugblätter) |
| Embeddings | `baai/bge-m3` über OpenRouter (bis ~8 000 Tokens, offenes Modell); zwischengespeichert in `data/cache/embeddings/`, Schlüssel ist der Hash des Textes. Ein voller Lauf kostet geschätzt 2 Cent und dauert etwa eine Minute |
| Clustering | UMAP (15 Nachbarn, 5 Dimensionen, Seed 42), HDBSCAN über BERTopic mit Mindestgröße 10 |
| Themenwörter | nur **Substantive** (spaCy `de_core_news_lg`), deutsche Stoppwörter, dazu **70 Organisationskürzel** aus der Normdatei (RCDS, SHB, MSB …); BHG bleibt als Sachbegriff drin |
| Zeit | Themenverteilung je Jahrgang (`topics_over_time`) |
| Prüfung | Dendrogramm der Themen, Reduktion auf 25 (`--num-topics 25`) |
| Beschriftung | Codierungstabelle `pipelines/04_topic/topic_labels.baai__bge-m3.n25.csv` |
| Ansicht | `pipelines/04_topic/topics_report.py`: Heatmap Thema × Jahr (Anteil am Jahrgang), aufklappbare Flugblattlisten, Link zum Dendrogramm |

Wichtig: Die Themenwörter-Filter ändern nur die Beschriftung, nicht die
Cluster. Die Codierungstabelle gilt nur für genau diesen Lauf (Modell,
Themenzahl, Seed stehen im Dateinamen bzw. in der JSON).

## 4. Ergebnisse

**Vergleich der Läufe**

| | MiniLM, Blöcke | bge-m3, Flugblätter | bge-m3, reduziert |
|---|---|---|---|
| Dokumente | 48 443 Blöcke | 1 911 | 1 911 |
| Themen | 234 | 39 | **24** |
| ohne Thema | 42 % | 23 % | 23 % |
| Laufzeit (Laptop, CPU) | ~70 min | ~2 min | ~2 min |

**Flugblätter je Jahrgang:** 1967: 3 · 1968: 59 · 1969: 212 · 1970: 180 ·
1971: 237 · 1972: 627 · 1973: 593. Die Heatmap zeigt deshalb Anteile, nicht
absolute Zahlen; 1967 ist nicht aussagekräftig.

**Themen (KI-Entwurf, ungeprüft)**

| # | Titel | Kategorie |
|---|---|---|
| 0 | Hochschulgesetz und Streiks | Sachthema |
| 1 | Politisches Mandat und Wahlkampf der Hochschulgruppen | gemischt |
| 2 | Wahlaufrufe zum Studentenparlament | gemischt |
| 3 | Konflikte um Lehrstühle, Senat und Rektorat | Sachthema |
| 4 | Studium, Lehre und Prüfungen in den Fachbereichen | Sachthema |
| 5 | Soziale Lage: Wohnen, Miete, BAföG | gemischt |
| 6 | Gesellschaftstheorie: Demokratie, Wissenschaft, Marxismus | Sachthema |
| 7 | Einladungen und Veranstaltungen | kein Sachthema |
| 8 | Lehrerbildung | Sachthema |
| 9 | Kandidatenlisten zu Fachbereichs- und Fachschaftswahlen | kein Sachthema |
| 10 | Berufsverbote und Radikalenerlass | Sachthema |
| 11 | Rektor- und Prorektorwahl | Sachthema |
| 12 | Gremienwahlen: Wahlordnung und Wahlvorschläge | kein Sachthema |
| 13 | Internationale Solidarität und Antiimperialismus | Sachthema |
| 14 | Ausländergesetz und Ausweisungen | Sachthema |
| 15 | Fahrpreiserhöhungen (Aktion Roter/Gelber Punkt) | Sachthema |
| 16 | Gegenveranstaltungen, Filme, Podien | gemischt |
| 17 | Berufungen und Stellenbesetzungen | Sachthema |
| 18 | Mensa- und Studentenwerkspreise | Sachthema |
| 19 | Fachschaft Soziologie/Politologie | gemischt |
| 20 | Entlassung der Lehrassistenten | Sachthema |
| 21 | Satire der „Bewegung des gemäßigten Fortschritts“ | kein Sachthema |
| 22 | Wahlergebnisse | kein Sachthema |
| 23 | Verbot der Grundkurse durch das Kultusministerium | Sachthema |

Auffällig im Zeitverlauf (39-Themen-Lauf): Streik/Hochschulgesetz mit
Spitzen 1969 und 1972/73; die Demokratische Mitte als Thema vor allem
1968–70; Berufsverbote ab 1972; Ausländergesetz fast nur 1972.

## 5. Bekannte Schwächen

- **Absender-Cluster:** Das Embedding erfasst auch Stil und Absender. Einige
  Themen sind eher Organisationen oder Serien (T21, teilweise T1 und T2).
- **Zu grobe Themen:** T0 fasst den Notstandsstreik 1968 mit den BHG-Streiks
  1969 und 1972/73 zusammen.
- **Namen in den Themenwörtern:** spaCy erkennt manche Nachnamen in
  OCR-Schreibweise als Substantive („drösler“, „eggerdinger“).
- **Harte Zuordnung:** jedes Flugblatt genau ein Thema oder keins; Flugblätter
  mit mehreren Themen werden verkürzt.
- **Ausreißer:** 23 % der Flugblätter haben kein Thema.
- **Abhängigkeit von der Segmentierung:** Fehler in `segments.json` schlagen
  direkt durch (siehe `segmentierungsfehler.md`).
- **Reproduzierbarkeit:** feste Seeds, aber Ergebnisse hängen von Parametern
  und dem Embedding-Anbieter ab; bge-m3 ist offen und ließe sich notfalls
  lokal rechnen.

## 6. Mögliche Verbesserungen

Nach Aufwand sortiert:

1. **Codierungstabelle prüfen** und den Status auf `geprüft` setzen.
2. **Themenzahl festlegen:** Dendrogramm ansehen; ggf. 30–35 Themen, damit
   z. B. 1968 und 1972 getrennt bleiben (braucht eine neue Tabelle).
3. **Ausreißer nachträglich zuordnen** (`reduce_outliers` in BERTopic),
   gekennzeichnet als unsicher.
4. **Namen vor dem Embedding maskieren** (Personen und Organisationen durch
   Platzhalter ersetzen), damit die Cluster weniger nach Absender entstehen.
   Kostet eine neue Einbettung (~2 Cent).
5. **Vergleichslauf mit `qwen/qwen3-embedding-8b`** (ebenfalls offen, ~2 Cent).
6. **Guided Topic Modeling** mit Startthemen (Hochschulgesetz, Notstand,
   Vietnam, Berufsverbote, Mensa/BAföG, Wahlen).
7. **Analyseraster:** Thema (Was) × Textsorte (Wie, aus den Metadaten) ×
   Herausgeber (Wer) × Jahr (Wann).
8. **Themen in UR_LeafletArchive** als Feld und Filter übernehmen.

## 7. Offene Punkte im Team

- Token auf `dev-ner` widerrufen und entfernen.
- Zusammenführen mit `main`: Ordnernummern kollidieren (`03_eval`/`04_metadata`
  gegen `03_ner`/`04_topic`), Konflikte in `pyproject.toml` und `ocr_viewer`.
- Entscheiden, ob die Block-Variante (`topic_modelling.py`) bleibt, etwa für
  die NER-Anreicherung, oder durch die Flugblatt-Variante ersetzt wird.

## 8. Reproduzieren

Abhängigkeiten: `bertopic`, `umap-learn`, `spacy` mit `de_core_news_lg`,
`stop-words`, `openai`, `python-dotenv`; `OPENROUTER_API_KEY` in `.env`.
Unter Windows das virtuelle Environment unter einem kurzen Pfad anlegen,
sonst lädt spaCy wegen der Pfadlänge nicht.

```powershell
python pipelines\04_topic\leaflet_topics.py --num-topics 25
python pipelines\04_topic\topics_report.py data\topics\topics.baai__bge-m3.json
```

Ausgaben liegen unter `data/topics/` (JSON, Heatmap, Dendrogramm) und
`data/cache/embeddings/`; beide Ordner sind nicht in Git und müssen lokal
erzeugt werden.
