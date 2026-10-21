from datetime import datetime, timezone

import pytest

from mbhf.models import TrackError
from mbhf.parsers import load_track

GPX = """<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><trkseg>
  <trkpt lat="45.9000" lon="6.8000"><ele>1000.5</ele><time>2026-09-12T05:00:00Z</time></trkpt>
  <trkpt lat="45.9001" lon="6.8001"><ele>1001.0</ele><time>2026-09-12T05:00:05Z</time></trkpt>
  <trkpt lat="45.9002" lon="6.8002"><ele>1002.0</ele><time>2026-09-12T07:00:10+02:00</time></trkpt>
 </trkseg></trk>
</gpx>"""

GPX_UNTIMED = GPX.replace("<time>2026-09-12T05:00:00Z</time>", "").replace(
    "<time>2026-09-12T05:00:05Z</time>", ""
)

KML = """<?xml version="1.0"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
 <Document><Placemark><gx:Track>
  <when>2026-09-12T05:00:00Z</when><when>2026-09-12T05:00:05Z</when>
  <gx:coord>6.8000 45.9000 1000</gx:coord><gx:coord>6.8001 45.9001 1001</gx:coord>
 </gx:Track></Placemark></Document></kml>"""

KML_LINE = """<?xml version="1.0"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><LineString>
 <coordinates>6.8,45.9,1000 6.81,45.91,1100</coordinates></LineString></Placemark></Document></kml>"""

# 23:59:58 -> 00:00:02 crosses midnight; pressure altitude 01000, GNSS 01020
IGC = "\n".join(
    [
        "AXXX000 test",
        "HFDTEDATE:120926,01",
        "B2359584554000N00648000EA0100001020",
        "B2359594554010N00648010EA0100501025",
        "B0000024554020N00648020EA0101001030",
        "B0000044554030N00648030VA0101501035",
        "B0000064554040N00648040EA0102001040",
        "G1234567890",
    ]
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="latin-1")
    return str(p)


def test_gpx_parses_and_normalises_time_to_utc(tmp_path):
    tr = load_track(_write(tmp_path, "a.gpx", GPX))
    assert len(tr.points) == 3
    assert tr.points[0].alt == 1000.5
    assert tr.points[2].t == datetime(2026, 9, 12, 5, 0, 10, tzinfo=timezone.utc)  # +02:00 -> UTC


def test_gpx_without_timestamps_is_refused(tmp_path):
    with pytest.raises(TrackError, match="timestamp"):
        load_track(_write(tmp_path, "b.gpx", GPX_UNTIMED))


def test_kml_gx_track(tmp_path):
    tr = load_track(_write(tmp_path, "a.kml", KML))
    assert len(tr.points) == 2 and tr.points[1].alt == 1001.0


def test_kml_plain_linestring_is_refused(tmp_path):
    with pytest.raises(TrackError, match="timestamps"):
        load_track(_write(tmp_path, "b.kml", KML_LINE))


def test_igc_parse_midnight_rollover_and_altitudes(tmp_path):
    tr = load_track(_write(tmp_path, "a.igc", IGC))
    assert tr.hint == "flight"                      # an IGC file is a flight by default
    assert len(tr.points) == 4                      # the V (2D) record is skipped
    assert tr.points[0].t == datetime(2026, 9, 12, 23, 59, 58, tzinfo=timezone.utc)
    assert tr.points[2].t == datetime(2026, 9, 13, 0, 0, 2, tzinfo=timezone.utc)
    assert tr.points[0].alt == 1020.0 and tr.points[0].alt_baro == 1000.0
    assert abs(tr.points[0].lat - (45 + 54.0 / 60)) < 1e-9
    assert abs(tr.points[0].lon - (6 + 48.0 / 60)) < 1e-9


def test_igc_without_date_is_refused(tmp_path):
    with pytest.raises(TrackError, match="HFDTE"):
        load_track(_write(tmp_path, "b.igc", IGC.replace("HFDTEDATE:120926,01\n", "")))


def test_unsupported_extension(tmp_path):
    with pytest.raises(TrackError, match="unsupported"):
        load_track(_write(tmp_path, "a.txt", "hello"))


def test_xml_entity_bomb_is_rejected(tmp_path):
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;">]>'
        '<gpx><trk><trkseg><trkpt lat="1" lon="1"><time>&b;</time></trkpt></trkseg></trk></gpx>'
    )
    with pytest.raises(TrackError):
        load_track(_write(tmp_path, "bomb.gpx", bomb))


TCX = """<?xml version="1.0" encoding="UTF-8" ?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
 <Activities><Activity Sport="Running"><Id>2026-09-12T05:00:00Z</Id>
  <Lap StartTime="2026-09-12T05:00:00Z"><Track>
   <Trackpoint><Time>2026-09-12T05:00:00Z</Time><DistanceMeters>0.0</DistanceMeters></Trackpoint>
   <Trackpoint><Time>2026-09-12T05:00:05Z</Time>
    <Position><LatitudeDegrees>45.9000</LatitudeDegrees><LongitudeDegrees>6.8000</LongitudeDegrees></Position>
    <AltitudeMeters>1000.5</AltitudeMeters></Trackpoint>
   <Trackpoint><Time>2026-09-12T07:00:10+02:00</Time>
    <Position><LatitudeDegrees>45.9002</LatitudeDegrees><LongitudeDegrees>6.8002</LongitudeDegrees></Position>
    <AltitudeMeters>1002.0</AltitudeMeters></Trackpoint>
  </Track></Lap></Activity></Activities></TrainingCenterDatabase>"""


def test_tcx_parses_and_skips_points_without_position(tmp_path):
    tr = load_track(_write(tmp_path, "a.tcx", TCX))
    assert tr.fmt == "tcx"
    assert len(tr.points) == 2                      # the first trackpoint has no position
    assert tr.points[0].alt == 1000.5
    assert tr.points[1].t == datetime(2026, 9, 12, 5, 0, 10, tzinfo=timezone.utc)


def test_tcx_without_any_position_is_refused(tmp_path):
    empty = TCX.split("<Trackpoint>")[0] + "<Trackpoint><Time>2026-09-12T05:00:00Z</Time></Trackpoint></Track></Lap></Activity></Activities></TrainingCenterDatabase>"
    with pytest.raises(TrackError):
        load_track(_write(tmp_path, "e.tcx", empty))
