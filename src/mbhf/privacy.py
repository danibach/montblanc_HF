"""The public part of a trace: what visitors see of an outing (Sarah, 29 October 2026).

A trace often starts at the pilot's door and may end there. Visitors are never sent that: the start of the trace is
left out up to ``HIDE_M`` of the climb on foot, or up to where it joins the itinerary other climbs take, whichever is
farther, and any drive before the climb with it; the end is left out after the last landing (the walk or the drive
back home). The pilot sees the whole
trace; the numbers of the outing (D+, D−, distances) are those of the whole trace.

The server writes the public parts (``trace_public``, ``climb_public``) next to the private ones; the database sends
visitors only those (supabase/migration-2026-10-29-private-starts.sql).
"""

from __future__ import annotations

import math
from typing import Optional

from .geo import haversine_m
from .segment import FLIGHT, WALK

HIDE_M = 500.0      # left out at least, at the start of the climb on foot
JOIN_M = 150.0      # a fix this close to the itinerary goes along it ...
JOIN_SHARE = 0.9    # ... and the trace has joined it when this share of the rest of its climb does


def _walked(trace: dict, idx: range) -> list[float]:
    """Metres covered from the first index of ``idx`` to each one of them."""
    lat, lon = trace["lat"], trace["lon"]
    out, d, prev = [], 0.0, None
    for i in idx:
        if prev is not None:
            d += haversine_m(lat[prev], lon[prev], lat[i], lon[i])
        out.append(d)
        prev = i
    return out


def _near(p: tuple[float, float], line: list, metres: float) -> bool:
    k = math.cos(math.radians(p[0]))
    for (a_lat, a_lon), (b_lat, b_lon) in zip(line, line[1:]):
        ax, ay, bx, by = a_lon * 111320.0 * k, a_lat * 110540.0, b_lon * 111320.0 * k, b_lat * 110540.0
        px, py = p[1] * 111320.0 * k, p[0] * 110540.0
        vx, vy = bx - ax, by - ay
        ln = vx * vx + vy * vy
        t = 0.0 if ln == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / ln))
        if math.hypot(px - ax - t * vx, py - ay - t * vy) <= metres:
            return True
    return len(line) == 1 and math.hypot((p[1] - line[0][1]) * 111320.0 * k, (p[0] - line[0][0]) * 110540.0) <= metres


def public_span(trace: dict, itinerary: Optional[list] = None) -> tuple[int, int]:
    """``(first, last)``: the indexes of the trace a visitor sees. ``itinerary`` is the line ([[lat, lon], …]) of the
    itinerary the outing belongs to, when other climbs take it too."""
    n = len(trace["t"])
    if n < 2:
        return 0, n - 1
    m = trace.get("m") or [WALK] * n
    flying = [i for i, x in enumerate(m) if x == FLIGHT]
    climb_end = flying[0] if flying else n - 1
    # the climb on foot: the run of walking fixes just before the first flight (a drive before it is left out)
    climb_start = climb_end
    while climb_start > 0 and m[climb_start - 1] == WALK:
        climb_start -= 1
    start = _walked(trace, range(climb_start, n))
    first = climb_start + next((i for i, d in enumerate(start) if d >= HIDE_M), len(start) - 1)
    if itinerary and len(itinerary) >= 2:
        pts = list(zip(trace["lat"][:climb_end + 1], trace["lon"][:climb_end + 1]))
        near = [_near(p, itinerary, JOIN_M) for p in pts]
        rest = 0
        join = None
        for i in range(len(near) - 1, -1, -1):
            rest += near[i]
            if near[i] and rest / (len(near) - i) >= JOIN_SHARE:
                join = i
        if join is not None:
            first = max(first, join)
    first = min(first, climb_end)
    # after the last landing: the walk or the drive back home
    last = (flying[-1] + 1 if flying[-1] + 1 < n else flying[-1]) if flying else n - 1
    return first, max(first, last)


def public_trace(trace: dict, first: int, last: int) -> dict:
    """The trace from ``first`` to ``last``, its times counted from its new first fix."""
    from datetime import datetime, timedelta

    t = trace["t"]
    t0 = datetime.fromisoformat(trace["t0"].replace("Z", "+00:00")) + timedelta(seconds=t[first])
    out = {k: v[first:last + 1] for k, v in trace.items() if isinstance(v, list)}
    out["t"] = [round(x - t[first], 1) for x in t[first:last + 1]]
    out["t0"] = t0.isoformat().replace("+00:00", "Z")
    return out


def public_climb(climb: Optional[dict], trace: dict, first: int) -> Optional[dict]:
    """The climb of the take-off map without the part a visitor does not see: its line starts at the fix of the
    climb nearest to the first public fix of the trace."""
    if not climb or not climb.get("line"):
        return climb
    line = climb["line"]
    p = (trace["lat"][first], trace["lon"][first])
    k = math.cos(math.radians(p[0]))
    j = min(range(len(line)), key=lambda i: math.hypot((line[i][1] - p[1]) * 111320.0 * k, (line[i][0] - p[0]) * 110540.0))
    if len(line) - j < 2:
        return {**climb, "line": line[-2:]}
    return {**climb, "line": line[j:]}


def public_parts(trace: Optional[dict], climb: Optional[dict], itinerary: Optional[list] = None) -> dict:
    """``{trace_public, climb_public}`` for the database."""
    if not trace or not trace.get("t"):
        return {"trace_public": None, "climb_public": climb or None}
    first, last = public_span(trace, itinerary)
    return {"trace_public": public_trace(trace, first, last), "climb_public": public_climb(climb, trace, first)}
