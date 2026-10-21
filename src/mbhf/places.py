"""Put names on an outing's places using OpenStreetMap, through the Overpass API.

Two steps, so that the same choice logic runs in the browser (which does its own fetch) and on the
server (which uses ``fetch_overpass``):

    query = overpass_query(outing)              # text to send to Overpass
    places = resolve_places(outing, response)   # the answer, turned into names

Nothing here needs a key. The names are whatever OpenStreetMap holds: when it holds nothing nearby,
the field stays empty and the outing is shown without that name.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .geo import haversine_m

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "mbhf-hikeandfly/0.2 (https://github.com/danibach/montblanc_HF)"

SUMMIT_RADIUS_M = 500
TAKEOFF_RADIUS_M = 600
PLACE_RADIUS_M = 3000
ELE_TOLERANCE_M = 400  # track altitudes drift by 100 m or more: only absurd differences rule a peak out
ELE_WEIGHT = 0.5  # metres of height difference that count as one metre of distance
SITE_RADIUS_M = 400  # a mapped paragliding take-off (sport=free_flying) near the take-off point
PLACE_TYPES = "hamlet|village|town|city|isolated_dwelling|locality"


def _around(radius: int, p: dict) -> str:
    return f"around:{radius},{p['lat']:.5f},{p['lon']:.5f}"


def overpass_query(outing: dict) -> Optional[str]:
    """The Overpass QL text for this outing, or None when it has no start point."""
    start, summit, takeoff = outing.get("start"), outing.get("summit"), outing.get("takeoff")
    if not start:
        return None
    parts = [
        f"is_in({start['lat']:.5f},{start['lon']:.5f})->.a;",
        "(",
        '  rel(pivot.a)["boundary"="administrative"]["admin_level"~"^(2|8)$"];',
        f'  node({_around(PLACE_RADIUS_M, start)})["place"~"^({PLACE_TYPES})$"]["name"];',
    ]
    for p in (summit, takeoff):
        if p:
            parts.append(f'  node({_around(SUMMIT_RADIUS_M if p is summit else TAKEOFF_RADIUS_M, p)})["natural"~"^(peak|saddle)$"]["name"];')
    if takeoff:
        parts.append(f'  node({_around(PLACE_RADIUS_M, takeoff)})["place"~"^({PLACE_TYPES})$"]["name"];')
        parts.append(f'  nwr({_around(SITE_RADIUS_M, takeoff)})["sport"="free_flying"]["name"];')
    parts += [");", "out tags center;"]
    return "[out:json][timeout:25];\n" + "\n".join(parts)


def _name(tags: dict) -> Optional[str]:
    return tags.get("name") or tags.get("name:en") or None


def _ele(tags: dict) -> Optional[float]:
    raw = str(tags.get("ele", "")).replace(",", ".").split(" ")[0].replace("m", "")
    try:
        return float(raw)
    except ValueError:
        return None


_SITE_PREFIX = re.compile(
    r"^\s*(?:d[ée]collage|take-?off|d[ée]part)\s+(?:(?:de\s+)?(?:parapente|deltaplane|vol\s+libre)\s*)?(?:(?:FFVL|ffvl)\s*)?"
    r"(?:de\s+la\s+|de\s+l['’]|du\s+|des\s+|de\s+|d['’]|\s)?",
    re.IGNORECASE,
)


def site_name(raw: str) -> Optional[str]:
    """"Décollage parapente FFVL de Planfait" -> "Planfait". None for a landing field."""
    if re.search(r"atterriss|landing", raw, re.IGNORECASE):
        return None
    name = _SITE_PREFIX.sub("", raw).strip(" -–·")
    if not name:
        return None
    return name[0].upper() + name[1:]


def _sites(elements: list) -> list[dict]:
    """Paragliding take-offs (nodes, or ways and relations with a centre), as ``{"id", "lat", "lon", "name"}``."""
    out = []
    for e in elements:
        tags = e.get("tags", {})
        if tags.get("sport") != "free_flying" or not _name(tags):
            continue
        c = e if "lat" in e else e.get("center") or {}
        name = site_name(_name(tags))
        if name and "lat" in c:
            out.append({"id": e.get("id"), "lat": c["lat"], "lon": c["lon"], "tags": {"name": name}})
    return out


def _nodes(elements: list, key: str, values: tuple[str, ...]) -> list[dict]:
    return [
        e for e in elements
        if e.get("type") == "node" and "lat" in e and e.get("tags", {}).get(key) in values and _name(e["tags"])
    ]


def _nearest(nodes: list[dict], p: dict, radius: int, alt: Optional[float] = None) -> Optional[dict]:
    best, best_score = None, None
    for e in nodes:
        d = haversine_m(p["lat"], p["lon"], e["lat"], e["lon"])
        if d > radius:
            continue
        score = d
        ele = _ele(e["tags"])
        if alt is not None and ele is not None:
            if abs(ele - alt) > ELE_TOLERANCE_M:
                continue
            score += ELE_WEIGHT * abs(ele - alt)
        if e["tags"].get("natural") == "saddle":
            score += 50  # a summit is a better match than a col next to it
        if best_score is None or score < best_score:
            best, best_score = e, score
    return best


def resolve_places(outing: dict, response: dict) -> dict:
    """Turn the Overpass answer into names. Missing information stays None."""
    elements = response.get("elements", []) if isinstance(response, dict) else []
    out: dict = {"country": None, "commune": None, "start_place": None, "summit": None, "takeoff": None}

    for e in elements:
        if e.get("type") != "relation":
            continue
        tags = e.get("tags", {})
        level = str(tags.get("admin_level", ""))
        if level == "2" and out["country"] is None:
            code = tags.get("ISO3166-1:alpha2") or tags.get("ISO3166-1")
            if code:
                out["country"] = {"code": str(code).upper(), "name": tags.get("name:en") or _name(tags)}
        elif level == "8" and out["commune"] is None:
            out["commune"] = _name(tags)

    places = _nodes(elements, "place", tuple(PLACE_TYPES.split("|")))
    peaks = _nodes(elements, "natural", ("peak", "saddle"))

    start = outing.get("start")
    if start:
        near = _nearest(places, start, PLACE_RADIUS_M)
        out["start_place"] = _name(near["tags"]) if near else None

    summit = outing.get("summit")
    if summit:
        peak = _nearest(peaks, summit, SUMMIT_RADIUS_M, summit.get("alt"))
        if peak:
            out["summit"] = {"name": _name(peak["tags"]), "osm_id": peak["id"], "ele": _ele(peak["tags"])}

    takeoff = outing.get("takeoff")
    if takeoff:
        site = _nearest(_sites(elements), takeoff, SITE_RADIUS_M)
        peak = _nearest(peaks, takeoff, TAKEOFF_RADIUS_M, takeoff.get("alt"))
        if site:
            out["takeoff"] = {"name": site["tags"]["name"], "osm_id": site["id"], "kind": "site"}
        elif peak:
            out["takeoff"] = {"name": _name(peak["tags"]), "osm_id": peak["id"], "kind": "peak"}
        else:
            near = _nearest(places, takeoff, PLACE_RADIUS_M)
            if near:
                out["takeoff"] = {"name": _name(near["tags"]), "osm_id": near["id"], "kind": "place"}
    return out


def fetch_overpass(query: str, urls: tuple[str, ...] = OVERPASS_URLS, attempts: int = 2, timeout: float = 40.0) -> dict:
    """POST the query to the Overpass mirrors in turn; raise OSError when none answers."""
    body = urllib.parse.urlencode({"data": query}).encode()
    last: Optional[Exception] = None
    for attempt in range(attempts):
        for url in urls:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last = exc
        time.sleep(3 * (attempt + 1))
    raise OSError(f"Overpass did not answer: {last}")
