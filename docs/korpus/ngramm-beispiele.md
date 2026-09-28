# N-Gramm-Analysen: fünf einfache Einstiege

Alle Zahlen unten sind auf dem vorhandenen OCR-Bestand gerechnet — **4 464 Seiten, 1,06 Mio. Token, 1967–1973**, alle 14 Bände. Werkzeug: `pipelines/06_analysis/ngrams.py` (nur Standardbibliothek, kein pandas, kein nltk).

Wichtig: alle fünf laufen auf der **Seitenebene** und brauchen das fertige Splitting nicht. Sie sind das, womit ihr sofort anfangen könnt.

```
Jahr    Seiten     Token  Bände
1967        13      5462  0118_0001
1968        85     19800  0118_0002
1969       317     71854  0118_0003
1970       294     62183  0118_0004
1971       629    149830  0118_0005
1972      1608    362945  0118_0006, 0118_0007, 0118_0008, 0118_0009
1973      1518    392897  0118_0010 … 0118_0014
Summe     4464   1064971
```

1967 ist mit 5 462 Token zu klein für Frequenzvergleiche — jede Aussage über dieses Jahr steht auf 13 Seiten. Das ist kein Mangel des Verfahrens, sondern eine Eigenschaft des Bestands, die man mitnennt.

---

## 1. Häufigkeitsliste — und warum sie ohne Vorverarbeitung nichts sagt

```bash
python pipelines/06_analysis/ngrams.py top -n 1 --top 12 --with-stopwords
python pipelines/06_analysis/ngrams.py top -n 1 --top 12
```

| mit Stoppwörtern | ohne |
|---|---|
| der 52025, die 46117, und 29885, den 15462, des 12467, das 11832 | studenten 5207, asta 2647, rcds 2441, universität 2356, regensburg 1944, bhg 1916, wurde 1795, alle 1687, studentenschaft 1680, kampf 1453, interessen 1328, politischen 1300 |

Die linke Spalte ist bei jedem deutschen Text identisch und damit wertlos. Die rechte ist schon ein Ergebnis: Das Vokabular ist institutionell (`asta`, `studentenschaft`, `bhg` = Bayerisches Hochschulgesetz) und agonal (`kampf`, `interessen`). Das ist der billigste Einstieg überhaupt und liefert zugleich die Kandidatenliste für Schritt 3.

## 2. Bi- und Trigramme — die Formelsprache der Bewegung

```bash
python pipelines/06_analysis/ngrams.py top -n 3 --top 12
```

```
   413  der universität regensburg        129  freie politische betätigung
   266  der verfaßten studentenschaft     112  der arbeitenden bevölkerung
   193  forschung und lehre               108  aktionsgemeinschaft liberaler studenten
   160  interessen der studenten          104  organe der verfaßten
   153  freiheit der wissenschaft         101  der uni regensburg
   149  mehrheit der studenten             98  der kleine senat
```

Hier wird sichtbar, was Einzelwörter verdecken: feste Kampfbegriffe (`freie politische betätigung`, `freiheit der wissenschaft`) und Legitimationsformeln (`mehrheit der studenten`, `interessen der studenten`) stehen neben nüchterner Gremiensprache (`der kleine senat`, `organe der verfaßten [Studentenschaft]`). Wer will, kann daraus direkt eine kleine Diskursanalyse machen: `freiheit der wissenschaft` gehört zum RCDS-Vokabular, `der arbeitenden bevölkerung` zum MSB/SHB-Vokabular — dieselbe Universität, zwei Sprachen.

**Ohne Bereinigung sieht dieselbe Liste so aus:**

```bash
python pipelines/06_analysis/ngrams.py top -n 3 --top 5 --raw
```

```
  1698  rcds rcds rcds
   641  der universität regensburg
   627  sprach-lit sprach-lit sprach-lit
   264  der verfaßten studentenschaft
   260  studentenschaft der universität
```

Die Kopfleisten der Blätter (`RCDS - RCDS - RCDS - …`) dominieren alles. Drei Schritte räumen das weg, alle drei sind im Skript und alle drei sind hier nötig:

* **Kopf- und Fußzeilen filtern** über den `block_type` aus dem Datalab-OCR (`PageHeader`, `PageFooter`, `Picture`). Das sind nur 3,2 % der Token, drückt aber z. B. die Werbeanzeige `bücher bei pustet` von 176 auf 36 Treffer — der Rest steckt in `Text`-Blöcken und muss, wenn er stört, über eine Stoppphrasen-Liste raus.
* **Dehyphenierung**: `Hilfskammer-\nmensch` → `Hilfskammermensch`. Ohne diesen Schritt zerfällt jedes am Zeilenende getrennte Wort in zwei Nicht-Wörter.
* **Sigel-Läufe stauchen**: dieselbe Zeichenkette dreimal hintereinander → einmal. Fängt die Leisten ab, die als `Text`-Block durchrutschen.

Das ist der Punkt, an dem die Korpusstruktur zahlt: Weil die Blocktypen im OCR erhalten bleiben, ist dieser Filter eine Zeile Code und keine Handarbeit.

## 3. Diachronie — relative Frequenz pro 10 000 Token

```bash
python pipelines/06_analysis/ngrams.py trend notstand vietnam streik berufsverbot "numerus clausus" mitbestimmung
```

```
                          1967    1968    1969    1970    1971    1972    1973
  notstand                 0.0     3.0     0.0     0.2     0.0     0.0     0.3
  vietnam                  0.0     0.0     0.7     5.0     0.3     1.3     2.1
  streik                   0.0     2.5    15.6     1.0     0.3     5.9    11.4
  berufsverbot             0.0     0.0     0.0     0.0     0.0     2.3     2.6
  numerus clausus          0.0     1.0     0.7     5.0     1.6     1.8     2.9
  mitbestimmung            0.0     2.0     1.3     2.1     3.5     5.2     5.0
```

Die wohl anschaulichste Analyse für einen Vortrag, und sie funktioniert: `notstand` ist ein reiner 1968er-Peak, `berufsverbot` existiert vor 1972 schlicht nicht (Radikalenerlass, Januar 1972) und bleibt danach präsent, `mitbestimmung` steigt stetig, `streik` hat zwei Spitzen (1969 und 1973). **Immer relative Frequenzen**, nie Rohzahlen: 1973 hat 72× so viele Token wie 1967, jede absolute Zählung misst nur die Bestandsgröße.

Zwei Vorsichtsmaßnahmen: die Jahre sind ungleich groß (siehe oben), und ein Wort kann in einem einzigen langen Papier zwanzigmal stehen. Belastbarer wird die Kurve, wenn ihr statt der Tokenfrequenz die **Anzahl der Blätter** zählt, in denen der Term vorkommt — das geht, sobald das Splitting steht, und ist ein guter Grund, beide Zahlen nebeneinander zu zeigen.

## 4. Keyness — was ist für ein Jahr charakteristisch?

```bash
python pipelines/06_analysis/ngrams.py keyness --top 6
```

Dunnings Log-Likelihood (G²) vergleicht jedes Jahr gegen alle übrigen — man muss die Suchbegriffe also nicht vorher kennen:

```
  1968: mayer (77), lsd (57), rektor (76), sds (31), universität (126), psychologie (43)
  1971: sprach- (114), grundkurse (120), ökonomie (143), literaturwissenschaften (84), marx (156), marxismus (79)
  1972: spd (320), gups (93), csu (334), shb (411), the (159), barzel (51)
  1973: mhg (273), bhg (1122), sem (472), gew (457), fsr (233), dab (144)
```

Lesbar als Chronik: 1968 dreht sich alles um Rektor Mayer, 1971 um den Streit über marxistische Grundkurse in den Sprach- und Literaturwissenschaften, 1972 um Bundespolitik (Barzel, Misstrauensvotum), 1973 um das Bayerische Hochschulgesetz.

Und die Methode findet nebenbei Datenprobleme — genau dafür ist sie am Anfang gut:

* `the (159)` in 1972 → es liegt englischsprachiges Material im Bestand; im selben Band geht es um die GUPS, eine palästinensische Studierendenorganisation, und um Abschiebungen im Herbst 1972.
* `onan (31)`, `dow (27)`, `treratola (25)`, `bla (33)` → OCR-Schrott, konzentriert in bestimmten Bänden. Ein Signal, sich die Scanqualität von Nr. 004 anzusehen.
* `sprach-` mit Bindestrich am Ende → eine Dehyphenierung, die nicht gegriffen hat (Trennung über einen Blockwechsel hinweg).

## 5. KWIC — Konkordanz, der Realitätscheck für jede Zahl

```bash
python pipelines/06_analysis/ngrams.py --bands 0118_0009,0118_0013 kwic Berufsverbot --limit 2
```

```
  [1972] …in den Räumen der Hochschule! WEG MIT DEM [BERUFSVERBOT] FÜR DEMOKRATEN UND INSBESONDERE KOMMUNISTEN…
  [1972] …müssen mit an vorderster Front gegen das  [Berufsverbot] stehen. Denn genau uns, denen schon an den H…
  [1973] …eine Personalakte beim KuMi (zwecks späterem [Berufsverbot]). Dieses BHG zeichnet sich also v.a. dadurch…
  [1973] …eine Personalakte beim KUMi (zwecks späterem [Berufsverbot]). Dieses BHG zeichnet sich also v.a. dadurch…
```

Keine Zahl aus 1–4 sollte in einen Text, ohne dass jemand ein Dutzend Belege gelesen hat — Frequenzen sagen nichts über Bedeutung, Ironie oder Negation. Nebenbei zeigen die beiden 1973er Belege (`KuMi` / `KUMi`) ein **Doppelstück**: dasselbe Blatt liegt zweimal im Bestand. Genau das findet der `content_hash` aus der Korpusstruktur automatisch, sobald die Dokumente geschnitten sind.

---

## Was ich zuerst machen würde

1. **1 und 2** heute — zwei Kommandos, und ihr habt eine erste Beschreibung des Vokabulars plus die Kandidatenliste für alles Weitere.
2. **4 (Keyness)** als nächstes, weil es in derselben Rechnung Befunde *und* Datenqualitätsprobleme liefert.
3. **3 (Diachronie)** für den Vortrag — eine Kurve pro Term, das trägt eine Folie.
4. **5 (KWIC)** durchgehend als Kontrolle, nie als eigenständige Analyse.

Erst danach lohnen die Verfahren, die Dokumentgrenzen brauchen: Frequenz nach ausstellender Organisation (LSD vs. RCDS vs. MSB), Blattzahl statt Tokenzahl, Kollokationen mit statistischem Assoziationsmaß, Topic Models. Die stehen im Vorschlag unter „grenzabhängig" und werden zusätzlich auf der `confirmed`-Teilmenge gegengerechnet.

Ein Hinweis zum Deutschen: All das arbeitet auf ungelemmatisierten Wortformen, `studenten` und `student` sind also zwei Einträge. Für einen ersten Zugriff ist das vertretbar; wenn ihr lemmatisieren wollt, ist `spacy` mit `de_core_news_sm` der übliche Weg — dann aber bitte als eigener, dokumentierter Vorverarbeitungsschritt, nicht stillschweigend.
