"""Split a track into bike / walk / flight parts.

Method
------
The challenge has a fixed shape: [bike out] -> walk (ascent) -> flight -> [walk] -> [bike back],
every part optional. We exploit that by labelling each fix with one of five ordered states

    0 bike_out   1 ascent (walk)   2 flight   3 walk_after_landing   4 bike_return

and finding, with a Viterbi pass, the cheapest labelling where the state can only stay or
move forward. The per-fix cost comes from smoothed ground speed, vertical speed and path
sinuosity (circling). Because the order is enforced, a fast downhill bike ride before the
walk cannot be mistaken for the flight, and a stop is simply absorbed by its neighbours.

The user can override any transition with a time (``Cuts``) and any file can be pinned to a
mode (``Point.hint``); both are hard constraints on the same search.

All thresholds are first guesses to be tuned on real tracks (see ``SegmenterConfig``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .geo import haversine_m
from .models import Point, Track, TrackError

STATE_MODES = ("bike", "walk", "flight", "walk", "bike")
STATE_ROLES = ("bike_out", "ascent", "flight", "walk_after_landing", "bike_return")
INF = 1e12


class SegmentationError(ValueError):
    """The constraints given (hints, cuts) cannot all be satisfied."""


@dataclass
class SegmenterConfig:
    # smoothing windows (seconds, each side of a fix)
    speed_window_s: float = 15.0
    vz_window_s: float = 30.0
    # fixes further apart than this are treated as a recording gap (no evidence either way)
    gap_s: float = 600.0
    # a fix never weighs more than this many seconds
    max_weight_s: float = 60.0
    # cost (in seconds-equivalent of full disagreement) of switching state once
    switch_penalty: float = 90.0
    # walking
    walk_free_kmh: float = 6.0
    walk_slope: float = 0.10           # cost/s per km/h above walk_free_kmh
    walk_max_climb_ms: float = 0.9     # nobody walks up faster than ~3 200 m/h
    # biking
    bike_slow_kmh: float = 4.0
    bike_max_kmh: float = 70.0
    bike_max_climb_ms: float = 1.2     # sustained climbing faster than this is not cycling
    bike_max_sink_ms: float = 2.0      # sinking faster than this is not cycling
    # No road in the Alps goes much above 2800 m; above this a bike is (almost) impossible.
    bike_max_alt_m: float = 2900.0
    # A glide-like descent (fast, steady sink) is slightly less bike-like than a plain ride.
    glide_min_kmh: float = 25.0
    glide_max_kmh: float = 60.0
    glide_sink_min_ms: float = 0.7
    # flying
    flight_min_kmh: float = 15.0
    flight_max_kmh: float = 85.0
    circling_sinuosity: float = 1.6
    # sanity thresholds used only for warnings
    min_flight_s: float = 120.0
    min_flight_descent_m: float = 100.0


@dataclass
class Cuts:
    """User-chosen transition instants. Any may be left out (None) to let the program decide.

    walk_start        first fix of the ascent on foot (end of the bike ride out)
    takeoff           first fix of the flight
    landing           first fix after the flight
    bike_return_start first fix of the ride back
    """

    walk_start: Optional[datetime] = None
    takeoff: Optional[datetime] = None
    landing: Optional[datetime] = None
    bike_return_start: Optional[datetime] = None

    def constraints(self) -> list[tuple[datetime, int]]:
        pairs = [
            (self.walk_start, 1),
            (self.takeoff, 2),
            (self.landing, 3),
            (self.bike_return_start, 4),
        ]
        out = []
        for when, state in pairs:
            if when is None:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            out.append((when, state))
        return out


@dataclass
class Segment:
    role: str                 # one of STATE_ROLES
    mode: str                 # bike | walk | flight
    i_start: int              # index of first fix in the (merged) track
    i_end: int                # index of last fix (inclusive)
    t_start: datetime
    t_end: datetime
    duration_s: float
    distance_m: float
    ascent_m: Optional[float]
    descent_m: Optional[float]
    mean_speed_kmh: float
    confidence: str           # high | medium | low
    boundary_gap_s: float     # recording gap just before this segment (uncertainty of its start)
    user_fixed_start: bool = False


@dataclass
class SegmentationResult:
    segments: list[Segment]
    labels: list[int]                      # state index per fix
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# features


@dataclass
class _Feat:
    v: Optional[float]        # ground speed, km/h (chord over the window)
    vz: Optional[float]       # vertical speed, m/s
    sinu: float               # path length / chord length over the window (>=1)
    weight: float             # seconds of evidence this fix stands for
    alt: Optional[float] = None   # altitude of the fix itself, metres


def _window(ts: list[float], i: int, half: float, gap: float = 600.0) -> tuple[int, int]:
    n = len(ts)
    j = i
    while j > 0 and ts[i] - ts[j - 1] <= half:
        j -= 1
    k = i
    while k < n - 1 and ts[k + 1] - ts[i] <= half:
        k += 1
    # always use at least the immediate neighbours (sparse recordings), but never reach
    # across a recording gap: the first fix after a gap should be judged on its own side
    if j == i and i > 0 and ts[i] - ts[i - 1] <= gap:
        j = i - 1
    if k == i and i < n - 1 and ts[i + 1] - ts[i] <= gap:
        k = i + 1
    return j, k


def compute_features(pts: list[Point], cfg: SegmenterConfig) -> list[_Feat]:
    n = len(pts)
    ts = [p.t.timestamp() for p in pts]
    cum = [0.0] * n
    for i in range(1, n):
        cum[i] = cum[i - 1] + haversine_m(pts[i - 1].lat, pts[i - 1].lon, pts[i].lat, pts[i].lon)

    feats: list[_Feat] = []
    for i in range(n):
        # weight: half the gap to each neighbour
        left = ts[i] - ts[i - 1] if i > 0 else None
        right = ts[i + 1] - ts[i] if i < n - 1 else None
        parts = [x for x in (left, right) if x is not None]
        weight = min(cfg.max_weight_s, sum(parts) / 2.0 if parts else 1.0)
        # a fix next to a recording gap carries no weight on the gap side
        weight = max(weight, 0.0)

        j, k = _window(ts, i, cfg.speed_window_s, cfg.gap_s)
        dt = ts[k] - ts[j]
        v: Optional[float] = None
        sinu = 1.0
        if dt > 0 and dt <= cfg.gap_s:
            chord = haversine_m(pts[j].lat, pts[j].lon, pts[k].lat, pts[k].lon)
            path = cum[k] - cum[j]
            v = chord / dt * 3.6
            if chord > 0.5 * dt and path > 0:  # moving at >0.5 m/s: sinuosity is meaningful
                sinu = min(10.0, path / chord)

        vz: Optional[float] = None
        j2, k2 = _window(ts, i, cfg.vz_window_s, cfg.gap_s)
        dt2 = ts[k2] - ts[j2]
        a0, a1 = pts[j2].alt, pts[k2].alt
        if dt2 > 0 and dt2 <= cfg.gap_s and a0 is not None and a1 is not None:
            vz = (a1 - a0) / dt2

        feats.append(_Feat(v=v, vz=vz, sinu=sinu, weight=weight, alt=pts[i].alt))
    return feats


# ---------------------------------------------------------------------------------------------
# emission costs (per second of evidence) for each mode


def _cost_walk(f: _Feat, c: SegmenterConfig) -> float:
    cost = 0.0
    if f.v is not None and f.v > c.walk_free_kmh:
        cost += min(1.5, (f.v - c.walk_free_kmh) * c.walk_slope)
    if f.vz is not None:
        if f.vz < -c.bike_max_sink_ms:
            cost += 0.4  # a walker does not sink at 2 m/s
        elif f.vz > c.walk_max_climb_ms:
            cost += min(1.0, 0.3 + (f.vz - c.walk_max_climb_ms) * 0.4)
    return cost


def _cost_bike(f: _Feat, c: SegmenterConfig) -> float:
    cost = 0.0
    if f.v is not None:
        if f.v < 1.0:
            cost += 0.3
        elif f.v < c.bike_slow_kmh:
            cost += 0.25
        elif f.v < 7.0:
            cost += 0.12
        elif f.v > c.bike_max_kmh:
            cost += min(1.5, (f.v - c.bike_max_kmh) * 0.05)
        if f.v > 10 and f.sinu > c.circling_sinuosity:
            cost += 0.4  # circling is not what a bike does
    if f.vz is not None:
        if f.vz > c.bike_max_climb_ms:
            cost += min(1.5, (f.vz - c.bike_max_climb_ms) * 0.4 + 0.3)
        elif f.vz < -c.bike_max_sink_ms:
            cost += min(1.5, (-f.vz - c.bike_max_sink_ms) * 0.4 + 0.3)
        elif (
            f.v is not None
            and c.glide_min_kmh <= f.v <= c.glide_max_kmh
            and -c.bike_max_sink_ms <= f.vz <= -c.glide_sink_min_ms
        ):
            cost += 0.1
    if f.alt is not None and f.alt > c.bike_max_alt_m:
        cost += 1.0
    return cost


def _cost_flight(f: _Feat, c: SegmenterConfig) -> float:
    cost = 0.0
    if f.v is not None:
        if f.v < 1.0:
            cost += 1.0  # hovering on the ground is not flying
        elif f.v < c.flight_min_kmh:
            cost += min(1.0, (c.flight_min_kmh - f.v) * 0.08)
        elif f.v > c.flight_max_kmh:
            cost += min(1.5, (f.v - c.flight_max_kmh) * 0.05)
    return cost


_COST = {"walk": _cost_walk, "bike": _cost_bike, "flight": _cost_flight}


def emission_costs(f: _Feat, cfg: SegmenterConfig) -> dict[str, float]:
    return {m: fn(f, cfg) for m, fn in _COST.items()}


# ---------------------------------------------------------------------------------------------
# segmentation


def segment_track(
    track: Track,
    cuts: Optional[Cuts] = None,
    cfg: Optional[SegmenterConfig] = None,
) -> SegmentationResult:
    cfg = cfg or SegmenterConfig()
    cuts = cuts or Cuts()
    pts = track.points
    n = len(pts)
    if n < 2:
        raise TrackError("a track needs at least 2 points to be segmented")

    feats = compute_features(pts, cfg)
    ts = [p.t for p in pts]
    constraints = cuts.constraints()

    # allowed states per fix: hints and cuts are hard constraints
    allowed: list[list[bool]] = []
    for i, p in enumerate(pts):
        ok = [True] * 5
        if p.hint is not None:
            for s in range(5):
                if STATE_MODES[s] != p.hint:
                    ok[s] = False
        for when, state in constraints:
            for s in range(5):
                if ts[i] < when and s >= state:
                    ok[s] = False
                elif ts[i] >= when and s < state:
                    ok[s] = False
        allowed.append(ok)

    # per-fix cost for each state
    ems = [emission_costs(feats[i], cfg) for i in range(n)]
    cost = [[INF] * 5 for _ in range(n)]
    for i in range(n):
        w = feats[i].weight
        for s in range(5):
            if allowed[i][s]:
                cost[i][s] = ems[i][STATE_MODES[s]] * w

    # Viterbi: state may only stay or move forward
    dp = [[INF] * 5 for _ in range(n)]
    back = [[-1] * 5 for _ in range(n)]
    for s in range(5):
        dp[0][s] = cost[0][s]
    for i in range(1, n):
        for s in range(5):
            if cost[i][s] >= INF:
                continue
            best, arg = INF, -1
            for sp in range(s + 1):
                prev = dp[i - 1][sp]
                if prev >= INF:
                    continue
                val = prev + (cfg.switch_penalty if sp != s else 0.0)
                if val < best:
                    best, arg = val, sp
            if arg >= 0:
                dp[i][s] = best + cost[i][s]
                back[i][s] = arg
    end_state = min(range(5), key=lambda s: dp[n - 1][s])
    if dp[n - 1][end_state] >= INF:
        raise SegmentationError(
            "no labelling satisfies the file hints and the chosen transition times together; "
            "check that the cuts are in chronological order and consistent with the file labels"
        )
    labels = [0] * n
    s = end_state
    for i in range(n - 1, -1, -1):
        labels[i] = s
        s = back[i][s] if i > 0 else s

    segments = _build_segments(pts, feats, ems, labels, constraints, cfg)
    warnings = _sanity_warnings(segments, cfg)
    return SegmentationResult(segments=segments, labels=labels, warnings=warnings)


def _ascent_descent(
    pts: list[Point], i0: int, i1: int, smooth_s: float = 30.0, hysteresis: float = 10.0
) -> tuple[Optional[float], Optional[float]]:
    """Total climb and descent, from a time-smoothed altitude and a hysteresis threshold.

    Raw GPS altitude jitters by several metres; summing every wiggle would inflate both totals.
    """
    seg = pts[i0 : i1 + 1]
    if sum(1 for p in seg if p.alt is not None) < 2:
        return None, None
    ts = [p.t.timestamp() for p in seg]
    sm: list[float] = []
    lo = 0
    for k in range(len(seg)):
        while ts[k] - ts[lo] > smooth_s:
            lo += 1
        hi = k
        while hi + 1 < len(seg) and ts[hi + 1] - ts[k] <= smooth_s:
            hi += 1
        vals = [seg[m].alt for m in range(lo, hi + 1) if seg[m].alt is not None]
        if vals:
            sm.append(sum(vals) / len(vals))
    if len(sm) < 2:
        return None, None
    up = down = 0.0
    ref = sm[0]
    for a in sm[1:]:
        d = a - ref
        if d >= hysteresis:
            up += d
            ref = a
        elif d <= -hysteresis:
            down += -d
            ref = a
    return up, down


def _boundary_level(
    pts: list[Point],
    feats: list[_Feat],
    ems: list[dict[str, float]],
    i_new: int,
    prev_mode: str,
    new_mode: str,
    window_s: float = 60.0,
) -> str:
    """How sharply the evidence flips at a boundary (first fix of the new part = ``i_new``)."""
    t0 = pts[i_new].t.timestamp()
    num_b = den_b = num_a = den_a = 0.0
    for k in range(len(pts)):
        dt = pts[k].t.timestamp() - t0
        if -window_s <= dt < 0:
            w = feats[k].weight
            num_b += w * (ems[k][new_mode] - ems[k][prev_mode])  # the new mode should look worse before
            den_b += w
        elif 0 <= dt <= window_s:
            w = feats[k].weight
            num_a += w * (ems[k][prev_mode] - ems[k][new_mode])  # the old mode should look worse after
            den_a += w
        elif dt > window_s:
            break
    if den_b == 0 or den_a == 0:
        return "medium"  # a recording gap: nothing to compare, the gap itself is flagged separately
    ev = (num_b / den_b + num_a / den_a) / 2.0
    if ev >= 0.4:
        return "high"
    if ev >= 0.1:
        return "medium"
    return "low"


def _build_segments(
    pts: list[Point],
    feats: list[_Feat],
    ems: list[dict[str, float]],
    labels: list[int],
    constraints: list[tuple[datetime, int]],
    cfg: SegmenterConfig,
) -> list[Segment]:
    segs: list[Segment] = []
    n = len(pts)
    i = 0
    fixed_instants = {state: when for when, state in constraints}
    while i < n:
        j = i
        while j + 1 < n and labels[j + 1] == labels[i]:
            j += 1
        s = labels[i]
        dist = sum(
            haversine_m(pts[k].lat, pts[k].lon, pts[k + 1].lat, pts[k + 1].lon) for k in range(i, j)
        )
        dur = (pts[j].t - pts[i].t).total_seconds()
        asc, desc = _ascent_descent(pts, i, j)
        # confidence of the boundary that starts this part (a user-fixed one is certain)
        if i == 0:
            conf = "n/a"
        elif s in fixed_instants:
            conf = "fixed"
        else:
            conf = _boundary_level(pts, feats, ems, i, STATE_MODES[labels[i - 1]], STATE_MODES[s])
        gap = (pts[i].t - pts[i - 1].t).total_seconds() if i > 0 else 0.0
        fixed = s in fixed_instants and i > 0
        segs.append(
            Segment(
                role=STATE_ROLES[s],
                mode=STATE_MODES[s],
                i_start=i,
                i_end=j,
                t_start=pts[i].t,
                t_end=pts[j].t,
                duration_s=dur,
                distance_m=dist,
                ascent_m=asc,
                descent_m=desc,
                mean_speed_kmh=(dist / dur * 3.6) if dur > 0 else 0.0,
                confidence=conf,  # of this part's start boundary
                boundary_gap_s=gap,
                user_fixed_start=fixed,
            )
        )
        i = j + 1
    return segs


def _sanity_warnings(segs: list[Segment], cfg: SegmenterConfig) -> list[str]:
    out: list[str] = []
    flights = [s for s in segs if s.mode == "flight"]
    if not flights:
        out.append("no flight part found: such a track would not be registered")
    for s in flights:
        if s.duration_s < cfg.min_flight_s:
            out.append(f"flight lasts only {s.duration_s:.0f} s; check the detection")
        if s.descent_m is not None and s.ascent_m is not None:
            net = s.descent_m - s.ascent_m
            if net < cfg.min_flight_descent_m:
                out.append(f"flight loses only {net:.0f} m of altitude; check the detection")
    if not any(s.role == "ascent" for s in segs):
        out.append("no ascent on foot found")
    for s in segs:
        if s.confidence == "low":
            out.append(
                f"the start of {s.role} ({s.t_start.isoformat()}) is ambiguous; "
                "check it on the plot and fix the transition by hand if needed"
            )
        if s.boundary_gap_s >= 120:
            out.append(
                f"{s.role}: the recording has a {s.boundary_gap_s / 60:.1f} min gap just before it, "
                "so its exact start is uncertain"
            )
    return out
