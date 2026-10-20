from synth import as_track, gpx_bytes, hike_and_fly, steep_flight_then_bike

from mbhf.analyse import analyse_bytes, prepare_bytes, terrain_query_for, with_terrain
from mbhf.terrain import elevation_query, parse_elevations, sample_flights


def data(g):
    return gpx_bytes(as_track(g))


def ground_like(samples, below):
    """A terrain `below` metres under the track at every sampled fix."""
    return [s["alt"] - below for s in samples]


def test_samples_cover_every_flight_and_stay_under_the_service_limit():
    p = prepare_bytes("a.gpx", data(hike_and_fly()))
    s = sample_flights(p.track, p.seg)
    assert 8 <= len(s) <= 100 and {x["flight"] for x in s} == {1}
    q = elevation_query(s)
    assert q.startswith("latitude=") and "&longitude=" in q


def test_a_flight_well_above_the_ground_is_kept():
    p = prepare_bytes("a.gpx", data(hike_and_fly()))
    s = sample_flights(p.track, p.seg)
    r = with_terrain(p, ground_like(s, below=300))
    assert r["outing"]["status"] == "ok" and r["outing"]["dminus_m"] > 800
    assert not any("follows the ground" in w or "to be checked" in w for w in r["outing"]["warnings"])
    assert any(w.startswith("Terrain: 100%") for w in r["outing"]["warnings"])


def test_a_descent_that_follows_the_ground_is_not_a_flight():
    p = prepare_bytes("a.gpx", data(hike_and_fly()))
    s = sample_flights(p.track, p.seg)
    r = with_terrain(p, ground_like(s, below=3))
    assert r["outing"]["status"] == "rejected" and r["outing"]["reason"] == "no_flight"
    assert any("follows the ground" in w for w in r["outing"]["warnings"])
    assert all(seg["mode"] != "flight" for seg in r["outing"]["segments"])


def test_ground_noise_of_a_few_tens_of_metres_does_not_turn_a_flight_into_a_ski_run():
    p = prepare_bytes("a.gpx", data(hike_and_fly()))
    s = sample_flights(p.track, p.seg)
    elev = [s_["alt"] - 150 + (40 if k % 2 else -40) for k, s_ in enumerate(s)]
    assert with_terrain(p, elev)["outing"]["status"] == "ok"


def test_without_elevations_the_flight_is_kept_and_a_note_says_so():
    p = prepare_bytes("a.gpx", data(hike_and_fly()))
    r = with_terrain(p, None)
    assert r["outing"]["status"] == "ok"
    assert any("Terrain check not available" in w for w in r["outing"]["warnings"])


def test_too_few_known_elevations_give_no_verdict():
    p = prepare_bytes("a.gpx", data(hike_and_fly()))
    s = sample_flights(p.track, p.seg)
    elev = [None] * len(s)
    assert with_terrain(p, elev)["outing"]["status"] == "ok"


def test_analyse_bytes_with_a_fetcher_applies_the_check():
    r = analyse_bytes("a.gpx", data(steep_flight_then_bike()), elevation_fetch=lambda s: ground_like(s, below=2))
    assert r["outing"]["status"] == "rejected"
    r = analyse_bytes("a.gpx", data(steep_flight_then_bike()), elevation_fetch=lambda s: ground_like(s, below=400))
    assert r["outing"]["status"] == "ok"
    r = analyse_bytes("a.gpx", data(steep_flight_then_bike()), elevation_fetch=lambda s: None)
    assert r["outing"]["status"] == "ok"


def test_the_service_answer_is_checked():
    assert parse_elevations({"elevation": [1, 2.5, None]}, 3) == [1.0, 2.5, None]
    assert parse_elevations({"elevation": [1]}, 3) is None
    assert parse_elevations({"error": True}, 3) is None
    assert parse_elevations({"elevation": [float("nan"), 5]}, 2) == [None, 5.0]


def test_the_browser_query_matches_the_samples():
    p = prepare_bytes("a.gpx", data(hike_and_fly()))
    q = terrain_query_for(p)
    n = len(sample_flights(p.track, p.seg))
    lat, lon = q.split("&")
    assert lat.count(",") + 1 == n and lon.count(",") + 1 == n


def test_a_descent_close_to_the_slope_is_kept_but_flagged():
    """Speed riding: mostly near the ground, with a few stretches in the air."""
    p = prepare_bytes("a.gpx", data(hike_and_fly()))
    s = sample_flights(p.track, p.seg)
    elev = [x["alt"] - (200 if k % 5 == 0 else 30) for k, x in enumerate(s)]
    r = with_terrain(p, elev)
    assert r["outing"]["status"] == "ok"
    assert any("to be checked" in w for w in r["outing"]["warnings"])
