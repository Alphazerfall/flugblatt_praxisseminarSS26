#!/usr/bin/env python3
"""Prompt, Antwortschema und Belegprüfung für die Metadaten-Extraktion (v2).

Als eigenes Modul, damit `extract_metadata.py` nur zwei Zeilen ändern muss:

    from prompt_v2 import build_prompt, RESPONSE_SCHEMA, check_grounding

    def extract_batch(client, model, year, batch, known_orgs=(), n_pages=None):
        interaction = client.interactions.create(
            model=model,
            input=[{"type": "text",
                    "text": build_prompt(year, batch, known_orgs=known_orgs)}],
            response_format={"type": "text", "mime_type": "application/json",
                             "schema": RESPONSE_SCHEMA},
            temperature=0,          # Extraktion, nicht Textproduktion
        )
        return {r["id"]: r for r in json.loads(interaction.output_text)["results"]}

Der Gewinn gegenüber v1 steckt weniger im Wortlaut als in zwei Strukturänderungen:
jedes Feld führt ein wörtliches Belegzitat mit (maschinell prüfbar, siehe
check_grounding), und die Felder stehen in der Reihenfolge Beleg -> Wert, damit das
Modell erst zitiert und dann normalisiert statt umgekehrt.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

# --------------------------------------------------------------------- Prompt

INSTRUCTIONS = """\
AUFGABE
Du erhältst den OCR-Text mehrerer Flugblätter der westdeutschen Studentenbewegung
(Universität Regensburg, 1967-1973). Jedes Blatt beginnt mit "=== Segment <id> ===";
"--- Seite N ---" markiert Seitenwechsel innerhalb desselben Blatts. Extrahiere für
JEDES Segment die unten genannten Felder.

Der Text ist in die Blöcke der OCR-Erkennung gegliedert. Jeder Block beginnt mit
einer Kennung "[S-B]" (S = Seite, B = Nummer des Blocks auf dieser Seite); Zeilen
ohne Kennung gehören zum Block darüber. Die Kennungen sind nicht Teil des
Flugblatts - sie dienen nur dazu, anzugeben, wo ein Beleg steht.

ZWECK UND FEHLERKOSTEN
Die Ergebnisse dienen einer quellengebundenen Erschließung und späteren historischen
Auswertung (u.a. einer Zeitreihe nach Erscheinungsdatum). Eine unbelegte Ergänzung
erzeugt eine falsche Zuschreibung oder Datierung, die sich in dieser Auswertung nicht
mehr von einer echten unterscheiden lässt. Ein leeres Feld ist deshalb IMMER einer
plausiblen, aber unbelegten Angabe vorzuziehen - lieber ehrlich leer als falsch voll.

QUELLENLAGE
Die Texte stammen aus OCR von Schreibmaschinen-Durchschlägen und Matrizendrucken.
Rechne mit Sperrschrift ("R e s o l u t i o n"), verrutschten Zeichen, fehlenden
Umlauten und Wörtern, die am Zeilenende getrennt sind. Leisten aus wiederholten
Kürzeln ("LSD - LSD - LSD - ...", "RCDS-RCDS-RCDS") sind Kopfleisten und nennen
fast immer die herausgebende Gruppe.

Abbildungen erscheinen als eigener Block "[S-B] [Abbildung, maschinell beschrieben -
nicht Text des Blatts: ...]". Die (meist englische) Beschreibung stammt von einem
Bildmodell, nicht vom Flugblatt: Nimm sie nie als Titel, Beleg oder Herausgeber.

Eingangsstempel und Ablagevermerke des Archivs erscheinen als "[S-B]
[Archivvermerk - kein Datum des Blatts: ...]" oder im Text als
"[Archivvermerk]". Das Stempeldatum ist der Tag, an dem das Blatt ins Archiv
kam: Nimm es nie als Datum, auch nicht als Erscheinungsdatum.
Eine Überschrift, deren Zeilen durch eine Abbildung getrennt sind, bleibt eine
Überschrift. Nimm für title_type "incipit" erst dann Fließtext von einer SPÄTEREN
Seite des Segments, wenn auf der/den ersten Seite(n) wirklich keine Überschrift
steht.

GRUNDREGELN
1. Antworte auf Deutsch. Übersetze nicht, fasse nicht zusammen, erfinde nichts.
2. Zu jedem inhaltlichen Feld gehört ein wörtliches Belegzitat aus dem Segmenttext.
   Das Zitat muss zeichengenau im Text vorkommen, einschließlich der OCR-Fehler.
   Gibt es keinen Beleg, lass Wert und Zitat leer.
3. Halte die Feldreihenfolge ein: erst das Belegzitat, dann der daraus abgeleitete Wert.
4. Genau ein Ergebnis je angegebener Segment-id. Nichts zusammenfassen, nichts
   auslassen, Reihenfolge beliebig.
5. Belegzitate enthalten nie die Kennungen "[S-B]". Zu jedem Beleg gehört ein
   Feld *_blocks mit den Kennungen ALLER Blöcke, aus denen das Zitat stammt, als
   Liste ohne eckige Klammern, z.B. ["35-1", "35-2"]. Ohne Beleg bleibt die Liste
   leer. Nenne nur Kennungen, die im Segment wirklich vorkommen.
6. Jedes Segment ist ein eigenes Blatt. Der Kopf nennt seine Seiten
   ("=== Segment 7 (Seiten 12-13) ==="); alle Kennungen eines Ergebnisses müssen auf
   diesen Seiten liegen. Übernimm nie Titel, Datum oder Namen aus einem
   benachbarten Segment - auch dann nicht, wenn ein Blatt unvollständig wirkt.

FELDER

title_evidence  Überschrift des Blatts, wörtlich wie im Text, mit Zeilenumbrüchen.
                Leer, wenn das Blatt keine Überschrift trägt. Eine Überschrift kann
                über mehrere Blöcke gehen - nimm dann alle ihre Zeilen auf. Kurze,
                allein stehende Zeilen am Anfang des Blatts, vor dem Fließtext, sind
                die Überschrift, auch wenn sie in der OCR nicht als solche
                ausgezeichnet sind. Ein als Banner mehrfach
                wiederholter Slogan ("AKTION GELBER PUNKT AKTION GELBER PUNKT AKTION
                GELBER PUNKT ...", wie eine Kopfleiste aus wiederholten Kürzeln, nur
                mit einem ganzen Wort/Satz statt einer Abkürzung) ist ein
                Gestaltungselement, KEINE Überschrift - die eigentliche Überschrift
                oder der erste inhaltliche Satz steht meist direkt darunter.
title_blocks    Kennungen der Blöcke, aus denen title_evidence stammt. Beim Incipit die
                Blöcke, aus denen die ersten Wörter stammen.
title           Dieselbe Überschrift lesbar geglättet: Zeilenumbrüche zu Leerzeichen,
                Sperrschrift zusammengezogen, durchgehende VERSALIEN zu normaler
                Groß-/Kleinschreibung. Der Wortlaut bleibt unverändert und
                vollständig: Kürze eine Überschrift nie ab und hänge kein "..." an.
                Ein "..." steht nur am Ende eines Incipits oder dort, wo es auch im
                Original steht.
title_type      "original" = das Blatt trägt diese Überschrift.
                "incipit"  = es gibt keine Überschrift, das Blatt beginnt direkt mit
                             Fließtext (ganzen Sätzen); nimm genau die ersten 10
                             Wörter des Fließtextes (weniger, wenn der Fließtext
                             kürzer ist) und beende mit "...". Kopfleiste, Datumszeile
                             und Herausgeberangabe zählen nicht zum Fließtext. Nicht
                             mehr als 10 Wörter, auch wenn der erste Satz länger ist.
                             Erfinde niemals einen beschreibenden Titel. Die Glättung
                             oben bei `title` (Sperrschrift, VERSALIEN) gilt genauso
                             für ein Incipit - "MITBÜRGERINNEN MITBÜRGER !" wird zu
                             "Mitbürgerinnen Mitbürger!", nicht unverändert übernommen.

series          Name der Reihe, wenn das Blatt Teil einer nummerierten oder benannten
                Folge ist - erkennbar an einer Kopfleiste wie "AStA - Info + AStA - Info
                + ..." oder an einem Reihentitel wie "Informationen aus dem Fachbereich
                Wirtschaftswissenschaft". Wörtlich, aber ohne die Wiederholungen:
                "AStA-Info", nicht "AStA - Info + AStA - Info + AStA - Info".
                Leer, wenn das Blatt zu keiner Reihe gehört.
                Die Reihe ist NICHT der Herausgeber und NICHT der Titel: Bei
                "AStA-Info: Der Henker wartet schon" ist "AStA-Info" die Reihe,
                "AStA" der Herausgeber und "Der Henker wartet schon" der Titel.
issue           Zählung innerhalb der Reihe, wörtlich ("Nr. 5", "Nr. 16, 17, 18",
                "2/1973"). Leer, wenn keine angegeben ist.

issuers         Wer das Blatt zu verantworten hat. Leere Liste, wenn niemand erkennbar ist.
  evidence      Textstelle, aus der das hervorgeht: Kopfleiste, Titel, Unterschrift,
                Impressum, Kontaktadresse, Wahlaufruf für die eigene Liste,
                Abschluss-Slogan.
  blocks        Kennungen der Blöcke, aus denen evidence stammt.
  surface       Name wie dort genannt, aber wie bei title geglättet: Sperrschrift
                zusammengezogen ("L I N K E   L I S T E" -> "Linke Liste"), eine als
                Kopfleiste wiederholte Kurzform nur einmal ("LSD- LSD -LSD-..." ->
                "LSD"). Der Name selbst bleibt unverändert, nur die Schreibweise wird
                geglättet.
  role          "issuer"    = ORGANISATION, Gruppe, Gremium oder Komitee, die das Blatt
                              herausgibt. Steht fast immer in der Kopfleiste oder im
                              Impressum.
                "signatory" = EINZELPERSON, die unterzeichnet oder als Verfasser
                              genannt ist.
  Drei Regeln, die du strikt einhalten musst:
  (a) Eine Einzelperson bekommt NIEMALS role "issuer". Personennamen wie
      "Hubert Fexer", "Carola Knirsch", "Roland Asanger" sind "signatory" -
      auch dann, wenn keine Gruppe genannt ist. Dann bleibt die Liste eben ohne
      "issuer"-Eintrag.
  (b) Nimm nur auf, wer das Blatt verantwortet - nicht jede Gruppe, die im Text
      erwähnt, zitiert oder angegriffen wird. Ein Blatt des RCDS über den SDS hat
      nur den RCDS als issuer.
  (c) Die herausgebende Gruppe steht nicht nur in der Kopfleiste. Sie ist auch
      belegt, wenn das Blatt
      - am Ende ein Impressum oder eine Kontaktadresse der Gruppe trägt
        ("SHB Hochschulgruppe Regensburg, Postfach 44"),
      - für die eigene Liste der Gruppe wirbt ("Wählt Liste 3 - SHB!"),
      - mit einem Slogan schließt, der die Gruppe nennt ("Darum: SHB!"),
      - im Titel die Gruppe als Verfasserin der eigenen Erklärung nennt
        ("Erklärung des AStA", "Antrag des AStA an ...", "AStA-Beitrag",
        "Stellungnahme der Fachschaft ..."). Nicht gemeint ist eine Gruppe,
        an die sich das Blatt richtet oder über die es spricht ("Offener Brief
        an den AStA", "Der AStA lügt").
      Nimm die Gruppe dann als "issuer" auf, zusätzlich zu den Unterzeichnern.
      Bevor du ein Blatt nur mit "signatory"-Einträgen abgibst, prüfe das Ende
      des Blatts auf solche Angaben.
  Nenne alle Unterzeichner, ohne Obergrenze. Als "signatory" zählt JEDE Person im
  Unterschriftsblock oder nach "Verantwortlich", "Verantwortl.", "V.i.S.d.P.",
  "gez." oder "i.A." - auch wenn ein Amt dabeisteht ("Maria Brandl,
  Referentin") und auch wenn nur der Nachname genannt ist
  ("Verantwortl.: Ostermeier, Kolb" -> "Ostermeier", "Kolb"). Das Amt gehört
  nicht in surface.

date_evidence   Datumsangabe wörtlich wie im Text ("23. 7. 68", "im November 1968").
                Leer, wenn date_type "undated" ist.
date_blocks     Kennungen der Blöcke, aus denen date_evidence stammt.
date_text       Dieselbe Angabe bereinigt.
date_iso        So genau normalisiert, wie es belegt ist: "1968-07-23", "1968-11"
                oder "1968". Ergänze niemals einen Tag, der nicht dasteht.
date_type       "issued"    = Erscheinungsdatum des Blatts.
                "event"     = Datum einer angekündigten Veranstaltung, die der
                              eigentliche Anlass des Blatts ist (Streikaufruf,
                              Einladung, Demo-Ankündigung); das Blatt ist nicht
                              JÜNGER als dieses Datum (meist kurz davor verteilt,
                              möglich auch am selben Tag).
                "undated"   = das Blatt ist nicht datiert. Das gilt auch, wenn im
                              Fließtext Daten vorkommen, die das Blatt nicht datieren:
                              Rückblicke, Zitate, Quellenangaben, eine vergangene
                              Sitzung, ein nur beiläufig erwähnter künftiger Termin
                              (z.B. eine Wahl als Randbemerkung). Alle Datumsfelder
                              bleiben dann leer.

                WO das Datum steht, entscheidet fast immer über den Typ:
                - ganz oben über oder neben der Kopfleiste, oder unten im Impressum
                  -> "issued"
                - in einem Aufruf oder einer Einladung, deren Anlass es ist ("am
                  Mittwoch, 29. Mai") -> "event"
                - mitten in einem Satz des Fließtextes ("bei der am 14.11.
                  veranstalteten Podiumsdiskussion") -> datiert das Blatt nicht,
                  also "undated"
                Ein Datum, das nur im Fließtext vorkommt, ist so gut wie nie das
                Erscheinungsdatum. Im Zweifel "undated" statt "issued".

doc_type        "flugblatt" | "offener_brief" | "einladung" | "broschuere" |
                "zeitschrift" | "protokoll" | "unklar".
                "unklar" auch dann, wenn das Segment erkennbar mehrere verschiedene
                Dokumente enthält (mehrere Kopfleisten, mehrere Erscheinungsdaten).

confidence      0.0-1.0 für die Zuordnung insgesamt.
"""

# Drei ausgearbeitete Beispiele. Das zweite lehrt die Unterscheidung zwischen
# Erscheinungs- und Veranstaltungsdatum, an der sonst jede spätere Zeitreihe
# systematisch danebenliegt; das dritte die Trennung von Reihe, Herausgeber und
# Titel, die im Findmittel des Archivs in einem Feld zusammenfallen.
EXAMPLES = """\
BEISPIELE
Die folgenden Ein-/Ausgabe-Paare zeigen nur das FORMAT der Antwort und wie man zu
ihr kommt - ihr Inhalt ist zu Demonstrationszwecken erfunden und kommt in den
echten Segmenten unten nicht vor, auch wenn ein echtes Segment ähnlich klingt (z.B.
weil es ebenfalls vom AStA handelt). Übernimm niemals Wortlaut, Namen oder Sätze
aus einem Beispiel in eine echte Ausgabe - jede Ausgabe stammt ausschließlich aus
dem jeweiligen Segmenttext unten in SEGMENTE.

Eingabe:
=== Segment 4 (Seiten 6-7) ===
--- Seite 6 ---
[6-1] 23. 7. 68
[6-2] LSD- LSD - LSD-LSD- LSD- LSD- LSD- LSD- LSD- LSD- LSD-
[6-3] EMIL FRANZEL UND FRANZ BAYER
[6-4] Oder : Wie man das Ansehen der Universität Regensburg
ruiniert
[6-5] Emil Franzel ist den Studenten sattsam als Hilfskammer- ...

Ausgabe:
{"id": 4,
 "title_evidence": "EMIL FRANZEL UND FRANZ BAYER\\nOder : Wie man das Ansehen der Universität Regensburg\\nruiniert",
 "title_blocks": ["6-3", "6-4"],
 "title": "Emil Franzel und Franz Bayer. Oder: Wie man das Ansehen der Universität Regensburg ruiniert",
 "title_type": "original", "series": "", "issue": "",
 "issuers": [{"evidence": "LSD- LSD - LSD-LSD- LSD- LSD- LSD- LSD- LSD- LSD- LSD-",
              "blocks": ["6-2"], "surface": "LSD", "role": "issuer"}],
 "date_evidence": "23. 7. 68", "date_blocks": ["6-1"], "date_text": "23.7.1968",
 "date_iso": "1968-07-23", "date_type": "issued", "doc_type": "flugblatt", "confidence": 0.95}
Begründung für title_blocks: Die Überschrift geht über zwei Blöcke, also stehen
beide in der Liste - und beide Zeilen gehören vollständig in den Titel.

Eingabe:
=== Segment 1 (Seite 1) ===
--- Seite 1 ---
[1-1] STUDENTENAUSSCHUSS IM AKTIONSKOMITEE NOTSTAND
[1-2] STREIK
[1-3] in der
Universität Regensburg
[1-4] am Mittwoch, 29. Mai 1968!
[1-5] Mittwoch - Tag der Selbstentmachtung des Parlaments ...

Ausgabe:
{"id": 1,
 "title_evidence": "STREIK\\nin der\\nUniversität Regensburg\\nam Mittwoch, 29. Mai 1968!",
 "title_blocks": ["1-2", "1-3", "1-4"],
 "title": "Streik in der Universität Regensburg am Mittwoch, 29. Mai 1968!",
 "title_type": "original", "series": "", "issue": "",
 "issuers": [{"evidence": "STUDENTENAUSSCHUSS IM AKTIONSKOMITEE NOTSTAND",
              "blocks": ["1-1"],
              "surface": "Studentenausschuss im Aktionskomitee Notstand", "role": "issuer"}],
 "date_evidence": "am Mittwoch, 29. Mai 1968", "date_blocks": ["1-4"],
 "date_text": "29. Mai 1968", "date_iso": "1968-05-29", "date_type": "event",
 "doc_type": "flugblatt", "confidence": 0.9}
Begründung für date_type: Der Streik wird angekündigt, das Blatt wurde also vor
dem 29. Mai verteilt. Es ist kein Erscheinungsdatum.

Eingabe:
=== Segment 36 (Seiten 52-53) ===
--- Seite 52 ---
[52-1] AStA - Info + AStA - Info + AStA - Info + AStA - Info + AStA - Info
[52-2] DER HENKER WARTET SCHON
[52-3] In den letzten Monaten hat sich im Iran (Persien) eine neue Welle von Terror ...

Ausgabe:
{"id": 36,
 "title_evidence": "DER HENKER WARTET SCHON", "title_blocks": ["52-2"],
 "title": "Der Henker wartet schon",
 "title_type": "original", "series": "AStA-Info", "issue": "",
 "issuers": [{"evidence": "AStA - Info + AStA - Info + AStA - Info",
              "blocks": ["52-1"], "surface": "AStA", "role": "issuer"}],
 "date_evidence": "", "date_blocks": [], "date_text": "", "date_iso": "",
 "date_type": "undated", "doc_type": "flugblatt", "confidence": 0.85}
Begründung für series: Die Kopfleiste nennt die Reihe "AStA-Info"; Herausgeber ist
der AStA, der Titel steht darunter. Die drei Angaben gehören in drei Felder.

Eingabe:
=== Segment 2 (Seiten 2-3) ===
--- Seite 2 ---
[2-1] lsd lsd lsd ls6 - wahlmitteilung - ls6 lsd lsd
[2-2] ARGUMENTE ZUR SACHE I
[2-3] Hochschulgesetz - Mittel zur Disziplinierung
[2-4] Bayerns CSU-Kultusminister Huber sagt sogar manchmal, was er denkt ...
--- Seite 3 ---
[3-1] ... Aus diesem Grunde beschlossen die knapp 200 Anwesenden bei der am 14.11.
vom LSD veranstalteten Podiumsdiskussion über "Hubers Hochschulgesetz" folgende
[3-2] R e s o l u t i o n : ... Sorge Sie dafür, daß bei den Wahlen zum
Studentenparlament vom 25. - 27.11.1968 jene Gruppen gewinnen ...

Ausgabe:
{"id": 2,
 "title_evidence": "ARGUMENTE ZUR SACHE I\\nHochschulgesetz - Mittel zur Disziplinierung",
 "title_blocks": ["2-2", "2-3"],
 "title": "Argumente zur Sache I: Hochschulgesetz - Mittel zur Disziplinierung",
 "title_type": "original", "series": "Wahlmitteilung", "issue": "",
 "issuers": [{"evidence": "lsd lsd lsd ls6 - wahlmitteilung - ls6 lsd lsd",
              "blocks": ["2-1"], "surface": "LSD", "role": "issuer"}],
 "date_evidence": "", "date_blocks": [], "date_text": "", "date_iso": "",
 "date_type": "undated", "doc_type": "flugblatt", "confidence": 0.8}
Begründung für date_type: Im Text stehen zwei Daten, aber keines datiert das Blatt
selbst. "am 14.11. veranstalteten Podiumsdiskussion" ist ein Rückblick mitten im
Satz. "vom 25. - 27.11.1968" ist nur ein beiläufig erwähnter Wahltermin, nicht die
Veranstaltung, um die es dem Blatt selbst geht (anders als beim Streik-Aufruf oben,
wo die Veranstaltung der eigentliche Anlass des Blattes ist) - deshalb kein
"event". Das Blatt ist also "undated", alle Datumsfelder bleiben leer. Wer hier
"1968-11-14" oder "1968-11-25" in date_iso einträgt, verschiebt jede spätere
Zeitreihe.

Eingabe:
=== Segment 12 (Seite 88) ===
--- Seite 88 ---
[88-1] AStA - Info
[88-2] Studentenschaft der Universität Regensburg
[88-3] AKTION GELBER PUNKT AKTION GELBER PUNKT AKTION GELBER PUNKT AKTION GELBER
[88-4] Die Aktion gelber Punkt wird fortgesetzt!
[88-5] FÜR ALLE, die es noch nicht wissen ...

Ausgabe:
{"id": 12,
 "title_evidence": "Die Aktion gelber Punkt wird fortgesetzt!", "title_blocks": ["88-4"],
 "title": "Die Aktion gelber Punkt wird fortgesetzt!",
 "title_type": "original", "series": "AStA-Info", "issue": "",
 "issuers": [{"evidence": "Studentenschaft der Universität Regensburg", "blocks": ["88-2"],
              "surface": "Studentenschaft der Universität Regensburg", "role": "issuer"}],
 "date_evidence": "", "date_blocks": [], "date_text": "", "date_iso": "",
 "date_type": "undated", "doc_type": "flugblatt", "confidence": 0.85}
Begründung für title: "AKTION GELBER PUNKT AKTION GELBER PUNKT AKTION GELBER PUNKT
..." ist wie eine Kürzel-Kopfleiste (siehe QUELLENLAGE) ein wiederholtes
Gestaltungselement, kein Satz und keine Überschrift - die eigentliche Aussage des
Blatts ist der Satz direkt danach. Wer die Wiederholung als title_evidence nimmt,
verliert den eigentlichen Inhalt.

Eingabe:
=== Segment 27 (Seite 41) ===
--- Seite 41 ---
[41-1] Seit Mitte Oktober treffen sich jeden Donnerstagabend etwa zwanzig Kommilitonen im
Republikanischen Club zu offenen Gesprächsrunden über die Zukunft der Universität.
Wer mitreden will, ist eingeladen, ganz gleich welcher Fachrichtung.
[41-2] Karin Vogt, Manfred Reuter

Ausgabe:
{"id": 27,
 "title_evidence": "", "title_blocks": ["41-1"],
 "title": "Seit Mitte Oktober treffen sich jeden Donnerstagabend etwa zwanzig ...",
 "title_type": "incipit", "series": "", "issue": "",
 "issuers": [{"evidence": "Karin Vogt, Manfred Reuter", "blocks": ["41-2"],
              "surface": "Karin Vogt", "role": "signatory"},
             {"evidence": "Karin Vogt, Manfred Reuter", "blocks": ["41-2"],
              "surface": "Manfred Reuter", "role": "signatory"}],
 "date_evidence": "", "date_blocks": [], "date_text": "", "date_iso": "",
 "date_type": "undated", "doc_type": "flugblatt", "confidence": 0.6}
Begründung: Das Blatt beginnt direkt mit ganzen Sätzen, ohne Kopf und ohne eigene
Überschrift - title_evidence bleibt leer (kein Beleg dafür), title_type wird
"incipit", title_blocks nennt trotzdem den Block, aus dem die Wörter stammen. Genau
die ersten 10 Wörter des Fließtextes, mit "..." beendet, auch wenn der Satz
weitergeht. Keine Organisation genannt, nur zwei Einzelpersonen - role "signatory"
für beide, issuers bleibt ohne "issuer"-Eintrag.

Eingabe:
=== Segment 19 (Seite 30) ===
--- Seite 30 ---
[30-1] WOHNHEIMPLÄTZE STATT VERWALTUNGSBAUTEN
[30-2] Noch immer fehlen in Regensburg über tausend Wohnheimplätze ...
[30-3] Deshalb bei der Wahl: Liste 3 - SHB!
[30-4] Ulrike Brandt, Thomas Seidl
[30-5] SHB Hochschulgruppe Regensburg, Postfach 44, 84 Regensburg

Ausgabe:
{"id": 19,
 "title_evidence": "WOHNHEIMPLÄTZE STATT VERWALTUNGSBAUTEN", "title_blocks": ["30-1"],
 "title": "Wohnheimplätze statt Verwaltungsbauten",
 "title_type": "original", "series": "", "issue": "",
 "issuers": [{"evidence": "SHB Hochschulgruppe Regensburg, Postfach 44", "blocks": ["30-5"],
              "surface": "SHB Hochschulgruppe Regensburg", "role": "issuer"},
             {"evidence": "Ulrike Brandt, Thomas Seidl", "blocks": ["30-4"],
              "surface": "Ulrike Brandt", "role": "signatory"},
             {"evidence": "Ulrike Brandt, Thomas Seidl", "blocks": ["30-4"],
              "surface": "Thomas Seidl", "role": "signatory"}],
 "date_evidence": "", "date_blocks": [], "date_text": "", "date_iso": "",
 "date_type": "undated", "doc_type": "flugblatt", "confidence": 0.85}
Begründung für issuers: Das Blatt hat keine Kopfleiste, aber das Impressum am Ende
nennt die Gruppe, und der Wahlaufruf für "Liste 3 - SHB" bestätigt sie. Deshalb
steht die Gruppe als "issuer" neben den beiden Unterzeichnern - anders als bei
Segment 27, wo nirgends eine Gruppe genannt ist.
"""


def segment_header(seg_id, page_range=None, n_pages=None):
    """"=== Segment 3 (Seiten 4-5) ===" - die Seiten machen die Grenze des Blatts
    sichtbar, gegen die das Modell seine Blockkennungen prüfen kann."""
    if page_range:
        start, end = page_range
        pages = f"Seite {start}" if start == end else f"Seiten {start}-{end}"
        return f"=== Segment {seg_id} ({pages}) ==="
    if n_pages:
        return f"=== Segment {seg_id} ({n_pages} {'Seite' if n_pages == 1 else 'Seiten'}) ==="
    return f"=== Segment {seg_id} ==="


def hints_section(hints):
    """Hinweise der maschinellen Prüfung für einzelne Segmente (nur bei der
    Nachfrage). Neutral formuliert: das Modell entscheidet mit Beleg."""
    if not hints:
        return ""
    lines = [f"Segment {sid}: {text}" for sid, text in hints.items()]
    return ("HINWEISE ZU EINZELNEN SEGMENTEN\n"
            "Eine maschinelle Prüfung hat Folgendes bemerkt. Prüfe es am Text und nimm nur auf, "
            "was der Text belegt:\n" + "\n".join(lines))


def build_prompt(year, batch, known_orgs=(), page_counts=None, page_ranges=None, hints=None):
    """batch: Liste von (segment_id, text). known_orgs: Kurznamen aus organizations.json.
    page_ranges: {segment_id: (erste Seite, letzte Seite)} für den Segmentkopf.

    `known_orgs` in den Prompt zu geben, löst einen guten Teil des
    Vereinheitlichungsproblems schon bei der Extraktion: Das Modell greift zur
    bekannten Schreibweise, statt je Batch eine neue zu erfinden.
    """
    parts = [INSTRUCTIONS, EXAMPLES]

    if known_orgs:
        parts.append(
            "BEKANNTE GRUPPEN\n"
            "Ist eine dieser Gruppen gemeint, benutze in `surface` genau diese Schreibweise.\n"
            "Steht im Text eine andere Gruppe, nimm deren Wortlaut - die Liste ist nicht\n"
            "abschließend.\n" + ", ".join(known_orgs) + "\n"
        )

    parts.append(f"JAHRGANG DES BANDES: {year}\n"
                 f"Ein Datum ohne Jahresangabe bezieht sich fast immer auf {year}.\n")

    body = []
    for seg_id, text in batch:
        head = segment_header(seg_id, (page_ranges or {}).get(seg_id),
                              (page_counts or {}).get(seg_id))
        body.append(f"{head}\n{text}")
    parts.append("SEGMENTE\n\n" + "\n\n".join(body))
    if hints:
        parts.append(hints_section(hints))

    # Die eigentliche Arbeitsanweisung steht bewusst hier am Ende, nach den
    # (bei --batch-size 50 oft langen) Segmenttexten, nicht nur in AUFGABE ganz
    # oben - bei langen Eingaben zählt die Position der Anweisung.
    ids = ", ".join(str(seg_id) for seg_id, _ in batch)
    parts.append(
        "Extrahiere jetzt ausschließlich die Segmente aus SEGMENTE oben, nach den "
        "Regeln und Beispielen weiter oben. Segment-ids aus den BEISPIELEN gehören "
        f"nicht in die Ausgabe. Erwartete ids in dieser Antwort: {ids}. Genau ein "
        "JSON-Objekt pro id, in Eingabereihenfolge."
    )

    return "\n\n".join(parts)


# --------------------------------------------------------------------- Schema
# Reihenfolge der Properties = Erzeugungsreihenfolge: erst Beleg, dann Wert.

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title_evidence": {"type": "string"},
                    "title_blocks": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                    "title_type": {"type": "string", "enum": ["original", "incipit", ""]},
                    "series": {"type": "string"},
                    "issue": {"type": "string"},
                    "issuers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "evidence": {"type": "string"},
                                "blocks": {"type": "array", "items": {"type": "string"}},
                                "surface": {"type": "string"},
                                "role": {"type": "string", "enum": ["issuer", "signatory"]},
                            },
                            "required": ["evidence", "blocks", "surface", "role"],
                        },
                    },
                    "date_evidence": {"type": "string"},
                    "date_blocks": {"type": "array", "items": {"type": "string"}},
                    "date_text": {"type": "string"},
                    "date_iso": {"type": "string"},
                    "date_type": {"type": "string",
                                  "enum": ["issued", "event", "undated"]},
                    "doc_type": {"type": "string",
                                 "enum": ["flugblatt", "offener_brief", "einladung",
                                          "broschuere", "zeitschrift", "protokoll", "unklar"]},
                    "confidence": {"type": "number"},
                },
                "required": ["id", "title_evidence", "title_blocks", "title", "title_type",
                             "series", "issue", "issuers", "date_evidence", "date_blocks",
                             "date_text", "date_iso", "date_type", "doc_type", "confidence"],
            },
        },
    },
    "required": ["results"],
}


# ------------------------------------------------------------- Belegprüfung

_WS = re.compile(r"\s+")


def _norm(s):
    return _WS.sub(" ", unicodedata.normalize("NFC", s or "")).strip().lower()


_NONWORD = re.compile(r"[^0-9a-zäöüß]+")


def _squeeze(s):
    """Nur Buchstaben und Ziffern: "AStA - Info + AStA" -> "astainfoasta"."""
    return _NONWORD.sub("", unicodedata.normalize("NFC", s or "").lower())


def quote_is_grounded(quote, segment_text, threshold=0.9):
    """Kommt das Belegzitat wirklich im Segmenttext vor?

    Exakter Vergleich nach Normalisierung von Leerraum und Groß-/Kleinschreibung;
    scheitert das, ein unscharfer Vergleich gegen das ähnlichste gleich lange
    Textfenster. So überstehen kleine Abweichungen (Bindestriche, Sperrschrift)
    die Prüfung, während frei Erfundenes durchfällt.
    """
    q, t = _norm(quote), _norm(segment_text)
    if not q:
        return True                      # leeres Feld ist kein Verstoß
    if q in t:
        return True
    n = len(q)
    if n < 8 or n > len(t):
        return False
    step = max(1, n // 4)
    best = 0.0
    for i in range(0, len(t) - n + 1, step):
        best = max(best, difflib.SequenceMatcher(None, q, t[i:i + n]).ratio())
        if best >= threshold:
            return True
    return False


# Vorname Nachname / H. Nachname / Nachname, Vorname - reicht für die Fälle,
# die uns aufgefallen sind ("Hubert Fexer", "Carola Knirsch", "R. Siegmaier").
PERSON_NAME = re.compile(
    r"^(?:[A-ZÄÖÜ][a-zäöüß]+|[A-ZÄÖÜ]\.)\s+[A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?$"
    r"|^[A-ZÄÖÜ][a-zäöüß]+,\s+[A-ZÄÖÜ][a-zäöüß]+$")
ORG_HINT = re.compile(
    r"(?i)bund|ring|liste|gruppe|komitee|kommittee|ausschu|schaft|verband|partei|union|front|"
    r"zelle|fraktion|initiative|konferenz|referat|\brat\b|gemeinde|jugend|studenten|hochschul|"
    r"universit|fachbereich|fachschaft|aktion|kreis|kollektiv|vereinigung|kommission|senat|"
    r"basis|zentral|e\.\s?v\.|"
    # politische Adjektive: "Demokratische Mitte", "Linke Liste", "Rote Zelle"
    r"demokratisch|liberal|christlich|sozial|marxist|kommunist|sozialistisch|\blinke\b|"
    r"\brote\b|\broter\b|\bmitte\b|unabhängig|studentisch|vertretung|kraft|\bdritte\b|"
    r"arbeit|assistent|katholisch|evangelisch|akademisch")


def looks_like_person(name):
    """Ist der Name eine Einzelperson? Organisationen enthalten fast immer ein
    Gattungswort ('Bund', 'Liste', 'Fachschaft'), Kürzel sind grossgeschrieben."""
    name = (name or "").strip()
    if not name or ORG_HINT.search(name):
        return False
    if name.isupper():                       # LSD, RCDS, MSB Spartakus
        return False
    return bool(PERSON_NAME.match(name))


# Presserechtliche Zeile am Blattende: "Verantwortl.: Asanger, Aulich / Haidplatz 8",
# "Verantwortlich für den Inhalt: Hans Heimerl, Karthaus-Prüll 12". Das Modell
# liest sie gern als Impressum der Gruppe und lässt die Personen weg.
RESPONSIBLE_LINE = re.compile(
    r"(?im)^\s*(?:verantwortlich(?:\s+für\s+den\s+inhalt)?|verantwortl\.|"
    r"v\.\s?i\.\s?s\.\s?d\.\s?p\.?|gez\.)\s*:?\s*([^\n]+)")
ADDRESS = re.compile(r"\d|(?i:str\.|straße|strasse|weg\b|platz\b|postfach|gasse|allee)")
NOT_A_NAME = re.compile(r"(?i)vorsitz|referent|sprecher|präsident|sekretär|beauftragt|"
                        r"^(regensburg|rgb|münchen|bonn|nürnberg|erlangen|würzburg|berlin)$")
NAME_PART = re.compile(r"^(?:[A-ZÄÖÜ]\.\s?|[A-ZÄÖÜ][a-zäöüß]+\s)*[A-ZÄÖÜ][a-zäöüß]{2,}$")


# Sperrschrift: "V e r a n t w o r t l i c h" - mindestens vier Einzelbuchstaben
SPACED_WORD = re.compile(r"\b(?:[^\W\d_] ){3,}[^\W\d_]\b")


def unspace(text):
    """Gesperrt gedruckte Wörter zusammenziehen: "V e r a n t w o r t l i c h :"
    -> "Verantwortlich :"."""
    return SPACED_WORD.sub(lambda m: m.group(0).replace(" ", ""), text or "")


def responsible_names(text):
    """Personen aus Zeilen, die mit "Verantwortlich", "V.i.S.d.P." oder "gez."
    beginnen, bis zur ersten Adresse. Ämter, Orte und Gruppen fallen weg;
    gesperrt gedruckte Stichwörter werden erkannt."""
    names = []
    for m in RESPONSIBLE_LINE.finditer(unspace(text)):
        line = re.split(r"\s[/·]\s|;|\bDruck\b", m.group(1))[0]
        for part in re.split(r",|\bund\b|&", line):
            part = part.strip(" .:-()")
            if not part:
                continue
            if ADDRESS.search(part):
                break
            if NAME_PART.match(part) and not NOT_A_NAME.search(part) and not ORG_HINT.search(part):
                names.append(part)
    return names


def missing_signatories(record, segment_text):
    """Namen aus der Verantwortlich-Zeile, die in keinem Eintrag von issuers
    stehen. OCR-Varianten ("Scheidinger"/"Schaidinger") zählen als vorhanden."""
    def letters(s):
        return re.sub(r"[^a-zäöüß]", "", (s or "").lower())

    surfaces = [letters(i.get("surface")) for i in record.get("issuers") or []]
    missing = []
    for name in responsible_names(segment_text):
        n = letters(name)
        if not any(s and (n in s or s in n or difflib.SequenceMatcher(None, n, s).ratio() >= 0.8)
                   for s in surfaces):
            missing.append(name)
    return missing


def evidence_position(quote, segment_text):
    """Relative Lage des Belegs im Segment (0 = Anfang, 1 = Ende); None wenn
    nicht gefunden. Ein Erscheinungsdatum steht oben oder ganz unten."""
    q, t = _norm(quote), _norm(segment_text)
    if not q or not t or q not in t:
        return None
    return t.index(q) / len(t)


def check_block_ids(record, blocks):
    """Stimmen die genannten Blockkennungen? blocks: {block_id: text} der
    Textblöcke des Segments (ohne Abbildungen).

    Modelle schreiben Kennungen nicht zuverlässig ab. Eine Kennung zählt nur, wenn
    es den Block gibt UND das Belegzitat wirklich darin steht.
    """
    fields = [("title", record.get("title_evidence"), record.get("title_blocks")),
              ("date", record.get("date_evidence"), record.get("date_blocks"))]
    fields += [(f"issuer {iss.get('surface')!r}", iss.get("evidence"), iss.get("blocks"))
               for iss in record.get("issuers") or []]
    problems = []
    for label, quote, ids in fields:
        ids = ids or []
        unknown = [b for b in ids if b not in blocks]
        if unknown:
            problems.append(f"{label}: Block-id unbekannt oder Abbildung: {', '.join(unknown)}")
        elif quote and not ids:
            problems.append(f"{label}: Beleg ohne Block-id")
        elif quote and not quote_is_grounded(quote, "\n".join(blocks[b] for b in ids)):
            problems.append(f"{label}: Beleg steht nicht in den genannten Blöcken")
    return problems


def check_grounding(record, segment_text, collection_year=None, blocks=None):
    """-> Liste von Problemhinweisen. Leere Liste = alles plausibel.

    Läuft ohne Handannotation über alle Records und liefert damit eine
    Qualitätskennzahl für den gesamten Bestand (Belegquote je Feld und Band).
    segment_text ist der Text OHNE Blockkennungen; blocks (optional) die
    Textblöcke des Segments für die Prüfung der Kennungen.
    """
    problems = []
    if blocks is not None:
        problems += check_block_ids(record, blocks)

    if record.get("title") and not quote_is_grounded(record.get("title_evidence"), segment_text):
        problems.append("title_evidence nicht im Text")
    if record.get("date_iso") and not quote_is_grounded(record.get("date_evidence"), segment_text):
        problems.append("date_evidence nicht im Text")
    for iss in record.get("issuers") or []:
        if not quote_is_grounded(iss.get("evidence"), segment_text):
            problems.append(f"issuer-evidence nicht im Text: {iss.get('surface')!r}")

    iso = record.get("date_iso") or ""
    if iso:
        if not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", iso):
            problems.append(f"date_iso nicht wohlgeformt: {iso!r}")
        elif collection_year and iso[:4] != str(collection_year):
            problems.append(f"date_iso {iso} passt nicht zum Jahrgang {collection_year}")
        if record.get("date_type") in ("", "undated"):
            problems.append("date_iso gesetzt, aber date_type leer/undated")
        # Gegenprobe mit dem Eingangsstempel: erschienen kann das Blatt nicht
        # nach dem Tag sein, an dem es ins Archiv kam. (Eine angekündigte
        # Veranstaltung darf dagegen später liegen.)
        received = record.get("received_date") or ""
        if (record.get("date_type") == "issued" and len(iso) == 10 and received
                and not record.get("received_year_uncertain") and iso > received):
            problems.append(f"Erscheinungsdatum {iso} liegt nach dem Eingangsstempel {received}")

    # Englische Funktionswörter im Titel: das Modell hat übersetzt oder zusammengefasst
    title = _norm(record.get("title"))
    if title and re.search(r"\b(the|and|of|for|against|student[s]?|university|flyer|leaflet)\b", title):
        if not quote_is_grounded(record.get("title"), segment_text, threshold=0.95):
            problems.append("Titel wirkt übersetzt/erfunden (englische Wörter, kein Beleg)")

    if record.get("title_type") == "original" and not record.get("title_evidence"):
        problems.append("title_type=original ohne Belegzitat")

    # Erscheinungsdatum steht oben (Kopf) oder ganz unten (Impressum). Steckt der
    # Beleg mitten im Fliesstext, ist es fast immer ein erwaehntes Datum - der
    # Fehler, der die Zeitreihe verschiebt.
    if record.get("date_type") == "issued" and record.get("date_evidence"):
        pos = evidence_position(record["date_evidence"], segment_text)
        if pos is not None and 0.15 < pos < 0.85:
            problems.append(f"date_type=issued, aber der Beleg steht mitten im Text "
                            f"(Position {pos:.0%}) - vermutlich kein Erscheinungsdatum")

    # Einzelpersonen sind Unterzeichner, nicht Herausgeber.
    for iss in record.get("issuers") or []:
        if iss.get("role") == "issuer" and looks_like_person(iss.get("surface")):
            problems.append(f"Person als issuer: {iss.get('surface')!r} - gehoert zu signatory")

    missing = missing_signatories(record, segment_text)
    if missing:
        problems.append(f"Unterzeichner fehlt (Verantwortlich-Zeile): {', '.join(missing)}")

    # Reihentitel steht auf dem Blatt, aber in der Kopfleistenschreibweise
    # ("AStA - Info + AStA - Info"), während wir die geglättete Form wollen
    # ("AStA-Info"). Deshalb hier ohne Trenn- und Leerzeichen vergleichen.
    series = record.get("series") or ""
    if series and _squeeze(series) not in _squeeze(segment_text):
        problems.append(f"series nicht im Text: {series!r}")
    if record.get("issue") and not series:
        problems.append("issue gesetzt, aber keine series")

    return problems


def archive_display(record):
    """Archivübliche Anzeigeform aus dem strukturierten Record.

    Das Findmittel schreibt eine Zeile je Blatt, "Herausgeber: Titel", und
    behandelt Reihentitel wie Herausgeber ("AStA-Info: Der Henker wartet schon").
    Diese Funktion erzeugt dieselbe Form aus unseren Feldern - damit bleiben die
    Daten mit dem Findmittel vergleichbar und für das Archiv lesbar, ohne dass
    wir Struktur aufgeben.

    >>> archive_display({"series": "AStA-Info", "title": "Der Henker wartet schon",
    ...                  "issuers": [{"surface": "AStA", "role": "issuer"}]})
    'AStA-Info: Der Henker wartet schon'
    """
    title = (record.get("title") or "").strip()
    if record.get("issue"):
        title = f"{title}, {record['issue']}".strip(", ")
    prefix = (record.get("series") or "").strip()
    if not prefix:
        surfaces = [i.get("surface", "").strip() for i in record.get("issuers") or []
                    if i.get("role") != "mentioned" and i.get("surface")]
        prefix = ", ".join(surfaces)
    return f"{prefix}: {title}" if prefix and title else (title or prefix)
