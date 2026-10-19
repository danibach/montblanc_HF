"""The climbing chrono: from leaving the Nid d'Aigle cylinder to entering the summit cylinder.

Rules implemented (draft, see the Notion pages):

* Nid d'Aigle: the clock starts at the LAST exit from its cylinder before the summit cylinder
  is entered (the exit after which the track never comes back). Exiting sideways or upwards
  both count. "Last exit" makes the result immune to GPS jitter on the edge of the cylinder.
* Summit: the clock stops at the first entry into the summit cylinder, which must be made on
  foot (not in flight).
* HF / BHF badge condition: the final exit from the summit cylinder must be by flight.
* Ranking only needs the chrono plus a flight somewhere in the track.

NOT implemented yet: the proof that the whole approach was on foot (no tramway or lift). Results
are therefore marked provisional.

Crossing times are linearly interpolated between the two fixes around the boundary, so they
are not tied to the sampling rate; ``uncertainty_s`` reports the time between those fixes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .geo import EARTH_RADIUS_M, haversine_m
from .models import Point, Track
from .rules import Cylinder, RuleSet
from .segment import SegmentationResult

FOOT = 1      # state index of the ascent on foot
FLIGHT = 2    # state index of the flight


@dataclass
class Crossing:
    kind: str            # "enter" | "exit"
    t: datetime          # interpolated instant
    index: int           # first fix inside (enter) or first fix outside (exit)
    label: int           # segmentation state of that fix
    gap_s: float         # seconds between the two fixes around the crossing


def inside(p: Point, cyl: Cylinder) -> bool:
    """A fix without altitude cannot be checked against the altitude band: it is outside."""
    if p.alt is None:
        return False
    return (
        haversine_m(p.lat, p.lon, cyl.lat, cyl.lon) <= cyl.radius_m
        and cyl.alt_min_m <= p.alt <= cyl.alt_max_m
    )


_M_PER_DEG = EARTH_RADIUS_M * math.pi / 180.0


def _horizontal_fraction(a: Point, b: Point, cyl: Cylinder, entering: bool) -> float:
    """Where the straight line from a to b crosses the cylinder's circle (exact, not distance-linear).

    A path between two distant fixes can pass close to the centre, so the distance to the centre
    is not linear along it; solve |a + f (b - a) - centre| = radius for f.
    """
    cos_lat = math.cos(math.radians(cyl.lat))
    ax, ay = (a.lon - cyl.lon) * _M_PER_DEG * cos_lat, (a.lat - cyl.lat) * _M_PER_DEG
    bx, by = (b.lon - cyl.lon) * _M_PER_DEG * cos_lat, (b.lat - cyl.lat) * _M_PER_DEG
    dx, dy = bx - ax, by - ay
    qa = dx * dx + dy * dy
    qb = 2 * (ax * dx + ay * dy)
    qc = ax * ax + ay * ay - cyl.radius_m**2
    disc = qb * qb - 4 * qa * qc
    if qa == 0 or disc < 0:
        return 1.0 if entering else 0.0
    root = math.sqrt(disc)
    f1, f2 = (-qb - root) / (2 * qa), (-qb + root) / (2 * qa)
    f = f1 if entering else f2
    return min(1.0, max(0.0, f))


def _crossing_fraction(a: Point, b: Point, cyl: Cylinder, entering: bool) -> float:
    """Fraction (0..1) of the way from fix a to fix b at which the cylinder is entered / left.

    The cylinder is the intersection of three conditions (within the radius, above the lower
    limit, below the upper limit). Each changes at some point along the straight line between
    the fixes; entering happens when the last condition becomes true, leaving when the first
    one becomes false.
    """
    assert a.alt is not None and b.alt is not None
    in_a = haversine_m(a.lat, a.lon, cyl.lat, cyl.lon) <= cyl.radius_m
    in_b = haversine_m(b.lat, b.lon, cyl.lat, cyl.lon) <= cyl.radius_m
    fractions: list[float] = []
    if in_a != in_b and ((entering and in_b) or (not entering and in_a)):
        fractions.append(_horizontal_fraction(a, b, cyl, entering))
    for limit, a_ok, b_ok in (
        (cyl.alt_min_m, a.alt >= cyl.alt_min_m, b.alt >= cyl.alt_min_m),
        (cyl.alt_max_m, a.alt <= cyl.alt_max_m, b.alt <= cyl.alt_max_m),
    ):
        if a_ok != b_ok and ((entering and b_ok) or (not entering and a_ok)):
            va, vb = a.alt - limit, b.alt - limit
            fractions.append(min(1.0, max(0.0, va / (va - vb))))
    if not fractions:
        return 1.0 if entering else 0.0
    return max(fractions) if entering else min(fractions)


def find_crossings(pts: list[Point], labels: list[int], cyl: Cylinder) -> list[Crossing]:
    out: list[Crossing] = []
    flags = [inside(p, cyl) for p in pts]
    for k in range(1, len(pts)):
        if flags[k] == flags[k - 1]:
            continue
        a, b = pts[k - 1], pts[k]
        entering = flags[k]
        if a.alt is None or b.alt is None:
            frac = 1.0 if entering else 0.0
        else:
            frac = _crossing_fraction(a, b, cyl, entering)
        out.append(
            Crossing(
                kind="enter" if entering else "exit",
                t=a.t + (b.t - a.t) * frac,
                index=k,
                label=labels[k],
                gap_s=(b.t - a.t).total_seconds(),
            )
        )
    return out


@dataclass
class Chrono:
    ruleset: str
    seconds: Optional[float] = None
    nid_exit: Optional[datetime] = None
    summit_enter: Optional[datetime] = None
    summit_final_exit: Optional[datetime] = None
    summit_exit_by_flight: bool = False
    has_flight: bool = False
    ranking_eligible: bool = False
    hf_conditions_met: bool = False
    uncertainty_s: float = 0.0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def compute_chrono(track: Track, result: SegmentationResult, rules: RuleSet) -> Chrono:
    pts, labels = track.points, result.labels
    out = Chrono(ruleset=rules.version)
    out.has_flight = any(s.mode == "flight" for s in result.segments)
    out.notes.append(
        "provisional: the check that the whole approach was on foot (no tramway or lift) "
        "is not implemented yet"
    )
    if any(p.alt is None for p in pts):
        out.notes.append("some fixes have no altitude and cannot be tested against the altitude bands")

    na = find_crossings(pts, labels, rules.nid_d_aigle)
    su = find_crossings(pts, labels, rules.summit)

    # --- summit: first entry, on foot
    entries = [c for c in su if c.kind == "enter"]
    foot_entries = [c for c in entries if c.label == FOOT]
    if not foot_entries:
        reason = "the track never enters the summit cylinder on foot"
        within = [p for p in pts if haversine_m(p.lat, p.lon, rules.summit.lat, rules.summit.lon) <= rules.summit.radius_m]
        if not within:
            nearest = min(haversine_m(p.lat, p.lon, rules.summit.lat, rules.summit.lon) for p in pts)
            reason += f" (closest approach {nearest:.0f} m, radius {rules.summit.radius_m:.0f} m)"
        else:
            alts = [p.alt for p in within if p.alt is not None]
            if alts:
                reason += (
                    f" (inside the radius, altitudes were {min(alts):.0f} to {max(alts):.0f} m "
                    f"against a band of {rules.summit.alt_min_m:.0f} to {rules.summit.alt_max_m:.0f} m)"
                )
        if entries:
            reason += "; it entered only while flying"
        out.problems.append(reason)
        return out
    s_enter = foot_entries[0]
    out.summit_enter = s_enter.t

    # --- summit: final exit must be by flight
    exits_after = [c for c in su if c.kind == "exit" and c.t > s_enter.t]
    if exits_after:
        final = exits_after[-1]
        out.summit_final_exit = final.t
        out.summit_exit_by_flight = final.label == FLIGHT
        if not out.summit_exit_by_flight:
            out.problems.append(
                "the track leaves the summit cylinder on foot, not by flight "
                f"(at {final.t.isoformat()}); no HF/BHF badge"
            )
    else:
        out.problems.append("the track never leaves the summit cylinder")

    # --- Nid d'Aigle: last exit before the summit entry, after being there on foot
    was_there_on_foot = any(
        inside(p, rules.nid_d_aigle) and labels[k] == FOOT and p.t <= s_enter.t for k, p in enumerate(pts)
    )
    exits_before = [c for c in na if c.kind == "exit" and c.t <= s_enter.t]
    if not was_there_on_foot or not exits_before:
        out.problems.append(
            "the track does not pass through the Nid d'Aigle cylinder on foot before the summit"
        )
        return out
    n_exit = exits_before[-1]
    out.nid_exit = n_exit.t
    out.seconds = (s_enter.t - n_exit.t).total_seconds()
    out.uncertainty_s = n_exit.gap_s + s_enter.gap_s
    if n_exit.gap_s >= 120 or s_enter.gap_s >= 120:
        out.notes.append(
            "a crossing happened across a recording gap of two minutes or more; "
            "the chrono is only accurate to within that gap"
        )
    if out.seconds <= 0:
        out.problems.append("the summit is reached before leaving Nid d'Aigle: inconsistent track")
        out.seconds = None
        return out

    out.ranking_eligible = out.has_flight
    if not out.has_flight:
        out.problems.append("no flight part in the track: it would not be registered in the ranking")
    out.hf_conditions_met = out.ranking_eligible and out.summit_exit_by_flight
    return out


def chrono_to_dict(c: Chrono) -> dict:
    def iso(t: Optional[datetime]) -> Optional[str]:
        return t.isoformat() if t else None

    return {
        "ruleset": c.ruleset,
        "provisional": True,
        "climb_seconds": None if c.seconds is None else round(c.seconds, 1),
        "climb_hms": None if c.seconds is None else _hms(c.seconds),
        "nid_d_aigle_last_exit": iso(c.nid_exit),
        "summit_first_entry_on_foot": iso(c.summit_enter),
        "summit_final_exit": iso(c.summit_final_exit),
        "summit_exit_by_flight": c.summit_exit_by_flight,
        "has_flight": c.has_flight,
        "ranking_eligible": c.ranking_eligible,
        "hf_conditions_met": c.hf_conditions_met,
        "uncertainty_s": round(c.uncertainty_s, 1),
        "problems": c.problems,
        "notes": c.notes,
    }


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
