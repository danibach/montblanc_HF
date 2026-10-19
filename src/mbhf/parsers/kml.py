"""KML parser.

Only timed tracks are usable: Google's ``gx:Track`` (parallel ``when`` and
``gx:coord`` lists). A plain ``LineString`` carries no timestamps and is refused.
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


def parse_kml(path: str, hint: Optional[str] = None, src: int = 0) -> Track:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, DefusedXmlException) as exc:
        raise TrackError(f"{path}: not a valid KML file ({exc})") from exc

    points: list[Point] = []
    untimed = invalid = 0
    saw_track = False
    saw_linestring = False

    for el in root.iter():
        name = _local(el.tag)
        if name == "LineString":
            saw_linestring = True
        if name != "Track":
            continue
        saw_track = True
        whens = [c.text for c in el if _local(c.tag) == "when"]
        coords = [c.text for c in el if _local(c.tag) == "coord"]
        if len(whens) != len(coords):
            raise TrackError(
                f"{path}: gx:Track has {len(whens)} timestamps but {len(coords)} coordinates"
            )
        for w, c in zip(whens, coords):
            when = parse_iso_time(w)
            parts = (c or "").split()
            if len(parts) < 2:
                invalid += 1
                continue
            try:
                lon, lat = float(parts[0]), float(parts[1])
                ele = float(parts[2]) if len(parts) > 2 else None
            except ValueError:
                invalid += 1
                continue
            if not valid_latlon(lat, lon):
                invalid += 1
                continue
            if ele is not None and not math.isfinite(ele):
                ele = None
            if when is None:
                untimed += 1
                continue
            points.append(Point(t=when, lat=lat, lon=lon, alt=ele, hint=hint, src=src))

    if not saw_track:
        if saw_linestring:
            raise TrackError(
                f"{path}: this KML only has a plain line path without timestamps; "
                "timestamps are required (a gx:Track with <when> elements)"
            )
        raise TrackError(f"{path}: no gx:Track found in KML")

    return finish_track(points, source=path, fmt="kml", hint=hint, untimed=untimed, invalid=invalid)
