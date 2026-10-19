"""Tram / lift detection on synthetic tracks laid on a synthetic rail line.

The rail line is the straight line from the trailhead to Nid d'Aigle used by the synthetic day
(about 10 km, 1800 m of climb: an 18 % gradient, a bit steeper than the real tram). Numbers are
invented; they show the code does what it is designed to do, not that the thresholds are right
for real tracks.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from synth_cyl import NA, RULES, TRAILHEAD, cyl_day, to_track

from mbhf.chrono import chrono_to_dict, compute_chrono
from mbhf.geo import haversine_m
from mbhf.models import Point, Track
from mbhf.rules import RuleSet
from mbhf.segment import segment_track
from mbhf.transport import Line, LineSet, Schedule, analyse_transport, import_osm, load_lines

TRAM = LineSet([Line("way/1", "Tramway du Mont-Blanc", "tram", "rack", ((TRAILHEAD[0], TRAILHEAD[1]), (NA[0], NA[1])))])
OPEN = Schedule({"periods": [{"from": "2026-09-01", "to": "2026-09-27", "status": "open",
                              "hours": {"first": "07:00", "last": "18:00"}}]})
CLOSED = Schedule({"periods": [{"from": "2026-09-01", "to": "2026-09-27", "status": "closed"}]})
UNKNOWN = Schedule({"periods": []})
T0 = datetime(2026, 9, 12, 8, 0, 0, tzinfo=timezone.utc)   # 10:00 in Paris
DEG = 1 / 111_320.0


def _run(g, schedule, lines=TRAM):
    tr = to_track(g)
    res = segment_track(tr)
    return compute_chrono(tr, res, RULES, lines, schedule)


def test_a_hiker_walking_along_the_rails_is_not_flagged():
    ch = _run(cyl_day(), OPEN)
    assert ch.transport.performed and ch.transport.verdict == "clear"
    on_rails = [s for s in ch.transport.stretches if s.kind == "tram"]
    assert on_rails and all(s.verdict == "on_foot" for s in on_rails)
    assert ch.ranking_eligible and ch.hf_conditions_met and not ch.flagged
    assert not chrono_to_dict(ch)["provisional"]


def test_a_tram_ride_during_opening_hours_is_flagged():
    ch = _run(cyl_day(ascent_a_s=3600), OPEN)       # the same 10 km in one hour
    assert ch.transport.verdict == "tram" and ch.flagged
    st = next(s for s in ch.transport.stretches if s.verdict == "tram")
    assert st.climb_rate_mh >= 1200 and st.operating == "yes"
    assert not ch.ranking_eligible and not ch.hf_conditions_met
    assert any("FLAGGED" in p and "tramway" in p for p in ch.problems)


def test_fast_on_the_rails_while_the_tram_is_closed_is_only_a_review():
    ch = _run(cyl_day(ascent_a_s=3600), CLOSED)
    assert ch.transport.verdict == "review" and not ch.flagged
    assert ch.ranking_eligible and ch.hf_conditions_met
    assert any("review" in p for p in ch.problems)


def test_unknown_timetable_assumes_the_tram_runs_and_says_so():
    ch = _run(cyl_day(ascent_a_s=3600), UNKNOWN)
    assert ch.transport.verdict == "tram"
    assert any("timetable" in n for n in ch.transport.notes)


def _along(line, kmh, dist_m=None, offset_m=0.0, t0=T0, dt=10, rise=None, start_m=0.0):
    """Fixes along the straight two-point line, optionally offset sideways."""
    (la, lo), (lb, lob) = line
    total = haversine_m(la, lo, lb, lob)
    dist_m = total - start_m if dist_m is None else dist_m
    pts, n = [], int(dist_m / (kmh / 3.6 * dt))
    for k in range(n + 1):
        s = (start_m + k * (kmh / 3.6) * dt) / total
        lat = la + (lb - la) * s
        lon = lo + (lob - lo) * s
        pts.append(Point(t=t0 + timedelta(seconds=k * dt), lat=lat + offset_m * DEG, lon=lon,
                         alt=1000 + (rise if rise is not None else 0.18) * s * total))
    return pts


def _tr(pts):
    return Track(points=pts, source="synthetic", fmt="gpx")


LINE = ((TRAILHEAD[0], TRAILHEAD[1]), (NA[0], NA[1]))


def test_a_bicycle_on_a_parallel_road_is_a_review_not_a_ride():
    pts = _along(LINE, 15, dist_m=3000, offset_m=25)            # 25 m beside the rails, 15 km/h
    r = analyse_transport(_tr(pts), [0] * len(pts), len(pts), TRAM, OPEN)
    assert r.verdict == "review" and not r.flagged


def test_a_vehicle_exactly_on_the_rails_labelled_as_bike_is_still_a_tram_ride():
    pts = _along(LINE, 10, dist_m=3000)                          # on the line, 1800 m/h
    r = analyse_transport(_tr(pts), [0] * len(pts), len(pts), TRAM, OPEN)
    assert r.verdict == "tram"


def test_slow_hiker_on_the_rails_is_on_foot_even_at_a_good_pace():
    pts = _along(LINE, 4.5, dist_m=3000)                         # 810 m/h
    r = analyse_transport(_tr(pts), [1] * len(pts), len(pts), TRAM, OPEN)
    assert r.verdict == "clear" and r.stretches and r.stretches[0].verdict == "on_foot"


def test_short_contact_with_the_rails_is_ignored():
    pts = _along(LINE, 10, dist_m=300)
    r = analyse_transport(_tr(pts), [1] * len(pts), len(pts), TRAM, OPEN)
    assert r.verdict == "clear" and r.stretches == []


def test_riding_during_a_recording_gap_is_caught():
    first = _along(LINE, 4, dist_m=700)                          # walk 700 m
    last_t = first[-1].t
    last_s = 700.0
    # phone off for 5 min while 800 m are covered (1440 m/h), then walking again
    resume = _along(LINE, 4, dist_m=700, t0=last_t + timedelta(seconds=300), start_m=last_s + 800, rise=0.18)
    pts = first + resume
    r = analyse_transport(_tr(pts), [1] * len(pts), len(pts), TRAM, OPEN)
    assert r.verdict == "tram"
    assert any(s.across_gap for s in r.stretches if s.verdict == "tram")


LIFT = LineSet([Line("way/9", "Télécabine test", "lift", "gondola", ((45.89, 6.70), (45.87, 6.75)))])
LIFT_LINE = ((45.89, 6.70), (45.87, 6.75))


def test_a_cable_car_ride_is_flagged_without_any_timetable():
    pts = _along(LIFT_LINE, 20, rise=0.3)
    r = analyse_transport(_tr(pts), [1] * len(pts), len(pts), LIFT, None)
    assert r.verdict == "lift" and r.flagged


def test_walking_under_a_lift_is_fine():
    pts = _along(LIFT_LINE, 4, rise=0.3)
    r = analyse_transport(_tr(pts), [1] * len(pts), len(pts), LIFT, None)
    assert r.verdict == "clear"


def test_without_line_geometry_the_check_is_not_performed_and_the_result_stays_provisional():
    ch = _run(cyl_day(), OPEN, lines=LineSet([]))
    assert not ch.transport.performed and ch.transport.verdict == "not_checked"
    d = chrono_to_dict(ch)
    assert d["provisional"] and any("NOT performed" in n for n in d["notes"])
    assert ch.ranking_eligible             # not flagged: nothing was found, but nothing was checked


def test_the_packaged_line_file_is_valid_even_when_still_empty():
    lines = load_lines()
    assert isinstance(bool(lines), bool)


def test_hiking_up_another_route_gives_no_ranking_but_still_the_badge():
    g = cyl_day()
    far = RULES.nid_d_aigle.__class__("nid_d_aigle", 45.99, 6.99, 200, 2350, 2450)   # a cylinder the track never visits
    elsewhere = RuleSet(RULES.version, RULES.accepted_formats, far, RULES.summit)
    tr = to_track(g)
    ch = compute_chrono(tr, segment_track(tr), elsewhere, TRAM, OPEN)
    assert ch.seconds is None and not ch.ranking_eligible
    assert ch.hf_conditions_met and ch.summit_exit_by_flight
    assert any("Nid d'Aigle" in p for p in ch.problems)


def test_a_tram_ride_blocks_the_badge_even_without_the_ranking():
    g = cyl_day(ascent_a_s=3600)
    far = RULES.nid_d_aigle.__class__("nid_d_aigle", 45.99, 6.99, 200, 2350, 2450)
    elsewhere = RuleSet(RULES.version, RULES.accepted_formats, far, RULES.summit)
    tr = to_track(g)
    ch = compute_chrono(tr, segment_track(tr), elsewhere, TRAM, OPEN)
    assert ch.flagged and not ch.hf_conditions_met


# --- timetable ---------------------------------------------------------------------------------
def _utc(h, m=0, day=12):
    return datetime(2026, 9, day, h, m, tzinfo=timezone.utc)


def test_schedule_hours_margin_and_unknown_dates():
    assert OPEN.operating(_utc(8)) == "yes"            # 10:00 in Paris
    assert OPEN.operating(_utc(5, 10)) == "yes"        # 07:10 Paris
    assert OPEN.operating(_utc(4, 45)) == "yes"        # 06:45 Paris: inside the 30 min margin
    assert OPEN.operating(_utc(3)) == "no"             # 05:00 Paris
    assert OPEN.operating(_utc(17)) == "no"            # 19:00 Paris
    assert CLOSED.operating(_utc(8)) == "no"
    assert OPEN.operating(datetime(2027, 6, 1, 8, tzinfo=timezone.utc)) == "unknown"


def test_the_packaged_timetable_knows_the_2026_closure_and_nothing_else():
    from mbhf.transport import load_schedule

    s = load_schedule()
    assert s.operating(datetime(2026, 10, 12, 9, tzinfo=timezone.utc)) == "no"      # closed 28 Sep - 11 Dec 2026
    assert s.operating(datetime(2026, 7, 12, 9, tzinfo=timezone.utc)) == "unknown"  # summer not loaded
    assert s.operating(datetime(2025, 10, 12, 9, tzinfo=timezone.utc)) == "unknown"


# --- OSM import -------------------------------------------------------------------------------
def _write(tmp_path, obj):
    p = tmp_path / "export.json"
    p.write_text(json.dumps(obj))
    return str(p)


def test_import_overpass_json_keeps_tram_and_lifts_and_ignores_other_railways(tmp_path):
    raw = {"elements": [
        {"type": "way", "id": 1, "tags": {"railway": "rack", "name": "Tramway du Mont-Blanc"},
         "geometry": [{"lat": 45.9, "lon": 6.7}, {"lat": 45.88, "lon": 6.75}]},
        {"type": "way", "id": 2, "tags": {"railway": "rail", "name": "Ligne de Saint-Gervais à Vallorcine"},
         "geometry": [{"lat": 45.9, "lon": 6.7}, {"lat": 45.95, "lon": 6.9}]},
        {"type": "way", "id": 3, "tags": {"aerialway": "gondola", "name": "Télécabine X"},
         "geometry": [{"lat": 45.89, "lon": 6.8}, {"lat": 45.87, "lon": 6.82}]},
        {"type": "way", "id": 4, "tags": {"aerialway": "station"},
         "geometry": [{"lat": 45.89, "lon": 6.8}, {"lat": 45.89, "lon": 6.8001}]},
    ]}
    out = import_osm(_write(tmp_path, raw))
    assert sorted((ln["kind"], ln["id"]) for ln in out["lines"]) == [("lift", "way/3"), ("tram", "way/1")]


def test_import_geojson_from_overpass_turbo(tmp_path):
    raw = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "way/7", "properties": {"@id": "way/7", "railway": "narrow_gauge",
                                                          "name": "Tramway du Mont-Blanc"},
         "geometry": {"type": "LineString", "coordinates": [[6.7, 45.9], [6.75, 45.88]]}},
    ]}
    out = import_osm(_write(tmp_path, raw))
    assert out["lines"][0]["coords"][0] == [45.9, 6.7]          # lat, lon


def test_import_refuses_an_export_without_the_tram_line(tmp_path):
    raw = {"elements": [{"type": "way", "id": 3, "tags": {"aerialway": "gondola"},
                         "geometry": [{"lat": 45.89, "lon": 6.8}, {"lat": 45.87, "lon": 6.82}]}]}
    with pytest.raises(ValueError, match="no tram line"):
        import_osm(_write(tmp_path, raw))
