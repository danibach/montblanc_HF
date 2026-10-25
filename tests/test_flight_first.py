"""A track that starts with a flight and goes on with a climb on foot counts (help page: "in any order").

A day of vol-bivouac: fly down from the summit, walk up to the next take-off, sleep there, fly again.
The verdict only asks for one flight and 200 m of climbing on foot, whatever the order.
"""
from datetime import timedelta

from synth import Gen, as_track, gpx_bytes

from mbhf.analyse import analyse_bytes


def run(g):
    return analyse_bytes("day.gpx", gpx_bytes(as_track(g)))


def _flight_then_climb(climb_m: float, seed: int = 11, pause_first_s: float = 3 * 60) -> Gen:
    """Recording starts at the take-off (2 300 m): optional short pause, 20 min flight down ~1 100 m, a walk on
    the landing field, then a climb of ``climb_m`` metres on foot."""
    g = Gen(seed=seed, alt=2300.0)
    if pause_first_s:
        g.leg("pause", pause_first_s, 0, 0.0, 60)
    g.leg("flight", 20 * 60, 36, -1100 / 1200, 230, dt=2.0, wobble=20, ramp=15)
    g.leg("landing_walk", 8 * 60, 4.0, 0.0, 250, wobble=10)
    g.leg("up", int(climb_m / 0.15), 2.4, 0.15, 60, wobble=12)
    return g


def test_flight_then_climb_counts():
    o = run(_flight_then_climb(700))["outing"]
    assert o["status"] == "ok", o
    assert len(o["flights"]) == 1
    assert 600 <= o["dplus_m"] <= 780, o["dplus_m"]
    assert 1000 <= o["dminus_m"] <= 1200, o["dminus_m"]
    assert o["score"] == o["dplus_m"] + o["dminus_m"]
    assert not any("did not lead to a take-off" in w for w in o["warnings"])


def test_recording_that_starts_in_the_air_counts():
    o = run(_flight_then_climb(700, pause_first_s=0))["outing"]
    assert o["status"] == "ok", o
    assert len(o["flights"]) == 1 and o["dplus_m"] >= 600


def test_flight_then_too_little_climb_is_refused():
    o = run(_flight_then_climb(120))["outing"]
    assert o["status"] == "rejected" and o["reason"] == "too_little_climb"


def test_vol_bivouac_day_flight_climb_flight():
    g = _flight_then_climb(700)
    g.leg("pause", 5 * 60, 0, 0.0, 60)
    g.leg("flight2", 12 * 60, 36, -600 / 720, 200, dt=2.0, wobble=20, ramp=15)
    g.leg("landing_walk2", 5 * 60, 4.0, 0.0, 200, wobble=10)
    o = run(g)["outing"]
    assert o["status"] == "ok", o
    assert len(o["flights"]) == 2
    assert 600 <= o["dplus_m"] <= 780, o["dplus_m"]
    assert 1500 <= o["dminus_m"] <= 1800, o["dminus_m"]


def test_vol_bivouac_over_two_days_with_the_night_gap():
    g = _flight_then_climb(700)
    g.leg("bivouac", 10 * 60, 0, 0.0, 60)
    g.t += timedelta(hours=11)  # recorder off overnight, same place
    g.leg("morning", 10 * 60, 0, 0.0, 60)
    g.leg("flight2", 12 * 60, 36, -600 / 720, 200, dt=2.0, wobble=20, ramp=15)
    g.leg("landing_walk2", 5 * 60, 4.0, 0.0, 200, wobble=10)
    o = run(g)["outing"]
    assert o["status"] == "ok", o
    assert len(o["flights"]) == 2
    assert 600 <= o["dplus_m"] <= 780, o["dplus_m"]
