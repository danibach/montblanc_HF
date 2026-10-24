"""Recording gaps: walked or driven? (outing.gap_verdict, decided by Dani and Sarah on 24 October 2026.)
Not walked: a flight with the recorder off? (outing.flight_gap_verdict, a proposal.)"""
from datetime import datetime, timedelta, timezone

from synth import gpx_bytes

from mbhf.access import access_query, parse_access
from mbhf.analyse import access_points, prepare_bytes, with_terrain
from mbhf.models import Point, Track
from mbhf.outing import flight_gap_verdict, gap_verdict
from mbhf.segment import VEHICLE, WALK
from mbhf.terrain import sample_flights

T0 = datetime(2025, 11, 11, 10, 0, tzinfo=timezone.utc)


def gap(minutes, east_m, climb_m, before=WALK, lead_s=600):
    """A walk (or a ride, ``before``) recorded for ``lead_s`` seconds, then a gap of ``minutes`` moving ``east_m``
    and climbing ``climb_m``, then a walk. Returns the verdict of the gap."""
    pts, labels = [], []
    for k in range(0, lead_s + 1, 30):
        pts.append(Point(t=T0 + timedelta(seconds=k), lat=45.9, lon=6.7, alt=600.0))
        labels.append(before if k < lead_s else WALK)
    t1 = pts[-1].t + timedelta(minutes=minutes)
    lon = 6.7 + east_m / (111320.0 * 0.6959)  # cos(45.9°)
    for k in range(0, 601, 30):
        pts.append(Point(t=t1 + timedelta(seconds=k), lat=45.9, lon=lon, alt=600.0 + climb_m))
        labels.append(WALK)
    i = next(k for k in range(1, len(pts)) if (pts[k].t - pts[k - 1].t).total_seconds() > 600)
    return gap_verdict(pts, [p.alt for p in pts], labels, i)


def test_ticket_9_a_drive_with_the_recorder_off():
    # 67 min, 3.57 km, +601 m, just after a ride recorded in the valley: a ride, not a walk
    v = gap(67, 3570, 601, before=VEHICLE)
    assert not v["on_foot"] and v["p_vehicle"] > 0.8 and v["vehicle_near"]
    assert 100 < v["need_min"] < 130 and v["able"] < 0.1  # an average walker needs ~1 h 50; few could do 67 min


def test_the_same_gap_without_a_ride_around_is_a_doubt():
    v = gap(67, 3570, 601)
    assert not v["vehicle_near"] and v["doubt"]  # decided, but to be checked


def test_a_pause_at_the_hut_with_the_recorder_off():
    v = gap(70, 40, -13)
    assert v["on_foot"] and v["pause"]


def test_an_easy_walk_with_the_recorder_off():
    v = gap(60, 2500, 250)  # an average walker needs ~62 min
    assert v["on_foot"] and v["p_vehicle"] < 0.3


def test_an_easy_walk_just_after_parking_stays_on_foot():
    v = gap(90, 2500, 250, before=VEHICLE)  # plenty of time for it on foot
    assert v["on_foot"]


def test_a_lift_far_too_fast_for_anyone():
    v = gap(15, 2000, 900)
    assert not v["on_foot"] and v["p_vehicle"] > 0.95


# ---- a flight with the recorder off (the 2019 Mont-Blanc track: off at the summit, back on 3 400 m above the valley)

def summit_then_gap(drop_m=1500.0):
    """Walk up 1 000 m in 2 h (to 2 000 m), the recorder off for 40 min while moving 15 km and losing
    ``drop_m``, then 10 min of walking on the flat."""
    pts = []
    for k in range(0, 2 * 3600 + 1, 30):
        pts.append(Point(t=T0 + timedelta(seconds=k), lat=45.9 + k * 6000 / 7200 / 111320.0, lon=6.7,
                         alt=1000.0 + 1000.0 * k / 7200))
    top = pts[-1]
    t1 = top.t + timedelta(minutes=40)
    for k in range(0, 601, 30):
        pts.append(Point(t=t1 + timedelta(seconds=k), lat=top.lat, lon=6.7 + (15000 + k) / (111320.0 * 0.6959),
                         alt=2000.0 - drop_m))
    return Track(points=pts, source="synthetic", fmt="gpx")


def ends_ground(samples, after_m):
    """The ground under the gap's ends: right under the summit, ``after_m`` under the first fix after it."""
    gap_fixes = [s for s in samples if s.get("gap")]
    return [s["alt"] - (after_m if s is gap_fixes[-1] else 0.0) if s.get("gap") else s["alt"] - 300 for s in samples]


def test_a_fix_in_the_air_after_the_gap_makes_it_a_flight():
    p = prepare_bytes("a.gpx", gpx_bytes(summit_then_gap()))
    s = sample_flights(p.track, p.seg)
    assert sum(1 for x in s if x.get("gap")) == 2
    o = with_terrain(p, ends_ground(s, after_m=700))["outing"]
    assert o["status"] == "ok" and o["dminus_m"] == 1500 and o["dplus_m"] > 900
    assert o["flights"][0]["recorder_off"] and o["flights"][0]["free_km"] > 11
    assert any("probably a flight with the recorder off" in w for w in o["warnings"])


def test_without_a_fix_in_the_air_it_stays_a_doubt_and_does_not_count():
    # the recorder came back on at the landing: a glide, a lift down or a road look the same
    p = prepare_bytes("a.gpx", gpx_bytes(summit_then_gap()))
    o = with_terrain(p, ends_ground(sample_flights(p.track, p.seg), after_m=5))["outing"]
    assert o["status"] == "rejected" and o["reason"] == "no_flight"
    assert any("perhaps a flight" in w and "to be checked" in w for w in o["warnings"])
    o = with_terrain(p, None)["outing"]  # terrain service unreachable: the same
    assert o["reason"] == "no_flight"


def test_far_from_any_road_or_lift_no_ride_fits_the_time_so_a_flight():
    # no fix in the air, but no road nor station within 4 km of the summit: walk 1 h before riding 15 km
    p = prepare_bytes("a.gpx", gpx_bytes(summit_then_gap()))
    keys = access_points(p)
    assert len(keys) == 2
    o = with_terrain(p, None, [4000.0, 0.0])["outing"]
    assert o["status"] == "ok" and o["dminus_m"] == 1500
    assert any("no road nor lift within 4 km" in w for w in o["warnings"])


def test_a_road_near_the_take_off_leaves_it_a_doubt():
    p = prepare_bytes("a.gpx", gpx_bytes(summit_then_gap()))
    o = with_terrain(p, None, [250.0, 0.0])["outing"]
    assert o["reason"] == "no_flight" and not any("perhaps a flight" in w for w in o["warnings"])


def test_steep_enough_to_ski_down_a_ride_is_possible():
    pts = [Point(t=T0, lat=45.9, lon=6.7, alt=3000.0), Point(t=T0 + timedelta(minutes=40), lat=45.9, lon=6.73, alt=1800.0)]
    f = flight_gap_verdict(pts, [p.alt for p in pts], [WALK, WALK], 1, access={0: 5000.0, 1: 5000.0})
    assert f["ride_able"] == 1.0 and not f["flight"]


def test_the_overpass_answer_gives_a_lower_bound_per_point():
    def counts(*rows):
        return {"elements": [{"type": "count", "tags": {"total": str(c)}} for row in rows for c in row]}
    assert parse_access(counts((0, 0, 0, 0, 0, 2), (5, 9, 9, 9, 9, 9)), 2) == [4000.0, 0.0]
    assert parse_access(counts((0,) * 6), 1) == [5000.0]
    assert parse_access({"elements": []}, 1) is None and parse_access(None, 1) is None
    assert "around:5000,45.83307,6.86524" in access_query([(45.83307, 6.86524)])


def test_a_gap_going_up_is_never_a_flight():
    v = gap(67, 3570, 601)
    pts = [Point(t=T0, lat=45.9, lon=6.7, alt=600.0), Point(t=T0 + timedelta(minutes=67), lat=45.9, lon=6.75, alt=1200.0)]
    f = flight_gap_verdict(pts, [p.alt for p in pts], [WALK, WALK], 1, {0: 600.0, 1: 0.0})
    assert not v["on_foot"] and not f["flight"] and f["p_flight"] == 0.0


def test_a_lift_down_sinks_too_fast_for_a_wing():
    # off at the top station, back on 2 750 m lower 8 min later, 4.6 km away: 5.7 m/s down, a cable car
    pts = [Point(t=T0, lat=45.9, lon=6.7, alt=3800.0), Point(t=T0 + timedelta(minutes=8), lat=45.9, lon=6.76, alt=1050.0)]
    f = flight_gap_verdict(pts, [p.alt for p in pts], [WALK, WALK], 1)
    assert f["sink_ms"] > 4 and not f["flight"] and not f["doubt"]


def test_a_ride_recorded_around_the_gap_weighs_against_a_flight():
    pts = [Point(t=T0 + timedelta(seconds=30 * k), lat=45.9, lon=6.7, alt=2000.0) for k in range(5)]
    pts.append(Point(t=pts[-1].t + timedelta(minutes=40), lat=45.9, lon=6.85, alt=800.0))
    labels = [VEHICLE] * 4 + [WALK, WALK]
    salt = [p.alt for p in pts]
    f = flight_gap_verdict(pts, salt, labels, 5)
    assert f["vehicle_near"] and not f["flight"] and not f["doubt"]  # even from the top, without a fix in the air
