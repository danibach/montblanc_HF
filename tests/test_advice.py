from datetime import datetime, timedelta, timezone

import pytest
from synth import as_track, drive_then_walk, gpx_bytes, hike_and_fly

from mbhf import advice
from mbhf.analyse import AnalysisError, analyse_bytes
from mbhf.models import Point


def run(g):
    return analyse_bytes("day.gpx", gpx_bytes(as_track(g)))


def pts(alts):
    t0 = datetime(2026, 6, 1, 8, tzinfo=timezone.utc)
    return [Point(t=t0 + timedelta(minutes=i), lat=45.0, lon=6.0, alt=a) for i, a in enumerate(alts)]


# ---- outings that do not count: the reason in words, the same for the browser and the server

def test_an_outing_that_counts_has_no_reason_text():
    assert run(hike_and_fly())["outing"]["reason_text"] is None


def test_no_flight_a_walk_up_and_down():
    o = run(drive_then_walk())["outing"]
    assert o["reason"] == "no_flight" and o["reason_text"] == advice.NO_FLIGHT


def test_recording_stopped_at_the_take_off():
    o = {"status": "rejected", "reason": "no_flight", "warnings": []}
    text = advice.refusal(o, pts([1000, 1400, 1800, 2210, 2205]))
    assert text.startswith("The recording ends at its highest point (2,210 m)") and "until you land" in text


def test_the_terrain_check_keeps_its_own_words():
    note = "A fast descent follows the ground (ski, bike or run), so it is not counted as a flight. Terrain: 2 %"
    o = {"status": "rejected", "reason": "no_flight", "warnings": [note]}
    assert advice.refusal(o, pts([1000, 1800, 1000])) == note


def test_too_little_climb_says_how_much():
    o = {"status": "rejected", "reason": "too_little_climb", "dplus_m": 140, "warnings": []}
    text = advice.refusal(o, pts([1000, 1140, 900]))
    assert text == "Only 140 m of climbing on foot were recorded (200 m needed). The climb must be in the file."


def test_recording_started_near_the_top():
    o = {"status": "rejected", "reason": "too_little_climb", "dplus_m": 0, "warnings": []}
    text = advice.refusal(o, pts([4091, 4091, 3000, 1200]))
    assert text.startswith("The recording starts at 4,091 m, near the highest point")


# ---- files that cannot be read

def test_a_file_without_track_points():
    gpx = b'<?xml version="1.0"?><gpx version="1.1" creator="x" xmlns="http://www.topografix.com/GPX/1/1"></gpx>'
    with pytest.raises(AnalysisError, match="the export is empty"):
        analyse_bytes("empty.gpx", gpx)


def test_a_route_is_not_a_recording():
    gpx = (b'<?xml version="1.0"?><gpx version="1.1" creator="OpenLayers" xmlns="http://www.topografix.com/GPX/1/1">'
           b'<rte><rtept lat="45.86" lon="6.76"><ele>1428</ele><time>2018-10-04T12:43:42Z</time></rtept></rte></gpx>')
    with pytest.raises(AnalysisError, match="holds a route"):
        analyse_bytes("planned.gpx", gpx)


def test_a_damaged_file():
    with pytest.raises(AnalysisError, match="damaged or incomplete"):
        analyse_bytes("broken.gpx", b"<gpx><trk><trkseg><trkpt")


def test_a_file_without_timestamps():
    with pytest.raises(AnalysisError, match="no timestamps"):
        analyse_bytes("day.gpx", gpx_bytes(as_track(hike_and_fly()), with_time=False))


def test_a_file_too_large():
    with pytest.raises(AnalysisError, match="Export only this activity"):
        analyse_bytes("big.gpx", b"x" * 20, max_bytes=10)
