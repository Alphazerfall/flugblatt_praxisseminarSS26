# Dehyphenierung: was passiert und warum

Gemessen am gesamten OCR-Bestand (14 Bände, 4 464 Seiten): **1 675 Trennungen an Zeilenenden, 1 338 verschiedene Wortpaare.** Vollständige Liste: `dehyphenierung.tsv` in diesem Ordner, erzeugt mit

```bash
python pipelines/06_analysis/ngrams.py hyphens -o docs/korpus/dehyphenierung.tsv
```

## Das Problem

Die Flugblätter sind auf Schreibmaschine getippt, also wird am Zeilenende getrennt. Im OCR steht dann:

```
Emil Franzel ist den Studenten sattsam als Hilfskammer-
mensch jeder des Axel Caesar Springer bekannt.
```

Ohne Behandlung produziert die Tokenisierung daraus `hilfskammer` und `mensch` — zwei Tokens, die es nicht gibt, und das eigentliche Wort fehlt in jeder Zählung. Bei 1 675 Fällen auf 1,06 Mio. Token ist der Effekt auf Frequenzlisten klein, aber er ist einseitig: Betroffen sind **überproportional die langen Komposita**, also genau das Vokabular, das bei diesem Material interessiert (`Hochschulgesetz`, `Studentenschaft`, `Literaturwissenschaften`).

## Warum die naive Regel nicht reicht

Ein simples `s/(\w)-\n(\w)/\1\2/` — mein erster Entwurf — behandelt drei verschiedene Sachverhalte gleich, von denen nur einer so funktioniert:

| Fall | Beispiel im Korpus | naiv | richtig |
|---|---|---|---|
| **Worttrennung** | `Hilfskammer-`⏎`mensch` | Hilfskammermensch ✓ | Hilfskammermensch |
| **Kompositum**, das zufällig an seinem eigenen Bindestrich umbricht | `AStA-`⏎`Fraktion` | AStAFraktion ✗ | AStA-Fraktion |
| **Ergänzungsstrich** | `Sprach-`⏎`und Literaturwissenschaften` | Sprachund ✗ | Sprach- und … |

Der dritte Fall ist der ärgerlichste: `Sprachund`, `Berufsund`, `Produktionsund` sind Wörter, die es nirgends gibt, und sie entstehen genau bei den Aufzählungen, in denen die Bewegung ihre Themen bündelt.

## Die Entscheidungsregel

`hyphen_decision()` in `ngrams.py`, drei Ausgänge, in dieser Reihenfolge geprüft:

1. **Ergänzungsstrich** — folgt `und`, `oder`, `bzw`, `sowie`, `beziehungsweise`, `resp`, bleibt der Strich stehen und die Wörter getrennt. 15 Paare, 17 Vorkommen.
2. **Korpusbeleg** — sonst wird gefragt, welche Form im *übrigen* Korpus tatsächlich vorkommt. `hilfskammermensch` zusammengeschrieben belegt, `hilfskammer-mensch` nicht → zusammenziehen. `asta-fraktion` 40× belegt, `astafraktion` nie → Bindestrich behalten.
3. **Form** — nur wenn beide Formen unbelegt sind: Sind beide Teile großgeschrieben (aber nicht durchgängig VERSAL), ist es vermutlich ein echtes Kompositum (`Steininger-Fetzer`), sonst eine Worttrennung.

Der Wortschatz für Schritt 2 wird aus Tokens gebildet, die **vollständig innerhalb einer Zeile** stehen. Sonst wäre die Begründung zirkulär — die Entscheidung über `Hilfskammer-`⏎`mensch` würde sich auf sich selbst stützen. So stützt sie sich auf andere Textstellen.

## Was dabei herauskommt

```
1675 Trennungen, 1338 verschiedene Paare
  1236  join      beleg_joined        durch den Korpus belegt
   245  join      form_trennung       kein Beleg, Form spricht für Trennung
    80  join      beleg_beide         beide Formen belegt, zusammen häufiger
    62  hyphen    form_kompositum     kein Beleg, beide Teile groß
    23  hyphen    beleg_hyph          Bindestrich-Form belegt
    17  ellipsis  ergaenzungsstrich
    12  hyphen    beleg_beide         beide belegt, mit Bindestrich häufiger
```

**93 % der Fälle sind einfache Worttrennungen**, und für vier Fünftel davon liefert der Korpus selbst den Beleg. Die 245 unbelegten sind überwiegend seltene Komposita und OCR-Kuriosa (`Eulen-`⏎`spiegel`, `Kulturre-`⏎`MAHLER`) — dort ist ein falsches Zusammenziehen folgenlos, weil das Ergebnis ohnehin ein Einzelfall bleibt.

Ohne den Korpusabgleich (`--no-vocab`) fällt die Bilanz deutlich schlechter aus: 1 561 mal `join` und 97 mal `hyphen`, also **80 Fälle mehr zusammengezogen**, darunter alle VERSAL-Trennungen wie `HOCH-`⏎`SCHULPOLITISCHEN`, die die reine Formregel für Komposita hält.

## Die Liste durchsehen

`dehyphenierung.tsv` hat eine Zeile pro Wortpaar, sortiert nach Entscheidung und Häufigkeit:

| Spalte | Bedeutung |
|---|---|
| `n` | Vorkommen im Korpus |
| `a`, `b` | die beiden Teile |
| `ergebnis` | was das Skript daraus macht |
| `entscheidung` | `join` / `hyphen` / `ellipsis` |
| `begruendung` | welche Regel gegriffen hat, mit Belegzahl |
| `vok_joined`, `vok_hyph` | wie oft die jeweilige Form sonst im Korpus steht |
| `baende` | in welchen Bänden |
| `kontext` | 40 Zeichen drumherum, zum Nachlesen |

Zum Prüfen lohnen sich zwei Filter: **alle 95 Nicht-`join`-Zeilen** (das ist in zehn Minuten durchgesehen) und innerhalb von `join` die 245 Zeilen mit `begruendung = form_trennung`, also die ohne Beleg. Was dort falsch entschieden ist, gehört als Ausnahme in den Code — dann bitte mit einem Kommentar, warum.

## Was das für die Analyse bedeutet

Gemessen, nicht geschätzt — drei Varianten desselben Korpus (ohne Dehyphenierung / naiv immer zusammenziehen / belegbasiert):

**Auf Frequenzlisten wirkt sich das praktisch nicht aus.** Die Top-50 der Uni-, Bi- und Trigramme sind zwischen belegbasiert und naiv *identisch*, gegenüber „gar keine Dehyphenierung" unterscheidet sich ein einziger Eintrag in den Unigrammen. Die Trendkurven ändern sich in der zweiten Nachkommastelle (`mitbestimmung` 1973: 4,98 → 5,04 pro 10 000). Betroffen sind 1 568 Token = **0,15 % des Korpus**. Für jede aggregierte Aussage ist die Dehyphenierung also irrelevant.

**Auf die Suche wirkt sie sich erheblich aus.** Dieselben 0,15 % verteilen sich nicht gleichmäßig, sondern auf lange Komposita — die betroffenen Wörter sind im Schnitt 13,7 Zeichen lang gegenüber 11,3 im Korpus. In Seitentreffern gerechnet:

| | |
|---|---|
| Typen, die ohne Dehyphenierung weniger Seiten treffen | 1 020 |
| davon ≥ 5 % der Treffer verloren | 660 |
| davon ≥ 25 % verloren | 435 |
| Typen, die ohne Dehyphenierung **gar nicht existieren** | 280 |

Konkret: `wirtschaftswissenschaftlichen` steht auf 32 Seiten, ohne Dehyphenierung findet man 27 (−15,6 %). `literaturwissenschaften` 71 statt 66 (−7 %). `fachschaftszentralrats` steht auf 5 Seiten, ohne Dehyphenierung auf 1.

**Die Konsequenz ist also nicht „unsere Zahlen waren falsch", sondern eine Arbeitsteilung:**

* Für **Frequenz- und Trendaussagen** ist die Vorverarbeitung unkritisch. Hier lohnt kein weiterer Aufwand — der begrenzende Faktor sind die OCR-Fehlerrate und die Dokumentgrenzen, nicht die Bindestriche.
* Für **Retrieval** — KWIC, „auf welchen Blättern kommt X vor", qualitative Auswahl von Belegstellen, später jede Zählung *pro Flugblatt* statt pro Token — ist sie kritisch. Genau dort verliert man einzelne Treffer, und ein verlorener Treffer heißt: ein Blatt fällt aus der Auswahl, das hineingehört.
* Für **Typen-basierte Maße** (Type-Token-Ratio, Vokabularreichtum, Hapax-Analysen) ebenfalls: ohne Dehyphenierung enthält das Korpus 63 682 statt 63 105 Typen, also **577 Wortformen, die es nie gegeben hat**.

Praktisch heißt das: die Vorverarbeitung einmal richtig festzurren (ist erledigt), im Methodenteil in drei Sätzen dokumentieren, und für die Ergebnisse *nicht* mehr darüber diskutieren. Eine Sensitivitätsprüfung lohnt nur dort, wo ein Befund knapp ist — und die ist billig, weil `--no-vocab` und `--raw` genau dafür da sind.

## Formulierung für den Methodenteil

> Als Textgrundlage dienen die OCR-Ausgaben aller 14 Bände (4 464 Seiten, rund 1,06 Mio. Token); Kopf- und Fußzeilen sowie Bildunterschriften werden anhand der von der OCR vergebenen Blocktypen ausgeschlossen, da die Kopfleisten der Flugblätter (etwa „RCDS – RCDS – RCDS …") die Frequenzlisten andernfalls dominieren. Bei der Tokenisierung werden Zeilenendtrennungen aufgelöst, wobei für jeden der 1 675 Fälle am übrigen Korpus geprüft wird, ob die zusammengeschriebene oder die Bindestrichform belegt ist, und Ergänzungsstriche („Sprach- und Literaturwissenschaften") erhalten bleiben; unmittelbar wiederholte Tokens werden auf ein Vorkommen reduziert. Ausgewertet werden nicht lemmatisierte Wortformen, für Frequenzauswertungen bereinigt um 629 Stoppwörter (Vereinigungsmenge von stopwords-iso und spaCy); Auswertungsskript, Stoppwortliste und die vollständige Liste der Trennungsentscheidungen sind im Projektrepositorium dokumentiert.

Optionale Fußnote, wenn ein Befund knapp ausfällt:

> Die Vorverarbeitung wurde auf ihre Ergebnisrelevanz geprüft: Die Auflösung der Zeilenendtrennungen betrifft 0,15 % der Token und verändert die Rangfolge der 50 häufigsten N-Gramme nicht; sie wirkt sich jedoch auf die Wiederauffindbarkeit langer Komposita aus, von denen 280 ohne diesen Schritt gar nicht als Wortform im Korpus erscheinen.

## Nebenbefund

Beim Aufräumen ist ein zweiter Fehler aufgefallen: Das alte Token-Muster ließ einen Bindestrich am Wortende zu, `Sprach- und` wurde also zu `sprach-`. Das erklärt den seltsamen Eintrag `sprach- (114)` in der Keyness-Liste von 1971 — er heißt jetzt `sprach (129)`. Beide Korrekturen zusammen ändern die Frequenzlisten nur geringfügig (`studenten` 5 207 → 5 251), aber sie ändern sie in die richtige Richtung, und der Effekt wächst mit der Länge der Wörter.
