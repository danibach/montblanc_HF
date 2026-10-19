"""The in-browser entry point: same analysis as the web app, compact trace, pinned transitions."""

import json
from datetime import timedelta, timezone

from synth_cyl import cyl_day, expected_chrono_seconds, to_track

from mbhf.browser import analyse_json
from mbhf.report import build_trace
from mbhf.service import Upload, analyse_uploads


def gpx_bytes(track, with_time: bool = True) -> bytes:
    rows = []
    for p in track.points:
        t = f"<time>{p.t.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}</time>" if with_time else ""
        rows.append(f'<trkpt lat="{p.lat:.6f}" lon="{p.lon:.6f}"><ele>{p.alt:.1f}</ele>{t}</trkpt>')
    return ('<?xml version="1.0"?><gpx version="1.1"><trk><trkseg>' + "".join(rows) + "</trkseg></trk></gpx>").encode()


def run(files, cuts=None):
    return json.loads(analyse_json(files, cuts))


def test_result_matches_the_web_app_analysis():
    data = gpx_bytes(to_track(cyl_day()))
    out = run([("jour.gpx", data, None)])
    assert out["ok"] is True
    r = out["result"]
    web = analyse_uploads([Upload("jour.gpx", data)], lang="fr").data
    for key in ("chrono", "report", "segments", "transitions", "warnings"):
        assert r[key] == web[key], key
    assert abs(r["chrono"]["climb_seconds"] - expected_chrono_seconds()) < 30
    assert r["engine"]["where"] == "browser"


def test_trace_arrays_are_compact_and_aligned():
    out = run([("jour.gpx", gpx_bytes(to_track(cyl_day())), None)])
    tr = out["result"]["trace"]
    n = len(tr["idx"])
    assert 2 <= n <= 1500
    assert len(tr["t"]) == len(tr["lat"]) == len(tr["lon"]) == len(tr["alt"]) == n
    assert tr["idx"][0] == 0 and tr["idx"][-1] == out["result"]["fixes"] - 1
    assert tr["t"] == sorted(tr["t"]) and tr["t"][0] == 0
    assert tr["t0"].endswith("+00:00")


def test_build_trace_keeps_every_fix_of_a_short_track():
    track = to_track(cyl_day())
    track.points = track.points[:50]
    tr = build_trace(track)
    assert tr["idx"] == list(range(50))


def test_a_pinned_takeoff_moves_the_flight_start():
    data = gpx_bytes(to_track(cyl_day()))
    first = run([("jour.gpx", data, None)])["result"]
    detected = first["transitions"]["takeoff"]
    assert detected
    from mbhf.parsers.common import parse_iso_time

    later = (parse_iso_time(detected) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = run([("jour.gpx", data, None)], {"takeoff": later})
    assert out["ok"] is True
    flight = [s for s in out["result"]["segments"] if s["role"] == "flight"][0]
    assert flight["start_fixed_by_user"] is True
    assert abs((parse_iso_time(flight["start"]) - parse_iso_time(later)).total_seconds()) <= 10


def test_errors_come_back_in_french_without_internals():
    out = run([("sans-heure.gpx", gpx_bytes(to_track(cyl_day()), with_time=False), None)])
    assert out["ok"] is False and "horodatage" in out["error"]
    out = run([("virus.exe", b"MZ", None)])
    assert out["ok"] is False and "IGC, GPX, KML ou FIT" in out["error"]
    out = run([("jour.gpx", gpx_bytes(to_track(cyl_day())), None)], {"takeoff": "pas une heure"})
    assert out["ok"] is False and "pas une heure" in out["error"]


def test_unreadable_file_gives_a_participant_message():
    out = run([("vide.gpx", b"<gpx", None)])
    assert out["ok"] is False
    assert "Traceback" not in out["error"]
