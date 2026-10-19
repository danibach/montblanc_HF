"""Was the approach made on foot? Detect rides on the Mont-Blanc tramway and on lifts.

Tramway du Mont-Blanc (rule agreed with the project owner):
    a stretch of the track is a tram ride when ALL THREE hold
      1. it follows the rail line (within ``tram_radius_m`` for at least ``tram_min_len_m``),
      2. the tram is running at that time (timetable; unknown counts as "possibly running"),
      3. it climbs faster than ``tram_min_rate_mh`` (default 1200 m/h) over a window of up to
         ``window_s`` seconds (the best hikers measured so far reach 800 m/h over 15 min).
    Walking along the rails (slow) is allowed. Fast on the rails while the tram is not running is
    not called a ride, only reported for review.

Other lifts (cable cars, gondolas, chairlifts, ...):
    a stretch that follows a lift line for ``lift_min_len_m`` at a sustained speed above
    ``lift_min_speed_kmh`` (walkers stay under 6 km/h). No timetable is needed. Slow lifts
    (fixed-grip chairlifts and drag lifts below ~8 km/h) cannot be told from walking and are
    therefore NOT detected.

A stretch whose fixes were mostly labelled "bike" by the segmenter is ambiguous (a tram ride
looks like a bike ride to the segmenter, and a cyclist on a road beside the rails looks like a
tram). It is called a ride only if its median distance to the line is within
``bike_lateral_m`` (a vehicle on the line sits on it; a road is usually further away);
otherwise it is reported for review. That distance is a first guess, to be tuned on real tracks.

The check only looks at fixes before the summit is entered (or before take-off).

The line geometry comes from OpenStreetMap (data/transport-osm.json, built with
``mbhf import-osm``) (c) OpenStreetMap contributors, ODbL. Without it the check is NOT performed
and the report says so.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from importlib import resources
from typing import Optional
from zoneinfo import ZoneInfo

from .geo import EARTH_RADIUS_M, haversine_m
from .models import Track

_M_PER_DEG = EARTH_RADIUS_M * math.pi / 180.0
BIKE_STATES = (0, 4)          # segmentation states bike_out / bike_return
LIFT_AERIALWAYS = ("cable_car", "gondola", "mixed_lift", "chair_lift", "funicular")


# ---------------------------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------------------------
@dataclass
class TransportConfig:
    tram_radius_m: float = 30.0
    lift_radius_m: float = 40.0
    tram_min_len_m: float = 500.0
    lift_min_len_m: float = 400.0
    bridge_s: float = 30.0            # short off-line interruptions inside one stretch
    gap_s: float = 120.0              # recording gap: handled separately
    gap_jump_min_m: float = 300.0
    tram_min_rate_mh: float = 1200.0  # climb rate that a walker does not sustain
    window_s: float = 600.0
    min_window_s: float = 120.0
    short_stretch_min_kmh: float = 9.0  # stretches shorter than min_window_s: judged by speed
    lift_min_speed_kmh: float = 8.0
    lift_window_s: float = 120.0
    lift_fast_fraction: float = 0.6
    bike_lateral_m: float = 12.0      # bike-labelled stretch: median distance to the line to count as on it


# ---------------------------------------------------------------------------------------------
# line geometry
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Line:
    id: str
    name: str
    kind: str                 # "tram" | "lift"
    subtype: str
    coords: tuple             # ((lat, lon), ...)


class LineSet:
    """Polylines grouped by (kind, name); distance from a fix to a group."""

    def __init__(self, lines: list[Line], source: str = "", note: str = ""):
        self.lines = lines
        self.source = source
        self.note = note
        pts = [c for ln in lines for c in ln.coords]
        self._lat0 = sum(p[0] for p in pts) / len(pts) if pts else 0.0
        self._lon0 = sum(p[1] for p in pts) / len(pts) if pts else 0.0
        self._cos = math.cos(math.radians(self._lat0))
        self.groups: dict[tuple[str, str], list[tuple[float, float, float, float]]] = {}
        self._bbox: dict[tuple[str, str], tuple[float, float, float, float]] = {}
        for ln in lines:
            key = (ln.kind, ln.name or ln.id)
            xy = [self._xy(lat, lon) for lat, lon in ln.coords]
            segs = self.groups.setdefault(key, [])
            for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
                segs.append((x1, y1, x2, y2))
        for key, segs in self.groups.items():
            xs = [s[0] for s in segs] + [s[2] for s in segs]
            ys = [s[1] for s in segs] + [s[3] for s in segs]
            self._bbox[key] = (min(xs), min(ys), max(xs), max(ys))

    def _xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self._lon0) * _M_PER_DEG * self._cos, (lat - self._lat0) * _M_PER_DEG

    def __bool__(self) -> bool:
        return bool(self.groups)

    def distance(self, key: tuple[str, str], lat: float, lon: float, cutoff: float = 1e9) -> float:
        """Distance in metres from the fix to the group's polylines (inf when beyond cutoff)."""
        x, y = self._xy(lat, lon)
        x0, y0, x1, y1 = self._bbox[key]
        if x < x0 - cutoff or x > x1 + cutoff or y < y0 - cutoff or y > y1 + cutoff:
            return math.inf
        best = math.inf
        for ax, ay, bx, by in self.groups[key]:
            dx, dy = bx - ax, by - ay
            qq = dx * dx + dy * dy
            f = 0.0 if qq == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / qq))
            d = math.hypot(x - (ax + f * dx), y - (ay + f * dy))
            if d < best:
                best = d
        return best


def load_lines(path: Optional[str] = None) -> LineSet:
    """Load the line geometry (default: the packaged OSM extract, which may still be empty)."""
    if path is None:
        text = resources.files("mbhf").joinpath("data/transport-osm.json").read_text(encoding="utf-8")
    else:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    data = json.loads(text)
    lines = [
        Line(
            id=str(d["id"]),
            name=str(d.get("name", "")),
            kind=str(d["kind"]),
            subtype=str(d.get("subtype", "")),
            coords=tuple((float(a), float(b)) for a, b in d["coords"]),
        )
        for d in data.get("lines", [])
        if len(d.get("coords", [])) >= 2
    ]
    return LineSet(lines, source=str(data.get("source", "")), note=str(data.get("note", "")))


# ---------------------------------------------------------------------------------------------
# OpenStreetMap import
# ---------------------------------------------------------------------------------------------
def _norm(text: str) -> str:
    return text.lower().replace("é", "e").replace("è", "e").replace("-", " ")


def import_osm(path: str, tram_match: str = "tramway du mont") -> dict:
    """Convert an Overpass JSON ("out geom") or GeoJSON export into the packaged line format.

    A way tagged ``railway=*`` whose name, ref, operator or route name contains ``tram_match`` is a
    tram line; a way tagged ``aerialway=<cable_car|gondola|mixed_lift|chair_lift|funicular>``
    (or ``railway=funicular``) is a lift. Everything else is ignored.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    ways: list[tuple[str, dict, list[tuple[float, float]]]] = []
    if isinstance(raw, dict) and "elements" in raw:                     # Overpass JSON
        for el in raw["elements"]:
            if el.get("type") == "way" and el.get("geometry"):
                ways.append(
                    (f"way/{el['id']}", el.get("tags", {}), [(g["lat"], g["lon"]) for g in el["geometry"]])
                )
    elif isinstance(raw, dict) and raw.get("type") == "FeatureCollection":  # GeoJSON (overpass-turbo)
        for ft in raw.get("features", []):
            geom = ft.get("geometry") or {}
            props = dict(ft.get("properties") or {})
            props.update(props.get("tags") or {})
            fid = str(props.get("@id") or ft.get("id") or f"feature/{len(ways)}")
            if geom.get("type") == "LineString":
                parts = [geom["coordinates"]]
            elif geom.get("type") == "MultiLineString":
                parts = geom["coordinates"]
            else:
                continue
            for k, part in enumerate(parts):
                ways.append((fid if len(parts) == 1 else f"{fid}#{k}", props, [(c[1], c[0]) for c in part]))
    else:
        raise ValueError("not an Overpass JSON ('elements') nor a GeoJSON FeatureCollection")

    match = _norm(tram_match)
    lines: list[dict] = []
    skipped = 0
    for wid, tags, coords in ways:
        if len(coords) < 2:
            continue
        rw, aw = tags.get("railway"), tags.get("aerialway")
        label = _norm(" ".join(str(tags.get(k, "")) for k in ("name", "ref", "operator", "route_name", "line")))
        kind = subtype = None
        if rw and match in label:
            kind, subtype = "tram", rw
        elif aw in LIFT_AERIALWAYS:
            kind, subtype = "lift", aw
        elif rw == "funicular":
            kind, subtype = "lift", "funicular"
        if kind is None:
            skipped += 1
            continue
        lines.append(
            {
                "id": wid,
                "name": str(tags.get("name", "")) or (tags.get("ref") or wid),
                "kind": kind,
                "subtype": subtype,
                "coords": [[round(a, 6), round(b, 6)] for a, b in coords],
            }
        )
    if not any(ln["kind"] == "tram" for ln in lines):
        raise ValueError(
            f"no tram line found (looked for {tram_match!r} in name/ref/operator of railway ways); "
            "check the export or pass --tram-match"
        )
    return {
        "source": "OpenStreetMap contributors (ODbL), imported from " + path.split("/")[-1],
        "note": f"{len(lines)} ways kept, {skipped} ignored",
        "lines": lines,
    }


# ---------------------------------------------------------------------------------------------
# timetable
# ---------------------------------------------------------------------------------------------
class Schedule:
    """When the tram runs. "yes" / "no" / "unknown" (no data for that date or hours not loaded)."""

    def __init__(self, data: dict):
        self.version = str(data.get("version", ""))
        self.tz = ZoneInfo(data.get("timezone", "Europe/Paris"))
        self.margin = timedelta(minutes=float(data.get("margin_min", 30)))
        self.periods = [
            (
                date.fromisoformat(p["from"]),
                date.fromisoformat(p["to"]),
                p.get("status", "open"),
                p.get("hours"),
            )
            for p in data.get("periods", [])
        ]

    def operating(self, t: datetime) -> str:
        local = t.astimezone(self.tz)
        for d0, d1, status, hours in self.periods:
            if d0 <= local.date() <= d1:
                if status == "closed":
                    return "no"
                if not hours:
                    return "unknown"
                first = datetime.combine(local.date(), time.fromisoformat(hours["first"]), self.tz)
                last = datetime.combine(local.date(), time.fromisoformat(hours["last"]), self.tz)
                return "yes" if first - self.margin <= local <= last + self.margin else "no"
        return "unknown"


def load_schedule(path: Optional[str] = None) -> Schedule:
    if path is None:
        text = resources.files("mbhf").joinpath("data/tmb-schedule.json").read_text(encoding="utf-8")
    else:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    return Schedule(json.loads(text))


# ---------------------------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------------------------
@dataclass
class Stretch:
    kind: str                   # "tram" | "lift"
    line: str
    t_start: datetime
    t_end: datetime
    i_start: int
    i_end: int
    length_m: float
    mean_speed_kmh: float
    climb_m: Optional[float]
    climb_rate_mh: Optional[float]     # best over the window (tram) / None for lifts
    operating: str                     # tram only: yes | no | unknown ("" for lifts)
    bike_labelled: bool
    across_gap: bool
    verdict: str                       # "tram" | "lift" | "review" | "on_foot"
    reason: str


@dataclass
class TransportReport:
    performed: bool
    verdict: str = "not_checked"        # "clear" | "tram" | "lift" | "review" | "not_checked"
    stretches: list[Stretch] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.verdict in ("tram", "lift")


def _runs(near: list[int], pts, cfg: TransportConfig):
    """Group near-line fixes into stretches; also return recording-gap pairs between near fixes."""
    runs: list[list[int]] = []
    gaps: list[tuple[int, int]] = []
    cur: list[int] = []
    for j in near:
        if cur:
            prev = cur[-1]
            dt = (pts[j].t - pts[prev].t).total_seconds()
            if dt <= cfg.bridge_s:
                cur.append(j)
                continue
            runs.append(cur)
            if j == prev + 1 and dt >= cfg.gap_s:
                gaps.append((prev, j))
            cur = []
        cur.append(j)
    if cur:
        runs.append(cur)
    return [(r[0], r[-1]) for r in runs], gaps


def _path_len(pts, a: int, b: int) -> float:
    return sum(haversine_m(pts[k].lat, pts[k].lon, pts[k + 1].lat, pts[k + 1].lon) for k in range(a, b))


def _best_climb_rate(pts, a: int, b: int, window_s: float) -> Optional[float]:
    if any(pts[k].alt is None for k in range(a, b + 1)):
        return None
    total = (pts[b].t - pts[a].t).total_seconds()
    w = min(window_s, total)
    best = -math.inf
    j = a
    for i in range(a, b + 1):
        j = max(j, i)
        while j + 1 <= b and (pts[j + 1].t - pts[i].t).total_seconds() <= w:
            j += 1
        dt = (pts[j].t - pts[i].t).total_seconds()
        if dt >= 0.9 * w and dt > 0:
            best = max(best, (pts[j].alt - pts[i].alt) / dt * 3600.0)
    return None if best == -math.inf else best


def _fast_fraction(pts, a: int, b: int, window_s: float, kmh: float) -> float:
    """Share of the stretch's fixes whose forward chord speed over window_s is at least kmh."""
    fast = tot = 0
    j = a
    for i in range(a, b + 1):
        j = max(j, i)
        while j + 1 <= b and (pts[j + 1].t - pts[i].t).total_seconds() <= window_s:
            j += 1
        dt = (pts[j].t - pts[i].t).total_seconds()
        if dt < 0.5 * window_s:
            continue
        tot += 1
        if haversine_m(pts[i].lat, pts[i].lon, pts[j].lat, pts[j].lon) / dt * 3.6 >= kmh:
            fast += 1
    return fast / tot if tot else 0.0


def _operating_over(schedule: Optional[Schedule], t0: datetime, t1: datetime) -> str:
    if schedule is None:
        return "unknown"
    states = {schedule.operating(t0 + (t1 - t0) * f) for f in (0.0, 0.5, 1.0)}
    if "yes" in states:
        return "yes"
    return "no" if states == {"no"} else "unknown"


def analyse_transport(
    track: Track,
    labels: list[int],
    limit: int,
    lines: LineSet,
    schedule: Optional[Schedule] = None,
    cfg: Optional[TransportConfig] = None,
) -> TransportReport:
    """Look for tram / lift rides among the fixes before ``limit`` (exclusive)."""
    cfg = cfg or TransportConfig()
    if not lines:
        return TransportReport(
            performed=False,
            notes=["tram and lift check NOT performed: no line geometry loaded (run mbhf import-osm)"],
        )
    pts = track.points[:limit]
    report = TransportReport(performed=True)
    for key in lines.groups:
        kind, name = key
        radius = cfg.tram_radius_m if kind == "tram" else cfg.lift_radius_m
        min_len = cfg.tram_min_len_m if kind == "tram" else cfg.lift_min_len_m
        near = [k for k, p in enumerate(pts) if lines.distance(key, p.lat, p.lon, radius) <= radius]
        if not near:
            continue
        runs, gaps = _runs(near, pts, cfg)
        for a, b in runs:
            length = _path_len(pts, a, b)
            if length < min_len or b <= a:
                continue
            report.stretches.append(_judge(kind, name, pts, labels, a, b, length, False, schedule, cfg, lines, key))
        for a, b in gaps:
            dist = haversine_m(pts[a].lat, pts[a].lon, pts[b].lat, pts[b].lon)
            if dist < cfg.gap_jump_min_m:
                continue
            report.stretches.append(_judge(kind, name, pts, labels, a, b, dist, True, schedule, cfg, lines, key))
    order = {"tram": 3, "lift": 3, "review": 2, "on_foot": 1}
    worst = max(report.stretches, key=lambda s: order[s.verdict], default=None)
    report.verdict = "clear" if worst is None or worst.verdict == "on_foot" else worst.verdict
    if any(s.operating == "unknown" and s.verdict == "tram" for s in report.stretches):
        report.notes.append(
            "the tram timetable for this date is not loaded: the tram was assumed to be running"
        )
    if any(p.alt is None for p in pts):
        report.notes.append("some fixes have no altitude: the climb-rate test could not use them")
    return report


def _judge(kind, name, pts, labels, a, b, length, across_gap, schedule, cfg, lines, key) -> Stretch:
    t0, t1 = pts[a].t, pts[b].t
    dur = max(1.0, (t1 - t0).total_seconds())
    speed = length / dur * 3.6
    alt0, alt1 = pts[a].alt, pts[b].alt
    climb = None if alt0 is None or alt1 is None else alt1 - alt0
    bike = sum(1 for k in range(a, b + 1) if labels[k] in BIKE_STATES) > 0.5 * (b - a + 1)
    lateral = sorted(lines.distance(key, pts[k].lat, pts[k].lon) for k in range(a, b + 1))[(b - a) // 2]
    on_line = lateral <= cfg.bike_lateral_m
    rate: Optional[float] = None
    operating = ""
    if kind == "tram":
        operating = _operating_over(schedule, t0, t1)
        if across_gap:
            rate = None if climb is None else climb / dur * 3600.0
            fast = rate is not None and rate >= cfg.tram_min_rate_mh
            how = "implied climb rate across a recording gap"
        elif dur < cfg.min_window_s:
            fast = speed >= cfg.short_stretch_min_kmh
            how = f"speed {speed:.1f} km/h over a very short stretch"
        else:
            rate = _best_climb_rate(pts, a, b, cfg.window_s)
            fast = rate is not None and rate >= cfg.tram_min_rate_mh
            how = "best climb rate over the window"
        rate_txt = "n/a" if rate is None else f"{rate:.0f} m/h"
        if not fast:
            verdict, reason = "on_foot", f"follows the rails but not fast ({how}: {rate_txt}, {speed:.1f} km/h)"
        elif bike and not on_line:
            verdict, reason = "review", (
                f"fast near the rails ({rate_txt}) and labelled as a bike ride, "
                f"{lateral:.0f} m from the line: possibly a bicycle on a parallel road"
            )
        elif operating == "no":
            verdict, reason = "review", f"fast on the rails ({rate_txt}) but the tram is not running then"
        else:
            verdict, reason = "tram", f"follows the rails, tram running ({operating}), {how}: {rate_txt}"
    else:
        if across_gap:
            fast = speed >= cfg.lift_min_speed_kmh
            how = f"implied speed {speed:.1f} km/h across a recording gap"
        else:
            frac = _fast_fraction(pts, a, b, cfg.lift_window_s, cfg.lift_min_speed_kmh)
            fast = frac >= cfg.lift_fast_fraction
            how = f"{frac * 100:.0f}% of the stretch faster than {cfg.lift_min_speed_kmh:g} km/h"
        if not fast:
            verdict, reason = "on_foot", f"follows the lift line at walking pace ({how})"
        elif bike and not on_line:
            verdict, reason = "review", (
                f"fast near the lift line ({how}) and labelled as a bike ride, "
                f"{lateral:.0f} m from the line: possibly a bicycle on a parallel road"
            )
        else:
            verdict, reason = "lift", f"follows the lift line at lift speed ({how})"
    return Stretch(
        kind=kind,
        line=name,
        t_start=t0,
        t_end=t1,
        i_start=a,
        i_end=b,
        length_m=length,
        mean_speed_kmh=speed,
        climb_m=climb,
        climb_rate_mh=rate,
        operating=operating,
        bike_labelled=bike,
        across_gap=across_gap,
        verdict=verdict,
        reason=reason,
    )


def transport_to_dict(r: TransportReport) -> dict:
    return {
        "performed": r.performed,
        "verdict": r.verdict,
        "notes": r.notes,
        "stretches": [
            {
                "kind": s.kind,
                "line": s.line,
                "start": s.t_start.isoformat(),
                "end": s.t_end.isoformat(),
                "length_m": round(s.length_m),
                "mean_speed_kmh": round(s.mean_speed_kmh, 1),
                "climb_m": None if s.climb_m is None else round(s.climb_m),
                "best_climb_rate_mh": None if s.climb_rate_mh is None else round(s.climb_rate_mh),
                "tram_running": s.operating or None,
                "across_recording_gap": s.across_gap,
                "verdict": s.verdict,
                "reason": s.reason,
            }
            for s in r.stretches
        ],
    }
