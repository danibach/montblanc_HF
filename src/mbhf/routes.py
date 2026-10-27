"""Routes: the climbs to one take-off that follow the same way up, gathered into one route.

Rule (decided on 23 October 2026 from the live climbs, see Notion « Décisions »): two climbs follow the same route
when their starts are less than ``START_M`` apart and the two lines stay within ``NEAR_M`` of each other along
``SHARE`` of the way (each line resampled every ``STEP_M``; each point compared with the nearest point of the other
line, both ways). On the live climbs, the same path stays within 15 to 110 m; different paths stray 400 m or more.
Two starts that meet higher up stay two routes: the walk-in differs. ``SHARE`` went from 90 % to 80 % on 25 October
2026: at the Pointe de Beauregard two winter climbs from La Clusaz by the same way kept 80 % of their points within
104 m (the zigzags of a ski climb part a little more), while the two ways from La Clusaz stray 550 m and more there.

Two more cases are the same route (Sarah, 27 October 2026, from the live routes: 80 routes for 62 take-offs, several
of them the same path):
* a climb that lies along another for ``INSIDE_SHARE`` of its way is that way from a start higher up (Les Moillats
  on the way from Les Esserts to the Col des Frêtes: 100 %; La Clusaz on the way from Les Verrier to Beauregard);
* two climbs starting less than ``SAME_START_M`` apart are one route when the shorter lies along the other for
  ``SAME_START_SHARE`` of its way (the three ways from Vesancy to La Vesancière, 76 to 96 %). Ways that part for
  longer stay apart (« via Les Corbassières » at Beauregard: 37 to 53 %); where pilots went is still seen on the heat
  map of the ways up, made from every climb.

A route is drawn as its median line (``median_line``): every climb is laid along the trunk (the climb the most others
lie along, the most central of them), point by point, and the middle of the climbs that pass there is kept, so ten
climbs of one way make one line that none of them strays from much, and a way joined from higher up keeps the
walk-in from lower down. A climb joins a route when it matches any climb of it.
Nothing here changes the analysis of a track.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from typing import Optional

START_M = 500.0
NEAR_M = 150.0
SHARE = 0.8
SAME_START_M = 300.0   # starts this close: the same route when the shorter way lies along the other ...
SAME_START_SHARE = 0.7  # ... for this share of its way
INSIDE_SHARE = 0.9     # a way that lies along another for this share of it is that way, from another start
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


def on_share(a: Climb, b: Climb) -> float:
    """Share of the points of ``a`` within NEAR_M of the line of ``b``: how much of ``a`` goes along ``b``."""
    return sum(1 for p in a.pts if b.grid.near(p)) / len(a.pts)


def same_route(a: Climb, b: Climb) -> bool:
    (ax, ay), (bx, by) = a.pts[0], b.pts[0]
    start = math.hypot(ax - bx, ay - by)
    shorter, longer = (a, b) if len(a.pts) <= len(b.pts) else (b, a)
    along = on_share(shorter, longer)
    if along >= INSIDE_SHARE or (start < SAME_START_M and along >= SAME_START_SHARE):
        return True
    if start >= START_M:
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


def trunk(route: list[Climb]) -> Climb:
    """The climb the most others lie along (INSIDE_SHARE), the most central of those: a way joined from higher up
    is drawn from the lowest start."""
    if len(route) == 1:
        return route[0]
    under = {c.id: sum(1 for o in route if o is not c and on_share(o, c) >= INSIDE_SHARE) for c in route}
    most = max(under.values())
    return central([c for c in route if under[c.id] == most])


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
    """The line of a route: every climb laid along the trunk, then, point by point, the median of the climbs that
    pass there (within NEAR_M: one that starts higher up does not pull the walk-in towards its start), east and north
    apart, lightly smoothed. One climb: its own line."""
    ref = trunk(route)
    if len(route) == 1:
        return ref.line
    lat0 = ref.lat0
    others = [c.pts if c.lat0 == lat0 else resample(c.line, lat0) for c in route if c is not ref]
    laid = [ref.pts] + [_laid_along(ref.pts, pts) for pts in others]
    def here(i):
        p = ref.pts[i]
        return [l[i] for l in laid if (l[i][0] - p[0]) ** 2 + (l[i][1] - p[1]) ** 2 <= NEAR_M ** 2]
    mid = [(statistics.median(q[0] for q in pts), statistics.median(q[1] for q in pts))
           for pts in (here(i) for i in range(len(ref.pts)))]
    smooth = [mid[0]] + [((mid[i - 1][0] + mid[i][0] + mid[i + 1][0]) / 3, (mid[i - 1][1] + mid[i][1] + mid[i + 1][1]) / 3)
                         for i in range(1, len(mid) - 1)] + [mid[-1]]
    step = max(1, math.ceil(len(smooth) / LINE_POINTS))
    kept = smooth[::step] + ([smooth[-1]] if (len(smooth) - 1) % step else [])
    return _latlon(kept, lat0)


VIA_M = 400.0  # a named place this close to where a way strays most from the others names it
# what names a way best, first: a pass or a summit, a hiking signpost, a hamlet, a lake, a wood
_VIA_RANK = (("mountain_pass", None), ("natural", "saddle"), ("natural", "peak"), ("information", "guidepost"),
             ("place", None), ("water", None), ("natural", "water"), ("natural", "wood"), ("landuse", "forest"))


def via_query(lat: float, lon: float) -> str:
    """Overpass QL: the named places, signposts, passes, lakes and woods around a point (twice VIA_M: when nothing is
    that close, the nearest farther one still tells the way apart)."""
    at = f"around:{2 * VIA_M:.0f},{lat:.5f},{lon:.5f}"
    return (f'[out:json][timeout:30];(node({at})[name][~"^(natural|place|mountain_pass|information|water)$"~"."];'
            f'way({at})[name][~"^(natural|water|landuse)$"~"."];);out center tags;')


def pick_via(elements: list, lat: float, lon: float, avoid: tuple = ()) -> Optional[str]:
    """The best name for a way that strays from the others at (lat, lon), from an Overpass answer: within VIA_M the
    kind of place first (``_VIA_RANK``), then the nearest; farther (up to twice VIA_M), the nearest. Names in
    ``avoid`` (the start, the take-off) are skipped."""
    k = math.cos(math.radians(lat))
    best = None
    farther = None
    for el in elements or []:
        tags = el.get("tags") or {}
        name = re.sub(r"\s*\([^)]*\)\s*$", "", (tags.get("name") or "").strip())  # « Les Corbassières (Ferme) »
        if not name or any(name.lower() == (a or "").lower() for a in avoid):
            continue
        rank = next((i for i, (key, val) in enumerate(_VIA_RANK) if key in tags and (val is None or tags[key] == val)), None)
        if rank is None:
            continue
        c = el if "lat" in el else el.get("center") or {}
        if "lat" not in c:
            continue
        d = math.hypot((c["lon"] - lon) * 111320.0 * k, (c["lat"] - lat) * 110540.0)
        if d <= VIA_M and (best is None or (rank, d) < best[0]):
            best = ((rank, d), name)
        elif d <= 2 * VIA_M and (farther is None or d < farther[0]):
            farther = (d, name)
    return best[1] if best else farther[1] if farther else None


def stray_point(line: list, others: list[list]) -> list:
    """The point of ``line`` farthest from every other line: where this way is its own."""
    lat0 = line[0][0]
    others_pts = [resample(o, lat0) for o in others]
    pts = _xy(line, lat0)
    def gap(p):
        return min(min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in o) for o in others_pts)
    return line[max(range(len(pts)), key=lambda i: gap(pts[i]))]


def routes_of(climbs: list[Climb], via=None) -> list[dict]:
    """``[{name, start_place, line, outing_ids}]`` for one take-off. A start with one way: « From La Clusaz ». A start
    with several: each way named after a place it goes by and the others do not, « via Les Corbassières »
    (``via(lat, lon, avoid) -> name or None``, from OpenStreetMap), else « Main way » for the busiest, « Way 2 »…"""
    out = []
    for g in group(climbs):
        # a way with several starts (joined from higher up, or starts close by) is named after the most frequent
        place = Counter(c.start_place for c in g if c.start_place).most_common(1)
        place = place[0][0] if place else None
        out.append({"name": f"From {place}" if place else "From an unnamed start", "start_place": place,
                    "line": median_line(g), "outing_ids": [c.id for c in g]})
    by_place: dict = {}
    for r in out:
        by_place.setdefault(r["start_place"], []).append(r)
    for place, ways in by_place.items():
        if len(ways) < 2:
            continue
        used = set()
        for n, r in enumerate(ways, start=1):
            name = None
            if via:
                lat, lon = stray_point(r["line"], [w["line"] for w in ways if w is not r])
                try:
                    name = via(lat, lon, (place,))
                except Exception:  # OpenStreetMap could not answer: a plain name, made again at the next sync
                    name = None
            r["name"] = f"via {name}" if name and name not in used else "Main way" if n == 1 else f"Way {n}"
            used.add(name)
    return out
