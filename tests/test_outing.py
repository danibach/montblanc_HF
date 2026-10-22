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


def _with_gap(g, after_s, gap_s, climb_m, moved_m=0.0):
    """Cut the recording ``after_s`` seconds into the track for ``gap_s``, coming back ``climb_m`` higher
    and ``moved_m`` metres further north (a car or a lift moves; a short walk does not)."""
    from dataclasses import replace
    from datetime import timedelta

    t_cut = g.points[0].t + timedelta(seconds=after_s)
    g.points = [
        p if p.t < t_cut else replace(p, t=p.t + timedelta(seconds=gap_s), alt=p.alt + climb_m, lat=p.lat + moved_m / 111_320.0)
        for p in g.points
    ]
    return g


def test_nothing_on_foot_across_a_recording_gap():
    """Issue #9: the recorder was off 67 min (a drive, 20 km further and 600 m higher): a walker could not
    have done that, so those 600 m are not climbed on foot. Distance across the gap is not counted either."""
    from synth import hike_and_fly

    plain = run(hike_and_fly())["outing"]
    gapped = run(_with_gap(hike_and_fly(), 30 * 60, 67 * 60, 600, moved_m=20_000))["outing"]
    assert abs(gapped["dplus_m"] - plain["dplus_m"]) < 40
    assert abs(gapped["walk_km"] - plain["walk_km"]) < 0.2
    assert any("recording gap of 67 min" in w and "nothing on foot counted" in w for w in gapped["warnings"])


def test_a_recording_gap_a_walker_could_cover_counts():
    """The recorder was off 25 min while walking: 150 m higher and 800 m further is about 360 m/h and
    2 km/h, a walk. The climb and the distance count, and a warning says so."""
    from synth import hike_and_fly

    plain = run(hike_and_fly())["outing"]
    gapped = run(_with_gap(hike_and_fly(), 30 * 60, 25 * 60, 150, moved_m=800))["outing"]
    assert abs(gapped["dplus_m"] - (plain["dplus_m"] + 150)) < 40
    assert gapped["walk_km"] > plain["walk_km"] + 0.5
    assert any("recording gap of 25 min" in w and "plausible on foot" in w for w in gapped["warnings"])


def test_a_rest_with_the_recorder_off_loses_nothing():
    """15 min in a hut with the recorder off, same place and same height: everything before still counts."""
    from synth import hike_and_fly

    plain = run(hike_and_fly())["outing"]
    gapped = run(_with_gap(hike_and_fly(), 30 * 60, 15 * 60, 0))["outing"]
    assert gapped["status"] == "ok"
    assert abs(gapped["dplus_m"] - plain["dplus_m"]) < 40
    assert abs(gapped["walk_km"] - plain["walk_km"]) < 0.2


def test_a_gap_too_fast_or_too_steep_for_a_walker_does_not_count():
    """The same 25 min, but 600 m higher with no distance (a lift, 1 440 m/h): not a walk."""
    from synth import hike_and_fly

    plain = run(hike_and_fly())["outing"]
    gapped = run(_with_gap(hike_and_fly(), 30 * 60, 25 * 60, 600, moved_m=300))["outing"]
    assert abs(gapped["dplus_m"] - plain["dplus_m"]) < 40


def test_a_pause_with_the_recorder_on_changes_nothing():
    from synth import Gen

    g = Gen(seed=4, alt=1000.0)
    g.leg("up1", 50 * 60, 2.6, 500 / 3000, 60, wobble=12)
    g.leg("rest", 25 * 60, 0, 0.0, 60)          # 25 min standstill, still recording
    g.leg("up2", 50 * 60, 2.6, 500 / 3000, 60, wobble=12)
    g.leg("pause", 5 * 60, 0, 0.0, 60)
    g.leg("flight", 20 * 60, 38, -900 / 1200, 230, dt=2.0, wobble=25, ramp=20)
    g.leg("landing_walk", 6 * 60, 4.0, -0.01, 250, wobble=15)
    o = run(g)["outing"]
    assert o["status"] == "ok" and 950 <= o["dplus_m"] <= 1060
    assert not any("gap" in w for w in o["warnings"])


def test_a_climb_given_up_does_not_count():
    """Issue #9: a climb, too much wind, down on foot, a drive to another take-off, a short climb and a
    flight. Only the climb that led to the take-off counts."""
    from synth import Gen

    g = Gen(seed=5, alt=900.0)
    g.leg("up_given_up", 60 * 60, 2.6, 700 / 3600, 60, wobble=12)
    g.leg("wait", 20 * 60, 0, 0.0, 60)
    g.leg("down_on_foot", 45 * 60, 3.0, -700 / 2700, 240, wobble=12)
    g.leg("drive", 25 * 60, 45, 900 / 1500, 120, dt=3.0)
    g.leg("up", 40 * 60, 2.6, 300 / 2400, 60, wobble=12)
    g.leg("pause", 5 * 60, 0, 0.0, 60)
    g.leg("flight", 20 * 60, 38, -1100 / 1200, 230, dt=2.0, wobble=25, ramp=20)
    g.leg("landing_walk", 6 * 60, 4.0, -0.01, 250, wobble=15)
    o = run(g)["outing"]
    assert len(o["flights"]) == 1
    assert 250 <= o["dplus_m"] <= 360, o["dplus_m"]
    assert any("did not lead to a take-off" in w for w in o["warnings"])


def test_a_climb_after_the_last_flight_counts():
    """Two flights, then a third climb with no take-off (back up to the bivouac, or to fetch the car):
    it is climbed on foot and the file holds a flight, so it counts."""
    from synth import two_flights

    base = run(two_flights())["outing"]
    g = two_flights()
    g.leg("up3", 40 * 60, 2.4, 400 / 2400, 20, wobble=12)
    g.leg("down3", 30 * 60, 3.0, -400 / 1800, 200, wobble=12)
    o = run(g)["outing"]
    assert len(o["flights"]) == 2
    assert abs(o["dplus_m"] - (base["dplus_m"] + 400)) < 60, (o["dplus_m"], base["dplus_m"])
    assert not any("did not lead to a take-off" in w for w in o["warnings"])


def test_a_climb_after_the_last_flight_counts_even_when_a_ride_follows():
    """Same, but a ride follows the climb (car, lift): the climb was still done on foot."""
    from synth import two_flights

    base = run(two_flights())["outing"]
    g = two_flights()
    g.leg("up3", 40 * 60, 2.4, 400 / 2400, 20, wobble=12)
    g.leg("drive", 25 * 60, 45, 900 / 1500, 120, dt=3.0)
    o = run(g)["outing"]
    assert len(o["flights"]) == 2
    assert abs(o["dplus_m"] - (base["dplus_m"] + 400)) < 60, (o["dplus_m"], base["dplus_m"])


def test_a_track_with_no_flight_at_all_still_shows_its_climbing():
    from synth import Gen

    g = Gen(seed=9, alt=900.0)
    g.leg("up", 60 * 60, 2.6, 600 / 3600, 60, wobble=12)
    g.leg("down", 45 * 60, 3.0, -600 / 2700, 240, wobble=12)
    o = run(g)["outing"]
    assert o["status"] == "rejected" and o["reason"] == "no_flight"
    assert o["dplus_m"] > 500
