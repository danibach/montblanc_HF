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

What counts on foot, once the track holds a flight: the walk before each flight and every walk after
the last one (back to the car, up to the bivouac). A climb given up in the middle of the day (a ride
of ``ride_break_m`` or more comes before any flight) does not count. Across a recording gap (no fix
for more than ``gap_s``) the climb and the distance count only if the gap was more likely walked than
driven (``gap_verdict``): no single speed limit can tell a slow car from a fast walker, so several clues
are weighed into a probability (decided by Dani and Sarah, 24 October 2026). A pause with the
recorder on is a standstill and changes nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .freedist import free_distance
from .geo import haversine_m, path_length_m
from .models import Point, Track
from .segment import FLIGHT, VEHICLE, WALK, MODES, Segment, SegmentationResult

SCORE_VERSION = 1


@dataclass
class OutingConfig:
    smooth_s: float = 30.0            # altitude averaging window (seconds, each side)
    climb_threshold_m: float = 15.0   # a dip smaller than this does not end a climb (to calibrate)
    min_walk_climb_m: float = 200.0   # climbing on foot needed for the outing to count
    min_flight_drop_m: float = 30.0   # a flight must lose at least this much height to count
    # no fix for longer than this: a recording gap, walked or driven (see gap_verdict)
    gap_s: float = 600.0
    # an average walker (a Naismith-like rule): flat pace, climbing and descending rates; the straight line
    # between the two fixes is stretched by gap_path_factor, a path is never straight
    gap_walk_kmh: float = 5.0
    gap_climb_m_h: float = 600.0
    gap_descent_m_h: float = 1800.0
    gap_path_factor: float = 1.25
    # walkers' paces spread around the average (log-normal): 0.35 makes 1.5 times faster than average ~12 %
    # of walkers, twice as fast ~2 %
    gap_pace_sigma: float = 0.35
    # before any clue, one gap in four is taken to be a ride
    gap_prior_vehicle: float = 0.25
    # a ride recorded within this many seconds before or after the gap makes a ride this many times likelier
    gap_context_s: float = 300.0
    gap_context_lr: float = 6.0
    # how likely the gap's duration is for a ride (a ride fits almost any duration: parking, waiting)
    gap_vehicle_like: float = 0.3
    # a probability of a ride in this band is a doubt: decided, with "to be checked"
    gap_doubt: tuple = (0.3, 0.75)
    # no further than this and no higher or lower: a pause, not a move
    gap_pause_m: float = 150.0
    gap_pause_dz_m: float = 30.0
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


def _vehicle_near(pts: list[Point], labels: list[int], i: int, within_s: float) -> bool:
    """A ride recorded within ``within_s`` before fix ``i - 1`` or after fix ``i`` (the two ends of the gap)."""
    k = i - 1
    while k >= 0 and (pts[i - 1].t - pts[k].t).total_seconds() <= within_s:
        if labels[k] == VEHICLE:
            return True
        k -= 1
    k = i
    while k < len(pts) and (pts[k].t - pts[i].t).total_seconds() <= within_s:
        if labels[k] == VEHICLE:
            return True
        k += 1
    return False


def gap_verdict(pts: list[Point], salt: list[Optional[float]], labels: list[int], i: int,
                cfg: Optional[OutingConfig] = None) -> dict:
    """The recording gap between fixes ``i - 1`` and ``i``: walked or driven? With the recorder off, the way
    taken is unknown: only the two ends, the time and what was recorded around the gap. Clues, weighed into
    the probability of a ride (Bayes, odds multiplied):

    * a ride recorded just before or after the gap: most likely the same ride going on (``gap_context_lr``);
    * the time an average walker needs for it (distance stretched by ``gap_path_factor``, climb, descent),
      and so the share of walkers fast enough (log-normal spread of paces): the rarer such a walker, the
      likelier a ride;
    * a gap with no move is a pause, walked.

    Returns ``on_foot``, ``p_vehicle``, ``doubt`` (decided, but to be checked), ``need_min`` (minutes an
    average walker needs), ``able`` (share of walkers fast enough) and ``vehicle_near``."""
    cfg = cfg or OutingConfig()
    p0, p1 = pts[i - 1], pts[i]
    minutes = (p1.t - p0.t).total_seconds() / 60.0
    d_m = haversine_m(p0.lat, p0.lon, p1.lat, p1.lon)
    a0 = salt[i - 1] if salt[i - 1] is not None else p0.alt
    a1 = salt[i] if salt[i] is not None else p1.alt
    dz = (a1 - a0) if a0 is not None and a1 is not None else 0.0
    near = _vehicle_near(pts, labels, i, cfg.gap_context_s)
    if d_m <= cfg.gap_pause_m and abs(dz) <= cfg.gap_pause_dz_m:
        return {"on_foot": True, "pause": True, "p_vehicle": 0.0, "doubt": False, "need_min": 0.0, "able": 1.0,
                "vehicle_near": near}
    need_h = (d_m / 1000.0 * cfg.gap_path_factor / cfg.gap_walk_kmh
              + max(dz, 0.0) / cfg.gap_climb_m_h + max(-dz, 0.0) / cfg.gap_descent_m_h)
    pace = max(need_h * 60.0 / max(minutes, 1e-6), 1e-6)  # how much faster than an average walker
    able = 0.5 * math.erfc(math.log(pace) / (cfg.gap_pace_sigma * math.sqrt(2.0)))
    odds = (cfg.gap_prior_vehicle / (1.0 - cfg.gap_prior_vehicle) * (cfg.gap_context_lr if near else 1.0)
            * cfg.gap_vehicle_like / max(able, 1e-9))
    p_vehicle = odds / (1.0 + odds)
    low, high = cfg.gap_doubt
    return {"on_foot": p_vehicle < 0.5, "pause": False, "p_vehicle": p_vehicle, "doubt": low < p_vehicle < high,
            "need_min": need_h * 60.0, "able": able, "vehicle_near": near}


def _gap_note(pts: list[Point], i: int, v: dict) -> str:
    """The warning that says what was decided about a recording gap, and why."""
    gap_min = (pts[i].t - pts[i - 1].t).total_seconds() / 60.0
    a0, a1 = pts[i - 1].alt, pts[i].alt
    change = f", {a0:.0f} m to {a1:.0f} m" if a0 is not None and a1 is not None else ""
    what = f"recording gap of {gap_min:.0f} min ({pts[i - 1].t.strftime('%H:%M')}{change})"
    if v["pause"]:
        return f"{what}: a pause, counted"
    why = [f"an average walker needs about {v['need_min']:.0f} min, {v['able']:.0%} of walkers could do it in {gap_min:.0f}"]
    if v["vehicle_near"]:
        why.insert(0, "a ride recorded just before or after")
    # "not walked": a ride, a lift, or a flight with the recorder off (the 2019 Mont-Blanc track: 15 km in 42 min)
    head = ("plausible on foot, counted" if v["on_foot"]
            else "probably not walked (a ride, a lift or a flight), nothing on foot counted across it")
    tail = " - to be checked" if v["doubt"] else ""
    return f"{what}: {head} ({'; '.join(why)}){tail}"


def _recorded_pieces(pts: list[Point], salt: list[Optional[float]], labels: list[int], i0: int, i1: int,
                     cfg: OutingConfig) -> list[tuple[int, int]]:
    """Index ranges of i0..i1 split where no fix was recorded for more than ``gap_s`` and the gap was more
    likely driven than walked (a walked gap stays inside one piece, so its climb and distance count)."""
    out, a = [], i0
    for i in range(i0 + 1, i1 + 1):
        if (pts[i].t - pts[i - 1].t).total_seconds() > cfg.gap_s and not gap_verdict(pts, salt, labels, i, cfg)["on_foot"]:
            out.append((a, i - 1))
            a = i
    out.append((a, i1))
    return out


def _walks_leading_to_a_flight(segments: list[Segment], cfg: OutingConfig) -> set[int]:
    """The walks (by ``id``) whose climbing counts: those followed by a flight with no ride of at least
    ``ride_break_m`` in between, and every walk after the last flight (back to the car, up to the bivouac).
    A walk before a ride with a flight nowhere after it in between (a climb given up) is left out."""
    leads: set[int] = set()
    pending: list[Segment] = []
    last_flight = max((k for k, s in enumerate(segments) if s.mode == "flight"), default=None)
    for k, s in enumerate(segments):
        if s.mode == "walk":
            pending.append(s)
            if last_flight is not None and k > last_flight:
                leads.add(id(s))
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
        for a, b in _recorded_pieces(pts, salt, seg.labels, s.i_start, s.i_end, cfg):
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
            warnings.append(_gap_note(pts, i, gap_verdict(pts, salt, seg.labels, i, cfg)))
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
