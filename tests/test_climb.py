import pytest
from synth import as_track, gpx_bytes, hike_and_fly, two_flights

from mbhf.analyse import analyse_bytes
from mbhf.climb import MAX_POINTS, climb_of
from mbhf.segment import FLIGHT, VEHICLE, WALK


def run(g):
    return analyse_bytes("day.gpx", gpx_bytes(as_track(g)))


def test_climb_of_a_hike_and_fly():
    res = run(hike_and_fly())
    c = climb_of(res["trace"], res["outing"]["flights"])
    o = res["outing"]
    # the climb ends at the take-off and holds the D+ on foot (the walk after the landing is flat)
    assert c["line"][-1] == pytest.approx([o["takeoff"]["lat"], o["takeoff"]["lon"]], abs=2e-4)
    assert c["dplus_m"] == pytest.approx(o["dplus_m"], rel=0.1)
    assert 1.5 * 3600 < c["duration_s"] < 3 * 3600
    assert 2 <= len(c["line"]) <= MAX_POINTS


def test_climb_goes_to_the_main_flight():
    res = run(two_flights())
    flights = res["outing"]["flights"]
    main = max(flights, key=lambda f: f["drop_m"])
    c = climb_of(res["trace"], flights)
    assert c["line"][-1] == pytest.approx([main["takeoff"]["lat"], main["takeoff"]["lon"]], abs=2e-4)


def toy_trace(labels):
    n = len(labels)
    return {"t0": "2026-06-01T08:00:00+00:00", "t": [60.0 * i for i in range(n)],
            "lat": [45.0 + 0.001 * i for i in range(n)], "lon": [6.0] * n,
            "alt": [1000 + 50 * i for i in range(n)], "m": labels}


def test_a_drive_before_the_walk_is_left_out():
    labels = [VEHICLE] * 5 + [WALK] * 10 + [FLIGHT] * 5
    c = climb_of(toy_trace(labels), [])  # no flight times: the first flight fix is the take-off
    assert c["duration_s"] == 10 * 60
    assert c["line"][0] == [45.005, 6.0] and c["line"][-1] == [45.015, 6.0]


def test_no_climb_without_walk_or_flight():
    assert climb_of(toy_trace([WALK] * 10), []) is None
    assert climb_of(toy_trace([FLIGHT] * 10), []) is None
    assert climb_of(None, []) is None
