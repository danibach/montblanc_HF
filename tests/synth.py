"""Synthetic tracks for tests: a climb on foot, a flight, a second climb, a ride.

The numbers are plausible but invented. They prove the code does what it is designed to do;
they do NOT prove it works on real tracks, which still have to be tested.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from mbhf.models import Point, Track

T0 = datetime(2026, 9, 12, 6, 0, 0, tzinfo=timezone.utc)


class Gen:
    def __init__(self, t0: datetime = T0, lat: float = 45.90, lon: float = 6.80, alt: float = 1000.0, seed: int = 1):
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
        wobble: float = 0.0,
        ramp: float = 0.0,
        circling: Optional[tuple[float, float, float, float]] = None,  # (start_s, end_s, deg_per_s, vz)
        noise: tuple[float, float] = (3.0, 4.0),
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
                )
            )
            self.x += v * dt * math.sin(hr)
            self.y += v * dt * math.cos(hr)
            self.alt += vzk * dt
            self.t += timedelta(seconds=dt)


def hike_and_fly(seed: int = 1) -> Gen:
    """Start at 1 000 m, climb 1 200 m on foot in 2 h, pause, fly 25 min down ~1 150 m, walk 10 min.

    Expected: D+ about 1 200 m, D- about 1 150 m, one flight.
    """
    g = Gen(seed=seed, alt=1000.0)
    g.leg("walk_up", 2 * 3600, 2.6, 1200 / 7200, 60, wobble=12)
    g.leg("summit_pause", 5 * 60, 0, 0.0, 60)
    g.leg("flight", 25 * 60, 38, -1150 / 1500, 230, dt=2.0, wobble=25, ramp=20, circling=(500, 620, 18.0, 1.6))
    g.leg("landing_walk", 10 * 60, 4.0, -0.01, 250, wobble=15)
    return g


def two_flights(seed: int = 2) -> Gen:
    """Climb 800 m, fly down 700 m, climb again 500 m (steeper), fly down 500 m."""
    g = Gen(seed=seed, alt=900.0)
    g.leg("up1", 80 * 60, 2.4, 800 / 4800, 70, wobble=12)
    g.leg("pause1", 4 * 60, 0, 0.0, 70)
    g.leg("fly1", 14 * 60, 36, -700 / 840, 220, dt=2.0, wobble=20, ramp=15)
    g.leg("walk1", 8 * 60, 4.0, 0.0, 240, wobble=10)
    g.leg("up2", 50 * 60, 2.4, 500 / 3000, 20, wobble=12)
    g.leg("pause2", 4 * 60, 0, 0.0, 20)
    g.leg("fly2", 10 * 60, 36, -500 / 600, 200, dt=2.0, wobble=20, ramp=15)
    g.leg("walk2", 5 * 60, 4.0, 0.0, 200, wobble=10)
    return g


def drive_then_walk(seed: int = 3) -> Gen:
    """No flight: a walk up and down. Rejected."""
    g = Gen(seed=seed, alt=1000.0)
    g.leg("up", 90 * 60, 2.5, 700 / 5400, 60, wobble=12)
    g.leg("down", 60 * 60, 3.5, -700 / 3600, 240, wobble=12)
    return g


def lift_then_fly(seed: int = 4) -> Gen:
    """A cable-car ride (fast, steady climb), then a flight: almost no walking, so rejected."""
    g = Gen(seed=seed, alt=1000.0)
    g.leg("walk_to_lift", 5 * 60, 4.0, 0.0, 60)
    g.leg("lift", 10 * 60, 22, 1.5, 60, dt=3.0, noise=(2.0, 3.0))
    g.leg("pause", 3 * 60, 0, 0.0, 60)
    g.leg("flight", 15 * 60, 36, -900 / 900, 230, dt=2.0, wobble=20, ramp=15)
    g.leg("walk", 5 * 60, 4.0, 0.0, 230)
    return g


def as_track(g: Gen, source: str = "synthetic") -> Track:
    return Track(points=list(g.points), source=source, fmt="gpx")


def gpx_bytes(track: Track, with_time: bool = True, with_alt: bool = True) -> bytes:
    rows = []
    for p in track.points:
        t = f"<time>{p.t.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}</time>" if with_time else ""
        e = f"<ele>{p.alt:.1f}</ele>" if with_alt else ""
        rows.append(f'<trkpt lat="{p.lat:.6f}" lon="{p.lon:.6f}">{e}{t}</trkpt>')
    return ('<?xml version="1.0"?><gpx version="1.1"><trk><trkseg>' + "".join(rows) + "</trkseg></trk></gpx>").encode()


def hike_then_drive_home(seed: int = 5) -> Gen:
    """Climb 700 m on foot, walk back down to the car park, then drive down a long road: no flight."""
    g = Gen(seed=seed, alt=1500.0)
    g.leg("up", 80 * 60, 2.6, 700 / 4800, 60, wobble=12)
    g.leg("down", 60 * 60, 3.6, -700 / 3600, 240, wobble=12)
    g.leg("pause", 3 * 60, 0, 0.0, 240)
    g.leg("drive", 25 * 60, 45, -0.7, 200, dt=3.0, wobble=6, noise=(2.0, 3.0))
    return g


def steep_flight_then_bike(seed: int = 6, sink: float = 2.5) -> Gen:
    """Climb to 4 700 m, long pause, a steep fast descent (2.5 m/s of sink at 38 km/h: glide 4:1, a speed-riding
    wing), then a bike ride on the flat."""
    g = Gen(seed=seed, alt=1000.0)
    g.leg("walk_up", 3 * 3600, 2.6, 3700 / 10800, 60, wobble=12)
    g.leg("summit_pause", 10 * 60, 0, 0.0, 60)
    g.leg("flight", 15 * 60, 38, -sink, 230, dt=2.0, wobble=10, ramp=20)
    g.leg("bike", 10 * 60, 30, 0.0, 250, dt=5.0, wobble=5)
    return g


def ski_then_fly(seed: int = 7) -> Gen:
    """Skins up 1 000 m, a long stop on the summit, a slow jerky ski descent of 720 m (labelled walking: 6 km/h),
    a stop at the take-off 700 m lower, then a 5-minute glide of 550 m under a mini-wing (38 km/h, 1.8 m/s)."""
    g = Gen(seed=seed, alt=1400.0)
    g.leg("up", 3 * 3600, 2.4, 1000 / 10800, 60, wobble=12)
    g.leg("summit_pause", 40 * 60, 0, 0.0, 60)
    g.leg("ski", 24 * 60, 6, -0.5, 200, dt=3.0, wobble=40)
    g.leg("pause", 20 * 60, 0, 0.0, 200, dt=3.0)
    g.leg("flight", 5 * 60, 38, -1.8, 20, dt=3.0, wobble=8, ramp=10)
    g.leg("landing_walk", 5 * 60, 3.0, 0.0, 20)
    return g


def slow_ski_descent(seed: int = 8) -> Gen:
    """Skins up 1 000 m, then one 14-minute ski descent at 14 km/h, 1.2 m/s of sink: not a flight."""
    g = Gen(seed=seed, alt=1400.0)
    g.leg("up", 3 * 3600, 2.4, 1000 / 10800, 60, wobble=12)
    g.leg("summit_pause", 10 * 60, 0, 0.0, 60)
    g.leg("ski", 14 * 60, 14, -1.2, 200, dt=3.0, wobble=30)
    g.leg("end", 5 * 60, 0, 0.0, 200)
    return g


def ski_head_then_flight(seed: int = 9) -> Gen:
    """Climb 1 000 m, then one fast descent that is first a ski run (3 min, 36 km/h, 2.2 m/s of sink), then a
    pause in the loss of altitude (80 s, straight, 0.6 m/s), then the flight (9 min, 36 km/h, 2.2 m/s)."""
    g = Gen(seed=seed, alt=1400.0)
    g.leg("up", 3 * 3600, 2.4, 1000 / 10800, 60, wobble=12)
    g.leg("summit_pause", 20 * 60, 0, 0.0, 60)
    g.leg("ski", 3 * 60, 36, -2.2, 200, dt=3.0, wobble=15, ramp=10)
    g.leg("pause", 80, 40, -0.6, 200, dt=3.0)
    g.leg("flight", 9 * 60, 36, -2.2, 200, dt=3.0, wobble=15)
    g.leg("landing_walk", 5 * 60, 3.0, 0.0, 200)
    return g
