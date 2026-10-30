"""Routes: the climbs to one take-off that follow the same way up, gathered into one route.

The rules of 23 and 25 October 2026 (starts under 500 m apart, 80 % of the way within 150 m; the same path stays
within 15 to 110 m on the live climbs, different paths stray 400 m or more) are replaced by this one:

Since 29 October 2026 (Sarah, from a prototype on the live climbs; see Notion « Points ouverts et idées »), a trace
and an itinerary are two things. The trace of an outing is kept whole (its numbers, the heat map of the ways up, even
when it leaves from home). The itinerary is the line the map proposes, and it never starts at a private place:
* each climb counts from where it first joins the public network for good (``Access.junction``: the paths, tracks
  and streets of OpenStreetMap; private ways and driveways left out), never from its first fix;
* climbs that join one another (one goes along the other for ``INSIDE_SHARE`` of the rest of its way, that rest
  being ``JOINED_MIN`` of its way at least) are one itinerary; the other ways pilots took stay on the heat map;
* the itinerary starts at the most used start (starts within ``STARTS_M`` are one), the lowest on a tie (the one
  with the longest way up), and at a parking when one is within ``PARKING_M`` of it;
* its line is the median of its climbs laid along the climb of that start with the longest way up.
Without the public network (OpenStreetMap did not answer), the climbs count from their first fix: the sync then
keeps the take-off's itineraries as they were rather than make them so.

Nothing here changes the analysis of a track.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from typing import Optional

NEAR_M = 150.0
INSIDE_SHARE = 0.9     # a climb that goes along another for this share of the rest of its way joins it ...
JOINED_MIN = 0.5       # ... when that rest is at least this share of its way: every climb meets the others at the
                       # take-off, two ways that only meet near the top stay two (Tête Pelouse: 13 to 16 % shared)
STARTS_M = 150.0       # starts this close are one start
PARKING_M = 100.0      # a parking this close to the start: the itinerary starts there
ON_NETWORK_M = 35.0    # a fix this close to a public way is on the public network ...
NETWORK_SHARE = 0.85   # ... and a climb has joined it when this share of its fixes over the next JOIN_M is
JOIN_M = 300.0
# the start names pilots use, where the map's differ (Sarah, 29 October 2026: Les Esserts is the landing field of
# Perroix); each one only within 2 km of the given point
PLACE_NAMES = {("Les Esserts", 45.852, 6.212): "Perroix"}
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


def joins(a: Climb, b: Climb) -> bool:
    """Whether ``a`` joins ``b``: from some fix on, INSIDE_SHARE of the rest of ``a`` is within NEAR_M of ``b``, and
    that rest is JOINED_MIN of ``a`` at least."""
    near = [b.grid.near(p) for p in a.pts]
    rest = 0
    for i in range(len(near) - 1, -1, -1):
        rest += near[i]
        if near[i] and rest / (len(near) - i) >= INSIDE_SHARE and (len(near) - i) >= max(2, JOINED_MIN * len(near)):
            return True
    return False


def same_route(a: Climb, b: Climb) -> bool:
    return joins(a, b) or joins(b, a)


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


def _place(c: Climb) -> Optional[str]:
    """The start's name as pilots say it (PLACE_NAMES)."""
    if not c.start_place:
        return None
    lat, lon = c.line[0]
    for (name, plat, plon), said in PLACE_NAMES.items():
        if name == c.start_place and math.hypot((lon - plon) * 111320.0 * math.cos(math.radians(plat)), (lat - plat) * 110540.0) <= 2000:
            return said
    return c.start_place


def starts(route: list[Climb]) -> list[list[Climb]]:
    """The climbs of a route by start (starts within STARTS_M are one), the most used first; on a tie, the one with
    the longest way up (the lowest)."""
    out: list[list[Climb]] = []
    for c in sorted(route, key=lambda c: -len(c.pts)):
        for s in out:
            if math.hypot(c.pts[0][0] - s[0].pts[0][0], c.pts[0][1] - s[0].pts[0][1]) <= STARTS_M:
                s.append(c)
                break
        else:
            out.append([c])
    return sorted(out, key=lambda s: (-len(s), -max(len(c.pts) for c in s)))


def lead(route: list[Climb]) -> Climb:
    """The climb that draws the route: the one with the longest way up from the most used start."""
    return max(starts(route)[0], key=lambda c: len(c.pts))


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
    """The line of a route: every climb laid along the lead climb, then, point by point, the median of the climbs that
    pass there (within NEAR_M: one that starts higher up does not pull the walk-in towards its start), east and north
    apart, lightly smoothed. One climb: its own line."""
    ref = lead(route)
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


_PUBLIC_HIGHWAYS = ("path", "footway", "track", "steps", "bridleway", "pedestrian", "living_street", "residential",
                    "unclassified", "service", "tertiary", "secondary")


def access_query(south: float, west: float, north: float, east: float) -> str:
    """Overpass QL: the public ways and the parkings of a box."""
    box = f"{south:.5f},{west:.5f},{north:.5f},{east:.5f}"
    return (f'[out:json][timeout:90];(way["highway"~"^({"|".join(_PUBLIC_HIGHWAYS)})$"]({box});'
            f'nwr["amenity"="parking"]({box}););out geom tags;')


class Access:
    """The public network and the parkings around a take-off, from an Overpass answer (``access_query``)."""

    def __init__(self, elements: list, lat0: float):
        self.lat0 = lat0
        self.cells: dict[tuple[int, int], list] = {}
        self.parkings: list[tuple[float, float]] = []
        for el in elements or []:
            tags = el.get("tags") or {}
            if tags.get("amenity") == "parking":
                if tags.get("access") in ("private", "customers", "no"):
                    continue
                c = el if "lat" in el else el.get("center") or {}
                if "lat" in c:
                    self.parkings += _xy([[c["lat"], c["lon"]]], lat0)
                elif el.get("geometry"):
                    g = _xy([[p["lat"], p["lon"]] for p in el["geometry"]], lat0)
                    self.parkings.append((sum(p[0] for p in g) / len(g), sum(p[1] for p in g) / len(g)))
            elif tags.get("highway") in _PUBLIC_HIGHWAYS and el.get("geometry"):
                if tags.get("access") in ("private", "no") or tags.get("foot") == "no" or \
                        tags.get("service") in ("driveway", "parking_aisle"):
                    continue
                g = _xy([[p["lat"], p["lon"]] for p in el["geometry"]], lat0)
                for s in zip(g, g[1:]):
                    for cell in {(int(p[0] // ON_NETWORK_M), int(p[1] // ON_NETWORK_M)) for p in s}:
                        self.cells.setdefault(cell, []).append(s)

    def on_network(self, p: tuple[float, float]) -> bool:
        ci, cj = int(p[0] // ON_NETWORK_M), int(p[1] // ON_NETWORK_M)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for a, b in self.cells.get((ci + di, cj + dj), ()):
                    vx, vy = b[0] - a[0], b[1] - a[1]
                    ln = vx * vx + vy * vy
                    k = 0 if ln == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / ln))
                    if math.hypot(p[0] - a[0] - k * vx, p[1] - a[1] - k * vy) <= ON_NETWORK_M:
                        return True
        return False

    def junction(self, line: list) -> int:
        """The index of ``line`` where the climb first joins the public network for good: a fix on it, with
        NETWORK_SHARE of the fixes of the next JOIN_M on it too; 0 when it never does (a climb off the paths keeps its
        own start). Only the way in from a private place is cut: a climb that leaves the paths higher up (snow, the
        last slope to a summit) keeps the rest of its way (Sarah, 30 October 2026: the « for good » of the whole rest
        cut La Tournette's itinerary to its last 130 m)."""
        pts = _xy(line, self.lat0)
        on = [self.on_network(p) for p in pts]
        along = [0.0]
        for a, b in zip(pts, pts[1:]):
            along.append(along[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        for i in range(len(on) - 1):
            if not on[i]:
                continue
            window = [on[k] for k in range(i, len(on)) if along[k] - along[i] <= JOIN_M]
            if sum(window) / len(window) >= NETWORK_SHARE:
                return i
        return 0

    def parking_near(self, point: list) -> Optional[list]:
        """The parking within PARKING_M of ``point`` ([lat, lon]), the nearest, or None."""
        p = _xy([point], self.lat0)[0]
        near = [q for q in self.parkings if math.hypot(q[0] - p[0], q[1] - p[1]) <= PARKING_M]
        if not near:
            return None
        return _latlon([min(near, key=lambda q: math.hypot(q[0] - p[0], q[1] - p[1]))], self.lat0)[0]


def routes_of(climbs: list[Climb], via=None, access: Optional[Access] = None) -> list[dict]:
    """``[{name, start_place, line, outing_ids}]`` for one take-off. A start with one way: « From La Clusaz ». A start
    with several: each way named after a place it goes by and the others do not, « via Les Corbassières »
    (``via(lat, lon, avoid) -> name or None``, from OpenStreetMap), else « Main way » for the busiest, « Way 2 »…
    With ``access``, each climb counts from where it joins the public network and an itinerary starts at a parking
    within PARKING_M of its start."""
    if access is not None:
        public = []
        for c in climbs:
            j = access.junction(c.line)
            public.append(Climb(c.id, c.line[j:], c.start_place, c.lat0) if j else c)
        climbs = public
    out = []
    for g in group(climbs):
        names = [_place(c) for c in starts(g)[0] if _place(c)]
        place = Counter(names).most_common(1)[0][0] if names else None
        line = median_line(g)
        parking = access.parking_near(line[0]) if access is not None else None
        if parking:
            line = [parking] + line
        out.append({"name": f"From {place}" if place else "From an unnamed start", "start_place": place,
                    "line": line, "outing_ids": [c.id for c in g]})
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
