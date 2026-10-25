import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import make_sectors  # noqa: E402


def terrain(suid, city, zip_code, lat, lon):
    return {"suid": suid, "toponym": f"T{suid}", "city": city, "zip": zip_code, "flying_functions_text": "décollage",
            "possible_usages_text": "parapente", "latitude": lat, "longitude": lon}


def test_a_sector_takes_the_take_offs_of_its_communes(monkeypatch):
    monkeypatch.setattr(make_sectors, "SECTORS", [
        ("Chartreuse – Saint-Hilaire", ["St Hilaire du Touvet", "Verdun@38"], []),
        ("Suisse", [], [[46.3, 7.0]]),
    ])
    raw = [terrain(1, "Saint-Hilaire-du-Touvet", "38660", 45.31, 5.89),  # another spelling of the same commune
           terrain(2, "Verdun", "38000", 45.2, 5.8), terrain(3, "Verdun", "09310", 42.8, 1.7)]  # two Verdun
    sectors, problems = make_sectors.build(raw)
    assert sectors[0]["points"] == [[45.31, 5.89], [45.2, 5.8]] and sectors[1]["points"] == [[46.3, 7.0]]
    assert problems == []


def test_a_commune_in_two_sectors_or_unknown_is_reported(monkeypatch):
    monkeypatch.setattr(make_sectors, "SECTORS", [("A", ["Passy"], []), ("B", ["Passy", "Nowhere"], [])])
    _, problems = make_sectors.build([terrain(1, "Passy", "74190", 45.92, 6.69)])
    assert problems == ["B: « Passy » is already in A", "B: no FFVL take-off in « Nowhere »"]


def test_the_real_sectors_have_no_commune_twice():
    keys = {}
    for name, communes, _ in make_sectors.SECTORS:
        for c in communes:
            k = make_sectors.key(c.partition("@")[0]) + c.partition("@")[2]
            assert keys.setdefault(k, name) == name, f"{c} in {keys[k]} and {name}"
