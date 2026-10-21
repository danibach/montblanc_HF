"""Helpers shared by the file parsers."""

from __future__ import annotations

import math
from dataclasses import replace
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


def clean_altitudes(
    points: list[Point], zero_jump_m: float = 50.0, spike_m: float = 80.0, spike_return_m: float = 30.0
) -> tuple[list[Point], int]:
    """Blank the altitudes that are plainly recording errors; returns (points, how many were blanked).

    Two kinds of error are removed, nothing else is touched:

    * a reading of exactly 0 m (the receiver had no altitude fix) when the nearest real altitudes on
      both sides are more than ``zero_jump_m`` away: a block of zeros in the mountains would otherwise
      count as thousands of metres of climbing. A track genuinely recorded near sea level is kept.
    * a single fix that jumps more than ``spike_m`` from its neighbour and falls back within
      ``spike_return_m`` of it at the next fix.

    A blanked fix keeps its position and time; only its altitude becomes unknown.
    """
    alts = [p.alt for p in points]
    n = len(alts)
    blank = 0

    def is_zero(a: Optional[float]) -> bool:
        return a is not None and abs(a) < 0.5

    prev_real: list[Optional[float]] = [None] * n
    last = None
    for i in range(n):
        prev_real[i] = last
        if alts[i] is not None and not is_zero(alts[i]):
            last = alts[i]
    next_real: list[Optional[float]] = [None] * n
    nxt = None
    for i in range(n - 1, -1, -1):
        next_real[i] = nxt
        if alts[i] is not None and not is_zero(alts[i]):
            nxt = alts[i]
    for i in range(n):
        a = alts[i]
        if not is_zero(a):
            continue
        refs = [r for r in (prev_real[i], next_real[i]) if r is not None]
        if refs and all(abs(r - a) > zero_jump_m for r in refs):
            alts[i] = None
            blank += 1

    for i in range(1, n - 1):
        a, b, c = alts[i - 1], alts[i], alts[i + 1]
        if a is None or b is None or c is None:
            continue
        if abs(b - a) > spike_m and abs(c - a) < spike_return_m:
            alts[i] = None
            blank += 1

    if not blank:
        return points, 0
    return [p if p.alt == al else replace(p, alt=al) for p, al in zip(points, alts)], blank
