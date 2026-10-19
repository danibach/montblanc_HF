"""Merge several track files (e.g. bike, walk and flight recorded separately) into one timeline."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Optional, Sequence

from .geo import haversine_m
from .models import Point, Track, TrackError

# When two files cover the same period, the more specific source wins.
_PRIORITY = {None: 0, "bike": 1, "walk": 2, "flight": 3}

GAP_WARN_S = 180.0          # report a recording gap longer than this
TELEPORT_KMH = 400.0        # faster than any plausible movement: report as a jump


def merge_tracks(tracks: Sequence[Track]) -> Track:
    """Combine tracks into one time-ordered track.

    Overlap rule: a point is dropped when another file with a higher priority
    (flight > walk > bike > unlabelled) covers the same moment; for files of equal
    priority the one listed first wins. This is what lets a watch recording of the
    whole day be combined with the flight recorder's own IGC file.
    """
    if not tracks:
        raise TrackError("no track to merge")
    warnings: list[str] = []
    for tr in tracks:
        warnings.extend(tr.warnings)

    ranges = [(tr.t_start, tr.t_end) for tr in tracks]
    kept: list[Point] = []
    for idx, tr in enumerate(tracks):
        prio = _PRIORITY[tr.hint]
        dropped = 0
        for p in tr.points:
            shadowed = False
            for jdx, other in enumerate(tracks):
                if jdx == idx:
                    continue
                oprio = _PRIORITY[other.hint]
                if oprio > prio or (oprio == prio and jdx < idx):
                    lo, hi = ranges[jdx]
                    if lo <= p.t <= hi:
                        shadowed = True
                        break
            if shadowed:
                dropped += 1
            else:
                if p.src != idx or (tr.hint is not None and p.hint != tr.hint):
                    p = replace(p, src=idx, hint=tr.hint if tr.hint is not None else p.hint)
                kept.append(p)
        if dropped:
            warnings.append(
                f"{tr.source}: {dropped} points fall inside the time range of a more specific "
                "file and were not used"
            )

    kept.sort(key=lambda p: p.t)
    unique: list[Point] = []
    last_t = None
    for p in kept:
        if p.t == last_t:
            continue
        unique.append(p)
        last_t = p.t
    if len(unique) < 2:
        raise TrackError("fewer than 2 points remain after merging")

    # Continuity diagnostics (information for the reviewer, not a rejection).
    for a, b in zip(unique, unique[1:]):
        dt = (b.t - a.t).total_seconds()
        if dt >= GAP_WARN_S:
            dist = haversine_m(a.lat, a.lon, b.lat, b.lon)
            warnings.append(
                f"gap of {dt / 60:.1f} min at {a.t.isoformat()} "
                f"(moved {dist / 1000:.2f} km while not recorded)"
            )
        elif dt > 0:
            kmh = haversine_m(a.lat, a.lon, b.lat, b.lon) / dt * 3.6
            if kmh > TELEPORT_KMH:
                warnings.append(f"position jump of {kmh:.0f} km/h at {a.t.isoformat()}")

    return Track(points=unique, source="+".join(t.source for t in tracks), fmt="merged", warnings=warnings)
