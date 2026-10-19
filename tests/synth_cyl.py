"""Synthetic day laid out on the real cylinder coordinates, so crossings have an analytic answer."""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Optional

from synth import Gen

from mbhf.geo import haversine_m
from mbhf.models import Point, Track
from mbhf.rules import load_ruleset

RULES = load_ruleset()
NA = (RULES.nid_d_aigle.lat, RULES.nid_d_aigle.lon)
SU = (RULES.summit.lat, RULES.summit.lon)
TRAILHEAD = (45.9253, 6.7141, 591.0)
LEG_B_S = 6 * 3600     # Nid d'Aigle -> summit, constant speed
NA_ALT, SU_ALT = 2400.0, 4806.0


class GeoGen(Gen):
    def line(self, name: Optional[str], a, b, dur: float, dt: float, hint: Optional[str] = None) -> None:
        if name:
            self.marks[name] = self.t
        n = int(dur / dt)
        for k in range(n):
            s = (k * dt) / dur
            self.points.append(
                Point(
                    t=self.t,
                    lat=a[0] + (b[0] - a[0]) * s,
                    lon=a[1] + (b[1] - a[1]) * s,
                    alt=a[2] + (b[2] - a[2]) * s,
                    hint=hint,
                )
            )
            self.t += timedelta(seconds=dt)

    def hold(self, name: Optional[str], at, dur: float, dt: float) -> None:
        self.line(name, at, at, dur, dt)


def cyl_day(flight: bool = True, seed: int = 1) -> GeoGen:
    g = GeoGen(seed=seed)
    g.line("bike_out", (45.90, 6.65, 600.0), TRAILHEAD, 20 * 60, 5)
    g.hold(None, TRAILHEAD, 60, 5)
    g.line("ascent_a", TRAILHEAD, (NA[0], NA[1], NA_ALT), 4 * 3600, 10)
    g.line("ascent_b", (NA[0], NA[1], NA_ALT), (SU[0], SU[1], SU_ALT), LEG_B_S, 10)
    g.hold("summit_hold", (SU[0], SU[1], SU_ALT), 10 * 60, 10)
    if flight:
        g.line("flight", (SU[0], SU[1], SU_ALT), (45.93, 6.70, 900.0), 25 * 60, 2)
        g.line("landing_walk", (45.93, 6.70, 900.0), (45.9305, 6.7022, 895.0), 10 * 60, 5)
    else:
        g.line("walk_down", (SU[0], SU[1], SU_ALT), (NA[0], NA[1], NA_ALT), 5 * 3600, 10)
    return g


def to_track(g: GeoGen) -> Track:
    return Track(points=list(g.points), source="synthetic", fmt="gpx")


def expected_chrono_seconds(rules=RULES) -> float:
    """Analytic time from leaving the Nid d'Aigle cylinder to entering the summit cylinder."""
    d = haversine_m(NA[0], NA[1], SU[0], SU[1])
    s_alt_exit = (rules.nid_d_aigle.alt_max_m - NA_ALT) / (SU_ALT - NA_ALT)
    s_h_exit = rules.nid_d_aigle.radius_m / d
    s_exit = min(s_alt_exit, s_h_exit)
    s_enter = max(1 - rules.summit.radius_m / d, (rules.summit.alt_min_m - NA_ALT) / (SU_ALT - NA_ALT))
    return (s_enter - s_exit) * LEG_B_S
