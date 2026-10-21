import pytest
from synth import as_track, gpx_bytes, hike_and_fly, lift_then_fly, drive_then_walk, hike_then_drive_home, two_flights

from mbhf.analyse import AnalysisError, analyse_bytes, thin
from mbhf.freedist import free_distance
from mbhf.geo import haversine_m
from mbhf.outing import climbs


def run(g):
    return analyse_bytes("day.gpx", gpx_bytes(as_track(g)))


# ---- climbs (the D+ definition: sum of climbs, wiggles under the threshold ignored)

def test_climbs_ignores_small_dips():
    up, down = climbs([0, 50, 45, 100, 95, 90, 40, 80], 15)
    # 0->100 (the 5 m dip is noise), 100->40, 40->80
    assert up == 140 and down == 60


def test_climbs_noise_alone_gives_nothing():
    assert climbs([100, 104, 99, 103, 98, 102], 15) == (0.0, 0.0)


def test_climbs_a_clean_descent():
    assert climbs([500, 400, 300], 15) == (0.0, 200.0)


# ---- free distance (up to three turn points)

def test_free_distance_straight_line():
    coords = [(45.0 + k * 0.001, 6.0) for k in range(100)]
    d, idx = free_distance(coords)
    assert idx[0] == 0 and idx[-1] == 99
    assert d == pytest.approx(haversine_m(*coords[0], *coords[-1]), rel=1e-6)


def test_free_distance_uses_turnpoints_on_a_zigzag():
    # out 10 km east, back 6 km west, out again 10 km east: best route through the turn points
    pts = [(45.0, 6.0 + k * 0.0013) for k in range(0, 101, 5)]
    pts += [(45.0, 6.13 - k * 0.0013) for k in range(5, 66, 5)]
    pts += [(45.0, 6.05 + k * 0.0013) for k in range(5, 101, 5)]
    d, idx = free_distance(pts)
    direct = haversine_m(*pts[0], *pts[-1])
    assert d == pytest.approx(27_400, rel=0.02)   # out 10.2 km + back 6.6 km + out 10.6 km
    assert d > direct * 1.8
    assert 3 <= len(idx) <= 5


def test_free_distance_of_a_single_point():
    assert free_distance([(45.0, 6.0)])[0] == 0.0


# ---- whole outings

def test_hike_and_fly_numbers():
    o = run(hike_and_fly())["outing"]
    assert o["status"] == "ok" and o["reason"] is None
    assert o["dplus_m"] == pytest.approx(1200, abs=40)
    assert 800 < o["dminus_m"] < 900          # thermal climb inside the flight is ignored: net drop
    assert o["score"] == o["dplus_m"] + o["dminus_m"]
    assert o["summit"]["alt"] == pytest.approx(2200, abs=25)
    assert o["start"]["alt"] == pytest.approx(1000, abs=10)
    assert o["takeoff"]["alt"] > 2100 and o["landing"]["alt"] < 1400
    assert 8 < o["flight_free_km"] < 15
    assert o["flight_free_km"] <= o["flight_path_km"]
    assert 9 < o["walk_km"] < 11
    assert o["date"] == "2026-09-12" and o["score_version"] == 1


def test_two_flights_add_up():
    o = run(two_flights())["outing"]
    assert len(o["flights"]) == 2
    assert o["dplus_m"] == pytest.approx(1300, abs=60)
    assert o["dminus_m"] == pytest.approx(1200, abs=60)
    assert o["dminus_m"] == sum(f["drop_m"] for f in o["flights"])


def test_no_flight_is_rejected():
    o = run(drive_then_walk())["outing"]
    assert o["status"] == "rejected" and o["reason"] == "no_flight"


def test_a_ride_up_does_not_count_as_a_climb():
    o = run(lift_then_fly())["outing"]
    assert o["status"] == "rejected" and o["reason"] == "too_little_climb"
    assert o["dplus_m"] < 100


def test_a_drive_home_is_not_a_flight():
    o = run(hike_then_drive_home())["outing"]
    assert o["status"] == "rejected" and o["reason"] == "no_flight"


def test_trace_is_compact_and_aligned():
    r = run(hike_and_fly())
    tr = r["trace"]
    n = len(tr["t"])
    assert 2 <= n <= 1200
    assert len(tr["lat"]) == len(tr["lon"]) == len(tr["alt"]) == len(tr["m"]) == n
    assert tr["t"] == sorted(tr["t"]) and tr["t"][0] == 0
    assert set(tr["m"]) <= {0, 1, 2} and 1 in tr["m"]


def test_file_facts():
    data = gpx_bytes(as_track(hike_and_fly()))
    f = analyse_bytes("My Day.gpx", data)["file"]
    assert f["format"] == "gpx" and f["size"] == len(data) and len(f["sha256"]) == 64


# ---- refusals

def test_file_without_time_is_refused():
    with pytest.raises(AnalysisError, match="timestamp"):
        analyse_bytes("a.gpx", gpx_bytes(as_track(hike_and_fly()), with_time=False))


def test_file_without_altitude_is_refused():
    with pytest.raises(AnalysisError, match="altitude"):
        analyse_bytes("a.gpx", gpx_bytes(as_track(hike_and_fly()), with_alt=False))


def test_wrong_extension_and_empty_and_huge():
    with pytest.raises(AnalysisError, match="IGC, GPX, KML, TCX or FIT"):
        analyse_bytes("virus.exe", b"MZ")
    with pytest.raises(AnalysisError, match="empty"):
        analyse_bytes("a.gpx", b"")
    with pytest.raises(AnalysisError, match="larger"):
        analyse_bytes("a.gpx", b"x" * 100, max_bytes=10)


def test_thinning_keeps_ends_and_spacing():
    pts = as_track(hike_and_fly()).points
    th = thin(pts)
    assert th[0] is pts[0] and th[-1] is pts[-1]
    assert all((b.t - a.t).total_seconds() >= 3 for a, b in zip(th[:-2], th[1:-1]))


def test_free_distance_is_added_up_over_the_flights():
    o = run(two_flights())["outing"]
    assert len(o["flights"]) == 2
    assert o["flight_free_km"] == pytest.approx(sum(f["free_km"] for f in o["flights"]), abs=0.02)
    assert o["flight_free_km"] > max(f["free_km"] for f in o["flights"])
