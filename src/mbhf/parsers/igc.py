"""IGC parser (flight recorder files).

Fixes come from ``B`` records; the date comes from the ``HFDTE`` header. Times are
UTC and roll over midnight. Both pressure and GNSS altitude are kept; the GNSS one
is preferred as the working altitude. The G-record signature is not verified here.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from ..models import Point, Track, TrackError
from .common import finish_track, valid_latlon

_DTE = re.compile(r"^HF(?:DTE|DTEDATE)[:]?(?:DATE:)?\s*(\d{6})", re.IGNORECASE)


def _parse_date(ddmmyy: str) -> date:
    day, month, yy = int(ddmmyy[0:2]), int(ddmmyy[2:4]), int(ddmmyy[4:6])
    # IGC has two-digit years; flights before 2000 are not relevant here.
    return date(2000 + yy, month, day)


def parse_igc(path: str, hint: Optional[str] = None, src: int = 0) -> Track:
    # An IGC file is by nature a flight: default the hint unless told otherwise.
    hint = hint or "flight"
    try:
        with open(path, "r", encoding="latin-1", errors="replace") as fh:
            lines = [ln.rstrip("\r\n") for ln in fh]
    except OSError as exc:
        raise TrackError(f"{path}: cannot read file ({exc})") from exc

    flight_date: Optional[date] = None
    for ln in lines:
        m = _DTE.match(ln)
        if m:
            try:
                flight_date = _parse_date(m.group(1))
            except ValueError:
                flight_date = None
            break
    if flight_date is None:
        raise TrackError(f"{path}: no valid HFDTE date header; timestamps cannot be built")

    points: list[Point] = []
    invalid = 0
    skipped_2d = 0
    current = flight_date
    prev_secs = -1
    for ln in lines:
        if not ln or ln[0] != "B" or len(ln) < 35:
            continue
        try:
            hh, mm, ss = int(ln[1:3]), int(ln[3:5]), int(ln[5:7])
            lat = int(ln[7:9]) + int(ln[9:14]) / 60000.0
            if ln[14] == "S":
                lat = -lat
            elif ln[14] != "N":
                raise ValueError("lat hemisphere")
            lon = int(ln[15:18]) + int(ln[18:23]) / 60000.0
            if ln[23] == "W":
                lon = -lon
            elif ln[23] != "E":
                raise ValueError("lon hemisphere")
            validity = ln[24]
            alt_baro = float(int(ln[25:30]))
            alt_gnss = float(int(ln[30:35]))
        except ValueError:
            invalid += 1
            continue
        if validity == "V":
            skipped_2d += 1
            continue
        if not (0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 61) or not valid_latlon(lat, lon):
            invalid += 1
            continue
        secs = hh * 3600 + mm * 60 + ss
        if prev_secs >= 0 and secs < prev_secs - 3600:  # midnight rollover
            current = current + timedelta(days=1)
        prev_secs = secs
        when = datetime(current.year, current.month, current.day, tzinfo=timezone.utc) + timedelta(
            seconds=secs
        )
        # GNSS altitude of exactly 0 usually means "not recorded".
        alt = alt_gnss if alt_gnss != 0.0 else alt_baro
        points.append(
            Point(t=when, lat=lat, lon=lon, alt=alt, alt_baro=alt_baro, hint=hint, src=src)
        )

    track = finish_track(points, source=path, fmt="igc", hint=hint, untimed=0, invalid=invalid)
    if skipped_2d:
        track.warnings.append(f"{path}: {skipped_2d} 2D-fix (V) records were ignored")
    return track
