# Segmentierungsfehler

Sammelliste bekannter Fehler in den Seitenunterteilungen
(`data/raw/<Band>/<stem>.segments.json`). Behoben wird im
`flugblatt_splitter/`, hier wird nur gesammelt und abgehakt.
Hintergrund und Detektor: [kontext-splitting.md](kontext-splitting.md).

## Eintragen

- **Seitenbereiche sind der Schlüssel, nicht Segment-IDs.** Jede Korrektur
  nummeriert die folgenden Segmente um. Die Segment-ID steht nur zur
  Orientierung dabei, mit Stand der `segments.json` zum Zeitpunkt des Eintrags.
- **Art:** `fehlender Schnitt` (ein Segment enthält mehrere Flugblätter) oder
  `überflüssiger Schnitt` (ein Flugblatt ist auf mehrere Segmente verteilt).
- **Status:** `offen` → `verdacht` (Beleg unsicher, erst prüfen) → `behoben`
  (mit Datum). Behobene Einträge bleiben stehen, damit nachvollziehbar ist,
  was sich geändert hat.
- **Quelle:** woher der Hinweis kommt, z. B. `segmentation_hints` eines
  Metadaten-Laufs (`pipelines/04_metadata/extract_metadata_v2.py`),
  `_foreign_blocks` (LLM zitiert Blöcke einer Nachbarseite),
  Findmittel-Abgleich, `detect_missing_cuts.py` oder Sichtprüfung.

Nach jeder Korrektur in einem Band: Metadaten für diesen Band mit `--fresh`
neu extrahieren. Die Checkpoints (`*.partial.jsonl`) sind nach Segment-ID
geschlüsselt und passen nach dem Umnummerieren nicht mehr.

## Prüfliste über alle Bände

[segmentgrenzen.tsv](segmentgrenzen.tsv), erzeugt mit
`python pipelines/01_pdf/check_boundaries.py` (Stand 29.09.2026: 254
Verdachtsfälle in 14 Bänden, 155 fehlende und 99 überflüssige Schnitte).
Die Durchsichten und ihre Ergebnisse stehen in
[segmentierung-pruefung.md](segmentierung-pruefung.md) (Durchgang 1 am
29.09.2026: 77 Fälle entschieden, 30 übernommen).

Das Skript bewertet jeden Seitenübergang danach, ob die Seite wie ein
Blattanfang oder wie eine Fortsetzung aussieht, und meldet Widersprüche zur
vorhandenen Segmentierung. Die Gewichte sind an der vorhandenen
Segmentierung gemessen (wie viel häufiger ein Merkmal auf Anfangsseiten
steht als auf Folgeseiten):

| Merkmal | spricht für | Faktor |
|---|---|---|
| Eingangsstempel des Archivs | Anfang | 20 |
| Datum in der Kopfzeile | Anfang | 9 |
| Impressum/Verantwortlich-Zeile am Ende der Vorseite | Anfang | 6 |
| Kopfleiste („LSD - LSD - LSD“) | Anfang | 5 |
| Seitenzahl 2–19 als Kopf- oder Fußzeile | Fortsetzung | 6 |
| Trennstrich, „b.w.“, „Fortsetzung“ | Fortsetzung | 3–7 |

Dazu Hinweise auf ganze Segmente: mehrere Findmittel-Titel, Text eines
anderen Blatts enthalten (`find_copies.py`), Nachbarseiten-Zitate in
mindestens zwei Metadaten-Läufen.

**Spalte `stufe`** (nach einer Stichprobe von 30 Fällen):

- `sicher` (11): mehrere unabhängige Signale, fast immer echt, z. B. Nr. 004
  S. 215|216 und 232–236 (Impressum, dann Stempel und neue Kopfleiste).
- `wahrscheinlich` (61): Stempel, Kopfleiste, Kopfzeilendatum oder
  Findmittel allein, etwa drei von vier echt.
- `prüfen` (182): Impressum, Seitenzahl oder Metadaten allein, etwa jeder
  zweite echt.

Typische Fehlalarme: Pressespiegel (jede Seite mit Datum und Quelle),
Kalenderseiten, Hefte mit Impressum auf der ersten Seite.

**Richtlinienfragen, die die Liste nicht entscheidet** (siehe
[kontext-splitting.md](kontext-splitting.md), Offene Fragen 2 und 3):

- Rückseite mit eigenem Kopf nach „b.w.“ (z. B. Nr. 013 S. 183|184, AStA-Info
  mit zwei Beiträgen): ein Blatt oder zwei?
- Mehrseitige Hefte (Nr. 010 „rcds aktuell“, „Studentenservice“): ein
  Dokument oder einzelne Beiträge?
- Pressespiegel: eine Sammlung oder einzelne Artikel?

Der ältere `detect_missing_cuts.py` sucht nur fehlende Schnitte über
Kopfzeilen; seine Signale stecken hier mit drin.

## Liste

| Band | Seiten | Seg.-ID | Art | Befund | Quelle | Status |
|---|---|---|---|---|---|---|
| Nr. 002 (1968) | 81 \| 82 | 56, 57 | überflüssiger Schnitt | S. 82 ist die Fortsetzung von S. 81 („Lehrstühlereien im Fachbereich …“): Kopfzeile „-2-“, Text setzt mitten im Gedankengang ein („Dagegen ließe sich …“). Richtig: ein Segment S. 81–82. | `segmentation_hints` + `_foreign_blocks` (82-8 bis 82-12) in `0118_0002.metadata.claude-blockids3.json`; Sichtprüfung 28.09.2026 | behoben 29.09.2026 |
| Nr. 010 (1973) | 5–6 \| 7–10 \| 11–13 \| 14 | 4, 5, 6, 7 | überflüssiger Schnitt | Vermutlich eine Broschüre „Studentenservice III WS 73/74“ des RCDS: Die Segmente 5–7 zitieren alle das Impressum auf S. 5 (Block 5-10) als Herausgeberbeleg; S. 7–10 enthalten Anzeigen (Stadtwerke), S. 14 die Kandidatenliste. Artikel könnten aber auch bewusst einzeln verzeichnet sein. | `_foreign_blocks` in `0118_0010.metadata.claude-blockids2.json` (Probelauf, 20 Segmente); 28.09.2026 | verdacht |
| Nr. 010 (1973) | 72–75 \| 76–80 \| 81 \| 82 \| 83 \| 84–85 | 30–35 | überflüssiger Schnitt | Vermutlich eine Ausgabe „rcds aktuell“: Logo auf S. 72, S. 81 beginnt mit „AKTUELLES - Fortsetzung“; die Segmente 30–34 verweisen jeweils auf die Folgeseite. | `segmentation_hints` in `0118_0010.metadata.claude-blockids2.json`; 28.09.2026 | verdacht |
| Nr. 010 (1973) | 138–151 \| 152–155 | 53, 54 | überflüssiger Schnitt | S. 152 beginnt mitten im Satz („…ausbringen von Examensklausuren gehörte genauso…“), Segment 54 hat deshalb nur ein Textfragment als Titel. | Sichtung Metadatenlauf; 28.09.2026 | verdacht |
| Nr. 010 (1973) | 88 \| 89 \| 90 | 37, 38, 39 | überflüssiger Schnitt | Drei Seiten Kandidatenlisten zu Fachbereichs- und Fachschaftsratswahlen mit fast gleichem Titel; Segment 37 verweist auf die Folgeseite. Könnten ein mehrseitiges Blatt sein. | `segmentation_hints`; 28.09.2026 | verdacht |
| Nr. 002 (1968) | 14–23 | 10 | fehlender Schnitt | Sechs verschiedene Findmittel-Titel fallen auf dieses Segment (u. a. „SHB: Offener Brief an Rektor Mayer“, „AStA: Erklärung des AStA“, „Demokratische Mitte: VDS“). Vermutlich fünf fehlende Schnitte, möglicherweise aber eine zusammengeheftete Dokumentation. | Findmittel-Abgleich, siehe [findmittel-auswertung.md](findmittel-auswertung.md) | verdacht |
