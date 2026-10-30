"""The climb on foot that reached the take-off, for the take-off map.

It is read from the stored trace (``build_trace``: times, positions, altitudes and the label of each fix) and the
outing's flights, so it can also be computed for outings already in the database. Nothing of the analysis is
changed: the labels found by the segmentation are used as they are.

The climb is the run of walking fixes just before the main flight (the one that loses the most height, whose
take-off is the outing's take-off). Driving, lifts and flights are left out.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from .geo import haversine_m
from .outing import OutingConfig, climbs
from .segment import FLIGHT, WALK

MAX_POINTS = 80        # the line kept for the map
# a short stretch labelled other than walking inside the climb (a GPS gap: the phone finds itself far away, as fast as
# a car) does not cut it; a drive or a lift is longer (Sarah, 30 October 2026: Montagne de Vaunessin, 156 m of its
# 733 m). With no ranking any more, a doubtful stretch keeps the climb whole
GAP_S = 300.0
GAP_M = 1000.0
VERSION = 2            # the rule the stored climbs were made with: those of an older one are made again
TOLERANCE_M = 12.0     # simplification: a fix closer than this to the straight line between its neighbours goes


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _simplify(line: list[tuple[float, float]], tol_m: float) -> list[int]:
    """Douglas-Peucker on a local flat projection: indexes of the fixes kept (always the first and the last)."""
    if len(line) <= 2:
        return list(range(len(line)))
    lat0 = math.radians(line[0][0])
    xy = [(lon * 111320.0 * math.cos(lat0), lat * 110540.0) for lat, lon in line]
    keep = {0, len(line) - 1}
    stack = [(0, len(line) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = xy[a], xy[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        far, far_d = None, tol_m
        for i in range(a + 1, b):
            px, py = xy[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / norm if norm else math.hypot(px - ax, py - ay)
            if d > far_d:
                far, far_d = i, d
        if far is not None:
            keep.add(far)
            stack += [(a, far), (far, b)]
    return sorted(keep)


def climb_of(trace: Optional[dict], flights: Optional[list]) -> Optional[dict]:
    """``{line: [[lat, lon], …], dplus_m, km, duration_s}`` of the climb to the main take-off, or None."""
    if not trace or not trace.get("m"):
        return None
    m, t = trace["m"], trace["t"]
    main = max(flights or [], key=lambda f: f.get("drop_m") or 0, default=None)
    end = -1
    if main and (main.get("takeoff") or {}).get("t"):
        at = _ts(main["takeoff"]["t"]) - _ts(trace["t0"])
        end = next((i for i, x in enumerate(t) if x >= at), -1)
    if end < 0:
        end = next((i for i, x in enumerate(m) if x == FLIGHT), -1)
    if end <= 0:
        return None
    last = end - 1
    while last >= 0 and m[last] != WALK:
        last -= 1
    lat, lon, alt = trace["lat"], trace["lon"], trace["alt"]
    first = last
    while first > 0:
        if m[first - 1] == WALK:
            first -= 1
            continue
        # a stretch that is neither walking nor flying, with walking before it: a short one is a GPS gap
        gap_end = first - 1
        gap_start = gap_end
        while gap_start > 0 and m[gap_start - 1] not in (WALK, FLIGHT):
            gap_start -= 1
        if gap_start == 0 or m[gap_start - 1] != WALK:
            break
        a, b = gap_start - 1, first
        if t[b] - t[a] > GAP_S and haversine_m(lat[a], lon[a], lat[b], lon[b]) > GAP_M:
            break
        first = gap_start - 1
    if last < 1 or last - first < 1:
        return None
    idx = list(range(first, last + 1)) + [end]  # up to the take-off itself
    metres = sum(haversine_m(lat[a], lon[a], lat[b], lon[b]) for a, b in zip(idx, idx[1:]))
    up, _ = climbs([alt[i] for i in idx if alt[i] is not None], OutingConfig().climb_threshold_m)
    line = [(lat[i], lon[i]) for i in idx]
    tol = TOLERANCE_M
    kept = _simplify(line, tol)
    while len(kept) > MAX_POINTS:
        tol *= 1.5
        kept = _simplify(line, tol)
    return {
        "line": [[round(line[k][0], 5), round(line[k][1], 5)] for k in kept],
        "dplus_m": round(up),
        "km": round(metres / 1000, 2),
        "duration_s": round(t[end] - t[first]),
        "v": VERSION,
    }
