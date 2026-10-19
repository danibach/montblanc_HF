"""Synthetic tracks for tests: a bike ride, an ascent on foot, a flight, and the way back.

The numbers are plausible but invented. They prove the code does what it is designed to do;
they do NOT prove it works on real tracks, which still have to be tested.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from mbhf.models import Point, Track

T0 = datetime(2026, 9, 12, 5, 0, 0, tzinfo=timezone.utc)


class Gen:
    def __init__(self, t0: datetime = T0, lat: float = 45.90, lon: float = 6.80, alt: float = 600.0, seed: int = 1):
        self.t = t0
        self.lat0, self.lon0 = lat, lon
        self.x = self.y = 0.0
        self.alt = alt
        self.rng = random.Random(seed)
        self.points: list[Point] = []
        self.marks: dict[str, datetime] = {}

    def leg(
        self,
        name: Optional[str],
        dur: float,
        kmh: float,
        vz: float,
        heading: float,
        dt: float = 5.0,
        hint: Optional[str] = None,
        wobble: float = 0.0,
        ramp: float = 0.0,
        circling: Optional[tuple[float, float, float, float]] = None,  # (start_s, end_s, deg_per_s, vz)
        noise: tuple[float, float] = (3.0, 6.0),
        src: int = 0,
    ) -> None:
        if name:
            self.marks[name] = self.t
        n = int(dur / dt)
        for k in range(n):
            tt = k * dt
            v = kmh / 3.6
            if ramp > 0 and tt < ramp:
                v *= tt / ramp
            h = heading + wobble * math.sin(2 * math.pi * tt / 60.0)
            vzk = vz
            if circling and circling[0] <= tt < circling[1]:
                h = heading + circling[2] * (tt - circling[0])
                vzk = circling[3]
            hr = math.radians(h)
            self.points.append(
                Point(
                    t=self.t,
                    lat=self.lat0 + (self.y + self.rng.gauss(0, noise[0])) / 111_320.0,
                    lon=self.lon0 + (self.x + self.rng.gauss(0, noise[0])) / (111_320.0 * math.cos(math.radians(self.lat0))),
                    alt=self.alt + self.rng.gauss(0, noise[1]),
                    hint=hint,
                    src=src,
                )
            )
            self.x += v * dt * math.sin(hr)
            self.y += v * dt * math.cos(hr)
            self.alt += vzk * dt
            self.t += timedelta(seconds=dt)


def full_day(seed: int = 1, steep_descent: bool = False) -> Gen:
    """Bike out, stop, ascent, summit pause, flight (with a thermal), landing, walk, bike back.

    Altitudes follow the real geography: valley at ~580 m, summit at ~4 800 m.
    """
    g = Gen(seed=seed, alt=580.0)
    g.leg("bike_out", 60 * 60, 15, 0.29, 80)                       # ride up to ~1 650 m
    if steep_descent:
        # a steep, straight bike descent (40 km/h, 12 % grade): looks like a glide on speed and sink alone
        g.leg(None, 3 * 60, 40, -1.3, 80)
        g.leg(None, 12 * 60, 12, 0.55, 80)
    g.leg(None, 60, 0, 0.0, 80)                                    # standing at the transition
    g.leg("ascent", 9 * 3600, 2.8, 0.097, 60, wobble=10)           # ~ +3 150 m on foot
    g.leg(None, 5 * 60, 0, 0.0, 60)                                # summit pause, kit up
    g.leg("flight", 25 * 60, 38, -2.7, 230, dt=2.0, wobble=25, ramp=20, circling=(500, 620, 18.0, 1.6))
    g.leg("landing_walk", 10 * 60, 4.0, -0.05, 250, wobble=15)
    g.leg("bike_return", 50 * 60, 32, -0.2, 250)
    return g


def as_track(g: Gen, source: str = "synthetic", hint: Optional[str] = None) -> Track:
    return Track(points=list(g.points), source=source, fmt="gpx", hint=hint)
