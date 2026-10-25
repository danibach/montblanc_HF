"""One outing in several files (multi.py, analyse.prepare_files)."""
import json
from datetime import datetime, timedelta

import pytest
from synth import T0, as_track, gpx_bytes, hike_and_fly

from mbhf import browser
from mbhf.analyse import AnalysisError, analyse_bytes, analyse_files
from mbhf.models import Track
from mbhf.multi import Ends, chain_problem, combined_sha256, groups, link_problem


def split(track, *at):
    """The track cut into files at these fractions of its fixes."""
    pts = track.points
    cuts = [0] + [int(len(pts) * f) for f in at] + [len(pts)]
    return [Track(points=pts[a:b], source="part", fmt="gpx") for a, b in zip(cuts, cuts[1:])]


def ends(h0, h1, lat0=45.9, lon0=6.8, lat1=45.9, lon1=6.8):
    return Ends(T0 + timedelta(hours=h0), lat0, lon0, T0 + timedelta(hours=h1), lat1, lon1)


def test_a_hike_and_fly_cut_in_two_files_counts_as_one():
    whole = as_track(hike_and_fly())
    climb, flight = split(whole, 0.6)
    files = [("climb.gpx", gpx_bytes(climb)), ("flight.gpx", gpx_bytes(flight))]
    # alone, neither counts: the climb has no flight, the flight no climb
    assert analyse_bytes(*files[0])["outing"]["reason"] == "no_flight"
    assert analyse_bytes(*files[1])["outing"]["reason"] == "too_little_climb"
    joined = analyse_files(files[::-1])  # in any order: joined in time order
    one = analyse_bytes("whole.gpx", gpx_bytes(whole))
    o, w = joined["outing"], one["outing"]
    assert o["status"] == "ok" and abs(o["dplus_m"] - w["dplus_m"]) <= 15 and abs(o["dminus_m"] - w["dminus_m"]) <= 15
    parts = joined["file"]["parts"]
    assert [p["name"] for p in parts] == ["climb.gpx", "flight.gpx"]
    assert joined["file"]["sha256"] == combined_sha256([p["sha256"] for p in parts])


def test_files_that_do_not_follow_one_another_are_refused_with_the_reason():
    climb, flight = split(as_track(hike_and_fly()), 0.6)
    moved = Track(points=[p.__class__(t=p.t, lat=p.lat + 0.05, lon=p.lon, alt=p.alt) for p in flight.points],
                  source="x", fmt="gpx")  # starts 5.6 km away
    with pytest.raises(AnalysisError, match="km from where the previous one ended"):
        analyse_files([("a.gpx", gpx_bytes(climb)), ("b.gpx", gpx_bytes(moved))])


def test_the_rules():
    assert link_problem(ends(0, 2), ends(2.5, 4)) is None
    assert "overlap" in link_problem(ends(0, 2), ends(1.5, 4))
    assert "h apart" in link_problem(ends(0, 2), ends(17, 18))            # 15 h: more than a night
    assert link_problem(ends(0, 10), ends(22, 30)) is None                  # 12 h: a night in a bivouac
    assert "km from" in link_problem(ends(0, 2), ends(3, 4, lat0=45.93))   # 3.3 km away
    week = [ends(24 * d, 24 * d + 12) for d in range(9)]
    assert "days" in chain_problem(week, [f"day{d}" for d in range(9)])
    assert "At most 10 files" in chain_problem([ends(k, k + 0.5) for k in range(11)], [str(k) for k in range(11)])


def test_groups_in_a_batch():
    # a ride, the climb, the ride home, an unrelated outing a week later, and the three already joined by hand
    files = [ends(3, 8), ends(0, 2.9), ends(8.2, 10), ends(200, 205), ends(0, 10)]
    assert groups(files) == [[1, 0, 2], [4], [3]]


def test_a_flight_marked_by_hand_on_an_outing_in_several_files():
    # Dani's Mont-Blanc files (Adze, the flight's altitude flattened onto the ground) only count with the flight
    # marked by hand on the joined track, in seconds after the first fix of the first file: that path, end to end
    whole = as_track(hike_and_fly())
    climb, rest = split(whole, 0.6)
    files = [("climb.gpx", gpx_bytes(climb)), ("flight.gpx", gpx_bytes(rest))]
    one = analyse_bytes("whole.gpx", gpx_bytes(whole))["outing"]["flights"][0]
    t0 = whole.points[0].t
    ranges = [[(datetime.fromisoformat(one["takeoff"]["t"]) - t0).total_seconds(),
               (datetime.fromisoformat(one["landing"]["t"]) - t0).total_seconds()]]
    o = analyse_files(files[::-1], manual_ranges=ranges)["outing"]
    assert o["status"] == "ok" and o["dminus_m"] > 800
    assert any("marked by hand" in w for w in o["warnings"])
    browser.parts_clear()
    for name, data in files:
        browser.parts_add(name, data)
    res = json.loads(browser.manual_parts_json(json.dumps(ranges)))
    assert res["ok"] and res["result"]["manual"] and res["result"]["outing"]["status"] == "ok"
    assert len(res["result"]["file"]["parts"]) == 2


def test_the_page_entry_points():
    climb, flight = split(as_track(hike_and_fly()), 0.6)
    a, b = gpx_bytes(climb), gpx_bytes(flight)
    ea = json.loads(browser.ends_json("a.gpx", a))["ends"]
    eb = json.loads(browser.ends_json("b.gpx", b))["ends"]
    assert json.loads(browser.groups_json(json.dumps([eb, None, ea]))) == [[2, 0], [1]]
    browser.parts_clear()
    browser.parts_add("b.gpx", b)
    browser.parts_add("a.gpx", a)
    res = json.loads(browser.analyse_parts_json())
    assert res["ok"] and res["result"]["outing"]["status"] == "ok" and len(res["result"]["file"]["parts"]) == 2
    assert res["result"]["terrain"]["query"]
