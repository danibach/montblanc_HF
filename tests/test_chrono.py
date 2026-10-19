from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from synth_cyl import RULES, SU, NA, cyl_day, expected_chrono_seconds, to_track

from mbhf.chrono import compute_chrono, find_crossings, inside
from mbhf.models import Point
from mbhf.rules import Cylinder, RuleSet, load_ruleset
from mbhf.segment import segment_track


def _run(g, rules=RULES):
    tr = to_track(g)
    res = segment_track(tr)
    return tr, res, compute_chrono(tr, res, rules)


def test_default_ruleset_has_the_agreed_values():
    r = load_ruleset()
    assert (r.nid_d_aigle.radius_m, r.nid_d_aigle.alt_min_m, r.nid_d_aigle.alt_max_m) == (200, 2350, 2450)
    assert (r.summit.radius_m, r.summit.alt_min_m, r.summit.alt_max_m) == (100, 4700, 4850)
    assert set(r.accepted_formats) == {"igc", "gpx", "kml", "fit"}


def test_chrono_matches_the_analytic_answer():
    g = cyl_day()
    _, _, ch = _run(g)
    assert ch.seconds is not None
    assert abs(ch.seconds - expected_chrono_seconds()) < 30  # fixes are 10 s apart
    assert ch.ranking_eligible and ch.summit_exit_by_flight and ch.hf_conditions_met
    assert ch.problems == []


def test_last_exit_rule_survives_a_one_fix_blip_at_the_cylinder_edge():
    """The real 2024 track had a 1 s altitude blip at the edge; the clock must not restart there."""
    g = cyl_day()
    clean = _run(g)[2].seconds
    # lift one fix in the middle of the Nid d'Aigle cylinder out of its altitude band
    idx = [k for k, p in enumerate(g.points) if inside(p, RULES.nid_d_aigle)]
    k = idx[len(idx) // 3]
    g.points[k] = replace(g.points[k], alt=2500.0)
    tr, res, ch = _run(g)
    crossings = find_crossings(tr.points, res.labels, RULES.nid_d_aigle)
    assert len([c for c in crossings if c.kind == "exit"]) >= 2   # the blip made an extra exit
    assert abs(ch.seconds - clean) < 1.0                          # ... which does not change the chrono


def test_descent_on_foot_gives_a_ranking_problem_and_no_badge():
    g = cyl_day(flight=False)
    _, _, ch = _run(g)
    assert not ch.has_flight and not ch.ranking_eligible and not ch.hf_conditions_met
    assert not ch.summit_exit_by_flight
    assert any("no flight" in p for p in ch.problems)


def test_summit_band_that_misses_the_track_explains_why():
    g = cyl_day()
    tight = RuleSet(
        version="t",
        accepted_formats=(),
        nid_d_aigle=RULES.nid_d_aigle,
        summit=Cylinder("summit", SU[0], SU[1], 100, 4900, 5000),
    )
    _, _, ch = _run(g, tight)
    assert ch.seconds is None
    assert any("summit" in p and "band" in p for p in ch.problems)


def test_tight_lower_limit_makes_the_foot_exit_fail():
    """Reproduces the real-track finding: with a band that cuts the top off, the track 'leaves' on foot."""
    g = cyl_day()
    # simulate a device reading 60 m low at the top: lower the altitudes above 4500 m
    pts = [replace(p, alt=p.alt - 60.0) if p.alt > 4500 else p for p in g.points]
    g.points = pts
    tight = RuleSet("t", (), RULES.nid_d_aigle, Cylinder("summit", SU[0], SU[1], 100, 4775, 4850))
    _, _, ch_tight = _run(g, tight)
    assert not ch_tight.summit_exit_by_flight      # left the cylinder on foot, below the band
    _, _, ch_wide = _run(g, RULES)
    assert ch_wide.summit_exit_by_flight           # the widened band is fine


def test_crossing_time_is_interpolated_between_fixes():
    cyl = Cylinder("c", 45.0, 6.0, 100.0, 1000.0, 2000.0)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deg = 1 / 111_320.0                              # one metre of latitude
    a = Point(t=t0, lat=45.0 + 300 * deg, lon=6.0, alt=1500.0)   # 300 m north: outside
    b = Point(t=t0 + timedelta(seconds=100), lat=45.0 - 100 * deg, lon=6.0, alt=1500.0)  # 100 m south: on the edge, inside
    cr = find_crossings([a, b], [1, 1], cyl)
    assert len(cr) == 1 and cr[0].kind == "enter"
    # radius reached after moving 200 of the 400 metres, i.e. half way
    assert abs((cr[0].t - t0).total_seconds() - 50.0) < 1.0
    assert cr[0].gap_s == 100.0
