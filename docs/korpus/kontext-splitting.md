# Projektkontext: Splitting-Kontrolle vor dem Korpusbau

**Diese Datei ist als erste Nachricht für eine neue Sitzung gedacht.** Sie enthält alles, was nötig ist, um ohne Vorgeschichte an der Aufgabe zu arbeiten. Stand: 20.08.2026.

---

## 0. Auftrag

Vor dem Korpusbau müssen die Dokumentgrenzen stimmen. Gesucht sind **fehlende und falsch gesetzte Schnitte** in den vorhandenen Segmentierungen. Es gibt bereits einen heuristischen Detektor (`pipelines/01_pdf/detect_missing_cuts.py`), der aus OCR-Kopfzeilen Verdachtsfälle meldet. Die Aufgabe: **diesen Prozess verbessern, voraussichtlich mit LLM-Unterstützung**, und das Ergebnis so ausgeben, dass es in der Review-Oberfläche direkt abgearbeitet werden kann.

Erfolgskriterium ist nicht „mehr Flags", sondern eine **messbar bessere Trefferquote**: mehr echte fehlende Schnitte gefunden, ohne die Prüfliste mit Fehlalarmen zu fluten.

**Zu klären ist dafür aber zuerst, woran überhaupt gemessen wird.** Im Projekt existiert bisher keine geprüfte Wahrheit — auch die als `confirmed` markierten Bände sind Einzelannotation ohne Gegenprüfung. Abschnitt 8 beschreibt den Weg dorthin; er sollte vor der Arbeit an den Detektoren gelesen werden, weil er die Reihenfolge bestimmt.

---

## 1. Das Projekt

Praxisseminar an der Universität Regensburg, Sommersemester 2026, drei Bearbeiter. Gegenstand ist eine Sammlung studentischer **Flugblätter der Universität Regensburg, 1967–1973** — Streikaufrufe, offene Briefe, Wahlwerbung, AStA-Mitteilungen, Programmhefte. Die Blätter sind auf Schreibmaschine getippt und vervielfältigt, viele mit charakteristischen Kopfleisten (`LSD - LSD - LSD - …`).

Physisch liegt die Sammlung als **14 gescannte Jahrgangsbände** vor, jeder ein PDF mit dutzenden bis hunderten Seiten. Ein Band enthält viele Flugblätter hintereinander; die Grenzen zwischen ihnen sind nicht markiert. Das Ziel ist ein durchsuchbares Korpus, in dem jedes Flugblatt ein Datensatz mit Titel, Datum und ausstellender Organisation ist.

Stand der Pipeline: **OCR ist für alle 14 Bände fertig** (Datalab/Chandra, Accurate-Modus). Die **Seitenunterteilung ist teilweise fertig** und kann Fehler enthalten — darum geht es hier. Die Metadatenextraktion und der Korpusbau kommen danach.

## 2. Material und Zahlen

4 464 Seiten, rund 1,06 Mio. Token Volltext.

| Band | Seiten | Segmente | `confirmed` | Median | p95 | max | Seiten mit PageHeader |
|---|---|---|---|---|---|---|---|
| Nr. 001 (1967) | 13 | 3 | 3 | 4 | 8 | 8 | 62 % |
| Nr. 002 (1968) | 85 | 59 | 0 | 1 | 2,0 | 10 | 52 % |
| Nr. 003 (1969) | 317 | 206 | 0 | 1 | 3,6 | 16 | 63 % |
| Nr. 004 (1970) | 294 | 109 | 2 | 1 | 7,0 | 58 | 57 % |
| Nr. 005 (1971) | 629 | **0** | – | – | – | – | 45 % |
| Nr. 006 (1972) | 455 | **0** | – | – | – | – | 44 % |
| Nr. 007 (1972) | 223 | **0** | – | – | – | – | 40 % |
| Nr. 008 (1972) | 325 | **0** | – | – | – | – | 56 % |
| Nr. 009 (1972) | 605 | 232 | 232 | 2 | 7,3 | 15 | 45 % |
| Nr. 010 (1973) | 217 | 75 | 75 | 2 | 8,2 | 14 | 24 % |
| Nr. 011 (1973) | 255 | 92 | 92 | 2 | 6,3 | 9 | 22 % |
| Nr. 012 (1973) | 286 | 129 | 129 | 2 | 5,5 | 12 | 37 % |
| Nr. 013 (1973) | 261 | 132 | 132 | 1 | 6,0 | 24 | 31 % |
| Nr. 014 (1973) | 499 | 170 | 170 | 2 | 10,0 | 17 | 28 % |

Zu lesen ist die Tabelle so: **Ein typisches Flugblatt ist ein bis zwei Seiten lang.** Alles, was deutlich darüber liegt, ist entweder ein mehrseitiges Heft (AStA-Info, Programm) oder ein Segment, in dem ein Schnitt fehlt. Nr. 004 hat ein 58-Seiten-Segment — das ist mit Sicherheit kein einzelnes Flugblatt.

Vier Bände (005–008, zusammen 1 632 Seiten) haben **noch gar keine Segmentierung**. Für sie ist die Aufgabe nicht Fehlersuche, sondern Erstsegmentierung — dieselben Verfahren, anderer Ausgangspunkt.

## 3. Dateien und Formate

```
data/raw/Nr. 009 (1972)/
  0118_0009.pdf                    # Scan des Jahrgangsbandes
  0118_0009.segments.json          # DIE Segmentierung (Handarbeit + Splitter-UI)
  0118_0009.boundary_flags.json    # Ausgabe von detect_missing_cuts.py --json
  0118_0009/
    0118_0009.json                 # Datalab-OCR, Blöcke pro Seite
    *_img.jpg                      # extrahierte Bilder
```

`data/` ist in `.gitignore` — Daten liegen nur lokal, Code und `docs/` sind versioniert.

**`segments.json`** — das Format, das die Splitter-Oberfläche liest und schreibt:

```json
{ "source_pdf": "0118_0009.pdf",
  "created": "2026-08-19T09:30:00+00:00",
  "segments": [
    {"id": 1, "title": "", "date": "", "start_page": 1, "end_page": 1, "confirmed": true}
  ] }
```

Regeln, die `flugblatt_splitter/backend/segmentation.py` erzwingt: **1-indizierte** Seiten, lückenlos, überschneidungsfrei, das erste Segment beginnt auf Seite 1, das letzte endet auf der letzten Seite. Eine Segmentierung mit Lücke wird beim Speichern abgelehnt.

**OCR-JSON** — Datalab-Struktur: `data["children"]` ist die Liste der Seiten, jede Seite hat `children` mit Blöcken. Relevante Felder je Block: `block_type` (`PageHeader`, `PageFooter`, `SectionHeader`, `Text`, `Picture`, `ListItem`, `Table`), `html`, `bbox`, `polygon`.

> **Fallstrick:** Die Seitenzuordnung immer über die **Array-Position** in `children` machen, nicht über das `id`-Feld. Bei batchweiser Konvertierung (`flugblatt_convert.py --batch-size`) beginnt die ID-Zählung in jedem Batch neu, die IDs kollidieren also über Batchgrenzen hinweg. Array-Index + 1 = Seitenzahl in `segments.json`.

## 4. Was schon existiert

| Pfad | Zweck |
|---|---|
| `pipelines/01_pdf/detect_missing_cuts.py` | der heuristische Detektor, um den es hier geht |
| `pipelines/01_pdf/datalab_auto_segment.py` | Datalabs Auto-Segmentierung → `.segments.auto.json` |
| `pipelines/02_ocr/*` | sechs OCR-Adapter (Datalab, Mistral, Gemini, OpenRouter, GLM) |
| `pipelines/04_metadata/extract_metadata.py` | Titel/Datum/Organisation je Segment per Gemini |
| `pipelines/06_analysis/ngrams.py` | N-Gramm-Werkzeug, enthält brauchbare Textaufbereitung |
| `flugblatt_splitter/` | FastAPI-Backend + JS-Frontend zum visuellen Schneiden |
| `ocr_viewer/` | Vergleichsoberfläche für OCR-Engines |
| `docs/korpus/korpusstruktur.md` | Datenmodell des geplanten Korpus, §7 behandelt genau dieses Problem |
| `docs/korpus/schema/page.schema.json` | Feldform von `boundary_signals` |
| `docs/korpus/segmentierungsfehler.md` | Sammelliste bestätigter und vermuteter Fehler; neue Funde dort eintragen |

Nützlich in `ngrams.py`: `load_text()` liefert den Volltext eines Bandes mit `\f` zwischen den Seiten und gefiltert nach Blocktypen, mit Plaintext-Cache unter `data/cache/ngram_txt/`. Für Grenzerkennung eher die ungefilterte Variante `load_text(stem, keep_headers=True)` verwenden — Kopfzeilen sind hier das Signal, nicht der Müll.

Umgebung: Windows, Python 3.10, keine virtuelle Umgebung nötig (`pip install -e .`). API-Schlüssel liegen in `.env` im Wurzelverzeichnis: `DATALAB_API_KEY`, `DATALAB_API_KEYS` (kommagetrennt, für Kontingent-Rotation), `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`.

## 5. Was über das Problem bekannt ist

Alles Folgende ist an Nr. 002 gemessen, nicht vermutet.

**Fehler sind fast immer fehlende, nicht falsche Schnitte.** Die Datalab-Auto-Segmentierung und die feine Handsegmentierung von Nr. 002 teilen sich 13 von 13 Schnittpunkten; 46 Schnitte hat nur die feine, **null** hat nur die automatische. Wer schnell segmentiert, fasst zusammen — er trennt nicht zu viel. Die Suche sollte sich also auf zu große Segmente konzentrieren.

**Drei Kopfzeilensignale sind belastbar** (Trefferquoten auf Nr. 002):

| Signal | Seiten | davon Segmentbeginn |
|---|---|---|
| Kopfzeile ist Seitenzahl > 1 (`- 2 -`, `- Seite 3 -`) | 16 | 1 |
| Kopfzeile ist Sigel-Leiste (`LSD - LSD - LSD`) | 3 | 3 |
| Kopfzeile enthält ein Datum (`23. 7. 68`) | 4 | 3 |

Eine Fortsetzungs-Seitenzahl spricht also fast sicher **gegen** einen Segmentbeginn, eine Sigel-Leiste sehr stark **dafür**.

**Der heutige Detektor** setzt drei Flags: `masthead_inside` (Sigel oder Datum auf einer Nicht-Erstseite → hier fehlt ein Schnitt), `continuation_start` (Segment beginnt auf einer Fortsetzungsseite → der Schnitt davor ist falsch, Segmente zusammenlegen), `long_segment` (länger als das 95. Perzentil des Bandes). Aktuelle Ausbeute:

```
Nr. 002:  3/59     Nr. 009: 20/232     Nr. 013: 12/132
Nr. 003: 13/206    Nr. 010:  8/75      Nr. 014:  9/170
Nr. 004:  5/109    Nr. 012: 18/129
```

## 6. Warum das nicht reicht

**Der Detektor kennt genau eine Signalquelle: `PageHeader`-Blöcke.** Deren Abdeckung liegt zwischen 22 % (Nr. 011) und 63 % (Nr. 003) der Seiten — im Schnitt etwa die Hälfte. Auf der anderen Hälfte kann er grundsätzlich nichts finden. Besonders unangenehm: Gerade die 1973er Bände, deren Segmente durchgängig `confirmed: true` tragen (was laut Abschnitt 8 nur „bearbeitet" heißt), haben mit 22–31 % die schlechteste Abdeckung — dort ist also weder die Heuristik stark noch die Annotation unabhängig geprüft.

Weitere Schwächen, die eine Verbesserung adressieren sollte:

1. **`long_segment` liefert keinen Vorschlag, wo geschnitten werden soll.** Es sagt nur „schau dir diese 12 Seiten an". Genau dort steckt laut Nr.-002-Referenz die Mehrzahl der echten Fehler — und genau dort hilft die Ausgabe am wenigsten.
2. **Kein Vertrauenswert.** Flags sind vorhanden oder nicht; es gibt eine grobe Severity, aber keinen Score, der Signale kombiniert und eine echte Prioritätsreihenfolge erzeugt.
3. **Textinhalt bleibt ungenutzt.** Der inhaltliche Bruch zwischen zwei Blättern ist offensichtlich, wenn man liest — anderes Thema, andere Anrede, Grußformel am Ende, Großüberschrift am Anfang, Wechsel der Organisation. Nichts davon wird ausgewertet.
4. **Layout bleibt ungenutzt.** `bbox`/`polygon` liegen in den OCR-Daten: großer Weißraum oben, ungewöhnlich große Schrift im ersten Block, ein `SectionHeader` als erster Block, deutlich anderer Satzspiegel als die Vorseite.
5. **Die Ausgabe ist nicht abarbeitbar.** Der Bericht ist Prosa für Menschen; niemand kann ihn in die Splitter-Oberfläche zurückspielen.
6. **Keine Messung.** Es ist unbekannt, wie viele echte Fehler gefunden und wie viele übersehen werden.

## 7. Vorschlag: LLM-gestützte Grenzerkennung

Die Grundidee ist, **jede Seitengrenze einzeln zu beurteilen** statt Segmente zu flaggen. Für jedes Seitenpaar (N, N+1) lautet die Frage: *Beginnt auf Seite N+1 ein neues Flugblatt?* Damit fallen fehlende und falsche Schnitte in dieselbe Entscheidung — man vergleicht am Ende die vorhergesagten Grenzen mit den vorhandenen.

**Das ist bezahlbar.** Bei einem Fenster aus den letzten ~500 Zeichen von Seite N und den ersten ~900 Zeichen von Seite N+1 ergeben alle 4 463 Grenzen des Gesamtkorpus zusammen etwa **5,7 Mio. Zeichen ≈ 1,4 Mio. Tokens** — ein Bruchteil dessen, was das Weiterreichen ganzer Bände kosten würde, und mit einem schnellen Modell (Gemini Flash ist über `extract_metadata.py` schon eingebunden) in einem Durchlauf machbar. Batchweise 20–40 Grenzen pro Anfrage, mit `response_schema`, analog zu `extract_metadata.py`.

**Was in den Prompt gehört**, über den reinen Text hinaus — die billigen Signale sollten mitgeliefert und nicht vom Modell erraten werden:

* die Kopfzeile beider Seiten im Rohtext,
* die Blocktypen-Folge der Seite N+1 (beginnt sie mit `SectionHeader`? `PageHeader`?),
* der vertikale Beginn des ersten Blocks (viel Weißraum oben = Blattanfang),
* die aktuelle Segmentzuordnung, aber **erst nach** der Entscheidung als Vergleich — nicht im Prompt, sonst bestätigt das Modell nur, was schon dasteht.

**Was zurückkommen sollte**, pro Grenze: `new_document` (bool), `confidence` (0–1), `reason` (ein Satz, auf Deutsch, mit Bezug auf konkrete Textmerkmale), optional `issuer_change` (bool). Der letzte Punkt ist wertvoll, weil ein Wechsel der ausstellenden Organisation der stärkste inhaltliche Grenzhinweis ist und später ohnehin als Metadatum gebraucht wird.

**Die Heuristiken bleiben und werden nicht ersetzt.** Sie sind kostenlos, deterministisch und auf ihrem Teilbereich sehr präzise. Sinnvoll ist eine Kombination: Wo die Kopfzeile eindeutig ist (`- 2 -` oder Sigel-Leiste), entscheidet die Heuristik und das LLM wird gar nicht gefragt; das spart etwa die Hälfte der Anfragen und verhindert, dass ein Modell einen sicheren Fall verschlechtert. Gefragt wird nur, wo kein Kopfzeilensignal vorliegt.

**Ausgabeformat.** Statt eines Prosaberichts eine Sidecar-Datei mit konkreten, abarbeitbaren Operationen:

```json
{ "source_pdf": "0118_0009.pdf",
  "created": "…", "method": "heuristik+gemini-3.5-flash",
  "suggestions": [
    {"op": "split", "segment_id": 156, "at_page": 435, "confidence": 0.92,
     "evidence": ["masthead_inside", "llm:0.95"],
     "reason": "Sigel-Leiste 'LINKE FRAKTION IM SP' dreifach wiederholt; Thema wechselt"},
    {"op": "merge", "segment_ids": [98, 99], "confidence": 0.85,
     "evidence": ["continuation_start"],
     "reason": "S. 300 trägt die Kopfzeile '- 8 -', ist also Fortsetzung"}
  ] }
```

Damit lässt sich die Splitter-Oberfläche um einen Vorschlagsmodus erweitern (annehmen / ablehnen / später), und Abgelehntes ist protokollierbar — was wiederum die Messgrundlage aus Abschnitt 8 liefert.

Denkbare Ergänzungen, falls Text allein nicht reicht: die Seitenbilder an ein Vision-Modell geben (teurer, aber der visuelle Blattanfang ist für ein Vision-Modell trivial), oder ein Embedding-basiertes Maß für den thematischen Bruch zwischen aufeinanderfolgenden Seiten (klassisches TextTiling, ganz ohne API).

## 8. Das Validierungsproblem — und der Plan dagegen

**Wichtigste Randbedingung: Es gibt im Projekt bisher keinerlei geprüfte Wahrheit.** Das Feld `confirmed: true` in den Bänden 009–014 wurde von derselben Person gesetzt, die die Segmente angelegt hat. Es bedeutet „bearbeitet", nicht „von jemand anderem geprüft und für richtig befunden". Damit gilt:

* Kein Band taugt als Gold-Set, auch die vollständig bestätigten nicht.
* Jede Aussage der Form „unser Detektor findet X % der Fehler" ist derzeit unbelegbar.
* Systematische Eigenheiten eines einzelnen Annotators (etwa: mehrseitige Hefte immer zusammenlassen) sind im Bestand unsichtbar, weil niemand dagegenhält.

Das ist kein Vorwurf, sondern der Normalfall bei Einzelannotation — und es ist mit überschaubarem Aufwand behebbar. Vorgeschlagene Reihenfolge:

**Schritt 1 — `confirmed` ehrlich benennen.** Das Feld vermischt zwei Dinge. Sauberer sind zwei: `annotated_by` (wer hat geschnitten) und `reviewed_by` (wer hat unabhängig geprüft, leer solange niemand). In der Korpusstruktur ist der Status bereits vierstufig vorgesehen (`auto` / `flagged` / `reviewed` / `confirmed`) — mit der Festlegung: **`confirmed` heißt, eine zweite Person hat zugestimmt.** Alle 830 heutigen Segmente wandern damit zunächst auf `annotated`. Das kostet eine Migration von zwanzig Zeilen und macht den Rest erst messbar.

**Schritt 2 — Doppelannotation einer Stichprobe, blind.** Der entscheidende Punkt ist *blind*: Die zweite Person darf die vorhandenen Schnitte **nicht sehen**, sonst entsteht Bestätigung statt Prüfung. Praktisch: einen Bereich von 150–200 aufeinanderfolgenden Seitengrenzen aus einem Band ziehen, den die zweite Person nicht selbst annotiert hat, und dort unabhängig für jede Grenze entscheiden — neues Blatt, ja oder nein. Ergebnis ist eine Liste `{stem, page, is_start, annotator}`.

Zur Größenordnung: In den segmentierten Bänden sind **43 % aller Seitengrenzen tatsächlich Dokumentgrenzen** (1 207 Segmente auf 2 832 Seiten, mittlere Länge 2,35 Seiten). Die Klassen sind also einigermaßen ausgeglichen, Cohens κ ist damit ein aussagekräftiges Maß und nicht durch Seltenheit verzerrt.

**Schritt 3 — Übereinstimmung berechnen und die Abweichungen ansehen.** Cohens κ plus Boundary-Precision/Recall zwischen den beiden Annotationen. Zwei Lesarten:

* κ hoch (> 0,8): Die Aufgabe ist gut definiert, der Bestand vermutlich brauchbar, und die Stichprobe wird nach Bereinigung zum Gold-Set.
* κ niedrig: Nicht die Personen sind das Problem, sondern die fehlenden Regeln. Dann ist Schritt 4 der eigentliche Ertrag.

**Schritt 4 — Aus den Abweichungen eine Annotationsrichtlinie schreiben.** Erfahrungsgemäß sind die meisten Uneinigkeiten keine Flüchtigkeitsfehler, sondern ungeklärte Fälle: Ist ein achtseitiges AStA-Info ein Dokument oder acht? Zählt eine angehängte Resolution zum Blatt oder ist sie eigenständig? Was ist mit der Rückseite eines beidseitig bedruckten Blattes, wenn sie inhaltlich etwas anderes bringt? Eine Richtlinie von ein bis zwei Seiten, geschrieben **aus den konkreten Streitfällen heraus**, löst das — und gehört ohnehin in den Methodenteil.

**Schritt 5 — Streitfälle gemeinsam entscheiden.** Die bereinigte Stichprobe ist dann das Gold-Set: die einzige Grundlage, gegen die Heuristik, LLM und Kombination gemessen werden können.

**Schritt 6 — erst jetzt Detektoren messen.** Precision, Recall, F1 jeder Variante gegen das Gold-Set. Und ein aufschlussreicher Zusatzvergleich: **Wie gut ist das LLM im Vergleich zur Mensch-Mensch-Übereinstimmung?** Erreicht es ein κ in derselben Größenordnung, ist es ein legitimer zweiter Annotator — und zwar einer, der sich im Gegensatz zu Menschen auf **alle 4 463 Grenzen** anwenden lässt. Das ist das eigentliche Argument für den LLM-Einsatz hier: nicht Genauigkeit, sondern Vollabdeckung.

**Schritt 7 — Vollabdeckung als Prüfliste nutzen.** Das LLM über alle Bände laufen lassen und nur die **Widersprüche** zur vorhandenen Annotation ausgeben. Diese Liste ist als Review-Warteschlange weit wertvoller als eine Zufallsstichprobe, weil jeder Eintrag ein konkreter Konfliktpunkt mit Begründung ist.

Aufwand für Schritte 2–5: realistisch ein halber Tag zu zweit. Das Ergebnis ist eine Zahl fürs Paper („Grenzsetzung zwischen zwei Annotatoren: κ = 0,8x an N = 200 Grenzen; Dokumentgrenzen des Korpus zu X % korrekt"), und aus dem größten Schwachpunkt wird eine dokumentierte Eigenschaft.

Nr. 002 eignet sich als kostenlose Vorstudie: Dort existieren zwei unabhängige Segmentierungen (fein von Hand, grob automatisch), deren Differenz die typische Fehlerart zeigt. Ein Gold-Set ist das nicht — keine der beiden ist geprüft —, aber es zeigt ohne Zusatzaufwand, wo Uneinigkeit entsteht.

## 9. Regeln für die Arbeit an den Daten

* **`segments.json` niemals direkt überschreiben.** Dort steckt Handarbeit. Vorschläge kommen in eine Sidecar-Datei neben der PDF (`.suggestions.json`, `.boundary_flags.json`). Wenn doch geschrieben wird, vorher eine Sicherung mit Zeitstempel anlegen — `datalab_auto_segment.py` und `extract_metadata.py` zeigen das Muster (`backup_existing()`).
* **Seitenzählung:** `segments.json` ist 1-indiziert, Datalab intern 0-indiziert. Diese Verwechslung ist die häufigste Fehlerquelle in diesem Repo.
* **Kontingente:** Die OCR-Läufe sind bezahlt und abgeschlossen. Keine Neu-OCR anstoßen, ohne das abzusprechen. Gemini-Aufrufe für Textanalyse sind unkritisch, aber batchen (siehe `--batch-size` in `extract_metadata.py`).
* **Kein Schreiben in `data/raw/**/*.pdf` oder in die OCR-JSONs.** Das sind die Rohdaten.
* Zwischenstände gehören nach `data/cache/` (ist in `.gitignore`), Dokumentation nach `docs/korpus/`.

## 10. Offene Fragen ans Team

1. **Wer hat welchen Band annotiert?** Für die Doppelannotation (Abschnitt 8) muss die zweite Person eine andere sein als die erste. Diese Zuordnung steht nirgends in den Daten — künftig gehört sie als `annotated_by` in `segments.json`, rückwirkend muss das Team sie aus dem Gedächtnis rekonstruieren.
2. **Mehrseitige Hefte:** Ein AStA-Info mit acht Seiten ist ein Dokument oder acht? Die Antwort ändert, was als fehlender Schnitt gilt — und sie gehört als erste Regel in die Annotationsrichtlinie.
3. **Anlagen und Rückseiten:** Zählt eine angehängte Resolution zum Blatt? Eine Rückseite mit anderem Inhalt? Ebenfalls Richtlinienfragen, die vor der nächsten Annotationsrunde geklärt sein sollten.
4. **Bände 005–008** (1 632 Seiten, keine Segmentierung): Erstsegmentierung automatisch mit anschließender Prüfung, oder von Hand wie die übrigen? Angesichts des Umfangs spricht viel für den automatischen Weg — und diese vier Bände sind zugleich die einzigen, bei denen sich der LLM-Vorschlagsmodus ohne Altlasten erproben lässt.
5. **Aufwandsgrenze:** Wie viele Stunden Handprüfung sind realistisch? Danach richtet sich, wie scharf die Vorschlagsliste gefiltert werden muss.

## 11. Kurzreferenz

```bash
# Verdachtsfälle eines Bandes anzeigen
python pipelines/01_pdf/detect_missing_cuts.py "data/raw/Nr. 009 (1972)/0118_0009.pdf"
# … und als JSON danebenlegen
python pipelines/01_pdf/detect_missing_cuts.py "data/raw/Nr. 009 (1972)/0118_0009.pdf" --json

# Automatische Segmentierung eines noch ungeteilten Bandes (schreibt .segments.auto.json)
python pipelines/01_pdf/datalab_auto_segment.py "data/raw/Nr. 005 (1971)/0118_0005.pdf"

# Splitter-Oberfläche (aus dem Wurzelverzeichnis, eigene venv), dann http://127.0.0.1:8020/
flugblatt_splitter\.venv\Scripts\python.exe -m uvicorn flugblatt_splitter.backend.main:app --reload --port 8020

# Volltext einer Seite ansehen (Python)
import sys; sys.path.insert(0, "pipelines/06_analysis")
import ngrams as N
seiten = N.load_text("0118_0009", keep_headers=True).split("\f")
print(seiten[434])          # Seite 435, 1-indiziert
```

Weiterführend im Repo: `docs/korpus/korpusstruktur.md` (§1 Befunde zur Fehlerart, §7 Umgang mit unsicherem Splitting, §7.5 Flag-Katalog), `docs/korpus/schema/page.schema.json` (Feldform `boundary_signals`), `pipelines/01_pdf/detect_missing_cuts.py` (Docstring erklärt die Heuristiken im Detail).
