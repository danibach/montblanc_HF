"""Could a ride explain a recording gap? How far the nearest road or lift station is from its two ends.

A gap that no walker could do was a ride, a lift, skis or a flight. A ride needs a road or a station: from
the summit of Mont Blanc the nearest one is more than 4 km away, a walk of an hour before any ride starts.
So for the ends of the gaps that may be a flight (``outing.flight_gap_candidates``) we ask OpenStreetMap,
through Overpass, how many roads (a 4x4 track included) and lift or train stations lie within a few radii,
and keep for each end a lower bound of the distance to the nearest one (``outing.flight_gap_verdict``).

    query = access_query(points)              # text for Overpass
    metres = parse_access(response, len(points))

The browser makes the request itself (like the terrain check); the server uses ``fetch_access``. If Overpass
cannot answer, nothing is known and the gap stays a doubt.
"""

from __future__ import annotations

from typing import Optional

ROAD = ('["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|track|'
        'living_street|road)(_link)?$"]')
RADII_M = (250, 1000, 2000, 3000, 4000, 5000)


def access_query(points: list[tuple[float, float]]) -> Optional[str]:
    """The Overpass QL text: for each point and each radius, one count of the roads and stations around it."""
    if not points:
        return None
    far = RADII_M[-1]
    out = ["[out:json][timeout:90];"]
    for lat, lon in points:
        at = f"{lat:.5f},{lon:.5f}"
        out.append(f"way(around:{far},{at}){ROAD}->.r;")
        out.append(f'(node(around:{far},{at})["aerialway"="station"];node(around:{far},{at})["railway"~"^(station|halt)$"];)->.l;')
        for r in RADII_M:
            out.append(f"(way.r(around:{r},{at});node.l(around:{r},{at}););out count;")
    return "\n".join(out)


def parse_access(response, expected: int) -> Optional[list[float]]:
    """For each point, the distance (metres) within which there is surely no road nor station: the radius
    before the first one holding some (0 when the nearest radius already does, the widest when none does).
    None when the answer is not usable."""
    try:
        counts = [int(e["tags"]["total"]) for e in response["elements"] if e.get("type") == "count"]
    except (KeyError, TypeError, ValueError):
        return None
    if len(counts) != expected * len(RADII_M):
        return None
    out: list[float] = []
    for k in range(expected):
        row = counts[k * len(RADII_M):(k + 1) * len(RADII_M)]
        first = next((n for n, c in enumerate(row) if c > 0), None)
        out.append(float(RADII_M[-1] if first is None else (RADII_M[first - 1] if first else 0)))
    return out


def fetch_access(points: list[tuple[float, float]]) -> Optional[list[float]]:
    """Server side: ask Overpass. None if it cannot answer."""
    from .places import fetch_overpass

    query = access_query(points)
    if not query:
        return None
    try:
        return parse_access(fetch_overpass(query, attempts=2, timeout=90.0), len(points))
    except OSError:
        return None
