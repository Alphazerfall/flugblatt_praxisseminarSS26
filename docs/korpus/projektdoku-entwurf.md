# Digitale Erschließung der Flugblattsammlung Rep. 118

**Arbeitsstand und Grundlagen — Entwurf als Ausgangspunkt der Projektdokumentation**

Praxisseminar, Sommersemester 2026 · Stand: 4. September 2026

> Dieses Dokument fasst zusammen, was wir tun, warum wir es so tun und wo wir stehen. Es ist als Gerüst für die spätere Projektdokumentation gedacht: Die Abschnitte entsprechen ungefähr den Kapiteln, die Zahlen sind belegt und reproduzierbar, die Formulierungen bewusst nüchtern. Vertiefungen stehen in den jeweils genannten Einzeldokumenten unter `docs/korpus/`.

---

## 1. Gegenstand und Motivation

Die Allgemeine Flugblattsammlung der Universität Regensburg (Universitätsarchiv, Rep. 118) dokumentiert studentische, universitäre und gesellschaftliche Aktivitäten seit der Gründungszeit der Universität. Angelegt wurde sie 1968 von der Universitätsbibliothek und 2004 an das Universitätsarchiv übergeben. Unser Projekt bearbeitet den Zeitraum **1967 bis 1973** — die Jahre zwischen der Aufnahme des Lehrbetriebs und der Konsolidierung der Hochschulpolitik nach dem Bayerischen Hochschulgesetz.

Der Bestand ist bislang nur als Papier und als Scan zugänglich. Wer wissen will, welche Gruppen wann welche Themen setzten, muss Karton für Karton durchsehen. Das Ziel des Projekts ist deshalb ein **durchsuchbares Korpus, in dem jedes einzelne Flugblatt ein Datensatz ist** — mit Titel, Datum und ausstellender Organisation.

Der Ertrag liegt nicht im Digitalisieren selbst. Er liegt in den Fragen, die dadurch überhaupt erst stellbar werden und die beim Lesen strukturell nicht zu beantworten sind:

* **Vergleich.** Sprechen politische Lager an derselben Universität verschieden? Eine Vorprobe auf Seitenebene legt nahe: Der RCDS argumentiert institutionell und personalisiert (`Entwurf`, `Mandat`, `Öffentlichkeit`, `Freiheit`), MSB und SHB argumentieren über Kollektive und Verbände (`Arbeiterklasse`, `gewerkschaftliche Orientierung`, GEW, VDS).
* **Abwesenheit.** Was fehlt, fällt beim Lesen nicht auf, weil man nur liest, was da ist. Beispiel: Die §218-Kampagne ab 1971 war eines der mobilisierendsten Themen der Zeit — in 4 464 Seiten Regensburger Flugblättern findet sich dazu **ein einziges Blatt** (Juli 1971), und die Häufigkeit von „Frauen" fällt von 2,25 (1970) auf 0,15 (1973) pro 10 000 Token, also gegen den nationalen Trend.
* **Zeitliche Auflösung.** Reagieren die Blätter auf ein Ereignis in Wochen oder in Monaten? Gibt es einen Semesterrhythmus?

Diese drei Fragetypen begründen den Aufwand. Sie bestimmen auch, worauf es bei der Aufbereitung ankommt: nicht auf Vollautomatisierung, sondern darauf, dass **Dokumentgrenzen, Herausgeber und Datum belastbar** sind — denn an ihnen hängt jede der drei Fragen.

Ausführlich: `docs/korpus/fragestellungen.md`, `docs/korpus/analyseplan.md`.

## 2. Material und Verarbeitungskette

Das Material liegt als **14 Jahrgangs-PDFs** vor, je ein digitalisierter Archivkarton, zusammen **4 464 Seiten** und rund **1,06 Millionen Token** Volltext.

```
Scan (PDF, 14 Bände)
  └─ 1. OCR                Datalab/Chandra, Accurate-Modus   → abgeschlossen
  └─ 2. Segmentierung      Aufteilung in einzelne Blätter    → 1 902 Segmente, teils ungeprüft
  └─ 3. Metadaten          Titel, Datum, Herausgeber per LLM → vorbereitet, noch nicht produktiv
  └─ 4. Korpusbau          Seiten- und Dokumentebene, JSONL  → Datenmodell steht, Umsetzung offen
  └─ 5. Analyse            N-Gramme, Keyness, Kollokationen  → Werkzeug einsatzbereit
```

Verteilung des Materials über die Jahre (die Bandzahl je Jahr entspricht der Zahl der Archivkartons):

| Jahr | Seiten | Token | Segmente |
|---|---|---|---|
| 1967 | 13 | 5 462 | 3 |
| 1968 | 85 | 19 801 | 59 |
| 1969 | 317 | 71 845 | 206 |
| 1970 | 294 | 62 172 | 109 |
| 1971 | 629 | 149 818 | 262 |
| 1972 | 1 608 | 362 886 | 665 |
| 1973 | 1 518 | 392 813 | 598 |
| **Summe** | **4 464** | **1 064 797** | **1 902** |

Ein Flugblatt umfasst im Median ein bis zwei Seiten, im Mittel 2,35 Seiten oder rund 560 Token. Der auswertbare Kern des Korpus ist **1969–1973**; für 1967 mit drei Blättern trägt keine Frequenzaussage.

> **Einschränkung zu 1973.** Die Zahlen dieses Jahrgangs beruhen auf fünf digitalisierten Kartons, das Archiv verzeichnet jedoch sechs. Der nicht digitalisierte Karton (Einheit 15) enthält laut Findmittel unter anderem das Aktionskomitee gegen die Berufsverbote, das Anti-Strauß-Komitee, die DKP-Hochschulgruppe Regensburg, CISNU sowie Flugblätter zum Putsch in Chile. Alle Angaben zu 1973 sind daher als Untergrenze zu lesen, und zwar nicht zufällig, sondern mit einer inhaltlichen Schlagseite (siehe Abschnitt 5).

## 3. Segmentierung: das Kernproblem der Aufbereitung

### 3.1 Worum es geht

Ein Jahrgangs-PDF enthält dutzende bis hunderte Flugblätter hintereinander, ohne Markierung der Übergänge. Die Segmentierung legt fest, wo ein Blatt beginnt und endet — und sie entscheidet damit, was im Korpus überhaupt ein Dokument ist. Ein falsch gesetzter Schnitt erzeugt einen Datensatz, dessen Titel, Datum und Herausgeber notwendig falsch sind, weil sie aus dem Text zweier verschiedener Blätter stammen.

Für die Segmentierung wurde ein eigenes Werkzeug entwickelt (`flugblatt_splitter/`), mit dem die Seitenfolge visuell durchgegangen und geschnitten wird. Ergänzend lässt sich die Auto-Segmentierung der Datalab-API abrufen.

### 3.2 Was wir über die Fehler wissen

Ein Vergleich der beiden Verfahren an Band 002 (1968) zeigt eine klare Asymmetrie: Die feine Handsegmentierung findet 59 Segmente, die Auto-Segmentierung 13. **Alle 13 automatischen Schnittpunkte sind auch Schnittpunkte der Handsegmentierung; kein einziger Schnitt existiert nur automatisch.** Fehler sind also fast ausschließlich *fehlende*, kaum *falsche* Schnitte — zu große Segmente sind das Problem, nicht zu kleine.

Zugleich enthalten die OCR-Daten bislang ungenutzte Grenzsignale. Datalab kennzeichnet Kopfzeilen als eigene Blöcke, und diese sind erstaunlich aussagekräftig (Auszählung an Band 002):

| Signal | Seiten | davon tatsächlich Segmentbeginn |
|---|---|---|
| Kopfzeile ist eine Seitenzahl > 1 („- 2 -", „- Seite 3 -") | 16 | 1 |
| Kopfzeile ist eine Sigel-Leiste („LSD - LSD - LSD …") | 3 | 3 |
| Kopfzeile enthält ein Datum („23. 7. 68") | 4 | 3 |

Eine Fortsetzungs-Seitenzahl spricht also nahezu sicher **gegen** einen Blattanfang, eine Sigel-Leiste sehr stark **dafür**. Auf dieser Grundlage markiert `pipelines/01_pdf/detect_missing_cuts.py` verdächtige Segmente. Die Ausbeute liegt je Band zwischen 3 von 59 und 20 von 232 Segmenten.

### 3.3 Die Grenze des Verfahrens

Der Detektor kennt genau eine Signalquelle. Der Anteil der Seiten mit auswertbarer Kopfzeile schwankt zwischen **22 % und 63 %** — im Mittel etwa die Hälfte des Materials ist für ihn unsichtbar, und ausgerechnet die Bände von 1973 liegen am unteren Ende. Eine Erweiterung, die auch den Textinhalt auswertet (thematischer Bruch, Wechsel des Herausgebers, Anrede- und Schlussformeln), ist deshalb vorgesehen; sie lässt sich als Beurteilung jeder einzelnen Seitengrenze durch ein Sprachmodell umsetzen und wäre mit rund 1,4 Millionen Eingabe-Token für das gesamte Korpus vertretbar.

Ausführlich: `docs/korpus/kontext-splitting.md`.

## 4. Metadatenextraktion

### 4.1 Verfahren

Pro Segment sollen Titel, Datum und ausstellende Organisation aus dem bereits vorhandenen OCR-Text gewonnen werden — ohne erneutes OCR und ohne Seitenbilder. `pipelines/04_metadata/` bündelt dazu mehrere Segmente in einen Modellaufruf und erzwingt die Antwortform über ein JSON-Schema. Die ursprüngliche Fassung mit einem Aufruf je Segment sprengte die Kontingente der kostenlosen Nutzungsstufe bereits bei einem einzigen Jahrgang; die Bündelung reduziert 1 902 Segmente auf 39 bis 96 Anfragen.

Eine Prüfung, wie viel sich ohne Sprachmodell erledigen ließe, fiel ernüchternd aus: Nur 7 % der Segmente tragen ein Datum in der Kopfzeile, nur 4 % eine Sigel-Kopfleiste auf der ersten Seite. Anders als bei der Grenzerkennung tragen die deterministischen Signale hier nicht. Die maßgebliche Frage ist deshalb nicht, wie sich das Modell vermeiden lässt, sondern wie seine Ausgabe überprüfbar wird.

### 4.2 Qualitätssicherung durch Belegzitate

Die überarbeitete Fassung (`prompt_v2.py`) verlangt zu jedem Feld ein **wörtliches Belegzitat aus dem Segmenttext**. Jedes Zitat wird maschinell gegen die Quelle geprüft. Daraus ergibt sich eine Qualitätskennzahl über den gesamten Bestand, ohne eine einzige Handannotation — die Belegquote je Feld und Band. Zwei weitere Prüfungen laufen im selben Durchgang mit: Ein normalisiertes Datum, dessen Jahr nicht zum Jahrgang passt, wird markiert; ein Titel mit englischen Funktionswörtern ohne Beleg gilt als übersetzt oder erfunden.

Ergänzend wurden Felder eingeführt, die für die spätere Auswertung nötig sind und in der ersten Fassung fehlten: mehrere Herausgeber je Blatt (gemeinsame Herausgeberschaft ist häufig), unscharfe Datumsangaben (`1968-11` statt eines erfundenen Tages) und die Unterscheidung zwischen **Erscheinungsdatum und angekündigtem Veranstaltungsdatum**. Letztere ist folgenreich: Ein Streikaufruf „am Mittwoch, 29. Mai 1968" wurde vor dem 29. Mai verteilt; ohne diese Unterscheidung liegt jede Zeitreihe systematisch daneben.

### 4.3 Offenes Problem: Vereinheitlichung der Organisationsnamen

Da jeder Modellaufruf nur seinen eigenen Stapel sieht, kann dieselbe Organisation je Segment unterschiedlich benannt werden („LSD", „Liberaler Studentenbund (LSD)", „Liberaler Studentenbund Deutschlands"). Das ist strukturell bedingt und durch ein größeres Modell nicht zu beheben. Vorgesehen ist eine **Normdatei** (`organizations.json`) mit kanonischer Kennung, Langform und Schreibvarianten; die Zuordnung wird damit zu einem deterministischen Nachschlagevorgang, der reproduzierbar bleibt. Abschnitt 5 beschreibt, warum dieser Schritt inzwischen deutlich kleiner ausfällt als geplant.

Ausführlich: `docs/korpus/metadaten-plan.md`.

## 5. Findmitteldaten des Archivs

Im September 2026 stellte das Universitätsarchiv einen Export seiner Verzeichnungsdaten zu Rep. 118 bereit (HIDA-DOC1-XML aus ACTApro). Der Export beschreibt die Sammlung auf Ebene der **Verzeichnungseinheiten** — 85 Einheiten für 1967 bis 2024, je eine Einheit pro Karton. Ein Einzelstückverzeichnis ist er nicht; die Metadatenextraktion wird dadurch nicht ersetzt.

Wertvoll ist er dennoch, an vier Stellen:

**Herausgeberlisten.** Das Feld `St_Darin` nennt je Einheit die vertretenen Gruppen, überwiegend mit ausgeschriebenem Namen („LSD. Liberaler Studentenbund Deutschland", „GOB. Gewerkschaftlich orientiertes Bündnis"). Für 1967–1973 sind das 214 Nennungen, die sich zu 127 Einträgen verdichten lassen. Damit liegt die in Abschnitt 4.3 beschriebene Normdatei im Rohbau vor — erstellt von Archivarinnen statt automatisch geclustert.

**Einzeltitel.** Das Feld `St_Entha` verzeichnet einzelne Blätter in der Form „Herausgeber: Titel", für unseren Zeitraum **219 Titel**. Sie sind sehr ungleich verteilt: 49 für 1968 (bei 59 Segmenten) und 132 für 1969 (bei 206 Segmenten), für 1970 bis 1973 zusammen nur 38. Das Feld ist ausdrücklich als Auswahl gekennzeichnet („u.a."), für 1968 und 1969 aber nahezu vollständig.

**Zuordnung der Einheiten zu unseren Bänden.** Drei Einheiten sind im Findmittel als organisationsrein ausgewiesen, und die entsprechenden Bände sind es auch: Band 007 hat mit 74,1 Nennungen von „RCDS" pro 10 000 Token den höchsten Wert des Korpus und entspricht der Einheit „Flugblätter 1972. RCDS"; Band 011 hat mit 41,1 den höchsten Wert für „Front" und entspricht „Flugblätter 1973. Demokratische Front"; Band 013 den höchsten für „AStA". Die Zuordnung Band *n* ↔ Einheit *n* ist damit bestätigt.

**Eine Überlieferungslücke.** Aus dieser Zuordnung folgt: Das Findmittel führt für 1967–1973 **fünfzehn** Einheiten, digitalisiert sind **vierzehn**. Nicht enthalten ist Einheit 15 („Flugblätter 1973") mit unter anderem dem Aktionskomitee gegen die Berufsverbote, dem Anti-Strauß-Komitee, der DKP-Hochschulgruppe, CISNU und Flugblättern zum Putsch in Chile. Für Aussagen über 1973, insbesondere zu Berufsverboten und internationalen Solidaritätsthemen, ist das eine systematische Lücke. Sie ist beim Archiv anzusprechen und bis dahin im Methodenteil zu nennen.

Hinzu kommen Provenienzangaben aus der Bestandsgeschichte, die eigene Beobachtungen erklären — etwa die Praxis, „nicht mehr als drei Exemplare" zu archivieren und Doppelexemplare für Ausstellungszwecke zu behalten. Die Doppelstücke, die uns in der Konkordanz aufgefallen sind, sind demnach gewollt und kein Digitalisierungsfehler.

Ausführlich: `docs/korpus/findmittel-auswertung.md`.

## 6. Validierungsstrategie

Bis zum Eingang der Findmitteldaten hatte das Projekt drei aufeinander aufbauende Verarbeitungsschichten — OCR, Segmentierung, Metadaten — und für keine einen externen Maßstab. Das Feld `confirmed` in den Segmentdaten wurde von derselben Person gesetzt, die die Segmente angelegt hat; es bedeutet „bearbeitet", nicht „unabhängig geprüft". Aussagen über Genauigkeit waren damit nicht belegbar.

Daraus ergibt sich das Vorgehen, das wir jetzt verfolgen:

**Die Jahrgänge 1968 und 1969 werden zur Referenzstrecke.** Für sie liegen 181 archivarisch verzeichnete Einzeltitel vor. An ihnen lassen sich beide Verfahren extern prüfen:

* *Segmentierung.* Fallen mehrere Archivtitel auf dasselbe Segment, fehlen dort Schnitte. Ein erster Abgleich ordnet alle 49 Titel von 1968 Segmenten des Bandes 002 zu — sechs davon demselben Segment (Seiten 14–23), was unabhängig bestätigt, dass dort mindestens fünf Schnitte fehlen.
* *Metadatenextraktion.* Die extrahierten Titel und Herausgeber lassen sich gegen die Archivfassung messen. Das ergibt eine Genauigkeitsangabe je Feld, ohne eigene Annotationsarbeit.

**Für die übrigen Jahrgänge** existiert dieser Maßstab nicht. Dort greifen die intern kalibrierten Verfahren: die Belegquote der Extraktion, die Grenzsignale des Detektors und eine blinde Doppelannotation einer Stichprobe durch zwei Bearbeiter. Die Schwellenwerte dafür werden an der Referenzstrecke eingestellt, wo die Wahrheit bekannt ist.

**Die Unsicherheit wird beziffert, nicht versteckt.** Jeder Datensatz führt seinen Segmentierungsstatus und die Herkunft jedes Feldes mit. Grenzabhängige Auswertungen werden zusätzlich auf der geprüften Teilmenge gerechnet; stimmen die Größenordnungen überein, ist das Ergebnis robust, andernfalls ist die Abweichung selbst ein Befund.

Nebenbefund zur Einordnung der OCR-Qualität: Das Findmittel nennt ein Blatt „Emil Franzel und Franz **Mayer**", die OCR liest „FRANZ **BAYER**". Da Rektor Franz Mayer die zentrale Figur der Regensburger Auseinandersetzungen von 1968 ist, dürfte die Archivfassung zutreffen — die Titelliste dient damit auch als kleine Referenz für OCR-Fehler bei Eigennamen.

## 7. Datenmodell

Das geplante Korpus trennt drei Ebenen: Band, **Seite** und Flugblatt. Der OCR-Text liegt auf der Seite, ein Flugblatt ist eine Gruppierung von Seiten mit Metadaten. Diese Entscheidung ist die Voraussetzung dafür, dass Korrekturen an der Segmentierung bezahlbar bleiben: Ein Neuschnitt ändert nur die Zuordnung Seite → Dokument, ohne erneutes OCR und ohne Datenverlust. Zugleich sind alle Auswertungen, die keine Dokumentgrenzen brauchen, schon jetzt möglich.

Das Korpus selbst ist ein **Build-Artefakt** aus Segmentdaten, OCR und Korrekturdateien; von Hand editiert wird ausschließlich in der Quellschicht, damit ein erneuter Bau keine Handarbeit überschreibt.

Ausführlich: `docs/korpus/korpusstruktur.md` mit JSON-Schemata und Beispieldatensätzen.

## 8. Arbeitsstand und nächste Schritte

| Schritt | Stand |
|---|---|
| OCR aller 14 Bände | abgeschlossen |
| Segmentierung | 1 902 Segmente; 835 als bearbeitet markiert, keine unabhängig geprüft |
| Grenzdetektor (Heuristik) | einsatzfähig, Reichweite durch Kopfzeilenabdeckung begrenzt |
| Metadatenextraktion | Skript, Prompt und Prüfroutine vorbereitet; noch kein produktiver Lauf |
| Normdatei | Rohbau aus dem Findmittel, 127 Einträge, Durchsicht ausstehend |
| Analysewerkzeug | einsatzfähig (`pipelines/06_analysis/ngrams.py`) |
| Korpusbau | Datenmodell entworfen, Umsetzung ausstehend |

Als nächste Schritte sind vorgesehen:

1. Durchsicht des Normdatei-Rohbaus zu `organizations.json`.
2. Sauberer Abgleich der Archivtitel mit den Segmenten der Bände 002 und 003 — Ergebnis ist ein geprüftes Referenzset und eine Fehlerliste für die Segmentierung.
3. Probelauf der Metadatenextraktion auf zwei Bänden verschiedener Jahre, Messung gegen die Referenzstrecke, anschließend Lauf über alle Bände.
4. Rückfrage an das Archiv zur nicht digitalisierten Einheit 15.
5. Erweiterung der Grenzerkennung um textbasierte Signale, gemessen an der Referenzstrecke.
6. Umsetzung des Korpusbaus und Beginn der inhaltlichen Auswertung.

## 9. Offene Fragen

* **Mehrseitige Hefte.** Ist ein achtseitiges AStA-Info ein Dokument oder acht? Die Antwort bestimmt, was als fehlender Schnitt gilt, und gehört als erste Regel in eine Annotationsrichtlinie.
* **Anlagen und Rückseiten.** Zählt eine angehängte Resolution zum Blatt? Eine Rückseite mit abweichendem Inhalt?
* **Datumsauflösung.** Höchstens 63 % der Segmente enthalten überhaupt eine Datumsangabe im Text; der Rest bleibt jahresgenau. Wie viele tages- oder monatsgenaue Daten tatsächlich erreichbar sind, ist vor der Planung von Zeitreihen zu messen.
* **1967.** Der Jahrgang umfasst drei Blätter und wurde nachträglich zusammengetragen. Er kann im Korpus geführt und bei Bedarf gefiltert werden; als Datengrundlage trägt er nicht.
* **Nicht digitalisierte Einheit 15 (1973).** Ob der Karton nachdigitalisiert werden kann, ist mit dem Archiv zu klären. Solange er fehlt, betrifft das nicht nur die Vollständigkeit, sondern die inhaltliche Zusammensetzung des Jahrgangs: Gerade die Blätter der Berufsverbots- und Internationalismus-Kampagnen sind unterrepräsentiert. Jede Auswertung zu 1973 — insbesondere die Häufigkeit von „Berufsverbot" und die Frage nach internationalen Solidaritätsthemen — muss diese Lücke ausweisen. Fällt eine Nachdigitalisierung aus, ist zu prüfen, ob die betroffenen Aussagen auf die übrigen Jahrgänge beschränkt werden.

---

### Verzeichnis der Einzeldokumente

| Datei | Inhalt |
|---|---|
| `korpusstruktur.md` | Datenmodell, Formatvergleich, Standards, Umgang mit unsicherem Splitting |
| `kontext-splitting.md` | Ausgangslage, Detektor, Validierungsplan für die Grenzerkennung |
| `segmentierungsfehler.md` | Sammelliste gefundener Segmentierungsfehler mit Status |
| `topic-modelling.md` | Ausgangsstand, Ansatz und Ergebnisse des Topic Modellings |
| `metadaten-plan.md` | Vorgehen der Metadatenextraktion, Belegprüfung, Kanonisierung |
| `findmittel-auswertung.md` | Bewertung der Archivdaten, Überlieferungslücke, abgeleitete Dateien |
| `analyseplan.md` | Analysen nach Ertrag sortiert, Machbarkeitsrechnung |
| `fragestellungen.md` | Wie aus Zahlen Befunde werden, mit erprobten Beispielen |
| `ngrams-handbuch.md` | Handbuch des Analysewerkzeugs mit echten Ausgaben |
| `dehyphenierung.md` | Vorverarbeitung des Textes, Wirkung auf die Ergebnisse |
