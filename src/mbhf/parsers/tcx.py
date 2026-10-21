"""TCX parser (Garmin Training Center, also written by iSmoothRun and many phone apps).

Every ``Trackpoint`` of every lap and activity is read; a point without a position (the recorder had
no fix yet) is skipped. Lap and activity boundaries mean nothing here: the points are put in time order.
"""

from __future__ import annotations

import math
from typing import Optional

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from ..models import Point, Track, TrackError
from .common import finish_track, parse_iso_time, valid_latlon


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(text: Optional[str]) -> Optional[float]:
    try:
        v = float(text) if text else None
    except ValueError:
        return None
    return v if v is not None and math.isfinite(v) else None


def parse_tcx(path: str, hint: Optional[str] = None, src: int = 0) -> Track:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, DefusedXmlException) as exc:
        raise TrackError(f"{path}: not a valid TCX file ({exc})") from exc

    points: list[Point] = []
    untimed = invalid = 0
    for el in root.iter():
        if _local(el.tag) != "Trackpoint":
            continue
        when = lat = lon = alt = None
        has_position = False
        for child in el.iter():
            name = _local(child.tag)
            if name == "Time":
                when = parse_iso_time(child.text)
            elif name == "LatitudeDegrees":
                lat, has_position = _number(child.text), True
            elif name == "LongitudeDegrees":
                lon, has_position = _number(child.text), True
            elif name == "AltitudeMeters":
                alt = _number(child.text)
        if not has_position:
            continue  # no fix yet: not a point of the track
        if lat is None or lon is None or not valid_latlon(lat, lon):
            invalid += 1
            continue
        if when is None:
            untimed += 1
            continue
        points.append(Point(t=when, lat=lat, lon=lon, alt=alt, hint=hint, src=src))

    return finish_track(points, source=path, fmt="tcx", hint=hint, untimed=untimed, invalid=invalid)
