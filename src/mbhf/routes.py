"""Routes: the climbs to one take-off that follow the same way up, gathered into one route.

Rule (decided on 23 October 2026 from the live climbs, see Notion « Décisions »): two climbs follow the same route
when their starts are less than ``START_M`` apart and the two lines stay within ``NEAR_M`` of each other along
``SHARE`` of the way (each line resampled every ``STEP_M``; each point compared with the nearest point of the other
line, both ways). On the live climbs, the same path stays within 15 to 110 m; different paths stray 400 m or more.
Two starts that meet higher up stay two routes: the walk-in differs. ``SHARE`` went from 90 % to 80 % on 25 October
2026: at the Pointe de Beauregard two winter climbs from La Clusaz by the same way kept 80 % of their points within
104 m (the zigzags of a ski climb part a little more), while the two ways from La Clusaz stray 550 m and more there.

A route is drawn as its median line (``median_line``): every climb is laid along the most central one, point by
point, and the middle of them is kept, so ten climbs of one way make one line that none of them strays from
much. A climb joins a route when it matches any climb of it.
Nothing here changes the analysis of a track.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Optional

START_M = 500.0
NEAR_M = 150.0
SHARE = 0.8
STEP_M = 25.0
ALIGN_AHEAD = 40       # laying a climb along another: look this many points (1 km) ahead for the nearest one
LINE_POINTS = 120      # a median line keeps at most this many points


def _xy(points: list, lat0: float) -> list[tuple[float, float]]:
    k = math.cos(math.radians(lat0))
    return [(lon * 111320.0 * k, lat * 110540.0) for lat, lon in points]


def _latlon(pts: list[tuple[float, float]], lat0: float) -> list[list[float]]:
    k = math.cos(math.radians(lat0))
    return [[round(y / 110540.0, 6), round(x / (111320.0 * k), 6)] for x, y in pts]


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
        self.lat0 = lat0 if lat0 is not None else line[0][0]
        self.pts = resample(line, self.lat0)
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


def _laid_along(ref: list[tuple[float, float]], pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """For each point of ``ref``, the nearest point of ``pts``, going only forward (a climb does not go back down
    its own way), looking at most ALIGN_AHEAD points ahead."""
    out, j = [], 0
    for p in ref:
        window = range(j, min(len(pts), j + ALIGN_AHEAD))
        j = min(window, key=lambda k: (pts[k][0] - p[0]) ** 2 + (pts[k][1] - p[1]) ** 2)
        out.append(pts[j])
    return out


def median_line(route: list[Climb]) -> list[list[float]]:
    """The line of a route: every climb laid along the most central one, then, point by point, the median of
    them (east and north apart), lightly smoothed. One climb: its own line."""
    ref = central(route)
    if len(route) == 1:
        return ref.line
    lat0 = ref.lat0
    others = [c.pts if c.lat0 == lat0 else resample(c.line, lat0) for c in route if c is not ref]
    laid = [ref.pts] + [_laid_along(ref.pts, pts) for pts in others]
    mid = [(statistics.median(l[i][0] for l in laid), statistics.median(l[i][1] for l in laid))
           for i in range(len(ref.pts))]
    smooth = [mid[0]] + [((mid[i - 1][0] + mid[i][0] + mid[i + 1][0]) / 3, (mid[i - 1][1] + mid[i][1] + mid[i + 1][1]) / 3)
                         for i in range(1, len(mid) - 1)] + [mid[-1]]
    step = max(1, math.ceil(len(smooth) / LINE_POINTS))
    kept = smooth[::step] + ([smooth[-1]] if (len(smooth) - 1) % step else [])
    return _latlon(kept, lat0)


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
        out.append({"name": name, "start_place": place, "line": median_line(g), "outing_ids": [c.id for c in g]})
    return out
