"""GPX parser (track points only; routes and waypoints are not tracks)."""

from __future__ import annotations

import math
from typing import Optional

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from ..models import Point, Track, TrackError
from .common import finish_track, parse_iso_time, valid_latlon


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_gpx(path: str, hint: Optional[str] = None, src: int = 0) -> Track:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, DefusedXmlException) as exc:
        raise TrackError(f"{path}: not a valid GPX file ({exc})") from exc

    points: list[Point] = []
    untimed = invalid = 0
    for el in root.iter():
        if _local(el.tag) != "trkpt":
            continue
        try:
            lat = float(el.get("lat"))
            lon = float(el.get("lon"))
        except (TypeError, ValueError):
            invalid += 1
            continue
        if not valid_latlon(lat, lon):
            invalid += 1
            continue
        ele: Optional[float] = None
        when = None
        for child in el:
            name = _local(child.tag)
            if name == "ele" and child.text:
                try:
                    ele = float(child.text)
                except ValueError:
                    ele = None
                if ele is not None and not math.isfinite(ele):
                    ele = None
            elif name == "time":
                when = parse_iso_time(child.text)
        if when is None:
            untimed += 1
            continue
        points.append(Point(t=when, lat=lat, lon=lon, alt=ele, hint=hint, src=src))

    return finish_track(points, source=path, fmt="gpx", hint=hint, untimed=untimed, invalid=invalid)
