"""Altitude readings that are plainly recording errors (0 m with no fix, one-fix spikes)."""

from dataclasses import replace

from synth import as_track, gpx_bytes, hike_and_fly

from mbhf.analyse import analyse_bytes
from mbhf.models import Track
from mbhf.parsers.common import clean_altitudes


def _with_alts(track, change):
    pts = [replace(p, alt=change(i, p.alt)) for i, p in enumerate(track.points)]
    return Track(points=pts, source=track.source, fmt=track.fmt)


def _clean_and_glitched():
    base = as_track(hike_and_fly())
    n = len(base.points)
    lo, hi = n // 5, n // 5 + 400  # a long block of zeros in the middle of the climb
    glitched = _with_alts(base, lambda i, a: 0.0 if lo <= i < hi else a)
    return base, glitched


def test_zero_block_in_the_mountains_is_ignored():
    base, glitched = _clean_and_glitched()
    a = analyse_bytes("a.gpx", gpx_bytes(base))["outing"]
    b = analyse_bytes("b.gpx", gpx_bytes(glitched))["outing"]
    assert b["status"] == "ok"
    assert abs(b["dplus_m"] - a["dplus_m"]) < 80          # not thousands of metres more
    assert abs(b["dminus_m"] - a["dminus_m"]) < 80
    assert any("altitude readings" in w for w in b["warnings"])
    assert not any("altitude readings" in w for w in a["warnings"])


def test_without_the_fix_the_zero_block_would_inflate_the_climb():
    # the situation the fix is for: the same block of zeros, taken at face value, is a huge fake climb
    from mbhf.outing import climbs

    alts = [1500.0] * 50 + [0.0] * 50 + [1520.0] * 50
    up, _ = climbs(alts, 15.0)
    assert up > 1500


def test_clean_altitudes_keeps_a_track_really_near_sea_level():
    pts = _with_alts(as_track(hike_and_fly()), lambda i, a: 0.0 if i % 3 == 0 else 2.0).points
    out, n = clean_altitudes(pts)
    assert n == 0 and out is pts


def test_zero_at_the_very_start_with_a_slow_climb_is_kept():
    pts = _with_alts(as_track(hike_and_fly()), lambda i, a: float(i) * 0.01).points
    out, n = clean_altitudes(pts)
    assert n == 0


def test_isolated_spike_is_removed_but_a_real_step_is_kept():
    pts = _with_alts(as_track(hike_and_fly()), lambda i, a: 1000.0).points
    spiked = list(pts)
    spiked[10] = replace(spiked[10], alt=1300.0)           # one fix 300 m up, back at the next one
    out, n = clean_altitudes(spiked)
    assert n == 1 and out[10].alt is None and out[9].alt == 1000.0

    stepped = [replace(p, alt=1000.0 if i < 20 else 1300.0) for i, p in enumerate(pts)]  # a real, lasting change
    out, n = clean_altitudes(stepped)
    assert n == 0


def test_points_keep_their_position_and_time():
    base, glitched = _clean_and_glitched()
    out, n = clean_altitudes(glitched.points)
    assert n > 0
    assert [(p.t, p.lat, p.lon) for p in out] == [(p.t, p.lat, p.lon) for p in glitched.points]
