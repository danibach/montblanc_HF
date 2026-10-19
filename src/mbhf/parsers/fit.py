"""FIT parser (Garmin / Suunto / COROS style activity files)."""

from __future__ import annotations

import math
from datetime import timezone
from typing import Optional

from ..models import Point, Track, TrackError
from .common import finish_track, valid_latlon

_SEMICIRCLE = 180.0 / 2**31


def parse_fit(path: str, hint: Optional[str] = None, src: int = 0) -> Track:
    try:
        import fitdecode
    except ImportError as exc:  # pragma: no cover
        raise TrackError("FIT support needs the 'fitdecode' package (pip install fitdecode)") from exc

    points: list[Point] = []
    untimed = invalid = 0
    try:
        with fitdecode.FitReader(path) as reader:
            for frame in reader:
                if frame.frame_type != fitdecode.FIT_FRAME_DATA or frame.name != "record":
                    continue
                raw_lat = frame.get_value("position_lat", fallback=None)
                raw_lon = frame.get_value("position_long", fallback=None)
                if raw_lat is None or raw_lon is None:
                    continue  # records without a GPS fix are normal (tunnels, start-up)
                lat, lon = raw_lat * _SEMICIRCLE, raw_lon * _SEMICIRCLE
                if not valid_latlon(lat, lon):
                    invalid += 1
                    continue
                when = frame.get_value("timestamp", fallback=None)
                if when is None:
                    untimed += 1
                    continue
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                alt = frame.get_value("enhanced_altitude", fallback=None)
                if alt is None:
                    alt = frame.get_value("altitude", fallback=None)
                if alt is not None:
                    alt = float(alt)
                    if not math.isfinite(alt):
                        alt = None
                points.append(
                    Point(t=when.astimezone(timezone.utc), lat=lat, lon=lon, alt=alt, hint=hint, src=src)
                )
    except (fitdecode.FitError, OSError) as exc:
        raise TrackError(f"{path}: not a readable FIT file ({exc})") from exc

    return finish_track(points, source=path, fmt="fit", hint=hint, untimed=untimed, invalid=invalid)
