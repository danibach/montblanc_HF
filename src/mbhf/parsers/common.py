"""Helpers shared by the file parsers."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from ..models import Point, Track, TrackError

# A file where more than this share of fixes lacks a timestamp is refused:
# the rules require timestamps, and a mostly-untimed file cannot be timed.
MAX_UNTIMED_SHARE = 0.05


def parse_iso_time(text: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp to an aware UTC datetime (naive input is taken as UTC)."""
    if not text:
        return None
    s = text.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def valid_latlon(lat: float, lon: float) -> bool:
    return (
        math.isfinite(lat)
        and math.isfinite(lon)
        and -90.0 <= lat <= 90.0
        and -180.0 <= lon <= 180.0
    )


def finish_track(
    points: list[Point],
    *,
    source: str,
    fmt: str,
    hint: Optional[str],
    untimed: int,
    invalid: int = 0,
) -> Track:
    """Apply the common checks and build the Track."""
    total = len(points) + untimed
    if total == 0:
        raise TrackError(f"{source}: no track points found")
    if untimed / total > MAX_UNTIMED_SHARE:
        raise TrackError(
            f"{source}: {untimed} of {total} points have no timestamp; "
            "timestamps are required to time a track"
        )
    if len(points) < 2:
        raise TrackError(f"{source}: fewer than 2 usable timed points")
    warnings: list[str] = []
    if untimed:
        warnings.append(f"{source}: {untimed} points without timestamp were dropped")
    if invalid:
        warnings.append(f"{source}: {invalid} points with invalid coordinates were dropped")
    points = sorted(points, key=lambda p: p.t)
    return Track(points=points, source=source, fmt=fmt, hint=hint, warnings=warnings)
