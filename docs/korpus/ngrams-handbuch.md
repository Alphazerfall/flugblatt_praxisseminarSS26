# `ngrams.py` — Handbuch

Werkzeug für erste korpuslinguistische Auswertungen auf den OCR-Volltexten. Nur Standardbibliothek: kein pandas, kein nltk, keine Modelle, keine API-Aufrufe.

Alle Ausgaben unten sind echte Läufe über den vollständigen Bestand — **14 Bände, 4 464 Seiten, 1 064 797 Token**, Stand 20.08.2026. Wenn ihr die OCR neu erzeugt, verschieben sich die Zahlen leicht.

```bash
python pipelines/06_analysis/ngrams.py <kommando> [optionen]
```

Der erste Lauf liest die großen Datalab-JSONs und legt den Plaintext unter `data/cache/ngram_txt/` ab (dauert wenige Sekunden); jeder weitere Lauf startet aus dem Cache. `data/` ist in `.gitignore`, der Cache stört also nichts. Nach einer neuen OCR den Cache löschen.

**Globale Optionen** (vor dem Kommando):

| Option | Wirkung |
|---|---|
| `--bands 0118_0002,0118_0009` | nur diese Bände (Standard: alle 14) |
| `--stopwords PFAD` | andere Stoppwortliste als `stopwords_de.txt` daneben |

---

## `size` — Korpusgröße je Jahr

Erster Aufruf bei jeder neuen Auswertung. Zeigt, welche Jahre überhaupt Aussagen tragen.

```bash
python pipelines/06_analysis/ngrams.py size
```

```
Jahr    Seiten     Token  Baende
1967        13      5462  0118_0001
1968        85     19801  0118_0002
1969       317     71845  0118_0003
1970       294     62172  0118_0004
1971       629    149818  0118_0005
1972      1608    362886  0118_0006, 0118_0007, 0118_0008, 0118_0009
1973      1518    392813  0118_0010, 0118_0011, 0118_0012, 0118_0013, 0118_0014
Summe     4464   1064797
```

**Lesehinweis:** 1973 hat 72-mal so viele Token wie 1967. Jede absolute Zählung misst deshalb vor allem die Bestandsgröße — für Vergleiche über die Zeit immer `trend` (relative Frequenzen) verwenden. Für 1967 trägt bei 5 462 Token keine Frequenzaussage.

---

## `top` — häufigste N-Gramme

```bash
python pipelines/06_analysis/ngrams.py top -n 1 --top 12
```

```
Top-12 1-Gramme (bereinigt, 1064797 Token):
    5251  studenten        1680  studentenschaft
    2659  asta             1453  kampf
    2455  rcds             1333  interessen
    2356  universität      1300  politischen
    1945  regensburg       1278  hochschule
    1920  bhg              1275  wissenschaft
```

Bei `-n 1` fallen Stoppwörter weg. `--with-stopwords` zeigt, warum:

```
   52025  der      29901  und      12467  des
   46120  die      15463  den      11832  das
```

Bei `-n 2` muss ein N-Gramm mindestens ein Inhaltswort enthalten, bei `-n 3` mindestens zwei — sonst bestünde die Liste aus Funktionswortketten.

```bash
python pipelines/06_analysis/ngrams.py top -n 3 --top 10
```

```
     414  der universität regensburg      149  mehrheit der studenten
     266  der verfaßten studentenschaft   129  freie politische betätigung
     193  forschung und lehre             112  der arbeitenden bevölkerung
     161  interessen der studenten        108  aktionsgemeinschaft liberaler studenten
     153  freiheit der wissenschaft       104  organe der verfaßten
```

**Lesehinweis:** Hier wird die Formelsprache sichtbar, die Einzelwörter verdecken — Kampfbegriffe (`freie politische betätigung`, `freiheit der wissenschaft`) neben Legitimationsformeln (`mehrheit der studenten`) und Gremiensprache (`organe der verfaßten [Studentenschaft]`). `freiheit der wissenschaft` gehört ins RCDS-Vokabular, `der arbeitenden bevölkerung` ins MSB/SHB-Vokabular.

`--raw` schaltet die gesamte Vorverarbeitung ab und zeigt, was sie leistet:

```bash
python pipelines/06_analysis/ngrams.py top -n 3 --top 6 --raw
```

```
    1699  rcds rcds rcds                  264  der verfaßten studentenschaft
     642  der universität regensburg      260  studentenschaft der universität
     627  sprach-lit sprach-lit sprach-lit 238  info info info
```

Ohne Filter fressen die Kopfleisten der Flugblätter die Liste auf. `--raw` ist die eingebaute Sensitivitätsprüfung: Wenn ein Befund mit und ohne Bereinigung gleich aussieht, hängt er nicht an der Vorverarbeitung.

| Option | Wirkung |
|---|---|
| `-n N` | N-Gramm-Länge (Standard 2) |
| `--top N` | Listenlänge (Standard 20) |
| `--raw` | ohne Bereinigung: mit Kopfzeilen, ohne Dehyphenierung, ohne Sigel-Kollaps |
| `--with-stopwords` | nur bei `-n 1`: Stoppwörter mitzählen |

---

## `trend` — relative Frequenz über die Jahre

Der Aufruf für Zeitverläufe. Einzelwörter und Mehrwortausdrücke (in Anführungszeichen) gemischt.

```bash
python pipelines/06_analysis/ngrams.py trend notstand vietnam streik berufsverbot \
    mitbestimmung "numerus clausus" "kampf gegen"
```

```
Relative Frequenz pro 10.000 Token
                          1967    1968    1969    1970    1971    1972    1973
  notstand                 0.0     3.0     0.0     0.2     0.0     0.0     0.3
  vietnam                  0.0     0.0     0.7     5.0     0.3     1.3     2.1
  streik                   0.0     3.5    16.6     1.0     0.3     5.9    11.5
  berufsverbot             0.0     0.0     0.0     0.0     0.0     2.3     2.6
  mitbestimmung            0.0     2.0     1.3     2.1     3.5     5.2     5.0
  numerus clausus          0.0     1.0     0.7     5.0     1.6     1.8     2.9
  kampf gegen              0.0     2.5     2.9     1.6     1.5     6.0     7.7

  Basis (Token je Jahr):   5462   19801   71845   62172  149818  362886  392813
```

**Lesehinweis:** `notstand` ist ein reiner 1968er-Ausschlag, `berufsverbot` existiert vor 1972 nicht (Radikalenerlass, Januar 1972) und bleibt danach präsent, `mitbestimmung` steigt stetig. Die Basiszeile gehört zur Interpretation: Ein Wert für 1967 beruht auf 5 462 Token und ist damit kaum belastbar.

**Grenze:** Gezählt werden Token, nicht Blätter. Ein einzelnes langes Papier, das ein Wort zwanzigmal enthält, erzeugt einen Ausschlag. Prüfen lässt sich das mit `collocates` (dort steht die Streuung) oder, sobald das Splitting steht, durch Zählen auf Dokumentebene.

---

## `keyness` — was ist für ein Jahr charakteristisch?

Vergleicht jedes Jahr mit allen übrigen (Dunnings Log-Likelihood, G²). Man muss die Suchbegriffe nicht vorher kennen — das Verfahren findet sie.

```bash
python pipelines/06_analysis/ngrams.py keyness --top 6
```

```
1967: würzburg (28), stud (26), universität (48), asta (38), studenten (36)
1968: mayer (77), lsd (60), rektor (76), sds (31), universität (126), psychologie (43)
1969: hirsch (77), kraus (89), art (181), koch (55), bla (33), huber (56)
1970: schumann (121), frage (175), grant (34), onan (31), pollok (53), dow (27)
1971: grundkurse (120), ökonomie (143), marx (158), literaturwissenschaften (84), sprach (129), marxismus (79)
1972: spd (324), gups (93), csu (338), shb (415), the (159), barzel (51)
1973: mhg (274), bhg (1125), sem (472), gew (461), fsr (229), dab (144)
```

Mit `-n 2` auch für Wortpaare:

```
1968: rektor mayer (24), universität regensburg (42), des rektors (21)
1971: sprach und (114), fachbereich sprach (56), politische ökonomie (64)
1972: der spd (171), csu cdu (49), bei pustet (42)
1973: das bhg (617), der gew (170), demokratische front (178), msb spartakus (212)
```

**Lesehinweis:** Lesbar als Chronik — 1968 dreht sich alles um Rektor Mayer, 1971 um den Streit über marxistische Grundkurse in den Sprach- und Literaturwissenschaften, 1973 um das Bayerische Hochschulgesetz. Das Verfahren findet dabei zuverlässig auch **Datenprobleme**: `onan`, `dow`, `treratola`, `bla` sind OCR-Schrott (gehäuft in Nr. 004 — ein Hinweis, dort die Scanqualität anzusehen), `the (159)` verrät englischsprachiges Material im Bestand, `bei pustet` eine Buchhandlungsanzeige in einer Fußzeile.

| Option | Wirkung |
|---|---|
| `-n N` | N-Gramm-Länge (Standard 1) |
| `--min-count N` | Mindesthäufigkeit im Jahr (Standard 25) — niedriger heißt mehr Rauschen |
| `--top N` | Einträge je Jahr (Standard 10) |

---

## `collocates` — welche Wörter stehen daneben?

Das Kommando für begriffsgeschichtliche Fragen: Wer benutzt ein Wort wofür, und ändert sich das? Zusätzlich prüft es die **Streuung** — ob der Befund über den Bestand verteilt ist oder in wenigen Papieren klumpt.

```bash
python pipelines/06_analysis/ngrams.py collocates spd --year 1972 --measure dice --top 12
```

```
'spd' — Jahr(e) 1972: 324 Treffer auf 141 von 1608 Seiten (8.93 pro 10.000 Token)
  Streuung: die 10 stärksten Seiten stellen 20 % der Treffer

  Kollokat                      gem.  gesamt  logDice
  fdp                             28      30     11.3
  shb                             43     418     10.9
  jungsozialisten                 20      98     10.6
  fdp-regierung                   15      15     10.5
  landtag                         15      62     10.3
  gewerkschaften                  11      67      9.8
  cdu                             11     164      9.5
  jusos                            7      39      9.3
```

Dieselbe Abfrage für 1973:

```
'spd' — Jahr(e) 1973: 139 Treffer auf 100 von 1518 Seiten (3.54 pro 10.000 Token)
  Streuung: die 10 stärksten Seiten stellen 26 % der Treffer

  fdp 31 · csu 26 · cdu 17 · jungsozialisten 10 · bildungsplanung 9 · dkp 9
```

**Lesehinweis — ein vollständiges Beispiel.** In der Keyness-Liste fällt `spd (324)` für 1972 auf. Drei Prüfungen:

1. *Artefakt?* Nein — 141 von 1 608 Seiten, verteilt über alle vier Bände des Jahres, die zehn stärksten Seiten stellen nur 20 %. Ein einzelnes langes Papier wäre bei über 50 % gelandet, und die Ausgabe hätte gewarnt.
2. *Nur die SPD?* Nein — `trend csu cdu barzel brandt spd` zeigt für 1972 gemeinsam 9,3 / 4,5 / 1,4 / 1,8 / 8,9 pro 10 000, jeweils der Höchstwert aller Jahre; `barzel` kommt praktisch nur 1972 vor. Bundespolitik dringt 1972 in die Hochschulflugblätter ein: gescheitertes Misstrauensvotum im April, vorgezogene Bundestagswahl im November.
3. *Worum geht es konkret?* Der stärkste Kollokat 1972 ist **`shb`**, nicht CDU — und im Jahr darauf ist er verschwunden. 1972 geht es also weniger um Wahlkampf als um einen innerlinken Namensstreit; die Belegstellen (`kwic`) zeigen es direkt: *„Es geht nicht darum, ob (inhaltlich) SPD oder SHB die wahre Sozialdemokratie vertreten…"*

Aus einer Zeile einer Rangliste wird so ein datierbarer Befund — und der Weg dahin sind genau diese drei Schritte.

| Option | Wirkung |
|---|---|
| `--year 1972` bzw. `--year 1971,1972` | auf Jahre einschränken |
| `-w N` | Fenstergröße in Token, ±N (Standard 5) |
| `--measure ll\|dice` | `ll` = Dunnings G² (Standard), `dice` = logDice |
| `--min-count N` | Mindestzahl gemeinsamer Treffer (Standard 4) |

**Welches Maß?** G² stellt seltene, exklusive Wörter nach oben; logDice die tatsächlich charakteristischen Partner und wächst nicht mit der Korpusgröße — deshalb in der Korpuslinguistik der übliche Wert für Kollokationslisten. Für Listen im Vortrag `--measure dice`. Skala grob: über 9 sehr stark, 7–9 stark, unter 5 kaum bemerkenswert.

---

## `kwic` — Konkordanz (keyword in context)

Der Realitätscheck. Keine Zahl aus den anderen Kommandos sollte in einen Text, ohne dass jemand ein Dutzend Belegstellen gelesen hat.

```bash
python pipelines/06_analysis/ngrams.py --bands 0118_0009,0118_0013 kwic Berufsverbot --limit 2
```

```
[1972 0118_0009] …heit in den Räumen der Hochschule! WEG MIT DEM [BERUFSVERBOT] FÜR DEMOKRATEN UND INSBESONDERE KOMMUNISTEN…
[1972 0118_0009] …hen, müssen mit an vorderster Front gegen das [Berufsverbot] stehen. Denn genau uns, denen schon an den Hoch…
[1973 0118_0013] …n eine Personalakte beim KuMi (zwecks späterem [Berufsverbot]). Dieses BHG zeichnet sich also v.a. dadurch…
[1973 0118_0013] …n eine Personalakte beim KUMi (zwecks späterem [Berufsverbot]). Dieses BHG zeichnet sich also v.a. dadurch…
```

**Lesehinweis:** Die beiden 1973er Belege (`KuMi` / `KUMi`) sind dasselbe Blatt — ein Doppelstück im Bestand, das die OCR zweimal leicht anders gelesen hat. Solche Funde nebenbei sind der Grund, warum `kwic` zu jeder Auswertung gehört.

Die Suche ist eine einfache Zeichenkettensuche ohne Berücksichtigung von Groß-/Kleinschreibung, kein Token-Match — `Berufsverbot` findet also auch `Berufsverbote`. `--limit` gilt **je Band**, `--width` steuert die Kontextbreite (Standard 45 Zeichen je Seite).

---

## `hyphens` — Zeilenendtrennungen prüfen

Diagnosekommando für die Vorverarbeitung: listet jede Trennung am Zeilenende mit der getroffenen Entscheidung.

```bash
python pipelines/06_analysis/ngrams.py hyphens -o docs/korpus/dehyphenierung.tsv
```

```
1675 Trennungen an Zeilenenden, 1338 verschiedene Paare (mit Korpusbeleg)
   1236  join     beleg_joined        durch den Korpus belegt
    245  join     form_trennung       kein Beleg, Form spricht für Trennung
     80  join     beleg_beide         beide Formen belegt, zusammen häufiger
     62  hyphen   form_kompositum     kein Beleg, beide Teile groß
     23  hyphen   beleg_hyph          Bindestrich-Form belegt
     17  ellipsis ergaenzungsstrich
     12  hyphen   beleg_beide
```

Ohne `-o` erscheinen die häufigsten Fälle auf der Konsole, mit `-o` die vollständige Liste als TSV (Spalten: Treffer, beide Teile, Ergebnis, Entscheidung, Begründung, Belegzahlen, Bände, Kontext). `--no-vocab` schaltet den Korpusabgleich ab und entscheidet nur nach Form — dann werden 80 Fälle mehr zusammengezogen, darunter alle VERSAL-Trennungen wie `HOCH-`⏎`SCHULPOLITISCHEN`.

Ausführlich in `docs/korpus/dehyphenierung.md`.

---

## Was vor jeder Zählung mit dem Text passiert

Fünf Schritte, in dieser Reihenfolge. `--raw` schaltet alle ab.

1. **Blockfilter.** Aus dem Datalab-OCR fliegen `PageHeader`, `PageFooter`, `PageNumber`, `Picture` und `Figure` raus — 3,2 % der Token, aber ohne diesen Schritt stehen die Kopfleisten der Blätter auf den vorderen Plätzen jeder Liste.
2. **Dehyphenierung.** `Hilfskammer-`⏎`mensch` → `Hilfskammermensch`, aber `Sprach-`⏎`und` bleibt `Sprach- und` und `AStA-`⏎`Fraktion` bleibt `AStA-Fraktion`. Entschieden wird am übrigen Korpus, nicht nach Faustregel.
3. **Tokenisierung.** Kleinschreibung, mindestens drei Zeichen, keine Ziffern. Binnenbindestriche bleiben (`christlich-demokratisch`), Bindestriche am Wortende nicht.
4. **Sigel-Kollaps.** Dieselbe Zeichenkette dreimal hintereinander wird auf ein Vorkommen gekürzt — fängt die Kopfleisten ab, die als `Text`-Block durch den Blockfilter rutschen.
5. **Stoppwörter** (nur wo sinnvoll, siehe die einzelnen Kommandos). 629 Einträge aus `stopwords_de.txt`, zusammengeführt aus stopwords-iso und spaCy.

Wichtig für den Methodenteil: Diese Schritte sind unterschiedlich folgenreich. Blockfilter und Stoppwortliste **verändern die Ergebnislisten sichtbar**, die Dehyphenierung betrifft nur 0,15 % der Token und ändert die Top-50 praktisch nicht — sie wirkt sich dafür stark auf die *Wiederauffindbarkeit* langer Komposita aus.

---

## Funktionen für eigene Auswertungen

Das Modul lässt sich importieren; die Kommandos sind nur dünne Hüllen darum.

```python
import sys; sys.path.insert(0, "pipelines/06_analysis")
import ngrams as N

N.VOCAB = N.inline_vocab(list(N.YEARS))       # einmal setzen, sonst greift nur die Formregel
seiten = N.prepare_pages("0118_0009")          # Tokenliste je Seite
tokens = N.prepare("0118_0009")                # Tokenliste für den ganzen Band
top    = N.ngram_counts(tokens, 2).most_common(20)
```

| Funktion | Zweck |
|---|---|
| `load_text(stem, keep_headers=False)` | Volltext eines Bandes, Seiten durch `\f` getrennt; nutzt/erzeugt den Cache |
| `extract_plaintext(stem, keep_headers)` | dasselbe direkt aus dem OCR-JSON, ohne Cache |
| `ocr_json_path(stem)` / `block_text(block)` | Pfad zum OCR-JSON / HTML eines Blocks als Text |
| `inline_vocab(stems)` | Wortschatz aus Tokens **innerhalb** einer Zeile — Grundlage der Trennungsentscheidung |
| `hyphen_decision(a, b, vocab)` | `("join"\|"hyphen"\|"ellipsis", Begründung)` für einen Trennungsfall |
| `apply_decision(a, b, decision)` | setzt die Entscheidung in Text um |
| `dehyphenate(text, vocab=None)` | wendet das auf einen ganzen Text an |
| `tokenize(text, dehyph=True, min_len=3, vocab=None)` | Text → Tokenliste |
| `collapse_runs(tokens, k=3)` | Sigel-Läufe stauchen |
| `prepare(stem, raw=False)` | Bequemform: laden + tokenisieren + stauchen |
| `prepare_pages(stem)` | dasselbe, aber eine Tokenliste je Seite |
| `ngram_counts(tokens, n, min_content=1)` | N-Gramm-Zähler; `min_content` = geforderte Inhaltswörter je N-Gramm |
| `log_likelihood(a, b, size_a, size_b)` | Dunnings G², vorzeichenbehaftet (positiv = im ersten Teilkorpus übervertreten) |
| `log_dice(a, f_node, f_coll)` | logDice für Kollokationen |
| `find_term(tokens, term)` | Startpositionen einer (auch mehrwortigen) Tokenfolge |
| `collocates(pages, term, window)` | `(Kollokat-Zähler, Treffer, Seiten mit Treffer, Treffer je Seite)` |
| `kwic(text, term, width, limit)` | Konkordanzzeilen |
| `by_year(stems, raw=False)` | Tokenlisten nach Erscheinungsjahr gebündelt |
| `load_stopwords(path=None)` | Stoppwortliste aus Datei |

Wichtige Modulwerte: `YEARS` (Band → Jahr), `DROP_BLOCKS` (gefilterte Blocktypen), `STOPWORDS`, `VOCAB` (wird von der Kommandozeile gesetzt; beim Import selbst setzen), `CACHE`, `RAW`.

---

## Grenzen

* **Keine Lemmatisierung.** `studenten` und `student` sind zwei Einträge. Für einen ersten Zugriff vertretbar; wer lemmatisieren will, nimmt spaCy mit `de_core_news_sm` — dann aber als eigener, dokumentierter Schritt.
* **Seitenebene, nicht Dokumentebene.** Alles zählt Token und Seiten, nicht Flugblätter. Aussagen wie „auf wie vielen Blättern kommt X vor" oder „welche Organisation sagt was" brauchen das fertige Splitting und die Metadatenebene aus `docs/korpus/korpusstruktur.md`.
* **OCR-Fehler sind nicht korrigiert.** Sie tauchen als Wörter auf, die es nicht gibt (`treratola`, `begefogregetz`) und sind mit `keyness` gut auffindbar, aber nicht bereinigt.
* **Kein Signifikanztest im engeren Sinn.** G² wird als Rangordnungsmaß benutzt, nicht als Hypothesentest mit Schwellenwert.
