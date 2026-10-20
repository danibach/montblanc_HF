import json

from synth import as_track, gpx_bytes, hike_and_fly

from mbhf.browser import analyse_json, places_query, resolve_places_json


def test_result_is_json_and_marked_as_browser():
    out = json.loads(analyse_json("day.gpx", gpx_bytes(as_track(hike_and_fly()))))
    assert out["ok"] is True
    assert out["result"]["engine"]["where"] == "browser"
    assert out["result"]["outing"]["status"] == "ok"


def test_errors_are_short_and_without_internals():
    out = json.loads(analyse_json("virus.exe", b"MZ"))
    assert out["ok"] is False and "IGC, GPX, KML or FIT" in out["error"]
    out = json.loads(analyse_json("vide.gpx", b"<gpx"))
    assert out["ok"] is False and "Traceback" not in out["error"]


def test_places_round_trip():
    res = json.loads(analyse_json("day.gpx", gpx_bytes(as_track(hike_and_fly()))))["result"]["outing"]
    q = places_query(json.dumps(res))
    assert q and q.startswith("[out:json]")
    out = json.loads(resolve_places_json(json.dumps(res), json.dumps({"elements": []})))
    assert out["country"] is None
