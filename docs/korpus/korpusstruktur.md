# Korpusstruktur Flugblattsammlung UR — Vorschlag

Stand: 2026-08-20 · Status: Diskussionsgrundlage für das Team

Ziel: eine Struktur, in der pro Flugblatt **Titel, Datum und ausstellende Organisation** liegen — und die es aushält, dass die Seitenunterteilung (Splitting) noch nicht fehlerfrei ist.

---

## 1. Ausgangslage (gemessen an Nr. 002 / 1968)

| Beobachtung | Zahl |
|---|---|
| Seiten im Band `0118_0002.pdf` | 85 |
| Segmente in `0118_0002.segments.json` (fein) | 59 (45× 1 Seite, 12× 2 Seiten, je 1× 6 und 10 Seiten) |
| Segmente in `0118_0002.segments.auto.json` (Datalab) | 13 (bis zu 25 Seiten lang) |
| Schnittpunkte, die beide Verfahren teilen | 13 von 13 |
| Schnittpunkte, die nur die feine Segmentierung hat | 46 |
| Schnittpunkte, die **nur** die Auto-Segmentierung hat | 0 |

Das ist der wichtigste Befund für die Splitting-Frage: die Auto-Segmentierung **erfindet keine falschen Schnitte, sie übersieht welche**. Fehler sind also fast ausschließlich *fehlende* Schnitte (zu große Segmente), nicht *falsche*. Das hat Konsequenzen fürs Datenmodell (Abschnitt 7).

Zweiter Befund: die OCR-Blöcke enthalten bereits starke Grenzsignale, die bisher niemand nutzt. Datalab liefert `PageHeader`-Blöcke, und die sehen so aus:

```
S. 3  →  "- Seite 2 -"        (Fortsetzungsseite)
S. 4  →  "LSD - LSD - LSD - LSD - LSD - ..."   (Kopfleiste = Beginn eines neuen Blatts)
S. 6  →  "23. 7. 68"           (Datum im Kopf = Beginn)
S. 15 →  "- 2 -"               (Fortsetzungsseite)
```

Ausgezählt über den ganzen Band:

| Signal | Seiten | davon tatsächlich Segmentbeginn |
|---|---|---|
| Kopfzeile ist eine Seitenzahl > 1 | 16 | 1 (Seite 82 — vermutlich selbst ein Splitting-Fehler) |
| Kopfzeile ist eine Sigel-Leiste (`LSD - LSD - …`) | 3 | 3 |
| Kopfzeile enthält ein Datum | 4 | 3 |

Eine Kopfzeile „- 2 -" ist also ein nahezu sicheres Signal *gegen* einen Segmentbeginn, eine Sigel-Leiste ein sehr gutes Signal *dafür*. Beides kostet nichts, es steht schon in den OCR-Daten.

Drittens: `pipelines/04_metadata/extract_metadata.py` extrahiert bereits genau die drei Felder (`title`, `issuing_org`, `date_text`/`date_iso`) und schreibt sie als Sidecar. Der Vorschlag hier baut darauf auf und ersetzt es nicht — er gibt dem Ergebnis nur ein tragfähigeres Zuhause als `segments.json`, in dem `title` heute ein einzelner String ist, in den `extract_metadata.py --install` die Organisation mit `" - "` hineinfaltet. Das ist beim Zurücklesen nicht mehr sauber trennbar und sollte nicht der kanonische Zustand werden.

---

## 2. Grundentscheidung: drei Ebenen, die Seite als Atom

```
Band (Jahrgangs-PDF)  0118_0002.pdf, "Nr. 002 (1968)", 85 Seiten
        │
        ├── Seite   0118_0002#p0006   ← trägt den OCR-Text. Unveränderlich.
        │           0118_0002#p0007
        │
        └── Flugblatt (Dokument)  0118_0002_0006  ← trägt die Metadaten.
                                                     Verweist auf Seiten. Veränderlich.
```

**Der Text liegt auf der Seite, nicht im Dokument.** Ein Dokument ist nur eine Gruppierung von Seiten plus Metadaten. Das ist die eine Entscheidung, an der alles andere hängt:

* Ein korrigiertes Splitting ändert **nur die Zuordnung Seite → Dokument**. Kein Re-OCR, keine Textduplikate, keine Migration.
* Analysen, die keine Dokumentgrenzen brauchen (N-Gramme, Vokabular über die Zeit, OCR-Qualität), laufen auf der Seitenebene — die ist schon jetzt vollständig und korrekt. Ihr müsst mit diesen Analysen **nicht** auf das Splitting warten.
* Analysen, die Grenzen brauchen (Anzahl Blätter pro Organisation, Topic Model pro Dokument), laufen auf der Dokumentebene und tragen deren Unsicherheit mit — sichtbar, weil jedes Dokument seinen Segmentierungsstatus mitführt.

Wenn Text stattdessen ins Dokument kopiert würde, wäre jede Splitting-Korrektur eine Datenmigration mit Verlustrisiko. Bei ~2 000–3 000 Blättern und einem Splitting, das sich noch bewegt, ist das der teure Weg.

---

## 3. Dateilayout und Formatwahl

### Vorschlag

```
data/corpus/
  pages.jsonl            # 1 Zeile pro Seite       (kanonisch, generiert)
  documents.jsonl        # 1 Zeile pro Flugblatt   (kanonisch, generiert)
  organizations.json     # Normdatei Organisationen (kanonisch, HAND-gepflegt)
  corrections.jsonl      # manuelle Überschreibungen (kanonisch, HAND-gepflegt)
  corpus.meta.json       # Build-Info: Zeitpunkt, OCR-Engine, Modelle, Zählungen
  build/                 # abgeleitet, .gitignore
    documents.parquet
    documents.csv        # für Kolleg*innen ohne Python
    corpus.db            # SQLite fürs Explorations-Tool
```

`data/raw/**` bleibt wie es ist: PDF, OCR-JSON, `segments.json`. Das Korpus ist ein **Build-Artefakt** daraus (siehe Abschnitt 7.3).

### Warum JSONL und nicht …

| Option | Dafür | Dagegen | Rolle |
|---|---|---|---|
| **JSONL** (eine Zeile pro Record) | git-diffbar (eine geänderte Zeile = ein geändertes Blatt), streambar, verschachtelte Felder ohne Schema-Kopfstände, kein Server, keine Extra-Abhängigkeit | keine Joins, keine Indizes; Datei muss zum Filtern durchlaufen werden | **kanonisch** |
| SQLite | echte Joins, Indizes, ideal als Backend fürs Explorations-Tool, eine Datei | Binärformat → in git nicht diffbar und bei drei parallel Arbeitenden praktisch nicht mergebar; Schemaänderungen brauchen Migrationen | **abgeleitet** (aus JSONL gebaut) |
| Parquet | schnell, typisiert, pandas/polars-nativ, klein | binär, nicht editierbar, verschachtelte Felder umständlich | **abgeleitet** |
| Eine JSON-Datei pro Blatt | sehr archivnah, gut zitierbar, einzelne Datei = einzelnes Objekt | ~3 000 Kleindateien; jede Splitting-Korrektur legt Dateien an und löscht welche → unübersichtliche git-Historie genau an der Stelle, die sich am meisten bewegt | optionaler Export |

Bei eurer Größenordnung (~3 000 Dokumente, ~10 000 Seiten, Volltext im niedrigen zweistelligen MB-Bereich) passt alles bequem in den Arbeitsspeicher. Performance ist kein Entscheidungskriterium — **Nachvollziehbarkeit im Team ist es.** Deshalb: Wahrheit im Textformat, Komfort im Binärformat, und das Binärformat ist jederzeit wegwerfbar.

---

## 4. Der Dokument-Record

Kommentierter Beispiel-Record (echte Daten, Nr. 002, Seiten 6–7):

```jsonc
{
  "schema_version": "1.0",
  "doc_id": "0118_0002_0006",           // lesbar, sortierbar: Band + erste Seite
  "doc_uid": "9c1d…",                   // UUID, überlebt Neuschnitte (s. 7.4)
  "supersedes": [],                     // UUIDs, aus denen dieser Record hervorging

  "source": {
    "volume_id": "0118_0002",
    "volume_label": "Nr. 002 (1968)",
    "source_pdf": "0118_0002.pdf",
    "collection_year": 1968,            // aus dem Ordnernamen, immer bekannt
    "start_page": 6, "end_page": 7, "n_pages": 2,
    "page_ids": ["0118_0002#p0006", "0118_0002#p0007"]
  },

  "title": {
    "text": "Emil Franzel und Franz Bayer. Oder: Wie man das Ansehen der Universität Regensburg ruiniert",
    "verbatim": "EMIL FRANZEL UND FRANZ BAYER\nOder : Wie man das Ansehen der Universität Regensburg\nruiniert",
    "type": "original",                 // original | supplied | incipit
    "source": "llm"                     // llm | human | heuristic
  },

  "date": {
    "text": "23. 7. 68",                // wie gedruckt
    "edtf": "1968-07-23",               // normalisiert
    "earliest": "1968-07-23",           // Bereichsgrenzen für Zeitfilter
    "latest":   "1968-07-23",
    "precision": "day",                 // day | month | year | unknown
    "type": "issued",                   // issued | event | mentioned | undated
    "basis": "printed",                 // printed | content | volume | external
    "source": "llm"
  },

  "issuers": [
    { "surface": "LSD - LSD - LSD - LSD - LSD",   // wie im Blatt
      "org_id": "lsd",                             // Normdatei-Schlüssel
      "role": "issuer",                            // issuer | signatory | mentioned
      "source": "llm" }
  ],

  "language": "de",
  "doc_type": "flugblatt",              // flugblatt | offener_brief | einladung | broschuere | zeitschrift | protokoll | unklar
  "topics": [],                         // später aus dem Topic Model, jetzt leer

  "content_hash": "sha256:2f7a…",       // Hash des Volltexts → Cache-Key + Änderungsdetektor
  "text_stats": { "n_chars": 5117, "n_words": 771 },

  "segmentation": {
    "status": "auto",                   // auto | flagged | reviewed | confirmed
    "method": "splitter_manual",        // datalab_auto | splitter_manual | heuristic
    "boundary_confidence": 0.86,
    "flags": [],                        // s. Tabelle 7.5
    "reviewed_by": null, "reviewed_at": null
  },

  "provenance": {
    "ocr":       { "engine": "datalab-chandra-2", "mode": "accurate", "run": "2026-08-17" },
    "extractor": { "model": "gemini-3.5-flash", "extracted_at": "2026-08-20T09:14:02Z" },
    "verified_fields": []               // z.B. ["date","issuers"] nach Sichtprüfung
  },

  "notes": "",
  "created": "2026-08-20T09:14:02Z",
  "updated": "2026-08-20T09:14:02Z"
}
```

### Warum die drei Kernfelder so und nicht als einfache Strings

**Titel.** Viele Blätter haben keine Überschrift; die Auto-Segmentierung hat das bisher mit erfundenen englischen Zusammenfassungen gefüllt („Political Protest Flyer - University of Regensburg 1968"). Das ist im Korpus gefährlich, weil man später nicht mehr sieht, was auf dem Blatt stand und was das Werkzeug dazuerfunden hat. Deshalb `type`:

* `original` — die Überschrift des Blatts, wörtlich (`verbatim` hält die OCR-Fassung mit Zeilenumbrüchen, `text` die geglättete Anzeigeform).
* `supplied` — kein Titel vorhanden, redaktionell vergeben; Anzeigekonvention `[Streikaufruf zu den Notstandsgesetzen]` in eckigen Klammern (bibliothekarische Konvention für Fremdtitel).
* `incipit` — Notbehelf: die ersten ~10 Wörter des Textes. Nie erfunden, immer belegbar.

**Datum.** Das ist das Feld mit den meisten Sonderfällen, und ein einzelner ISO-String verliert genau die Information, die man später braucht:

| Fall aus Nr. 002 | text | edtf | precision | type | basis |
|---|---|---|---|---|---|
| „23. 7. 68" im Kopf (S. 6) | `23. 7. 68` | `1968-07-23` | day | issued | printed |
| „STREIK … am Mittwoch, 29. Mai 1968!" (S. 1) | `29. Mai 1968` | `1968-05` | month | event | content |
| Wahlaufruf „25. – 27.11.1968" (S. 2) | `25.-27.11.1968` | `1968-11-25/1968-11-27` | day | event | content |
| gar nichts datiert | `""` | `1968` | year | undated | volume |

`type: "event"` ist wichtig: ein Streikaufruf für den 29. Mai wurde *vor* dem 29. Mai verteilt — das Datum ist eine Obergrenze, kein Erscheinungsdatum. Wer das nicht trennt, baut sich später eine Zeitreihe, die systematisch danebenliegt. `earliest`/`latest` machen jede dieser Angaben ohne Sonderlogik filterbar: „alle Blätter aus dem Sommersemester 1968" ist ein simpler Bereichsvergleich, auch bei jahresgenauen Daten. **Kein Datum ist unbekannt** — dank Ordnername ist mindestens das Jahr immer belegt, `basis: "volume"` sagt ehrlich, woher es kommt.

**Organisation.** Zwei Gründe für Array plus Normdatei statt eines Strings:

* Blätter werden gemeinsam herausgegeben (S. 14 im Band trägt den Kopf `LSD - SHB - SDS - LSD - SHB - SDS`). Ein String erzwingt hier eine willkürliche Entscheidung.
* Dieselbe Gruppe erscheint in Dutzenden Schreibweisen (`LSD`, `lsd`, `L.S.D.`, `Liberaler Studentenbund Deutschlands`), teils OCR-verunreinigt. Ohne kontrolliertes Vokabular ist „wie viele Blätter kamen vom SDS?" nicht beantwortbar. `surface` bewahrt das Gedruckte, `org_id` macht es zählbar.

`organizations.json` ist eine kleine, **von Hand gepflegte** Datei — vermutlich 30–60 Einträge für die ganze Sammlung:

```json
[
  { "org_id": "lsd",
    "name": "LSD",
    "full_name": "Liberaler Studentenbund Deutschlands",
    "type": "studentische_gruppe",
    "variants": ["LSD", "lsd", "L.S.D.", "Liberaler Studentenbund"],
    "gnd_id": "",
    "notes": "in Regensburg bis ca. 1970 aktiv" }
]
```

Das Angleichen (`surface` → `org_id`) läuft automatisch über die `variants` plus unscharfen Abgleich; was nicht zugeordnet werden kann, bleibt `org_id: null` und landet in einer Liste unaufgelöster Schreibweisen, aus der die Normdatei wächst. Wichtig: **nichts wird stillschweigend zusammengeworfen** — unaufgelöst ist ein sichtbarer Zustand, kein Datenverlust.

---

## 5. Der Seiten-Record

```jsonc
{
  "page_id": "0118_0002#p0006",
  "volume_id": "0118_0002",
  "page_no": 6,
  "doc_id": "0118_0002_0006",           // aktuelle Zuordnung — das Feld, das sich beim Neuschnitt ändert
  "position_in_doc": 1,

  "text": "23. 7. 68\nLSD- LSD - LSD-LSD- …",
  "blocks_ref": { "file": "0118_0002/0118_0002.json", "child_index": 5 },  // Blöcke/Boxen nicht duplizieren

  "page_header": "23. 7. 68",
  "boundary_signals": {                 // vorberechnet, s. 7.5
    "header_page_number": null,
    "header_is_masthead": true,
    "header_has_date": true,
    "first_block_type": "PageHeader",
    "start_score": 0.9
  },
  "ocr": { "engine": "datalab-chandra-2", "mode": "accurate",
           "run": "2026-08-17", "inference_failed": false }
}
```

`blocks_ref` statt eingebetteter Blöcke: die 85 Seiten von Nr. 002 haben allein 2 MB Blockdaten mit Polygonen. Die bleiben im Datalab-JSON, das Korpus zeigt nur darauf. Wer Boxen braucht (Explorations-Tool, spätere ALTO-Ausgabe), lädt sie gezielt nach.

`ocr.engine` pro Seite mitzuführen kostet nichts und rettet euch, sobald ein Band mit einer anderen Engine oder nachträglich neu erkannt wird — der Vergleich Chandra/Mistral steht ja noch aus.

---

## 6. Standards: was es gibt und was ich empfehle

| Standard | Was es ist | Was es euch bringt | Kosten |
|---|---|---|---|
| **Dublin Core** | 15 flache Felder (`title`, `creator`, `date`, `publisher`, `subject`, `language`, `identifier`, `source`, `rights`) | Lingua franca für Repositorien; nötig, wenn die UB die Sammlung je über OAI-PMH ausliefert | fast nichts: eine Zuordnungstabelle |
| **EDTF** (ISO 8601-2) | Datumssyntax für Unschärfe: `1968-11`, `1968-11-25/1968-11-27`, `1968-07~` (ungefähr), `1968-07-23?` (unsicher) | löst euer Datumsproblem exakt und ist maschinell parsebar | gering: ein Feld, eine Bibliothek (`edtf-validate`) |
| **TEI P5** | XML für Volltext *mit* editorischer Auszeichnung; Metadaten im `teiHeader` | Standard der Digital Humanities; richtig, wenn der **Text selbst** ediert/annotiert und publiziert werden soll | hoch: XML-Werkzeugkette, mühsam für die Analyse in Python |
| **METS/ALTO** | Digitalisierungs-Container + Layout/OCR mit Koordinaten pro Wort | das, womit Bibliotheken Digitalisate übernehmen; ihr habt mit den Datalab-Blöcken faktisch schon ALTO-nahe Daten | mittel bis hoch, und nur sinnvoll bei tatsächlicher Übergabe |

**Empfehlung: pragmatisches JSON + EDTF fürs Datum + dokumentiertes Dublin-Core-Mapping. TEI und METS jetzt nicht.**

Begründung: TEI und METS sind *Austauschformate*. Man erzeugt sie am Ende aus sauberen Daten — man arbeitet nicht darin. Wer in TEI anfängt, während das Splitting noch wackelt, redigiert XML statt Inhalte. Das DC-Mapping dagegen kostet eine Tabelle und hält die Tür zu beiden offen:

| unser Feld | Dublin Core |
|---|---|
| `title.text` | `dc:title` |
| `issuers[].surface` | `dc:creator` (bzw. `dc:publisher`) |
| `date.edtf` | `dc:date` |
| `language` | `dc:language` |
| `doc_id` | `dc:identifier` |
| `source.source_pdf` + Seitenbereich | `dc:source` |
| `doc_type` | `dc:type` |

Solange die Blockkoordinaten im Datalab-JSON erhalten bleiben (siehe `blocks_ref`), bleibt auch ein späterer ALTO-Export möglich. Das ist der eigentliche Punkt: **nichts wegwerfen, was ein Standard später bräuchte** — und nicht heute schon einen Standard bedienen, den niemand angefordert hat.

---

## 7. Umgang mit dem noch unsicheren Splitting

Die Kernidee: **das Splitting nicht als Vorbedingung behandeln, sondern als Datenfeld.** Es ist kein Zustand, den man erreicht, sondern eine Eigenschaft, die jedes Dokument mitführt und die sich verbessert.

### 7.1 Die Seite ist das Atom

Siehe Abschnitt 2. Ein Neuschnitt schreibt `pages.jsonl` in der Spalte `doc_id` um und baut `documents.jsonl` neu. Text, OCR-Provenienz und Blockdaten bleiben unberührt. Das ist der Unterschied zwischen „wir müssen das Korpus neu bauen" (Minuten) und „wir müssen das Korpus migrieren" (Tage plus Verlustrisiko).

### 7.2 Status statt Perfektion

`segmentation.status` mit vier Werten:

* `auto` — automatisch geschnitten, niemand hat hingesehen
* `flagged` — automatisch, aber mindestens ein Verdachtssignal (7.5)
* `reviewed` — ein Mensch hat die Grenzen gesehen und für plausibel gehalten
* `confirmed` — ein Mensch hat sie explizit bestätigt (das existierende `confirmed`-Feld im Splitter)

Jede Auswertung nennt, auf welcher Teilmenge sie beruht. Für die Arbeit heißt das konkret: grenzabhängige Ergebnisse werden **zweimal** gerechnet — einmal auf allem, einmal nur auf `confirmed`. Stimmen die Größenordnungen überein, ist das Ergebnis robust; weichen sie ab, habt ihr das selbst gefunden und könnt es benennen. Das ist dieselbe Logik wie bei eurer OCR-Fehlerrate: eine bekannte, bezifferte Unsicherheit ist wissenschaftlich sauber, eine unbekannte nicht.

### 7.3 Das Korpus ist ein Build-Artefakt, kein Arbeitsstand

```
data/raw/**/segments.json          (Hand + Splitter-UI)   ─┐
data/raw/**/<stem>.json  (OCR)                            ─┤
data/corpus/organizations.json     (Hand)                 ─┼─→  build_corpus.py  →  data/corpus/*.jsonl
data/corpus/corrections.jsonl      (Hand)                 ─┘
```

Regel: **In `documents.jsonl` wird nie von Hand editiert.** Korrekturen gehen in die Quellschicht — Grenzen in `segments.json` über die Splitter-UI, Metadaten in `corrections.jsonl`:

```json
{"doc_uid": "9c1d…", "field": "date", "value": {"edtf": "1968-07-23", "precision": "day", "type": "issued", "basis": "printed"}, "by": "vk", "at": "2026-08-21", "reason": "LLM hatte das Veranstaltungsdatum genommen"}
```

Der Build wendet Korrekturen zuletzt an und setzt `source: "human"` sowie `provenance.verified_fields`. Dadurch ist der Build **idempotent**: ihr könnt ihn nach jeder Splitting-Verbesserung neu laufen lassen, ohne je Handarbeit zu verlieren. Ohne diese Trennung passiert unweigerlich das Gegenteil — der erste Rebuild überschreibt drei Wochen Korrekturarbeit.

### 7.4 Identität über Neuschnitte hinweg

`doc_id` = `{Band}_{erste Seite}` ist lesbar und sortierbar, aber an die Startseite gebunden. Beim häufigsten Fehlerfall — ein zu großes Segment wird geteilt — behält das erste Teilstück seine Startseite und damit seine `doc_id`; nur die neuen Teile bekommen neue.

Für alles, was Korrekturen anhängt (`corrections.jsonl`, spätere Annotationen, Links aus dem Explorations-Tool), reicht das nicht. Deshalb zusätzlich `doc_uid` (UUID), mit dieser Übertragungsregel beim Rebuild:

> Für jedes neue Segment die Seitenmenge mit allen alten Segmenten desselben Bandes vergleichen (Jaccard-Ähnlichkeit). Beste Übereinstimmung ≥ 0,5 → alte `doc_uid` übernehmen. Sonst neue UUID vergeben und die alten UIDs in `supersedes` eintragen.

Ergebnis: Ein 23-Seiten-Segment, das in fünf Blätter zerfällt, verliert seine Korrekturen nicht — das größte Teilstück erbt die Identität, die anderen sind als Abkömmlinge erkennbar. Und `supersedes` macht die Geschichte nachvollziehbar, statt sie zu überschreiben.

### 7.5 Verdachtssignale — Prüfaufwand dorthin lenken, wo er wirkt

206 Segmente allein in Nr. 003 linear durchzusehen ist unattraktiv. Die folgenden Signale sind aus vorhandenen Daten berechenbar und ergeben eine Prioritätsreihenfolge (die Trefferzahlen sind an Nr. 002 gemessen):

| Flag | Regel | Belastbarkeit |
|---|---|---|
| `continuation_start` | Segment beginnt auf einer Seite, deren `PageHeader` eine Seitenzahl > 1 ist | sehr hoch — 16 solche Seiten im Band, 15 sind korrekt *keine* Segmentstarts |
| `masthead_inside` | eine Nicht-Erstseite trägt eine Sigel-Kopfleiste (`LSD - LSD - …`) oder ein Datum im Kopf | hoch — alle 3 Sigel-Seiten und 3 von 4 Datums-Seiten sind Segmentstarts; ein solcher Kopf mitten im Segment heißt: hier fehlt ein Schnitt |
| `long_segment` | `n_pages` über dem 95. Perzentil des Bandes | hoch bei dieser Sammlung — 45 von 59 Segmenten sind einseitig; ein 23-Seiten-„Flugblatt" ist fast sicher ein Bündel |
| `issuer_switch` | die Metadatenextraktion liefert für verschiedene Seiten desselben Segments verschiedene Organisationen | mittel |
| `date_jump` | mehr als ein gedrucktes Datum im Segment | mittel |
| `no_metadata` | Titel, Organisation und Datum alle leer | mittel — oft ein Zeichen, dass das Segment kein zusammenhängendes Dokument ist |
| `auto_disagreement` | Grenze existiert nur in einer der beiden Segmentierungen | niedrig als Einzelsignal, nützlich als Kombination |

Alles mit mindestens einem Flag bekommt `status: "flagged"`; die Splitter-UI kann danach sortieren. Zur Größenordnung, gemessen: Wendet man die ersten drei Flags auf die 59 Segmente von Nr. 002 an, werden **3 markiert** — Segment 10 (S. 14–23, `long_segment`), Segment 45 (S. 62–67, `masthead_inside` + `long_segment`) und Segment 57 (S. 82, `continuation_start`). Das sind genau die drei Stellen, die man sich ansehen würde. Auf das Auto-Splitting angewandt fällt entsprechend das 23-Seiten-Segment sofort auf.

Angesichts der Asymmetrie aus Abschnitt 1 (Auto-Schnitte sind fast immer richtig, es fehlen welche) sind `masthead_inside` und `long_segment` die beiden Flags, die die meisten echten Fehler finden.

### 7.6 Die Fehlerrate messen, nicht schätzen

Analog zu eurer OCR-Validierung: **ein Gold-Set für Grenzen.** Pro Jahrgang ~30 zufällige Seiten von Hand ansehen und für jede Seitengrenze notieren, ob dort ein Blattwechsel ist. Daraus:

* Boundary Precision / Recall / F1 für die Auto-Segmentierung
* dieselbe Zahl für die heuristisch nachgeschärfte Version — damit ist belegbar, ob die Signale aus 7.5 etwas bringen
* eine Zahl fürs Paper: „Die Dokumentgrenzen sind zu X % korrekt; grenzabhängige Auswertungen wurden zusätzlich auf der geprüften Teilmenge (n = …) validiert."

Der Aufwand ist ein Nachmittag und macht aus dem größten Schwachpunkt des Korpus eine dokumentierte Eigenschaft.

### 7.7 Jetzt anfangen, nicht warten

Die Metadatenextraktion (`04_metadata`) kostet wenige Cent pro Band und ist wiederholbar. Deshalb: **jetzt auf dem aktuellen Splitting laufen lassen.** `content_hash` (SHA-256 über den normalisierten Volltext des Segments) dient als Cache-Schlüssel — beim Rebuild nach einer Splitting-Korrektur werden nur Dokumente neu extrahiert, deren Text sich tatsächlich geändert hat. Ein Neuschnitt in Band 3 kostet dann nicht die Extraktion des ganzen Korpus, sondern die der betroffenen Segmente.

---

## 8. Migrationspfad

1. `organizations.json` anlegen — 15–20 offensichtliche Gruppen (LSD, SDS, SHB, RCDS, AStA, Studentenparlament, BDKJ, …) reichen zum Start; der Rest wächst aus den unaufgelösten Schreibweisen.
2. `pipelines/05_corpus/build_corpus.py` schreiben: liest `segments.json` + OCR-JSON + Metadaten-Sidecar + `corrections.jsonl`, schreibt `pages.jsonl` / `documents.jsonl` / `corpus.meta.json`, berechnet Signale und Flags.
3. `extract_metadata.py` auf Sidecar-Betrieb festlegen; `--install` (das Zurückschreiben in `segments.json` mit `"Org - Titel"`) nicht mehr verwenden — die Zusammenführung übernimmt der Build.
4. Build für Nr. 002 und Nr. 003 fahren, die Flag-Liste durchsehen, Erfahrungswerte für die Schwellwerte sammeln.
5. Gold-Set für Grenzen (7.6).
6. Erst danach die abgeleiteten Formate (Parquet/SQLite) und das Explorations-Tool darauf setzen.

Schritt 2 lässt sich als nächstes umsetzen, wenn das Datenmodell hier so trägt.

---

## 9. Offene Fragen fürs Team

1. **Bündel-Dokumente:** Ein AStA-Info mit acht Seiten ist ein Dokument — oder acht? Vorschlag: ein Dokument, `doc_type: "zeitschrift"`, und die Fragestellung entscheidet, ob solche Typen in eine Auswertung eingehen.
2. **Doppelstücke:** Wenn dasselbe Blatt in zwei Bänden liegt — eigener Record je Exemplar (archivisch korrekt) plus `duplicate_of`? Über `content_hash` automatisch auffindbar.
3. **Personen:** Unterzeichner*innen (`role: "signatory"`) mit aufnehmen oder erst mal weglassen? Datenschutzrechtlich unkritisch bei zeitgeschichtlichem Material, aber Pflegeaufwand.
4. **1967 (Nr. 001):** Bleibt der Jahrgang draußen (Folie 10), oder kommt er mit `collection_year: 1967` einfach mit ins Korpus und wird bei Bedarf gefiltert? Letzteres kostet nichts und lässt die Entscheidung offen.
