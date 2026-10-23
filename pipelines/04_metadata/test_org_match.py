from org_match import other_institution, resolve


def test_other_institution():
    # Nr. 001, Scan 6: university named without its city
    assert other_institution({"surface": "Allgemeiner Studentenausschuß der Universität", "evidence":
                              "INFORMATIONSBLATT FÜR DOZENTEN UND STUDENTEN DER BAYERISCHEN "
                              "JULIUS-MAXIMILIANS-UNIVERSITÄT"})
    assert other_institution({"surface": "AStA der LMU", "evidence": ""})
    assert other_institution({"surface": "AStA Würzburg", "evidence": ""})
    assert not other_institution({"surface": "AStA", "evidence": "AStA der Universität Regensburg"})
    assert not other_institution({"surface": "AStA", "evidence": "AStA - Info"})


def test_lowercase_acronym_alone():
    registry = [("als", ["als"], True)]
    assert resolve("als", registry) == ["als"]
    assert resolve("so wie als Gruppe", registry) == []
