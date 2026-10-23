# Flugblätter der Universität Regensburg – Arbeits-Repository

Arbeits-Repository des Praxisseminars im Sommersemester 2026. Das Projekt hat
die Flugblattsammlung 1967–1973 des Universitätsarchivs Regensburg (Rep. 118)
per OCR erschlossen, in einzelne Flugblätter getrennt, mit Metadaten versehen
und nach Themen geordnet.

Hier liegen die Versuche und Auswertungen bis Anfang Oktober 2026. Ab dem 24.09.
ging die Arbeit in das Repository der Anwendung über, das auch die Dokumentation
enthält: <https://github.com/woidveit02/UR_LeafletArchive>. Dieses Repository
wird nicht weiter gepflegt. Es enthält die Skripte zu den Auswertungen, auf die
der Bericht verweist (Kap. 3, 5, 7 und 12.6).

## Inhalt

| Ordner | Inhalt |
|---|---|
| `pipelines/01_pdf/` | TIFF-Scans zu PDF, Abgleich mit dem Findmittel, Prüfliste der Segmentgrenzen, Suche nach Mehrfachexemplaren (`find_copies.py`) |
| `pipelines/02_ocr/` | Skripte für die getesteten OCR-Systeme (Datalab, Mistral, Gemini, OpenRouter, GLM-OCR) |
| `pipelines/03_eval/` | Goldstandard und CER-Messung, Übersicht der OCR-Modelle (`ocr-modelle-uebersicht.md`), Herkunft der Testseiten (`testkorpus-seiten.csv`) |
| `pipelines/04_metadata/` | Metadaten per LLM, Belegprüfung, Abgleich mit dem Register; `prompt_versions/` enthält die Prompt-Fassungen der Runden 1–12 |
| `pipelines/04_topic/` | erster Themenlauf (BERTopic), Anleitung in `SETUP.md` |
| `pipelines/06_analysis/` | N-Gramme (heute `scripts/ngrams.py` in der Anwendung) |
| `ocr_viewer/` | OCR-Ausgaben neben dem Scan vergleichen, Goldstandard korrigieren |
| `flugblatt_splitter/` | Bände von Hand in Flugblätter trennen |
| `docs/korpus/` | Schemata, Beispieldaten, Findmittel-Abgleich, Notizen zur Segmentierung |
| `test_set_generator.py` | Ziehung des Testkorpus (100 Seiten) |

Scans, OCR-Ausgaben und Metadatenläufe sind nicht im Repository. Die Skripte
erwarten sie unter `data/raw/<Band>/` und `data/test_set/`.

Die Branches `dev-ner` und `dev-topic-naming` enthalten die ersten Versuche zu
Named Entity Recognition und zur Benennung der Themen.

## Einrichten

```sh
pip install -e .            # optional: ".[eval]" für dinglehopper
```

API-Schlüssel gehören in eine `.env` im Wurzelordner (Namen in
`pipelines/02_ocr/README.md`). Splitter und OCR-Viewer haben eigene Anleitungen
in ihren Ordnern.

## Team

Veit Korpies, Felix Lindner und Sebastian Simbeck, Praxisseminar im
Masterstudiengang Medieninformatik. Die Flugblätter gehören dem
Universitätsarchiv Regensburg; Korpus und Metadaten dürfen laut Archiv
veröffentlicht werden, auch mit Personennamen.
