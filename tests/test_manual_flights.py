"""Flights marked by hand on the map: a refused track can be given its flight."""
import json

from synth import as_track, gpx_bytes, slow_ski_descent

from mbhf.analyse import analyse_bytes, prepare_bytes, with_manual_flights, finish
from mbhf.browser import analyse_json, manual_json, terrain_json


def _ski_span(g):
    t0 = g.points[0].t
    start = g.marks["ski"] if "ski" in g.marks else None
    return t0, start


def _ranges(data):
    """The ski descent of the synthetic track, in seconds after the first fix (3 h climb + 10 min pause)."""
    return [[3 * 3600 + 10 * 60 + 30, 3 * 3600 + 24 * 60 + 10]]


def test_track_without_flight_gets_one_by_hand():
    data = gpx_bytes(as_track(slow_ski_descent()))
    refused = analyse_bytes("ski.gpx", data)["outing"]
    assert refused["status"] == "rejected" and refused["reason"] == "no_flight"

    out = json.loads(manual_json("ski.gpx", data, json.dumps(_ranges(data))))
    assert out["ok"] is True
    o = out["result"]["outing"]
    assert o["status"] == "ok" and len(o["flights"]) == 1
    assert o["dminus_m"] > 300
    assert "Flights marked by hand" in o["warnings"]
    assert out["result"]["manual"] is True
    assert all(0 <= m <= 2 for m in out["result"]["trace"]["m"]) and 1 in out["result"]["trace"]["m"]


def test_reversed_range_is_the_same():
    data = gpx_bytes(as_track(slow_ski_descent()))
    a, b = _ranges(data)[0]
    one = json.loads(manual_json("ski.gpx", data, json.dumps([[a, b]])))["result"]["outing"]
    two = json.loads(manual_json("ski.gpx", data, json.dumps([[b, a]])))["result"]["outing"]
    assert one["score"] == two["score"]


def test_note_survives_the_terrain_check():
    data = gpx_bytes(as_track(slow_ski_descent()))
    res = json.loads(manual_json("ski.gpx", data, json.dumps(_ranges(data))))["result"]
    sha = res["file"]["sha256"]
    # an elevation service that says "the ground is far below": the marked flight stands
    samples = len(res["terrain"]["query"].split("&")[0].split("=")[1].split(","))
    answer = json.dumps({"elevation": [0.0] * samples})
    after = json.loads(terrain_json(sha, answer))
    assert after["ok"] is True
    assert "Flights marked by hand" in after["result"]["outing"]["warnings"]
    assert after["result"]["outing"]["status"] == "ok"


def test_nothing_marked_is_an_error_not_a_crash():
    data = gpx_bytes(as_track(slow_ski_descent()))
    out = json.loads(manual_json("ski.gpx", data, "[]"))
    assert out["ok"] is False and "Traceback" not in out["error"]


def test_normal_analysis_unchanged():
    data = gpx_bytes(as_track(slow_ski_descent()))
    assert json.loads(analyse_json("ski.gpx", data))["result"]["outing"]["reason"] == "no_flight"
