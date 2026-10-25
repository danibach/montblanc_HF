"""Position errors that go somewhere and come back (parsers.common.drop_jumps)."""
from datetime import datetime, timedelta, timezone

from mbhf.models import Point
from mbhf.parsers.common import drop_jumps

T0 = datetime(2024, 11, 10, 4, 0, tzinfo=timezone.utc)
DLAT = 1 / 111320.0  # one metre north


def walk(n, start_s=0, lat=45.85, alt=3800.0, step_m=1.0):
    return [Point(t=T0 + timedelta(seconds=start_s + k), lat=lat + k * step_m * DLAT, lon=6.83, alt=alt) for k in range(n)]


def test_a_detour_far_away_and_back_is_dropped():
    # the Mont-Blanc night (Nov 2024): at 3,800 m, 5 km away at an impossible speed for 14 min, then back
    before = walk(600)
    away = [Point(t=T0 + timedelta(seconds=600 + k), lat=45.85 - 5000 * DLAT, lon=6.83, alt=1500.0) for k in range(840)]
    after = walk(300, start_s=1440 + 1320, lat=before[-1].lat)  # 22 minutes without a fix, then on where it was
    kept, n = drop_jumps(before + away + after)
    assert n == 840 and all(p.alt == 3800.0 for p in kept)


def test_one_wild_fix_is_dropped():
    pts = walk(120)
    pts[60] = Point(t=pts[60].t, lat=pts[60].lat + 3000 * DLAT, lon=6.83, alt=3800.0)
    kept, n = drop_jumps(pts)
    assert n == 1 and len(kept) == 119


def test_fixes_of_the_same_second_far_apart_start_a_detour():
    before = walk(300)
    glitch = [Point(t=before[-1].t, lat=45.85 - 1500 * DLAT * k, lon=6.83, alt=3000.0) for k in range(1, 4)]
    after = walk(300, start_s=900, lat=before[-1].lat)
    kept, n = drop_jumps(before + glitch + after)
    assert n == 3


def test_a_fast_ride_that_does_not_come_back_is_kept():
    # a motorway at 160 km/h for 20 minutes: no way back to where it started
    pts = walk(300) + walk(1200, start_s=300, lat=45.85 + 300 * DLAT, step_m=160 / 3.6)
    kept, n = drop_jumps(pts)
    assert n == 0 and kept is pts


def test_a_normal_track_is_untouched():
    pts = walk(3600)
    assert drop_jumps(pts) == (pts, 0)
