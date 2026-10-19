"""Everything a participant reads must be French. Known English messages must all have a rule."""

import io
import re

import pytest
from synth_cyl import RULES, cyl_day, to_track
from test_transport import CLOSED, OPEN, TRAM, UNKNOWN, _run

from mbhf.chrono import compute_chrono
from mbhf.i18n import translate
from mbhf.rules import Cylinder, RuleSet
from mbhf.segment import segment_track
from mbhf.service import AnalysisError, Upload, analyse_uploads
from mbhf.transport import LineSet

ENGLISH = re.compile(
    r"\b(the|track|not|and|was|were|is|has|from|with|found|file|files|flight|walk|ride|check|"
    r"cannot|before|after|never|only|because)\b",
    re.I,
)


def assert_french(text: str):
    assert not ENGLISH.search(text.replace("gx:Track", "")), f"English left in: {text!r}"


SAMPLES = [
    "Rando.gpx: no track points found",
    "Rando.gpx: 12 of 100 points have no timestamp; timestamps are required to time a track",
    "Rando.gpx: fewer than 2 usable timed points",
    "Rando.gpx: 3 points without timestamp were dropped",
    "Rando.gpx: 3 points with invalid coordinates were dropped",
    "Rando.gpx: not a valid GPX file (syntax error)",
    "Rando.kml: not a valid KML file (syntax error)",
    "Rando.fit: not a readable FIT file (boom)",
    "Rando.kml: gx:Track has 10 timestamps but 9 coordinates",
    "Rando.kml: this KML only has a plain line path without timestamps; timestamps are required (a gx:Track with <when> elements)",
    "Rando.kml: no gx:Track found in KML",
    "Rando.igc: no valid HFDTE date header; timestamps cannot be built",
    "Rando.igc: 4 2D-fix (V) records were ignored",
    "Rando.gpx: cannot read file (nope)",
    "Rando.gpx: file too large (999 bytes)",
    "Rando.xyz: unsupported format '.xyz'; use IGC, GPX, KML or FIT",
    "no track to merge",
    "a.gpx: 5 points fall inside the time range of a more specific file and were not used",
    "fewer than 2 points remain after merging",
    "gap of 12.5 min at 2026-09-12T09:00:00+00:00 (moved 1.25 km while not recorded)",
    "position jump of 450 km/h at 2026-09-12T09:00:00+00:00",
    "a track needs at least 2 points to be segmented",
    "no labelling satisfies the file hints and the chosen transition times together; check that the cuts are in chronological order and consistent with the file labels",
    "no flight part found: such a track would not be registered",
    "flight lasts only 30 s; check the detection",
    "flight loses only 120 m of altitude; check the detection",
    "no ascent on foot found",
    "the start of ascent (2026-09-12T09:00:00+00:00) is ambiguous; check it on the plot and fix the transition by hand if needed",
    "flight: the recording has a 5.5 min gap just before it, so its exact start is uncertain",
    "some fixes have no altitude and cannot be tested against the altitude bands",
    "FLAGGED: the approach seems to use the Mont-Blanc tramway (not authorised): no ranking and no badge until reviewed",
    "FLAGGED: the approach seems to use a lift (not authorised): no ranking and no badge until reviewed",
    "the approach has a stretch to review for a possible tram or lift ride",
    "the track never enters the summit cylinder on foot (closest approach 350 m, radius 100 m)",
    "the track never enters the summit cylinder on foot (inside the radius, altitudes were 4600 to 4650 m against a band of 4900 to 5000 m)",
    "the track never enters the summit cylinder on foot (closest approach 12 m, radius 100 m); it entered only while flying",
    "the track leaves the summit cylinder on foot, not by flight (at 2026-09-12T09:00:00+00:00); no HF/BHF badge",
    "the track never leaves the summit cylinder",
    "the track does not pass through the Nid d'Aigle cylinder on foot before the summit: no climbing chrono and no ranking (the HF/BHF badge does not need it)",
    "a crossing happened across a recording gap of two minutes or more; the chrono is only accurate to within that gap",
    "the summit is reached before leaving Nid d'Aigle: inconsistent track",
    "no flight part in the track: it would not be registered in the ranking",
    "tram and lift check NOT performed: no line geometry loaded (run mbhf import-osm)",
    "the tram timetable for this date is not loaded: the tram was assumed to be running",
    "some fixes have no altitude: the climb-rate test could not use them",
    "follows the rails but not fast (best climb rate over the window: 650 m/h, 4.1 km/h)",
    "follows the rails but not fast (implied climb rate across a recording gap: n/a, 2.0 km/h)",
    "fast on the rails (1809 m/h) but the tram is not running then",
    "fast near the rails (1809 m/h) and labelled as a bike ride, 25 m from the line: possibly a bicycle on a parallel road",
    "follows the rails, tram running (yes), best climb rate over the window: 1809 m/h",
    "follows the rails, tram running (unknown), speed 12.0 km/h over a very short stretch: n/a",
    "follows the lift line at walking pace (0% of the stretch faster than 8 km/h)",
    "fast near the lift line (80% of the stretch faster than 8 km/h) and labelled as a bike ride, 20 m from the line: possibly a bicycle on a parallel road",
    "follows the lift line at lift speed (implied speed 14.2 km/h across a recording gap)",
]


@pytest.mark.parametrize("message", SAMPLES)
def test_every_known_message_has_a_french_rule(message):
    out = translate("fr", message)
    assert out != message
    assert_french(out)


def test_decimals_use_a_comma_but_times_are_untouched():
    out = translate("fr", "gap of 12.5 min at 2026-09-12T09:00:00.123+00:00 (moved 1.25 km while not recorded)")
    assert "12,5 min" in out and "1,25 km" in out


def test_english_stays_english():
    assert translate("en", SAMPLES[0]) == SAMPLES[0]


def _messages(ch):
    out = list(ch.problems) + list(ch.notes)
    if ch.transport:
        out += list(ch.transport.notes) + [s.reason for s in ch.transport.stretches]
    return out


@pytest.mark.parametrize(
    "make",
    [
        lambda: _run(cyl_day(), OPEN),
        lambda: _run(cyl_day(), OPEN, lines=LineSet([])),
        lambda: _run(cyl_day(ascent_a_s=3600), OPEN),
        lambda: _run(cyl_day(ascent_a_s=3600), CLOSED),
        lambda: _run(cyl_day(ascent_a_s=3600), UNKNOWN),
        lambda: _run(cyl_day(flight=False), OPEN),
    ],
)
def test_real_chrono_messages_are_all_translated(make):
    for message in _messages(make()):
        if re.match(r"^(tram|lift|review): ", message):
            continue                                   # per-stretch notes are not shown (the section lists them)
        assert_french(translate("fr", message))


def test_summit_band_that_misses_the_track_is_translated():
    tr = to_track(cyl_day())
    tight = RuleSet("t", (), RULES.nid_d_aigle, Cylinder("summit", RULES.summit.lat, RULES.summit.lon, 100, 4900, 5000))
    ch = compute_chrono(tr, segment_track(tr), tight, LineSet([]), OPEN)
    texts = [translate("fr", m) for m in ch.problems]
    assert any("bande de 4900 à 5000 m" in t for t in texts)
    for t in texts:
        assert_french(t)


def _fr(files, **kw):
    return analyse_uploads([Upload(n, b) for n, b in files], lang="fr", **kw)


def test_file_errors_are_french():
    cases = {
        "empty": ([("a.gpx", b"")], "vide"),
        "ext": ([("a.txt", b"x")], "pas accepté"),
        "none": ([], "Choisissez"),
        "bad gpx": ([("a.gpx", b"<gpx")], "GPX valide"),
    }
    for _, (files, expected) in cases.items():
        with pytest.raises(AnalysisError) as e:
            _fr(files)
        assert expected in str(e.value)
        assert_french(str(e.value))
    with pytest.raises(AnalysisError) as e:
        _fr([("a.gpx", b"x")], cuts={"takeoff": "demain"})
    assert "impossible de lire" in str(e.value) and "Décollage" in str(e.value)


def test_the_whole_result_is_french(tmp_path):
    from test_web import gpx_bytes

    result = _fr([("jour.gpx", gpx_bytes(to_track(cyl_day(ascent_a_s=3600))))], lines=TRAM, schedule=OPEN)
    d = result.data
    texts = list(d["warnings"]) + _messages_from_dict(d["chrono"])
    texts += [e["label"] for e in d["report"]["places"]] + [p["title"] for p in d["report"]["parts"]]
    texts += [e.get("near") or "" for e in d["report"]["places"]]
    for t in texts:
        assert_french(t)
    assert "dim." in d["report"]["track"]["start"]["local_date"] or "sam." in d["report"]["track"]["start"]["local_date"]


def _messages_from_dict(ch):
    out = list(ch["problems"]) + list(ch["notes"])
    if ch["transport"]:
        out += ch["transport"]["notes"] + [s["reason"] for s in ch["transport"]["stretches"]]
    return out
