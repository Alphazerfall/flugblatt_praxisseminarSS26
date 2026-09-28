# Metadaten-Extraktion: wie ich vorgehen würde

Stand 20.08.2026. Bezieht sich auf `pipelines/04_metadata/extract_metadata.py`.

---

## 0. Ausgangslage, gemessen

Die Segmentierung liegt inzwischen für alle 14 Bände vor:

| | |
|---|---|
| Segmente gesamt | **1 902** |
| davon `confirmed: true` | 835 (Bände 001, 004, 009–014) |
| Bände ohne ein einziges `confirmed` | 002, 003, 005, 006, 007, 008 |

> **Hinweis:** `extract_metadata.py` liest `seg_doc["segments"]`, also *alle* Segmente — nicht nur die bestätigten. Das ist gut so (sonst kämen sechs Bände gar nicht vor), aber es heißt auch: Die Metadaten werden auf einer teils ungeprüften Segmentierung erzeugt. Steht ein Schnitt falsch, ist auch der Titel falsch. Das gehört in die Provenienz jedes Records, nicht in eine Fußnote.

Wie viel sich ohne LLM erledigen ließe, habe ich ausgezählt — die Antwort ist: **wenig.**

| Signal auf der ersten Segmentseite | Segmente | Anteil |
|---|---|---|
| Datum in der Kopfzeile | 134 | 7 % |
| Sigel-Kopfleiste (`LSD - LSD - LSD`) | 70 | 4 % |
| *irgendein* Datum im Segmenttext | 1 206 | 63 % |

Anders als bei der Grenzerkennung tragen die deterministischen Signale hier kaum. Das LLM macht die Arbeit, und die Frage ist nicht, wie man es umgeht, sondern **wie man seiner Ausgabe trauen kann.**

Die dritte Zeile ist zugleich die wichtigste Zahl des ganzen Schritts: **Höchstens 63 % der Blätter können überhaupt ein tages- oder monatsgenaues Datum bekommen** — und real weniger, weil ein Teil dieser Fundstellen Veranstaltungs- oder Zitatdaten sind. Der Rest bleibt auf Jahresgenauigkeit aus dem Bandtitel. Das begrenzt später jede Zeitreihe (siehe `analyseplan.md`, Abschnitt 2).

---

## 1. Das Prinzip: erst messen können, dann produzieren

Der Testlauf auf Nr. 002 „sah solide aus". Das ist kein Qualitätsurteil, sondern ein Eindruck — und derselbe Fehler wie bei `confirmed: true` in der Segmentierung. Bevor 1 902 Records entstehen, braucht es zwei Dinge, die beide billig sind:

**(a) Automatische Plausibilitätsprüfung über alle Records.** Kostet nichts und läuft auf dem gesamten Bestand — siehe Abschnitt 2, `evidence_quote`.

**(b) Ein kleines Gold-Set.** 50–60 Segmente, geschichtet über die Jahre (die Blätter ändern sich stark: 1968 Streikaufrufe, 1973 Gremienpapiere), von Hand mit Titel, Organisation und Datum versehen. Zwei Personen machen davon 20 gemeinsam, um die Regeln abzugleichen — dieselbe Logik wie bei der Doppelannotation der Grenzen. Aufwand: zwei bis drei Stunden.

Daraus ergeben sich die Zahlen für den Methodenteil: Genauigkeit je Feld, nicht „sah gut aus".

---

## 2. Die größte Qualitätsverbesserung: Belegzitate

Ein Feld ins Antwortschema aufnehmen, das mehr bringt als jeder Modellwechsel:

```jsonc
{
  "id": 7,
  "title": "Emil Franzel und Franz Bayer",
  "title_evidence": "EMIL FRANZEL UND FRANZ BAYER",   // wörtlich aus dem OCR-Text
  "issuers": [{"surface": "LSD", "evidence": "LSD- LSD - LSD-LSD- LSD-"}],
  "date_text": "23. 7. 68",
  "date_evidence": "23. 7. 68",
  "date_iso": "1968-07-23",
  "date_type": "issued",        // issued | event | mentioned | undated
  "title_type": "original"      // original | supplied | incipit
}
```

Jedes Belegzitat lässt sich **automatisch gegen den Segmenttext prüfen**: Kommt die Zeichenkette dort vor (normalisierte Leerzeichen, Groß-/Kleinschreibung egal, notfalls Fuzzy-Schwelle 0,9)? Wenn nein, hat das Modell erfunden oder halluziniert übersetzt.

Warum das der zentrale Hebel ist: Ihr bekommt damit eine **Qualitätskennzahl über alle 1 902 Records, ohne eine einzige Handannotation.** Die Belegquote je Feld und je Band ist ein freier Proxy für die Extraktionsgüte; das Gold-Set aus Abschnitt 1 dient dann nur noch der Kalibrierung („bei 95 % Belegquote liegt die tatsächliche Genauigkeit bei X").

Zwei weitere Prüfungen im selben Stil, ebenfalls gratis:

* **Jahresabgleich:** Weicht `date_iso` vom Jahr des Bandes ab, ist es verdächtig (meist ein zitiertes historisches Datum). Als Flag, nicht als Korrektur.
* **Sprachprüfung des Titels:** Die Datalab-Auto-Segmentierung hat seinerzeit englische Titel erfunden („Political Protest Flyer – University of Regensburg 1968"). Ein Titel, der nicht wörtlich im Text steht oder englische Funktionswörter enthält, gehört markiert.

### Weitere Prompt-Änderungen, nach Wirkung sortiert

1. **Verbot, zu erfinden — mit Ausweichweg.** Statt „empty string if genuinely not stated" besser: `title_type` mitliefern lassen. `original` = Überschrift steht da; `incipit` = die ersten Wörter des Textes; und redaktionelle Titel gar nicht erst vom Modell erzeugen lassen. Damit ist im Nachhinein unterscheidbar, was auf dem Blatt stand und was das Werkzeug beigesteuert hat.
2. **Keine Übersetzung, keine Zusammenfassung.** Explizit: deutscher Wortlaut, keine Paraphrase.
3. **Mehrere Herausgeber zulassen.** `issuers` als Array — Blätter erscheinen gemeinsam (`LSD - SHB - SDS` als Kopfleiste).
4. **Erscheinungs- gegen Veranstaltungsdatum trennen** (`date_type`). Der Streikaufruf „am Mittwoch, 29. Mai 1968" wurde *vor* dem 29. Mai verteilt. Ohne diese Unterscheidung liegt jede Zeitreihe systematisch daneben.
5. **Die bisher bekannten Organisationen mitgeben.** Die wachsende Normdatei (Abschnitt 3) als kurze Liste in den Prompt — „falls eine dieser Gruppen gemeint ist, nutze genau diese Schreibweise". Das löst einen guten Teil des Vereinheitlichungsproblems schon bei der Extraktion und kostet ein paar hundert Token je Request.
6. **Segmentlänge mitgeben.** Ein 23-seitiges Segment ist vermutlich kein einzelnes Flugblatt; das Modell soll dann `doc_type: "unklar"` liefern dürfen statt einen Titel zu raten.

---

## 3. Kanonisierung: als Build-Schritt, nicht als zweiter LLM-Durchlauf

Die Diagnose im Projektkontext ist richtig — pro Batch fehlt der Gesamtkontext. Die naheliegende Lösung („noch ein LLM-Durchlauf mit allen Namen") ist aber nur zur Hälfte richtig. Ein LLM, das *bei jeder Auswertung neu* über Namen entscheidet, ist nicht reproduzierbar: Zwei Läufe können unterschiedlich clustern, und im Paper steht dann eine Zahl, die niemand nachrechnen kann.

Besser ist eine Arbeitsteilung, in der das LLM einmalig **vorschlägt** und ein Mensch **entscheidet**:

```
1902 Records
   └─ alle issuing_org-Werte einsammeln, normalisieren        (deterministisch)
        · Groß-/Kleinschreibung, Interpunktion, Mehrfach-Leerzeichen
        · Klammer-Akronyme auflösen: "Liberaler Studentenbund (LSD)" → Akronym LSD + Langform
   └─ nach Akronym blocken, innerhalb der Blöcke fuzzy clustern (deterministisch)
   └─ die deduplizierte Liste (voraussichtlich 200–400 Zeichenketten)
      EINMAL an ein LLM: "gruppiere und schlage kanonische Einträge vor"   (1 Request)
   └─ Mensch prüft das Ergebnis einmal → organizations.json (30–60 Einträge)   ← die Wahrheit
   └─ Mapping surface → org_id ist danach ein Lookup                (deterministisch, ewig)
```

Das Ergebnis ist genau die Normdatei aus `docs/korpus/korpusstruktur.md`: `org_id`, `name`, `full_name`, `type`, `variants[]`. Sie ist versioniert, im Diff nachvollziehbar und beim nächsten Korpusbau unverändert anwendbar. Was sich nicht zuordnen lässt, bleibt `org_id: null` und landet in einer Liste unaufgelöster Schreibweisen — sichtbar, nicht stillschweigend zusammengeworfen.

Der Zusatznutzen: Sobald die Normdatei existiert, geht sie nach Abschnitt 2.5 in den Extraktions-Prompt zurück. Ein zweiter Extraktionslauf produziert dann von vornherein deutlich einheitlichere Werte.

---

## 4. Der Produktionslauf

**Rechnung:** 1 902 Segmente à ~560 Token ≈ **1,1 Mio. Eingabe-Token** — praktisch das gesamte Korpus einmal durch das Modell. Bei `--batch-size 20` sind das 96 Requests, bei 50 noch 39.

Gegen das Free-Tier-Limit von 20 Requests/Tag heißt das: 5 Tage bei Batch 20, 2 Tage bei Batch 50. Drei Auswege, in dieser Reihenfolge:

1. **Batchgröße hoch** (40–50). Die Antwortqualität leidet erfahrungsgemäß erst, wenn der Kontext wirklich lang wird; mit striktem Array-Schema ist 50 unkritisch. Vorher an zehn Segmenten gegenprüfen, ob die Qualität hält.
2. **Schlüsselrotation**, wie sie `flugblatt_convert.py` für Datalab schon macht — drei Teammitglieder, drei Kontingente.
3. **Bezahltes Kontingent.** Bei 1,1 Mio. Token auf einem Flash-Tier sind das Centbeträge. Für zwei Tage Wartezeit lohnt die Diskussion kaum.

**Robustheit — der wichtigste Punkt bei mehrtägigen Läufen:** `extract_metadata.py` sammelt aktuell alle Ergebnisse im Speicher und schreibt erst am Ende. Bricht der Lauf bei Batch 90 von 96 ab, ist alles weg. Vor dem großen Lauf einbauen:

* **Checkpoint je Batch** in eine `.metadata.partial.jsonl` (`flugblatt_convert.py --batch-size` hat dieses Muster bereits),
* **Resume**: beim Start vorhandene Checkpoints einlesen und nur fehlende Batches anfragen,
* **Retry mit Backoff** bei 429/5xx, statt den Lauf abzubrechen,
* **`--limit`/`--dry-run`** zum Probieren, ohne Kontingent zu verbrennen.

---

## 5. Reihenfolge

| | Schritt | Aufwand |
|---|---|---|
| 1 | Schema und Prompt erweitern (Belegzitate, `title_type`, `date_type`, `issuers` als Array) | 1–2 h |
| 2 | Prüfskript: Belegquote, Jahresabgleich, Sprachprüfung | 1 h |
| 3 | Checkpoint + Resume + Retry in `extract_metadata.py` | 1–2 h |
| 4 | Probelauf auf **zwei** Bänden aus verschiedenen Jahren (etwa 002 und 013), Belegquote ansehen, Prompt nachschärfen | halber Tag |
| 5 | Gold-Set: 50–60 Segmente von Hand, geschichtet über die Jahre | 2–3 h zu zweit |
| 6 | Genauigkeit je Feld gegen das Gold-Set messen → Zahl für den Methodenteil | 1 h |
| 7 | Produktionslauf über alle 14 Bände | 2 Tage (Kontingent) |
| 8 | Kanonisierung nach Abschnitt 3 → `organizations.json` | halber Tag |
| 9 | Optional: zweiter Extraktionslauf mit Normdatei im Prompt | wie 7 |

Schritte 1–3 sind Voraussetzung für alles Weitere und zusammen ein Tag. **Schritt 4 vor Schritt 7** ist der eigentliche Rat: Ein Probelauf auf zwei Bänden aus verschiedenen Jahren kostet vier Requests und verhindert, dass ihr 96 Requests in eine Prompt-Schwäche investiert, die man an zwanzig Records gesehen hätte.

---

## 6. Was ich nicht machen würde

* **`--install` benutzen.** Es faltet die Organisation als `"Org - Titel"` in ein Stringfeld und macht die Trennung unumkehrbar. Der Sidecar ist die richtige Ablage; die Zusammenführung übernimmt der Korpusbau.
* **Auf ein stärkeres Modell hoffen.** Die Diagnose im Projektkontext ist richtig: Das Vereinheitlichungsproblem ist strukturell und wird durch Modellgröße nicht behoben. Umgekehrt gilt aber auch: Belegzitate und ein sauberes Schema bringen bei einem Flash-Modell mehr als ein Wechsel auf ein großes Modell ohne beides.
* **Die Extraktion vor der Grenzprüfung als endgültig betrachten.** Wo ein Schnitt fehlt, ist der Titel des zusammengeklebten Segments zwangsläufig falsch. `content_hash` je Segment mitschreiben — dann muss nach einer Splitting-Korrektur nur neu extrahiert werden, was sich tatsächlich geändert hat, statt alle 1 902 Records erneut durchs Modell zu schicken.
