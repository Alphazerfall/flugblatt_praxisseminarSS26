NER-Pipeline
============

Die Pipeline erkennt Entitäten in Datalab-OCR-JSON-Dateien und schreibt die
Ergebnisse als `<datei>.ner.json`.

Labels
------

- `ACTOR`: Organisationen, Autoren, Drucker und Verlage
- `LOC`: Orte und geografische Angaben
- `PERSON`: Personen
- `TIME`: Daten, Zeiträume, Wochentage und Uhrzeiten

Aufruf
------

```powershell
.venv\Scripts\python.exe pipelines\03_ner\ner.py data\test_set\jsonDatalab\test_set.json
```

Als Eingabe sind auch mehrere JSON-Dateien oder Verzeichnisse möglich. Mit
`--model` kann ein anderes spaCy-Modell angegeben werden. Standardmäßig wird
`de_core_news_lg` verwendet.

Term-Dateien (White- und Blacklist)
------------

Eigene Begriffe können manuell in die .txt-Dateien im terms-Ordner hinzugefügt werden. 
Ein Begriff pro Zeile; Leerzeilen und Zeilen mit `#` werden ignoriert.

Blacklist-Einträge beginnen mit `!`, zum Beispiel `!Berlin`. Sie werden nur
für das Label der jeweiligen Datei unterdrückt. Ein normaler Eintrag wird als
Whitelist-Begriff erkannt.
