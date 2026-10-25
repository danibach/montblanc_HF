import json

from synth import as_track, gpx_bytes, hike_and_fly

from mbhf.analyse import analyse_bytes
from mbhf.rows import outing_row


def test_row_with_names():
    res = analyse_bytes("a.gpx", gpx_bytes(as_track(hike_and_fly())))
    places = {"country": {"code": "FR", "name": "France"}, "commune": "Servoz", "start_place": "Les Granges",
              "summit": {"name": "Pointe Haute", "osm_id": 20, "ele": 2205}, "takeoff": {"name": "Col", "osm_id": 22, "kind": "peak"}}
    row = outing_row(res, places)
    assert row["title"] == "Pointe Haute" and row["country_code"] == "FR" and row["places_pending"] is False
    assert row["score"] == row["dplus_m"] + row["dminus_m"]
    assert row["takeoff_alt"] > 2000 and row["landing_alt"] < 1500
    assert "i_start" not in row["flights"][0] and len(row["trace"]["t"]) > 10
    json.dumps(row)  # must be plain JSON


def test_row_without_names_asks_for_a_retry():
    res = analyse_bytes("a.gpx", gpx_bytes(as_track(hike_and_fly())))
    row = outing_row(res, None)
    assert row["places_pending"] is True and row["title"].startswith("Hike & Fly · ")
    assert row["country_code"] is None


def test_fallback_title_and_empty_lookup_stays_pending():
    from mbhf.rows import fallback_title

    assert fallback_title("2021-09-29", 1606.4) == "Hike & Fly · 29 Sep 2021 · 1,606 m"
    assert fallback_title("2021-09-29", None) == "Hike & Fly · 29 Sep 2021"
    res = analyse_bytes("a.gpx", gpx_bytes(as_track(hike_and_fly())))
    empty = {"country": None, "commune": None, "start_place": None, "summit": None, "takeoff": None}
    row = outing_row(res, empty)  # Overpass answered, but with no names
    assert row["places_pending"] is True and row["title"] == fallback_title(row["outing_date"], row["summit_alt"])
