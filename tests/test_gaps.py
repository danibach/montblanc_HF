"""Recording gaps: walked or driven? (outing.gap_verdict, decided by Dani and Sarah on 24 October 2026)."""
from datetime import datetime, timedelta, timezone

from mbhf.models import Point
from mbhf.outing import gap_verdict
from mbhf.segment import VEHICLE, WALK

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
