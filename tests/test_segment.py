from datetime import timedelta

import pytest
from synth import Gen, as_track, full_day

from mbhf.merge import merge_tracks
from mbhf.models import Track
from mbhf.segment import Cuts, SegmentationError, segment_track

ROLES = ["bike_out", "ascent", "flight", "walk_after_landing", "bike_return"]
TOL = timedelta(seconds=90)


def _by_role(res):
    return {s.role: s for s in res.segments}


def test_auto_recovers_order_and_boundaries():
    g = full_day()
    res = segment_track(as_track(g))
    assert [s.role for s in res.segments] == ROLES
    seg = _by_role(res)
    # the true boundary lies at the start of the leg that follows each stop
    assert abs(seg["ascent"].t_start - (g.marks["ascent"] - timedelta(seconds=60))) <= TOL
    assert abs(seg["flight"].t_start - g.marks["flight"]) <= TOL
    assert abs(seg["walk_after_landing"].t_start - g.marks["landing_walk"]) <= TOL
    assert abs(seg["bike_return"].t_start - g.marks["bike_return"]) <= TOL
    assert not any("no flight" in w for w in res.warnings)


def test_steep_bike_descent_is_not_taken_for_the_flight():
    g = full_day(steep_descent=True)
    res = segment_track(as_track(g))
    assert [s.role for s in res.segments] == ROLES
    flight = _by_role(res)["flight"]
    assert abs(flight.t_start - g.marks["flight"]) <= TOL
    # the whole outbound ride, steep part included, stays one bike segment
    assert _by_role(res)["bike_out"].duration_s > 29 * 60


def test_user_cut_forces_the_takeoff():
    g = full_day()
    late = g.marks["flight"] + timedelta(minutes=3)
    res = segment_track(as_track(g), Cuts(takeoff=late))
    flight = _by_role(res)["flight"]
    assert flight.user_fixed_start
    assert late <= flight.t_start < late + timedelta(seconds=5)


def test_conflicting_cuts_are_reported():
    g = full_day()
    with pytest.raises(SegmentationError):
        segment_track(
            as_track(g),
            Cuts(takeoff=g.marks["landing_walk"], landing=g.marks["flight"]),
        )


def test_no_flight_is_flagged():
    g = Gen()
    g.leg("bike_out", 15 * 60, 25, 0.1, 80)
    g.leg("ascent", 60 * 60, 4.2, 0.33, 60, wobble=10)
    g.leg(None, 20 * 60, 4.0, -0.33, 240, wobble=10)               # walks back down
    res = segment_track(as_track(g))
    assert not any(s.mode == "flight" for s in res.segments)
    assert any("no flight" in w for w in res.warnings)


def test_files_pinned_to_modes_with_different_sampling():
    """Option 2: separate bike / walk / flight files recorded at different rates."""
    # one generator keeps position and time continuous across the files
    g = Gen()
    g.leg("bike_out", 15 * 60, 25, 0.1, 80, dt=30.0, hint="bike", src=0)
    g.leg("ascent", 120 * 60, 4.2, 0.33, 60, dt=10.0, hint="walk", wobble=10, src=1)
    g.leg("flight", 25 * 60, 38, -1.1, 230, dt=1.0, hint="flight", wobble=25, ramp=20, src=2)
    g.leg("bike_return", 50 * 60, 32, -0.45, 250, dt=30.0, hint="bike", src=3)
    by_src: dict[int, list] = {}
    for p in g.points:
        by_src.setdefault(p.src, []).append(p)
    hints = {0: "bike", 1: "walk", 2: "flight", 3: "bike"}
    tracks = [Track(points=by_src[i], source=f"f{i}", fmt="gpx", hint=hints[i]) for i in range(4)]
    res = segment_track(merge_tracks(tracks))
    assert [s.role for s in res.segments] == ["bike_out", "ascent", "flight", "bike_return"]
    assert res.segments[2].t_start == g.marks["flight"]


def test_specific_file_wins_where_files_overlap():
    """A watch records the whole day; the flight recorder's own file covers the flight."""
    g = full_day()
    watch = as_track(g, source="watch.gpx")
    f0 = g.marks["flight"]
    f1 = g.marks["landing_walk"]
    igc_points = [p for p in g.points if f0 <= p.t < f1]
    igc = Track(points=igc_points, source="vario.igc", fmt="igc", hint="flight")
    merged = merge_tracks([watch, igc])
    assert any("more specific" in w for w in merged.warnings)
    res = segment_track(merged)
    flight = _by_role(res)["flight"]
    assert flight.t_start == f0
    # speeds are smoothed over +-15 s, so a boundary can be a few seconds late
    assert flight.t_end <= f1 + timedelta(seconds=15)
    # inside the flight's time range only flight-hinted points remain
    inside = [p for p in merged.points if f0 <= p.t < f1]
    assert inside and all(p.hint == "flight" for p in inside)


def test_gap_is_reported():
    g = Gen()
    g.leg("bike_out", 10 * 60, 25, 0.1, 80)
    g.t += timedelta(minutes=10)
    g.x += 5000
    g.leg("ascent", 30 * 60, 4.2, 0.33, 80)
    res = segment_track(as_track(g))
    ascent = [s for s in res.segments if s.mode == "walk"][0]
    assert ascent.boundary_gap_s >= 600
