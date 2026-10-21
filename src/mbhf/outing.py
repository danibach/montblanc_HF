"""From a segmented track to one scored outing.

What is measured (all from the track alone, nothing is typed in by the participant):

* where the walk started, the highest point reached on foot, where each flight took off and landed
* D+ on foot: the sum of the climbs, each from a low point to the next high point; a dip smaller
  than ``climb_threshold_m`` does not end a climb (it is GPS noise)
* D- in flight: for each flight, take-off altitude minus landing altitude (thermals ignored)
* distance on foot, and the FAI free distance of each flight, added up over the outing
* score = D+ on foot + D- in flight, in metres (``score_version`` says which formula)

A track counts as a Hike & Fly outing when it holds at least one flight and at least
``min_walk_climb_m`` of climbing on foot. Anything else is reported as ``rejected`` with a reason.

Only the climbing that leads to a take-off counts: the walk since the last landing or the last ride
before each flight. A climb given up without taking off (too much wind, then down on foot or by car)
does not count, even when the same file holds a flight later. Across a recording gap (no fix for more
than ``gap_s``: the recorder was off, often in a car or a lift) neither D+ nor distance is counted;
a pause with the recorder on is a standstill and changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .freedist import free_distance
from .geo import path_length_m
from .models import Point, Track
from .segment import FLIGHT, VEHICLE, WALK, MODES, Segment, SegmentationResult

SCORE_VERSION = 1


@dataclass
class OutingConfig:
    smooth_s: float = 30.0            # altitude averaging window (seconds, each side)
    climb_threshold_m: float = 15.0   # a dip smaller than this does not end a climb (to calibrate)
    min_walk_climb_m: float = 200.0   # climbing on foot needed for the outing to count
    min_flight_drop_m: float = 30.0   # a flight must lose at least this much height to count
    # no fix for longer than this: a recording gap, nothing on foot is counted across it
    gap_s: float = 600.0
    # a ride at least this long ends the climb on foot that led to it (shorter: a misread step, ignored)
    ride_break_m: float = 500.0
    max_trace_points: int = 1200


def smooth_altitudes(pts: list[Point], half_window_s: float) -> list[Optional[float]]:
    """Moving average of the altitude over +- ``half_window_s`` seconds (None where unknown)."""
    n = len(pts)
    ts = [p.t.timestamp() for p in pts]
    out: list[Optional[float]] = []
    lo = hi = 0
    total = 0.0
    count = 0
    for i in range(n):
        while hi < n and ts[hi] - ts[i] <= half_window_s:
            if pts[hi].alt is not None:
                total += pts[hi].alt
                count += 1
            hi += 1
        while ts[i] - ts[lo] > half_window_s:
            if pts[lo].alt is not None:
                total -= pts[lo].alt
                count -= 1
            lo += 1
        out.append(total / count if count else None)
    return out


def climbs(values: list[float], threshold: float) -> tuple[float, float]:
    """Total climb and total descent of a series, ignoring wiggles smaller than ``threshold``."""
    if len(values) < 2:
        return 0.0, 0.0
    pivots = [values[0]]
    ext = values[0]
    d = 0  # 0 undecided, 1 rising, -1 falling
    for a in values[1:]:
        if d == 0:
            if a - ext >= threshold:
                d, ext = 1, a
            elif ext - a >= threshold:
                d, ext = -1, a
        elif d == 1:
            if a > ext:
                ext = a
            elif ext - a >= threshold:
                pivots.append(ext)
                d, ext = -1, a
        else:
            if a < ext:
                ext = a
            elif a - ext >= threshold:
                pivots.append(ext)
                d, ext = 1, a
    pivots.append(ext)
    up = sum(max(0.0, b - a) for a, b in zip(pivots, pivots[1:]))
    down = sum(max(0.0, a - b) for a, b in zip(pivots, pivots[1:]))
    return up, down


def _pt(p: Point, alt: Optional[float] = None) -> dict:
    a = alt if alt is not None else p.alt
    return {
        "lat": round(p.lat, 5),
        "lon": round(p.lon, 5),
        "alt": None if a is None else round(a),
        "t": p.t.isoformat(),
    }


def _edge_alt(salt: list[Optional[float]], pts: list[Point], i0: int, i1: int, end: bool) -> Optional[float]:
    """Altitude at the start (or end) of a part: the middle value of its first (or last) fixes."""
    idx = range(max(i0, i1 - 4), i1 + 1) if end else range(i0, min(i1, i0 + 4) + 1)
    vals = sorted(pts[i].alt for i in idx if pts[i].alt is not None)
    if vals:
        return vals[len(vals) // 2]
    vals = sorted(salt[i] for i in idx if salt[i] is not None)
    return vals[len(vals) // 2] if vals else None


def build_trace(track: Track, labels: list[int], max_points: int = 1200) -> dict:
    """Compact arrays to draw the track: at most ``max_points`` fixes, always the first and last.

    Times are seconds after ``t0`` (UTC); ``m`` is the label of each kept fix (0 walk, 1 flight,
    2 vehicle).
    """
    pts = track.points
    n = len(pts)
    if n <= max_points:
        idx = list(range(n))
    else:
        step = (n - 1) / (max_points - 1)
        idx = sorted({round(i * step) for i in range(max_points)})
    t0 = pts[0].t
    return {
        "t0": t0.isoformat(),
        "t": [round((pts[i].t - t0).total_seconds(), 1) for i in idx],
        "lat": [round(pts[i].lat, 5) for i in idx],
        "lon": [round(pts[i].lon, 5) for i in idx],
        "alt": [None if pts[i].alt is None else round(pts[i].alt) for i in idx],
        "m": [labels[i] for i in idx],
    }


def _recorded_pieces(pts: list[Point], i0: int, i1: int, gap_s: float) -> list[tuple[int, int]]:
    """Index ranges of i0..i1 split where no fix was recorded for more than ``gap_s``."""
    out, a = [], i0
    for i in range(i0 + 1, i1 + 1):
        if (pts[i].t - pts[i - 1].t).total_seconds() > gap_s:
            out.append((a, i - 1))
            a = i
    out.append((a, i1))
    return out


def _walks_leading_to_a_flight(segments: list[Segment], cfg: OutingConfig) -> set[int]:
    """The walks (by ``id``) whose climbing counts: those followed by a flight with no ride of at least
    ``ride_break_m`` in between. A walk after the last flight, or before a ride with no flight in between
    (a climb given up), does not lead to a take-off."""
    leads: set[int] = set()
    pending: list[Segment] = []
    for s in segments:
        if s.mode == "walk":
            pending.append(s)
        elif s.mode == "flight":
            leads.update(id(w) for w in pending)
            pending = []
        elif s.distance_m >= cfg.ride_break_m:
            pending = []
    return leads


def build_outing(track: Track, seg: SegmentationResult, cfg: Optional[OutingConfig] = None) -> dict:
    cfg = cfg or OutingConfig()
    pts = track.points
    salt = smooth_altitudes(pts, cfg.smooth_s)
    warnings: list[str] = list(seg.warnings)

    walks = [s for s in seg.segments if s.mode == "walk"]
    flights_raw = [s for s in seg.segments if s.mode == "flight"]

    # ---- on foot
    dplus = 0.0
    walk_m = 0.0
    highest: Optional[int] = None
    lost_climb = 0.0
    leads = _walks_leading_to_a_flight(seg.segments, cfg)
    for s in walks:
        up = 0.0
        for a, b in _recorded_pieces(pts, s.i_start, s.i_end, cfg.gap_s):
            series = [x for x in salt[a : b + 1] if x is not None]
            up += climbs(series, cfg.climb_threshold_m)[0]
            walk_m += path_length_m([(pts[i].lat, pts[i].lon) for i in range(a, b + 1)])
        if id(s) in leads:
            dplus += up
        else:
            lost_climb += up
        for i in range(s.i_start, s.i_end + 1):
            if salt[i] is not None and (highest is None or salt[i] > salt[highest]):
                highest = i
    for i in range(1, len(pts)):
        gap = (pts[i].t - pts[i - 1].t).total_seconds()
        if gap > cfg.gap_s and seg.labels[i - 1] == WALK and seg.labels[i] == WALK:
            a0, a1 = pts[i - 1].alt, pts[i].alt
            change = f", {a0:.0f} m to {a1:.0f} m" if a0 is not None and a1 is not None else ""
            warnings.append(f"recording gap of {gap / 60:.0f} min ({pts[i - 1].t.strftime('%H:%M')}{change}): "
                            "nothing on foot counted across it")
    if not flights_raw:  # no flight at all: the outing is refused anyway, show the climbing as measured
        dplus, lost_climb = dplus + lost_climb, 0.0
    if lost_climb >= cfg.climb_threshold_m:
        warnings.append(f"{lost_climb:.0f} m climbed on foot that did not lead to a take-off: not counted")
    start_walk = walks[0].i_start if walks else None

    # ---- in flight
    flights: list[dict] = []
    for s in flights_raw:
        a0 = _edge_alt(salt, pts, s.i_start, s.i_end, end=False)
        a1 = _edge_alt(salt, pts, s.i_start, s.i_end, end=True)
        drop = max(0.0, a0 - a1) if a0 is not None and a1 is not None else 0.0
        if drop < cfg.min_flight_drop_m:
            warnings.append(f"flight at {s.t_start.isoformat()} loses only {drop:.0f} m: not counted")
            continue
        coords = [(pts[i].lat, pts[i].lon) for i in range(s.i_start, s.i_end + 1)]
        free_m, tp = free_distance(coords)
        flights.append(
            {
                "takeoff": _pt(pts[s.i_start], a0),
                "landing": _pt(pts[s.i_end], a1),
                "duration_s": round(s.duration_s),
                "drop_m": round(drop),
                "path_km": round(path_length_m(coords) / 1000, 2),
                "free_km": round(free_m / 1000, 2),
                "turnpoints": [_pt(pts[s.i_start + k]) for k in tp],
                "i_start": s.i_start,
                "i_end": s.i_end,
            }
        )
    dminus = sum(f["drop_m"] for f in flights)
    main = max(flights, key=lambda f: f["drop_m"]) if flights else None

    # ---- verdict
    status, reason = "ok", None
    if not flights:
        status, reason = "rejected", "no_flight"
    elif dplus < cfg.min_walk_climb_m:
        status, reason = "rejected", "too_little_climb"

    vehicle_m = sum(s.distance_m for s in seg.segments if s.mode == "vehicle")
    if vehicle_m > 500:
        warnings.append(f"{vehicle_m / 1000:.1f} km of the track look like a vehicle: left out of the score")

    dplus_r = round(dplus)
    out = {
        "status": status,
        "reason": reason,
        "started_at": pts[0].t.isoformat(),
        "date": pts[0].t.date().isoformat(),
        "duration_s": round((pts[-1].t - pts[0].t).total_seconds()),
        "start": _pt(pts[start_walk]) if start_walk is not None else None,
        "summit": _pt(pts[highest], salt[highest]) if highest is not None else None,
        "takeoff": main["takeoff"] if main else None,
        "landing": main["landing"] if main else None,
        "dplus_m": dplus_r,
        "dminus_m": dminus,
        "walk_km": round(walk_m / 1000, 2),
        "flight_free_km": round(sum(f["free_km"] for f in flights), 2),
        "flight_path_km": round(sum(f["path_km"] for f in flights), 2),
        "vehicle_km": round(vehicle_m / 1000, 2),
        "score": dplus_r + dminus,
        "score_version": SCORE_VERSION,
        "flights": flights,
        "segments": [
            {
                "mode": s.mode,
                "start": s.t_start.isoformat(),
                "end": s.t_end.isoformat(),
                "duration_s": round(s.duration_s),
                "distance_km": round(s.distance_m / 1000, 2),
            }
            for s in seg.segments
        ],
    }
    out["warnings"] = warnings
    return out
