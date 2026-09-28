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

## Liste

| Band | Seiten | Seg.-ID | Art | Befund | Quelle | Status |
|---|---|---|---|---|---|---|
| Nr. 002 (1968) | 81 \| 82 | 56, 57 | überflüssiger Schnitt | S. 82 ist die Fortsetzung von S. 81 („Lehrstühlereien im Fachbereich …“): Kopfzeile „-2-“, Text setzt mitten im Gedankengang ein („Dagegen ließe sich …“). Richtig: ein Segment S. 81–82. | `segmentation_hints` + `_foreign_blocks` (82-8 bis 82-12) in `0118_0002.metadata.claude-blockids3.json`; Sichtprüfung 28.09.2026 | offen |
| Nr. 002 (1968) | 14–23 | 10 | fehlender Schnitt | Sechs verschiedene Findmittel-Titel fallen auf dieses Segment (u. a. „SHB: Offener Brief an Rektor Mayer“, „AStA: Erklärung des AStA“, „Demokratische Mitte: VDS“). Vermutlich fünf fehlende Schnitte, möglicherweise aber eine zusammengeheftete Dokumentation. | Findmittel-Abgleich, siehe [findmittel-auswertung.md](findmittel-auswertung.md) | verdacht |
