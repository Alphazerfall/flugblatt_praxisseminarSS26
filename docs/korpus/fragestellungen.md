# Wie aus N-Grammen ein Befund wird

Das Problem mit Frequenzlisten: Sie bestätigen meistens, was man ohnehin weiß. Dass 1968 „Notstand" das Thema war und 1972 „Berufsverbot", bringt keine Historikerin zum Aufhorchen — das steht in jedem Überblickswerk. Der Aufwand rechtfertigt sich erst, wenn das Korpus etwas kann, was Lesen nicht kann. Das sind vier Dinge, und drei davon habe ich am vorhandenen Material getestet.

---

## 1. Vergleichen statt zählen

Eine Häufigkeitsliste des Gesamtkorpus beschreibt einen Durchschnitt, den es nicht gibt. Interessant wird es, wenn zwei Teilkorpora **gegeneinander** gerechnet werden.

Als Vorprobe habe ich Seiten grob nach politischem Lager sortiert (eine Seite zählt, wenn ein Kürzel mindestens dreimal und mindestens doppelt so oft wie jedes andere vorkommt — 301 Seiten RCDS, 232 Seiten MSB/SHB/SDS) und die Vokabulare mit G² verglichen:

| typisch RCDS | | typisch MSB/SHB |  |
|---|---|---|---|
| `universität` | 237 : 75 | `arbeiterklasse` | 2 : 62 |
| `entwurf` | 82 : 9 | `gewerkschaftlichen` | 0 : 50 |
| `öffentlichkeit` | 76 : 12 | `orientierung` | 4 : 66 |
| `mandat` | 80 : 18 | `sozialdemokratischen` | 0 : 47 |
| `artikel` | 51 : 4 | `ddr` | 5 : 61 |
| `freiheit` | 52 : 10 | `dkp` | 7 : 61 |
| `henrich`, `obermair`, `schaidinger` (Namen) | | `gew`, `laf`, `vds` (Organisationen) | |

Das ist bereits ein Befund und keine Trivialität: Die beiden Lager reden nicht nur über verschiedene Themen, sie benutzen **verschiedene Bezugsgrößen**. Der RCDS argumentiert institutionell und personalisiert (Satzungsentwurf, Mandat, Öffentlichkeit, namentlich genannte Professoren und Ministerialbeamte), die Linke argumentiert über Kollektive und Dachverbände (Arbeiterklasse, gewerkschaftliche Orientierung, GEW, VDS). „Freiheit" ist ein RCDS-Wort, „demokratisch" ein Wort der Gegenseite — beide beanspruchen dasselbe normative Feld mit unterschiedlichem Vokabular.

**Achtung:** Die Zuordnung oben ist ein Behelf. Eine Seite, die „RCDS" oft nennt, kann auch ein Angriff *auf* den RCDS sein. Belastbar wird das erst über das Feld `issuers` aus der Korpusstruktur. Genau dafür lohnt sich diese Arbeit — die Vorprobe zeigt, dass der Ertrag da ist.

Weitere Achsen desselben Typs: dieselbe Gruppe früh vs. spät (radikalisiert sich der SHB zwischen 1969 und 1973 sprachlich?), Flugblatt vs. AStA-Info (Agitation vs. Verwaltung), Regensburg vs. überregionale Nachdrucke.

## 2. Nach Abwesenheit suchen

Das ist der Zugriff, den close reading strukturell nicht hat: Was **nicht** im Korpus steht, fällt beim Lesen nicht auf, weil man nur liest, was da ist. Ein Beispiel, das ich geprüft habe:

```
Seiten mit „§218" / „Abtreibung" / „Fristenlösung":
  1967:  0/13     1970:  0/294     1973:  2/1518
  1968:  0/85     1971:  1/629
  1969:  0/317    1972:  3/1608
```

Von diesen acht Treffern sind sechs Fehltreffer (Bombentonnage „218.700" in einem Vietnam-Text, „Selbstabtreibung" als Metapher, eine Seminarthemenliste). Übrig bleibt **genau ein Flugblatt**, Juli 1971: „WEG MIT DEM ABTREIBUNGSPARAGRAPHEN". Eines, auf 4 464 Seiten.

Parallel dazu die Kurve für `frauen` pro 10 000 Token:

```
1967   1968   1969   1970   1971   1972   1973
0.00   1.01   1.95   2.25   1.07   0.17   0.15
```

Das läuft der nationalen Entwicklung **entgegen**: Die §218-Kampagne ab 1971 war eines der mobilisierendsten Themen der Zeit, und in den Regensburger Flugblättern verschwindet das Frauenthema genau dann. Das ist die Sorte Befund, die man vorzeigen kann — dateierbar, quantifiziert, kontraintuitiv.

**Bevor ihr das behauptet, zwei Kontrollen.** Erstens Komposition: Die Bände 006–014 könnten schlicht anderes Material enthalten (mehr AStA-Bürokratie, weniger Agitation), dann misst die Kurve die Bestandszusammensetzung und nicht den Diskurs. Prüfen über `doc_type`, sobald das Splitting steht. Zweitens Vokabular: Vielleicht heißt es 1973 nicht mehr „Frauen", sondern anders — `emanzipation`, `hausfrau`, `kollegin`, `genossin` gegenprüfen. Hält der Befund beiden Kontrollen stand, ist er publikabel.

Weitere Abwesenheitsfragen: Wann taucht „Ökologie"/„Umwelt" auf (in Bayern ab Mitte der 70er ein Thema — hier vermutlich noch nicht)? Ab wann verschwindet „Springer"? Kommt „Ausländer"/„Gastarbeiter" vor?

## 3. Das umkämpfte Wort

Beide Lager sagen „Demokratisierung", „Freiheit", „Interessen der Studenten" — aber sie meinen Verschiedenes. Das lässt sich zeigen, und zwar über **Kollokationen**: Welche Wörter stehen im Fenster von ±5 Tokens um den Begriff, getrennt nach Lager und nach Jahr?

Der Befund hätte die Form: „‚Demokratisierung' steht beim RCDS neben `satzung`, `mandat`, `wahl`; beim MSB neben `betrieb`, `arbeiterklasse`, `basis`. Zwischen 1969 und 1972 verschiebt sich der Gebrauch von X nach Y." Das ist eine begriffsgeschichtliche Aussage mit Zahlen dahinter — der Typ Ergebnis, für den Korpusmethoden in der Zeitgeschichte überhaupt eingesetzt werden.

Braucht: Kollokationsfenster plus ein Assoziationsmaß (G² oder Log-Dice), etwa 30 Zeilen Code, und die `issuers`-Metadaten.

## 4. Die lokale Besonderheit

Die Universität Regensburg nahm 1967 den Lehrbetrieb auf. Diese Sammlung dokumentiert eine Studentenbewegung an einer Hochschule **ohne eigene Tradition** — es gab keinen Vorgängerdiskurs, an den man anknüpfen konnte. Die dazu passende Frage ist keine über Regensburg, sondern eine allgemeine: **Was importiert eine solche Bewegung fertig, und was entwickelt sie selbst?**

Operationalisierbar über den Abgleich mit einem Referenzkorpus (DTA/DWDS-Zeitungskorpus der Jahre, oder die digitalisierten Flugblattbestände anderer Universitäten): Wörter, die hier zeitgleich mit dem überregionalen Diskurs auftauchen, sind importiert; Wörter, die vorher oder nur hier auftreten, sind lokal. In eurer Liste stehen dafür schon Kandidaten — `bhg` (1 125 Treffer, bayerisches Spezifikum), `sprach-lit`, `mhg`, `fsr`.

---

## Woran man merkt, dass ein Befund neu ist

Vier Kriterien, die ich anlegen würde, bevor etwas in den Vortrag kommt:

1. **Dateierbar** — der Befund hat ein Jahr oder einen Wendepunkt, nicht nur eine Rangliste.
2. **Kontraintuitiv oder mindestens nicht selbstverständlich** — wenn eine Kennerin der Periode „ja, klar" sagt, war es Aufwand ohne Ertrag.
3. **Am Einzelbeleg überprüfbar** — zu jeder Zahl gehören fünf KWIC-Zeilen, die man vorlesen kann. Ein Befund, der beim Nachlesen zerfällt, war ein Artefakt.
4. **Gegen die eigene Datenlage geprüft** — Bestandszusammensetzung, OCR-Qualität, Dokumentgrenzen. Jede der drei kann eine schöne Kurve erzeugen, die nichts über die Geschichte sagt.

Und die unbequeme Ehrlichkeit dabei: Die stärksten Ergebnisse dieses Korpus werden **Vergleiche und Abwesenheiten** sein, nicht Häufigkeiten. Beide brauchen die Metadatenebene — Lager, Datum, Textsorte. Die Frequenzliste läuft ohne alles; sie ist deshalb der Anfang und nicht das Ergebnis.
