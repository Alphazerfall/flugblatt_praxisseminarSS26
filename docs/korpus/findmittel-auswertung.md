# Findmitteldaten Rep. 118 — was wir davon haben

Bewertung des XML-Exports des Universitätsarchivs (HIDA-DOC1 aus ACTApro, Export vom 02.09.2026).
Auswertung reproduzierbar über `pipelines/04_metadata/parse_findmittel.py`.

---

## Kurzfassung

Es ist **kein Einzelstückverzeichnis** — die Erwartung, hier fertige Metadaten für jedes Flugblatt zu finden, erfüllt sich nicht. Die Datei beschreibt 85 Verzeichnungseinheiten für den Zeitraum 1967–2024, also einen Karton pro Einheit; genau eine Einheit entspricht einer unserer Jahrgangs-PDFs.

**Trotzdem ist die Lieferung sehr wertvoll**, und zwar an vier Stellen, die alle auf unserem kritischen Pfad liegen:

| Was | Umfang | Wofür |
|---|---|---|
| `St_Darin`: Herausgeber je Einheit, meist mit ausgeschriebenem Namen | 214 Nennungen, 127 Rohbau-Einträge für 1967–1973 | **Normdatei** — löst das Kanonisierungsproblem |
| `St_Entha`: Einzeltitel in der Form „HERAUSGEBER: Titel" | **219 Titel** für 1967–1973 | **Gold-Set** für die Metadaten-Extraktion |
| Zuordnung Einheit ↔ PDF | 15 Einheiten gegen 14 PDFs | deckt eine **Digitalisierungslücke** auf |
| Bestandsgeschichte | Fließtext | Provenienzangaben für den Methodenteil |

---

## 1. Struktur der Lieferung

```
1 Bestand (Best)       Rep. 118, mit Bestandsgeschichte
54 Klassifikationen    Jahresgruppen ("bis einschließlich 1971", "1972", ...)
85 Verzeichnungseinheiten (Vz)   = ein Karton/Ordner, 1967-2024
```

Für unseren Zeitraum sind das die Einheiten 1–15. Felder je Einheit: Signatur, Bestellsignatur, Laufzeit (nur jahresgenau), Klassifikation, `St_Darin`, `St_Entha`. **Keine Angaben auf Blattebene, keine Digitalisat-Verknüpfung** (das einzige `DD_FilePath`-Feld im ganzen Export hängt an einer Einheit von 2020).

## 2. Die Einheiten entsprechen unseren PDFs — bis auf eine

Das Findmittel führt für 1967–1973 **15 Einheiten**, wir haben **14 PDFs**. Die Zuordnung `Nr. NNN` ↔ `Vz NNN` lässt sich am Inhalt bestätigen: Drei Einheiten sind im Findmittel als organisationsrein ausgewiesen, und genau die entsprechenden Bände sind es auch (relative Frequenz pro 10 000 Token):

| Band | laut Findmittel | `rcds` | `asta` | `front` |
|---|---|---|---|---|
| 0118_0007 | Vz 7 = „Flugblätter 1972. RCDS" | **74,1** | 18,4 | 1,6 |
| 0118_0008 | Vz 8 = „Flugblätter 1972. AStA" | 28,9 | **43,7** | 0,3 |
| 0118_0010 | Vz 10 = „Flugblätter 1973. RCDS" | **84,6** | 4,1 | 2,2 |
| 0118_0011 | Vz 11 = „Flugblätter 1973. Demokratische Front" | 29,9 | 31,2 | **41,1** |
| 0118_0013 | Vz 13 = „Flugblätter 1973. AStA" | 9,6 | **47,1** | 1,6 |

Jeder dieser Bände hat für das erwartete Kürzel den Höchstwert des gesamten Korpus. Die Zuordnung 1:1 steht damit.

> ### Daraus folgt: **Vz 15 fehlt in unserem Bestand.**
>
> „15 - Flugblätter 1973" ist nicht digitalisiert. Laut `St_Darin` enthält gerade diese Einheit: Aktion 3. Welt, Aktionskomitee gegen die Einschüchterung der BHG-Opposition, **Aktionskomitee gegen die Berufsverbote**, Aktionskomitee gegen die Erpressung von Demokraten, Anti-Strauß-Komitee, CISNU, DFG, **DKP-Hochschulgruppe Regensburg**, GOB, KHB, Komitee Kampf der Inflation, KSV — sowie „Flugblätter zum Putschversuch in Chile".
>
> Das ist politisch einer der dichtesten Kartons des Jahres. Für jede Aussage über 1973 — und besonders für die Berufsverbots- und Internationalismus-Themen — ist das eine **systematische Lücke, keine zufällige.** Zwei Dinge folgen: beim Archiv nachfragen, ob Vz 15 nachdigitalisiert werden kann, und die Lücke bis dahin im Methodenteil nennen.

## 3. Normdatei: das Kanonisierungsproblem ist damit weitgehend erledigt

`St_Darin` listet je Einheit die Herausgeber, in der Form `Kürzel. Ausgeschriebener Name`:

```
- LSD. Liberaler Studentenbund Deutschland
- MSB Spartakus
- ADF. Aktion Demokratische Fachschaften
- BEGEFOGREGETZ
- GOB. Gewerkschaftlich orientiertes Bündnis
```

Für 1967–1973 sind das 214 Nennungen, die `parse_findmittel.py` zu **127 Rohbau-Einträgen** verdichtet (45 davon mit Langform). Für den ganzen Bestand bis 2024 wären es 908 Schreibweisen.

Das ist der Normdatei-Ansatz aus `korpusstruktur.md` — nur ist die Vorarbeit jetzt **von Archivarinnen gemacht** statt von einem LLM geclustert. Konsequenzen für `metadaten-plan.md`, Abschnitt 3:

* Der geplante einmalige LLM-Durchlauf zur Gruppenbildung wird überflüssig oder schrumpft auf einen Abgleich.
* Die Liste geht als `known_orgs` in den Extraktions-Prompt (`prompt_v2.build_prompt`) — das Modell greift dann von vornherein zur archivüblichen Schreibweise.
* **Zusatznutzen:** Jede Gruppe trägt die Einheiten mit, in denen sie vorkommt. Damit ist prüfbar, ob eine extrahierte Zuschreibung überhaupt plausibel ist — ein „SDS" in einem 1973er Band widerspricht dem Findmittel und gehört markiert.

`organizations.seed.json` ist ausdrücklich ein **Rohbau**: Die Trennung Kürzel/Langform ist heuristisch und produziert Fehler (`1. Mai-Komitee` → Kürzel „1"; `AK Kritische Juristen` → Kürzel „AK"). Er ersetzt die Handdurchsicht nicht, aber er verkürzt sie von „aus dem Nichts" auf „durchsehen und korrigieren".

## 4. Gold-Set: 219 Titel, aber sehr ungleich verteilt

`St_Entha` nennt einzelne Blätter, jeweils als `HERAUSGEBER: Titel`:

```
LSD: Emil Franzel und Franz Mayer, Oder: Wie man das Ansehen der Universität Regensburg ruiniert
SHB: Offener Brief an Rektor Mayer
Demokratische Mitte: Hunde, wollt ihr ewig Leben?
AStA: Urabstimmung für Streik
```

Verteilung über unseren Zeitraum:

| Jahr | Titel im Findmittel | Segmente im Korpus | Abdeckung |
|---|---|---|---|
| 1967 | 3 | 3 | hoch |
| **1968** | **49** | 59 | **~83 %** |
| **1969** | **132** | 206 | **~64 %** |
| 1970 | 2 | 109 | 2 % |
| 1971 | 4 | 262 | 2 % |
| 1972 | 10 | 665 | 1,5 % |
| 1973 | 19 | 598 | 3 % |

**1968 und 1969 sind nahezu erschlossen, der Rest praktisch gar nicht.** Das Feld beginnt überall mit „u.a.:" — es ist erklärtermaßen eine Auswahl, keine Vollständigkeitsangabe.

Für uns heißt das: Das teuer geplante Gold-Set (50–60 handannotierte Segmente, zwei bis drei Stunden zu zweit) **existiert bereits** — mit 181 Einträgen für 1968/69, geschrieben von Archivarinnen am physischen Original. Das ist qualitativ besser als alles, was wir in einem Nachmittag herstellen könnten.

### Zuordnungstest

Ein einfacher Abgleich der 49 Titel von 1968 gegen die 59 Segmente von Band 002 (Wortabdeckung des Titels im Segmenttext) ordnet **alle 49 zu**. Zwei Vorbehalte: Kurze Titel erzeugen Fehltreffer, und die Zuordnung ist noch nicht eindeutig — mehrere Titel landen auf demselben Segment. Ein belastbarer Abgleich braucht seltene Wörter stärker gewichtet und eine Eindeutigkeitsbedingung.

**Und genau das Nicht-Eindeutige ist der zweite Fund:** Auf Segment 10 (Seiten 14–23) entfallen **sechs** verschiedene Archivtitel — „LSD SHB SDS: Dokumentation, Rektor Mayer sorgt für Ordnung", „SHB: Offener Brief an Rektor Mayer", „AStA-Info: Der AStA stellt fest", „AStA: Erklärung des AStA", „AStA: Öffentliche Erklärung des AStA", „Demokratische Mitte: VDS". Das ist unabhängige Bestätigung dafür, dass in diesem Segment mindestens fünf Schnitte fehlen. **Das Findmittel liefert damit für 1968/69 eine externe Prüfinstanz für die Segmentierung** — genau die unabhängige Wahrheit, die dem Projekt bisher fehlt (siehe `kontext-splitting.md`, Abschnitt 8).

### Eine OCR-Korrektur nebenbei

Das Findmittel schreibt „Emil Franzel und **Franz Mayer**", unser OCR liest „EMIL FRANZEL UND FRANZ **BAYER**". Da Rektor Franz Mayer die zentrale Figur der Regensburger Auseinandersetzungen von 1968 ist (in der Keyness-Liste steht `mayer (77)` als das Wort des Jahres 1968), ist die Archivfassung mit hoher Wahrscheinlichkeit richtig und die OCR hat B/M verwechselt. Die 219 Titel sind also auch eine kleine Referenz für OCR-Fehler bei Eigennamen.

## 5. Bestandsgeschichte: Provenienzangaben für den Methodenteil

Der Fließtext im Bestandssatz beantwortet Fragen, die wir sonst offenlassen müssten:

* Die Sammlung wurde **1968 von der Universitätsbibliothek angelegt** und 2004 ans Universitätsarchiv übergeben. Der 1967er-Bestand ist also rückwirkend zusammengetragen — das erklärt, warum Band 001 nur 13 Seiten hat, und mahnt zur Vorsicht bei jeder Aussage über 1967.
* Verzeichnet wurde in Etappen 2007, 2008 und 2011 — was die extrem ungleiche Tiefe von `St_Entha` erklärt.
* **„Von Flugblättern wurden in der Regel nicht mehr als drei Exemplare archiviert. Doppelexemplare wurden teilweise behalten, insbesondere für Ausstellungszwecke, um auch die Rückseiten zeigen zu können."** Das erklärt die Doppelstücke, die uns in der Konkordanz aufgefallen sind (dasselbe Blatt zweimal in Band 013) — sie sind gewollt, kein Digitalisierungsfehler.
* Im Juli 2008 kamen 23 Ordner mit Flugschriften 1967–1995 vom **Studentenwerk** hinzu. Der Bestand ist also nicht aus einer Hand gewachsen, was Zusammensetzungseffekte über die Jahre erwartbar macht — relevant für die Kontrollrechnung zum Frauen-Befund.
* Verwandte Bestände: **Rep. 125 Universitätszeitungen** und **Rep. 159 Flugblattsammlung Werner Chrobak**. Beide sind Kandidaten für den Referenzkorpusvergleich aus `analyseplan.md`, D1 — und Rep. 159 wäre eine zweite, unabhängige Regensburger Flugblattüberlieferung.

## 6. Was sich dadurch am Plan ändert

| Bisher geplant | Neu |
|---|---|
| Gold-Set von Hand erstellen (2–3 h zu zweit) | **entfällt für 1968/69** — 181 Archivtitel nutzen; Handarbeit nur noch für 1970–1973 |
| Kanonisierung per LLM-Durchlauf über alle Namen | **entfällt weitgehend** — Normdatei aus `St_Darin` aufbauen und durchsehen |
| Segmentierung nur intern doppelt annotieren | zusätzlich **extern prüfen** an den 181 Titeln von 1968/69 |
| Digitalisierung als vollständig annehmen | **Vz 15 fehlt** — nachfragen und dokumentieren |

Reihenfolge, die ich daraus ableite:

1. `organizations.seed.json` von Hand durchsehen → `organizations.json` (ein bis zwei Stunden, ersetzt einen ganzen geplanten Arbeitsschritt).
2. Abgleich Archivtitel ↔ Segmente für Band 002 und 003 sauber implementieren (seltene Wörter gewichten, eindeutige Zuordnung erzwingen). Ergebnis: ein geprüftes Gold-Set **und** eine Fehlerliste für die Segmentierung von 1968/69.
3. Metadaten-Extraktion mit `prompt_v2` auf Band 002 laufen lassen und **gegen die 49 Archivtitel messen** — das ist die Zahl für den Methodenteil, ohne eigene Annotationsarbeit.
4. Beim Archiv nach Vz 15 fragen.

## 7. Grenzen

* Nur jahresgenaue Laufzeiten — für die Datumsauflösung (`analyseplan.md`, Abschnitt 2) hilft das Findmittel nicht.
* Keine Digitalisat-Verknüpfung, keine Blattzählung je Einheit, also auch keine Sollzahl, gegen die wir unsere Segmentzahl prüfen könnten.
* `St_Entha` ist eine Auswahl („u.a."). Ein Blatt, das dort fehlt, fehlt nicht im Karton. Als Gold-Set ist die Liste damit für **Precision** brauchbar (steht der Titel drin, muss er auch bei uns auftauchen), nicht aber für **Recall** im strengen Sinn.
* Die Titel sind archivarische Kurzfassungen, nicht immer der Wortlaut des Blattkopfs. Beim Messen gegen unsere Extraktion also unscharf vergleichen und `title_type` im Blick behalten.
