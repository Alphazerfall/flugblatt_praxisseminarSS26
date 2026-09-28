# Analyseplan: was geht, sobald das Korpus steht

Ergänzung zu `fragestellungen.md` (dort: *wie* aus Zahlen ein Befund wird). Hier: **welche Analysen das fertige Korpus erlaubt, was sie kosten und was sie voraussichtlich einbringen.**

---

## 1. Was das Korpus voraussichtlich hergibt

Alles Weitere hängt an diesen Zahlen. Hochgerechnet aus der Segmentdichte der bereits geteilten Bände (1 207 Dokumente auf 2 832 Seiten = 0,426 Dokumente je Seite):

| Jahr | Dokumente | |
|---|---|---|
| 1967 | 3 | |
| 1968 | 59 | |
| 1969 | 206 | |
| 1970 | 109 | |
| 1971 | ~268 | hochgerechnet |
| 1972 | ~660 | hochgerechnet |
| 1973 | 598 | |
| **Summe** | **~1 900** | |

Dazu: ein typisches Dokument ist **2,35 Seiten bzw. rund 560 Token** lang, der Median liegt bei ein bis zwei Seiten. Weil noch Schnitte fehlen, sind das **Untergrenzen** — die tatsächliche Zahl liegt höher, in Nr. 002 etwa lag die feine Segmentierung um den Faktor 4,5 über der automatischen.

Drei Konsequenzen, die die Methodenwahl bestimmen:

**Die Dokumente sind kurz.** 560 Token sind zwei Absätze. Verfahren, die auf Wortverteilungen *innerhalb* eines Dokuments beruhen — allen voran klassisches Topic Modeling — arbeiten damit an der unteren Grenze.

**Die Jahre sind extrem ungleich.** 1967 hat drei Dokumente, 1972 rund 660. Jede Auswertung „pro Jahr" ist für 1967–1968 kaum belastbar. Der auswertbare Kern ist **1969–1973**.

**Die Akteure sind schief verteilt.** Eine grobe Vorprobe (Seite zählt für eine Gruppe, wenn deren Kürzel mindestens dreimal und dominant vorkommt) ordnet nur etwa 15 % der Seiten zu, zeigt aber die Schieflage deutlich:

| Jahr | LSD | SDS | SHB | RCDS | MSB | Jusos | AStA |
|---|---|---|---|---|---|---|---|
| 1968 | 8 | 0 | 0 | 1 | 0 | 0 | 11 |
| 1969 | 2 | 1 | 0 | 7 | 0 | 0 | 47 |
| 1970 | 0 | 0 | 0 | 6 | 0 | 0 | 19 |
| 1971 | 0 | 0 | 0 | 28 | 7 | 0 | 30 |
| 1972 | 0 | 0 | 37 | 87 | 17 | 1 | 56 |
| 1973 | 0 | 0 | 6 | 132 | 60 | 5 | 92 |

Mit echten `issuers`-Metadaten steigt die Abdeckung stark, die Schieflage bleibt: **RCDS, AStA und MSB/SHB tragen den Bestand, und zwar erst ab 1971.** Vergleiche zwischen Lagern funktionieren für 1971–1973; ein Vergleich LSD gegen SDS für 1968 hat keine Datengrundlage.

---

## 2. Der größte Hebel: Datumsauflösung

Eine einzige Kennzahl entscheidet, wie viel aus dem Korpus herauszuholen ist: **Wie viele Dokumente bekommen ein Datum auf Monats- oder Tagesgenauigkeit?**

* Nur Jahresauflösung → jede Zeitreihe hat **sieben Punkte**. Damit lassen sich Trends behaupten, aber keine Ereignisse zuordnen.
* Monatsauflösung → rund **80 Punkte**, und plötzlich sind Fragen beantwortbar wie: Reagieren die Blätter auf den Radikalenerlass (Januar 1972) innerhalb von Wochen oder erst im Sommer? Wie sieht die Produktionskurve um die Studentenparlamentswahlen aus? Gibt es Semesterrhythmen — Spitzen im November und Mai, Löcher in den Semesterferien?

Das ist der Unterschied zwischen „das Thema kam 1972 auf" und „das Thema erscheint sechs Wochen nach dem Erlass, zuerst beim MSB, drei Monate später auch beim AStA". Zweiteres ist ein Befund, Ersteres eine Jahreszahl.

**Konkreter nächster Schritt, eine Stunde Aufwand:** `extract_metadata.py` auf einen fertig segmentierten Band laufen lassen und auszählen, wie sich `date.precision` verteilt (`day` / `month` / `year`). Fällt der Anteil mit Tages- oder Monatsdatum unter etwa ein Drittel, lohnt es, gezielt nachzubessern — Datumsangaben stehen oft in Kopf- oder Fußzeilen, die eine Heuristik aus den OCR-Blöcken direkt lesen kann, ohne LLM.

---

## 3. Die Analysen, nach Ertrag sortiert

### Gruppe A — deskriptiv, sicher, unterschätzt

Diese vier laufen ohne Modellierung, sind praktisch risikofrei und liefern trotzdem Befunde, die **niemand aus dem Archiv abzählen kann**. Genau darin liegt ihr Wert.

**A1 Produktionskurve.** Blätter pro Monat über sieben Jahre. Zeigt Mobilisierungsspitzen, Semesterrhythmus und tote Phasen. Aufwand: ein Nachmittag. Voraussetzung: Datumsauflösung (Abschnitt 2).

**A2 Akteursverteilung über die Zeit.** Blätter je Organisation je Halbjahr — wer produziert wann wie viel. Aus der Tabelle oben ist zu erwarten: LSD verschwindet nach 1969, SHB hat einen kurzen Ausschlag 1972, MSB steigt ab 1971 stark, RCDS ist durchgehend präsent und ab 1971 der produktivste Akteur. Das ist eine **Organisationsgeschichte der Regensburger Studentenschaft in einer Grafik** — und sie ist neu, weil bisher niemand die Blätter gezählt hat.

**A3 Textsortenverteilung.** `doc_type` über die Zeit: Wird aus Agitation Verwaltung? Die Vermutung liegt nahe (1968 Streikaufrufe, 1973 AStA-Info-Hefte und Gremienprotokolle), belegt ist sie nicht.

**A4 Umfangsentwicklung.** Durchschnittliche Blattlänge über die Jahre. Ein einseitiges Flugblatt und ein zwölfseitiges Positionspapier sind verschiedene politische Kommunikationsformen; die Verschiebung zwischen ihnen ist messbar.

> **Erwarteter Ertrag: hoch. Aufwand: niedrig.** Diese vier ergeben zusammen das Kapitel „Der Bestand", das jede Arbeit über eine Sammlung braucht und das hier ausnahmsweise auf Zahlen statt auf Eindrücken beruht.

### Gruppe B — vergleichend, der eigentliche Kern

**B1 Keyness zwischen Lagern.** RCDS gegen MSB/SHB, jeweils 1971, 1972, 1973 getrennt. Die Vorprobe auf Seitenebene hat bereits zwei getrennte politische Sprachen gezeigt — RCDS institutionell und personalisiert (`entwurf`, `mandat`, `öffentlichkeit`, `freiheit`), die Linke kollektiv und verbandsbezogen (`arbeiterklasse`, `gewerkschaftliche orientierung`, `ddr`). Mit echten `issuers` wird daraus eine belastbare Aussage. **Datenlage gut** ab 1971.

**B2 Kollokationen umkämpfter Begriffe.** `demokratisierung`, `freiheit`, `interessen der studenten`, `mitbestimmung` — je Lager und je Jahr. Ergebnisform: „‚Demokratisierung' steht beim RCDS neben `satzung`, `mandat`, `wahl`; beim MSB neben `betrieb`, `basis`, `arbeiterklasse`." Das ist eine begriffsgeschichtliche Aussage mit Zahlen dahinter, und `ngrams.py collocates` kann es bereits — es fehlt nur der Lagerfilter.

**B3 Abwesenheitsanalyse.** Systematisch prüfen, was fehlt. Der §218-Befund steht schon: **ein einziges Flugblatt** in 4 464 Seiten, während `frauen` von 2,25 (1970) auf 0,15 (1973) fällt — gegen den nationalen Trend. Weitere Kandidaten: Umwelt/Ökologie, Ausländer/Gastarbeiter, Springer nach 1970. Sobald Dokumente statt Seiten gezählt werden, wird daraus „auf X von 660 Blättern des Jahres 1972".

**B4 Rhetorische Merkmale als Genremaß.** Imperative, direkte Anrede (`Kommilitonen!`, `Kolleginnen und Kollegen`), Mobilisierungsformeln (`wir fordern`, `alle zur`, `kommt zur`), Ausrufezeichendichte, Anteil VERSAL-Text. Damit lässt sich Agitation von Verwaltungsprosa **quantitativ** trennen und über die Zeit verfolgen — und der Befund aus A3 unabhängig prüfen. Aufwand gering, Ertrag unterschätzt.

> **Erwarteter Ertrag: hoch. Aufwand: mittel.** Hier entstehen die Ergebnisse, die über eine Bestandsbeschreibung hinausgehen.

### Gruppe C — Modellierung, mit Vorbehalt

**C1 Topic Model.** Erwartungsgemäß das, wonach im Kolloquium gefragt wird — und hier voraussichtlich das schwächste Ergebnis. 1 900 Dokumente à 560 Token sind für LDA wenig; die Topics werden grobkörnig („Hochschulpolitik", „Bundespolitik", „Gremien") und ihre Interpretation beliebig. *Falls doch:* mehrere Blätter desselben Monats und Akteurs zu Pseudo-Dokumenten bündeln, oder statt LDA ein Embedding-Clustering (`sentence-transformers`, deutsches Modell) verwenden, das mit kurzen Texten besser umgeht. Als Explorationswerkzeug brauchbar, als Hauptergebnis nicht.

**C2 Ko-Erwähnungsnetzwerk.** Welche Organisationen werden gemeinsam in einem Blatt genannt, und in welcher Rolle — Bündnispartner oder Gegner? Ergibt eine Netzwerkgrafik pro Jahr, die die Umgruppierungen 1968→1973 zeigt. Reizvoll und gut vorzeigbar; die Schwierigkeit ist die Vorzeichenfrage (Nennung ≠ Bündnis), die ohne Textprüfung nicht zu klären ist.

**C3 Vokabulardiffusion.** Wandert Vokabular zwischen den Lagern? Etwa: Wann taucht `gewerkschaftlich` erstmals in RCDS-Blättern auf? Methodisch anspruchsvoll (Erstbeleg-Datierung, Abgrenzung von Zitat und Übernahme), aber der originellste Befundtyp in dieser Liste, weil er ein *Ereignis* datiert statt einen Zustand beschreibt.

> **Erwarteter Ertrag: mittel bis unsicher. Aufwand: hoch.** Erst angehen, wenn A und B stehen.

### Gruppe D — nur mit externem Bezug

**D1 Vergleich mit einem Referenzkorpus.** Die Universität Regensburg nahm 1967 den Lehrbetrieb auf. Diese Sammlung dokumentiert eine Studentenbewegung an einer Hochschule **ohne eigene Tradition**. Die zugehörige Frage ist allgemein: *Was importiert eine solche Bewegung fertig, was entwickelt sie selbst?* Operationalisierbar über den Abgleich mit DWDS/DTA-Zeitungsdaten derselben Jahre oder mit digitalisierten Flugblattbeständen anderer Universitäten. Kandidaten für lokales Vokabular stehen schon in der Keyness-Liste: `bhg` (1 125 Treffer, bayerisches Spezifikum), `mhg`, `fsr`, `sprach-lit`.

> **Ertrag: potenziell der höchste — das wäre die Aussage, die über Regensburg hinausweist. Aufwand: hoch,** weil ein zweites Korpus beschafft und vergleichbar gemacht werden muss.

---

## 4. Empfehlung

| Rang | Analyse | Aufwand | Bedingung |
|---|---|---|---|
| 1 | **A2 Akteursverteilung über die Zeit** | niedrig | `issuers` + Normdatei |
| 2 | **B1 Keyness zwischen Lagern, 1971–1973** | mittel | `issuers` |
| 3 | **A1 Produktionskurve** | niedrig | Datum monatsgenau |
| 4 | **B3 Abwesenheitsanalyse** | niedrig | Dokumentgrenzen |
| 5 | **B2 Kollokationen umkämpfter Begriffe** | mittel | `issuers` |
| 6 | **B4 Rhetorische Merkmale** | niedrig | Dokumentgrenzen |
| 7 | C2 Netzwerk / C3 Diffusion | hoch | alles obige |
| 8 | D1 Referenzkorpusvergleich | hoch | externes Korpus |

**Wenn nur drei Sachen fertig werden: A2, B1, B3.** Begründung: A2 nutzt genau die Metadaten, für die ihr das Korpus gebaut habt, und liefert eine Grafik, die eine Präsentation trägt. B1 ist der methodische Kern — zwei politische Sprachen an einer Universität, mit Zahlen belegt. B3 liefert den kontraintuitiven Einzelbefund, an den sich Zuhörer erinnern.

Auffällig an dieser Liste: **Vier der sechs Top-Analysen brauchen `issuers`, keine einzige braucht ein Modell.** Der Ertrag liegt in den Metadaten, nicht in den Verfahren — was die Priorität für die verbleibende Arbeit vorgibt: erst Splitting, dann Organisationszuordnung, dann Datumsauflösung. Die Analysen selbst sind danach eine Frage von Tagen.

## 5. Was ich nicht machen würde

* **Sentimentanalyse.** Kein deutsches Sentiment-Lexikon ist auf Agitationsprosa der 1970er kalibriert. „Kampf", „Front", „Angriff" sind hier keine negativen Emotionen, sondern Normalvokabular. Die Ergebnisse wären systematisch falsch und schwer zu bemerken.
* **Autorschaftsattribution / Stilometrie.** Es gibt keine Autoren, nur Organisationen, und die Texte sind zu kurz.
* **Named Entity Recognition auf Personen als Selbstzweck.** Die OCR-Qualität bei Eigennamen ist ausweislich der Keyness-Listen durchwachsen (`treratola`, `bergenthal`), und ein Personennetzwerk aus fehlerhaften Namen sieht überzeugender aus, als es ist.
* **Ein Topic Model als Hauptergebnis.** Siehe C1 — als Explorationswerkzeug ja, als Befund nein.
