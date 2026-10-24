"""Routes: the climbs to one take-off that follow the same way up, gathered into one route.

Rule (decided on 23 October 2026 from the live climbs, see Notion « Décisions »): two climbs follow the same route
when their starts are less than ``START_M`` apart and the two lines stay within ``NEAR_M`` of each other along
``SHARE`` of the way (each line resampled every ``STEP_M``; each point compared with the nearest point of the other
line, both ways). On the live climbs, the same path stays within 15 to 110 m; different paths stray 400 m or more.
Two starts that meet higher up stay two routes: the walk-in differs.

A route is drawn with one of its real climbs, the most central one (closest to all the others), not an average
that could cut across the slope. A climb joins a route when it matches any climb of it.
Nothing here changes the analysis of a track.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Optional

START_M = 500.0
NEAR_M = 150.0
SHARE = 0.9
STEP_M = 25.0


def _xy(points: list, lat0: float) -> list[tuple[float, float]]:
    k = math.cos(math.radians(lat0))
    return [(lon * 111320.0 * k, lat * 110540.0) for lat, lon in points]


def resample(line: list, lat0: float) -> list[tuple[float, float]]:
    """The line as flat points (metres) every STEP_M."""
    pts = _xy(line, lat0)
    out = [pts[0]]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) // STEP_M))
        out += [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(1, n + 1)]
    return out


class _Grid:
    """Points of a line in cells of NEAR_M, to tell quickly whether a point has one of them within NEAR_M."""

    def __init__(self, pts):
        self.cells: dict[tuple[int, int], list] = {}
        for p in pts:
            self.cells.setdefault((int(p[0] // NEAR_M), int(p[1] // NEAR_M)), []).append(p)

    def near(self, p) -> bool:
        ci, cj = int(p[0] // NEAR_M), int(p[1] // NEAR_M)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for q in self.cells.get((ci + di, cj + dj), ()):
                    if (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 <= NEAR_M ** 2:
                        return True
        return False


class Climb:
    """One outing's climb, ready to compare: ``line`` is [[lat, lon], …] from the bottom to the take-off."""

    def __init__(self, outing_id: str, line: list, start_place: Optional[str] = None, lat0: Optional[float] = None):
        self.id, self.line, self.start_place = outing_id, line, start_place
        self.pts = resample(line, lat0 if lat0 is not None else line[0][0])
        self.grid = _Grid(self.pts)


def far_share(a: Climb, b: Climb) -> float:
    """Share of the points of both lines farther than NEAR_M from the other line."""
    far = sum(1 for p in a.pts if not b.grid.near(p)) + sum(1 for p in b.pts if not a.grid.near(p))
    return far / (len(a.pts) + len(b.pts))


def same_route(a: Climb, b: Climb) -> bool:
    (ax, ay), (bx, by) = a.pts[0], b.pts[0]
    if math.hypot(ax - bx, ay - by) >= START_M:
        return False
    return far_share(a, b) <= 1 - SHARE


def group(climbs: list[Climb]) -> list[list[Climb]]:
    """The routes of one take-off, the most climbed first."""
    groups: list[list[Climb]] = []
    for c in climbs:
        joined = [g for g in groups if any(same_route(c, x) for x in g)]
        if not joined:
            groups.append([c])
            continue
        first = joined[0]
        first.append(c)
        for g in joined[1:]:  # c links two routes: they are one
            first += g
            groups.remove(g)
    return sorted(groups, key=len, reverse=True)


def central(route: list[Climb]) -> Climb:
    """The climb closest to all the others of its route (the first one when they are two)."""
    if len(route) <= 2:
        return route[0]
    return min(route, key=lambda c: sum(far_share(c, o) for o in route if o is not c))


def routes_of(climbs: list[Climb]) -> list[dict]:
    """``[{name, start_place, line, outing_ids}]`` for one take-off: « From La Clusaz », « From La Clusaz (variant 2) »."""
    out = []
    seen = Counter()
    for g in group(climbs):
        place = Counter(c.start_place for c in g if c.start_place).most_common(1)
        place = place[0][0] if place else None
        seen[place] += 1
        name = f"From {place}" if place else "From an unnamed start"
        if seen[place] > 1:
            name += f" (variant {seen[place]})"
        out.append({"name": name, "start_place": place, "line": central(g).line, "outing_ids": [c.id for c in g]})
    return out
