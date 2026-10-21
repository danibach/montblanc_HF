"""Split a track into walking, flying and riding parts.

Every fix gets one of three labels, and the cheapest labelling over the whole track is found with a
Viterbi pass (the label may change as often as the evidence demands, each change has a cost):

    walk      on foot (hiking, climbing, walking after landing, standing still)
    flight    under a paraglider
    vehicle   anything else that moves: car, bike, tram, cable car, skis...

The per-fix cost comes from smoothed ground speed, vertical speed and how much the path circles.
Only walking climbs and flights count towards a score; the vehicle parts are simply left out.

All thresholds are first guesses and were only tried on synthetic tracks: they still have to be
tuned on real ones (see ``SegmenterConfig``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .geo import haversine_m
from .models import Point, Track, TrackError

WALK, FLIGHT, VEHICLE = 0, 1, 2
MODES = ("walk", "flight", "vehicle")
INF = 1e12


@dataclass
class SegmenterConfig:
    # smoothing windows (seconds, each side of a fix)
    speed_window_s: float = 15.0
    vz_window_s: float = 30.0
    # fixes further apart than this are a recording gap (no evidence either way)
    gap_s: float = 600.0
    # a fix never weighs more than this many seconds
    max_weight_s: float = 60.0
    # cost (in seconds-equivalent of full disagreement) of changing label once
    switch_penalty: float = 90.0
    # a flight never leads straight to a vehicle (you land, then walk), nor the reverse
    flight_vehicle_penalty: float = 400.0
    # a track rarely starts inside a vehicle
    start_vehicle_penalty: float = 200.0
    # walking
    walk_free_kmh: float = 6.0
    walk_slope: float = 0.10           # cost/s per km/h above walk_free_kmh
    walk_max_climb_ms: float = 0.9     # nobody walks up faster than ~3 200 m/h
    walk_max_sink_ms: float = 2.0
    # flying
    flight_min_kmh: float = 15.0
    flight_max_kmh: float = 85.0
    # Glide over the ground (wind included): a paraglider 7-9:1, a run&fly wing 6:1 or more, a speed-riding
    # wing 4-5:1. A fix that sinks faster than 2 m/s and glides worse than this is a slope under the feet.
    # On seven real tracks (flights from 5 to 179 minutes) any value from 2 to 6 gives the same result.
    flight_min_glide: float = 4.0
    circling_sinuosity: float = 1.6
    # when speed and sink cannot tell a glide from a ride, prefer the glide (this is a Hike & Fly site)
    vehicle_bias: float = 0.3
    # a flight shorter than this is noise, not a flight
    min_flight_s: float = 60.0
    # A take-off follows a climb on foot: after a walk of at least ``launch_walk_s``, a "flight" that
    # starts more than ``launch_tolerance_m`` below the highest point of that walk is a drive home.
    launch_walk_s: float = 300.0
    launch_tolerance_m: float = 300.0
    # After landing, a level stretch (altitude within ``landing_band_m``) of at least ``landing_tail_s`` at the
    # end of a flight is the ground, not the air.
    landing_band_m: float = 20.0
    landing_tail_s: float = 120.0
    # A wing flies at 25-45 km/h and does not stop: a "flight" whose median ground speed is lower is a
    # ski or a walk down (on seven real winter tracks: flights 27-38 km/h, a ski descent 14 km/h).
    flight_min_median_kmh: float = 18.0
    # The launch rule above must not throw out a glide that is clearly a flight: steady, never stopping
    # (10th percentile of the speed), sinking at least ``sure_sink_ms`` and gliding no flatter than
    # ``sure_glide`` over the ground. A ski descent stops, a road is flatter than 10:1.
    sure_p10_kmh: float = 12.0
    sure_sink_ms: float = 1.0
    sure_glide: float = 10.0


@dataclass
class Segment:
    mode: str                 # walk | flight | vehicle
    i_start: int              # index of the first fix in the track
    i_end: int                # index of the last fix (inclusive)
    t_start: datetime
    t_end: datetime
    duration_s: float
    distance_m: float


@dataclass
class SegmentationResult:
    segments: list[Segment]
    labels: list[int]
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Feat:
    v: Optional[float]        # ground speed, km/h (chord over the window)
    vz: Optional[float]       # vertical speed, m/s
    sinu: float               # path length / chord length over the window (>=1)
    weight: float             # seconds of evidence this fix stands for


def _window(ts: list[float], i: int, half: float, gap: float = 600.0) -> tuple[int, int]:
    n = len(ts)
    j = i
    while j > 0 and ts[i] - ts[j - 1] <= half:
        j -= 1
    k = i
    while k < n - 1 and ts[k + 1] - ts[i] <= half:
        k += 1
    # always use at least the immediate neighbours (sparse recordings), but never reach
    # across a recording gap
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
        left = ts[i] - ts[i - 1] if i > 0 else None
        right = ts[i + 1] - ts[i] if i < n - 1 else None
        parts = [x for x in (left, right) if x is not None]
        weight = max(0.0, min(cfg.max_weight_s, sum(parts) / 2.0 if parts else 1.0))

        j, k = _window(ts, i, cfg.speed_window_s, cfg.gap_s)
        dt = ts[k] - ts[j]
        v: Optional[float] = None
        sinu = 1.0
        if 0 < dt <= cfg.gap_s:
            chord = haversine_m(pts[j].lat, pts[j].lon, pts[k].lat, pts[k].lon)
            path = cum[k] - cum[j]
            v = chord / dt * 3.6
            if chord > 0.5 * dt and path > 0:  # moving at >0.5 m/s: sinuosity is meaningful
                sinu = min(10.0, path / chord)

        vz: Optional[float] = None
        j2, k2 = _window(ts, i, cfg.vz_window_s, cfg.gap_s)
        dt2 = ts[k2] - ts[j2]
        a0, a1 = pts[j2].alt, pts[k2].alt
        if 0 < dt2 <= cfg.gap_s and a0 is not None and a1 is not None:
            vz = (a1 - a0) / dt2
        feats.append(_Feat(v=v, vz=vz, sinu=sinu, weight=weight))
    return feats


# ---------------------------------------------------------------------------------------------
# emission costs (per second of evidence)


def _cost_walk(f: _Feat, c: SegmenterConfig) -> float:
    cost = 0.0
    if f.v is not None and f.v > c.walk_free_kmh:
        cost += min(1.5, (f.v - c.walk_free_kmh) * c.walk_slope)
    if f.vz is not None:
        if f.vz < -c.walk_max_sink_ms:
            cost += 0.4  # a walker does not sink at 2 m/s
        elif f.vz > c.walk_max_climb_ms:
            cost += min(1.0, 0.3 + (f.vz - c.walk_max_climb_ms) * 0.4)
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
        if f.vz is not None:
            sink = -f.vz
            # sinking faster than the steepest glide allowed: a steep slope under the feet, not a wing.
            # The glide is measured along the path flown: a spiral loses height over little ground.
            path_v = f.v * min(f.sinu, 3.0)
            if sink > 2.0 and sink > (path_v / 3.6) / c.flight_min_glide:
                cost += 0.8
            # climbing in a straight line: a lift, not a thermal
            if f.vz > 0.5 and f.sinu < 1.2:
                cost += 0.6
            # level and straight at cruising speed: not gliding
            if f.vz > -0.25 and f.sinu < c.circling_sinuosity:
                cost += 0.4
    return cost


def _cost_vehicle(f: _Feat, c: SegmenterConfig) -> float:
    cost = c.vehicle_bias
    if f.v is not None:
        if f.v < 1.0:
            cost += 0.3
        elif f.v < 4.0:
            cost += 0.25
        elif f.v < 7.0:
            cost += 0.12
        if f.v > 10 and f.sinu > c.circling_sinuosity:
            cost += 0.4  # circling is not what a vehicle does
    return cost


_COST = (_cost_walk, _cost_flight, _cost_vehicle)


# ---------------------------------------------------------------------------------------------


def segment_track(track: Track, cfg: Optional[SegmenterConfig] = None) -> SegmentationResult:
    cfg = cfg or SegmenterConfig()
    pts = track.points
    n = len(pts)
    if n < 2:
        raise TrackError("a track needs at least 2 points to be segmented")

    feats = compute_features(pts, cfg)
    cost = [[fn(feats[i], cfg) * feats[i].weight for fn in _COST] for i in range(n)]

    def switch(a: int, b: int) -> float:
        if a == b:
            return 0.0
        if {a, b} == {FLIGHT, VEHICLE}:
            return cfg.flight_vehicle_penalty
        return cfg.switch_penalty

    dp = [[INF] * 3 for _ in range(n)]
    back = [[0] * 3 for _ in range(n)]
    for s in range(3):
        dp[0][s] = cost[0][s] + (cfg.start_vehicle_penalty if s == VEHICLE else 0.0)
    for i in range(1, n):
        for s in range(3):
            best, arg = INF, 0
            for sp in range(3):
                val = dp[i - 1][sp] + switch(sp, s)
                if val < best:
                    best, arg = val, sp
            dp[i][s] = best + cost[i][s]
            back[i][s] = arg
    state = min(range(3), key=lambda s: dp[n - 1][s])
    labels = [0] * n
    for i in range(n - 1, -1, -1):
        labels[i] = state
        state = back[i][state]

    _drop_short_flights(pts, labels, cfg)
    _trim_landing(pts, labels, cfg)
    _demote_slow_flights(pts, labels, cfg)
    _demote_unlaunched_flights(pts, labels, cfg)
    segments = _build_segments(pts, labels)
    return SegmentationResult(segments=segments, labels=labels)


def _drop_short_flights(pts: list[Point], labels: list[int], cfg: SegmenterConfig) -> None:
    """A flight shorter than ``min_flight_s`` is noise: call it walking."""
    n = len(pts)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and labels[j + 1] == labels[i]:
            j += 1
        if labels[i] == FLIGHT and (pts[j].t - pts[i].t).total_seconds() < cfg.min_flight_s:
            for k in range(i, j + 1):
                labels[k] = WALK
        i = j + 1


def _trim_landing(pts: list[Point], labels: list[int], cfg: SegmenterConfig) -> None:
    """Cut the level stretch at the end of a flight: that is the pilot on the ground (walking or riding)."""
    for label, i, j in _runs(labels):
        tail = sorted(p.alt for p in pts[max(i, j - 6) : j + 1] if p.alt is not None)
        if label != FLIGHT or not tail:
            continue
        end_alt = tail[len(tail) // 2]  # median of the last fixes: one noisy altitude must not decide
        k = j
        while k > i and pts[k - 1].alt is not None and abs(pts[k - 1].alt - end_alt) <= cfg.landing_band_m:
            k -= 1
        if k == i or (pts[j].t - pts[k].t).total_seconds() < cfg.landing_tail_s:
            continue
        dist = sum(haversine_m(pts[m].lat, pts[m].lon, pts[m + 1].lat, pts[m + 1].lon) for m in range(k, j))
        speed = dist / (pts[j].t - pts[k].t).total_seconds() * 3.6
        for m in range(k + 1, j + 1):
            labels[m] = VEHICLE if speed > 8.0 else WALK


def _runs(labels: list[int]) -> list[tuple[int, int, int]]:
    out = []
    i, n = 0, len(labels)
    while i < n:
        j = i
        while j + 1 < n and labels[j + 1] == labels[i]:
            j += 1
        out.append((labels[i], i, j))
        i = j + 1
    return out


def _speeds_kmh(pts: list[Point], i: int, j: int, step_s: float = 3.0) -> list[float]:
    """Ground speeds along fixes i..j, measured over chords of about ``step_s`` seconds."""
    out: list[float] = []
    a = i
    for k in range(i + 1, j + 1):
        dt = (pts[k].t - pts[a].t).total_seconds()
        if dt >= step_s:
            d = haversine_m(pts[a].lat, pts[a].lon, pts[k].lat, pts[k].lon)
            out.append(d / dt * 3.6)
            a = k
    return out


def _percentile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def _demote_slow_flights(pts: list[Point], labels: list[int], cfg: SegmenterConfig) -> None:
    """A "flight" whose median ground speed is below ``flight_min_median_kmh`` is a ski or a walk down."""
    for label, i, j in _runs(labels):
        if label != FLIGHT:
            continue
        v = _speeds_kmh(pts, i, j)
        if v and _percentile(v, 0.5) < cfg.flight_min_median_kmh:
            for k in range(i, j + 1):
                labels[k] = VEHICLE


def _is_sure_flight(pts: list[Point], i: int, j: int, cfg: SegmenterConfig) -> bool:
    """Steady glide, never stopping, steep enough for a wing and not flatter than a road."""
    v = _speeds_kmh(pts, i, j)
    dur = (pts[j].t - pts[i].t).total_seconds()
    if len(v) < 10 or dur <= 0 or pts[i].alt is None or pts[j].alt is None:
        return False
    sink = (pts[i].alt - pts[j].alt) / dur
    if sink < cfg.sure_sink_ms or _percentile(v, 0.10) < cfg.sure_p10_kmh:
        return False
    return (_percentile(v, 0.5) / 3.6) / sink <= cfg.sure_glide


def _demote_unlaunched_flights(pts: list[Point], labels: list[int], cfg: SegmenterConfig) -> None:
    """A take-off follows a climb on foot. A "flight" that starts far below the top of the walk
    before it is a ride down (car, bike, skis...): call it a vehicle, unless it is clearly a glide.
    (A ski descent before the take-off is labelled walking and lowers the take-off below the summit.)"""
    last_top: Optional[float] = None
    for label, i, j in _runs(labels):
        if label == WALK and (pts[j].t - pts[i].t).total_seconds() >= cfg.launch_walk_s:
            alts = [p.alt for p in pts[i : j + 1] if p.alt is not None]
            last_top = max(alts) if alts else last_top
        elif label == FLIGHT and last_top is not None and pts[i].alt is not None:
            if pts[i].alt < last_top - cfg.launch_tolerance_m and not _is_sure_flight(pts, i, j, cfg):
                for k in range(i, j + 1):
                    labels[k] = VEHICLE


def _build_segments(pts: list[Point], labels: list[int]) -> list[Segment]:
    segs: list[Segment] = []
    n = len(pts)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and labels[j + 1] == labels[i]:
            j += 1
        dist = sum(
            haversine_m(pts[k].lat, pts[k].lon, pts[k + 1].lat, pts[k + 1].lon) for k in range(i, j)
        )
        segs.append(
            Segment(
                mode=MODES[labels[i]],
                i_start=i,
                i_end=j,
                t_start=pts[i].t,
                t_end=pts[j].t,
                duration_s=(pts[j].t - pts[i].t).total_seconds(),
                distance_m=dist,
            )
        )
        i = j + 1
    return segs
