"""Refused tracks that were edited with a track tool (advice.editor_of, the ride from the top)."""
from datetime import datetime, timedelta, timezone

from mbhf import advice
from mbhf.models import Point

T0 = datetime(2024, 11, 10, 9, 0, tzinfo=timezone.utc)


def test_the_track_editor_is_named_from_the_gpx_creator():
    assert advice.editor_of(b'<?xml version="1.0"?><gpx version="1.1" creator="Adze - https://getadze.com/">') == "Adze"
    assert advice.editor_of(b'<gpx creator="gpx.studio">') == "gpx.studio"
    assert advice.editor_of(b'<gpx creator="StravaGPX">') is None      # an app's own export: not named
    assert advice.editor_of(b"HFDTE101124") is None                     # an IGC


def outing_with_a_ride(start_alt, end_alt):
    """Up on foot to 4,750 m by 10:00, then a ride from ``start_alt`` to ``end_alt`` in 25 minutes."""
    pts = [Point(t=T0 + timedelta(minutes=m), lat=45.83, lon=6.86, alt=4000 + 12.5 * m) for m in range(61)]
    pts += [Point(t=T0 + timedelta(minutes=62 + m), lat=45.83, lon=6.86, alt=start_alt + (end_alt - start_alt) * m / 25)
            for m in range(26)]
    seg = [{"mode": "walk", "start": pts[0].t.isoformat(), "end": pts[60].t.isoformat()},
           {"mode": "vehicle", "start": pts[61].t.isoformat(), "end": pts[-1].t.isoformat()}]
    return {"status": "rejected", "reason": "no_flight", "segments": seg, "warnings": []}, pts


def test_a_fast_descent_from_the_top_read_as_a_ride():
    outing, pts = outing_with_a_ride(4740, 600)
    text = advice.refusal(outing, pts)
    assert text.startswith("No flight found: the fast descent from the top (4,740 m, at 10:02 UTC) was read as a ride")
    assert "original recording" in text
    assert "written by Adze" in advice.refusal(outing, pts, editor="Adze")


def test_a_ride_in_the_valley_is_not_a_descent_from_the_top():
    outing, pts = outing_with_a_ride(1200, 600)
    assert advice.refusal(outing, pts) == advice.NO_FLIGHT
    assert advice.refusal(outing, pts, editor="Adze").startswith(advice.NO_FLIGHT + " This file was written by Adze")
