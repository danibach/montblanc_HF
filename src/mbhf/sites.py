"""The take-off register: official take-offs (FFVL, OpenStreetMap) and the rule that ties an outing to one.

Sources, both open:
* FFVL, « Terrains de pratique », data.gouv.fr, Licence Ouverte 2.0 (Etalab): France, updated daily. Kept: the
  terrains used as a take-off.
* OpenStreetMap, ``sport=free_flying`` (or ``free_flying:site=takeoff``) with a name, ODbL: anywhere. An OSM take-off
  closer than ``AUTO_M`` to an FFVL one is the same place and is left out (the federation's name wins).

An outing's take-off point is tied to the nearest known take-off (brief of the map, section 4):
* closer than ``SAME_SPOT_M``: the same spot, tied at once (``auto``) whatever the altitudes say (an official
  altitude can be a nominal one: the FFVL gives 4 800 m for the Mont Blanc), and an official take-off wins over a
  provisional one even when the provisional one is closer;
* closer than ``AUTO_M``: tied at once (``auto``);
* between ``AUTO_M`` and ``CONFIRM_M``: tied, to be confirmed by hand (``to_confirm``);
* farther, or more than ``MAX_DALT_M`` higher or lower (two take-offs on either side of a ridge): a new
  provisional take-off is made at the outing's point, named as the outing's take-off is today (OSM name of the
  take-off, else summit, else start). Later outings near it are tied to it, so a wild summit gets its take-off.
  The point of a provisional take-off is then moved to the median of the take-off points of its outings
  (``centre_of``), so it stops depending on whichever outing came first. Official take-offs never move.
Nothing here changes the analysis of a track.
"""

from __future__ import annotations

import math
import re
import statistics
from typing import Iterable, Optional

SAME_SPOT_M = 50.0
AUTO_M = 100.0
CONFIRM_M = 200.0
MAX_DALT_M = 100.0
SOURCE_RANK = {"ffvl": 0, "osm": 1, "provisional": 2}  # the first wins when two are as close


def metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = math.pi / 180
    a = (math.sin((lat2 - lat1) * r / 2) ** 2
         + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin((lon2 - lon1) * r / 2) ** 2)
    return 12742000 * math.asin(math.sqrt(a))


_SMALL = {"de", "des", "du", "la", "le", "les", "et", "sur", "sous", "en", "au", "aux", "d", "l"}


def pretty_name(name: str) -> str:
    """FFVL names are in capitals: « LA CLUSAZ - AIGUILLE DES CALVAIRES (ETE) » -> « La Clusaz - Aiguille des Calvaires (Ete) »."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name or name != name.upper():
        return name
    words = re.split(r"([\s\-'’()/]+)", name.lower())
    out = []
    for i, w in enumerate(words):
        if not w or not w[0].isalpha():
            out.append(w)
        elif i > 0 and w in _SMALL:
            out.append(w)
        else:
            out.append(w[0].upper() + w[1:])
    return "".join(out)


def _number(value) -> Optional[float]:
    try:
        return float(str(value).replace(",", ".").split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def ffvl_takeoffs(terrains: Iterable[dict]) -> list[dict]:
    """The take-offs of the FFVL open-data file (terrains.json)."""
    out = []
    for t in terrains:
        if "décollage" not in (t.get("flying_functions_text") or "") or t.get("latitude") is None:
            continue
        out.append({
            "source": "ffvl", "source_id": str(t["suid"]), "name": pretty_name(t.get("toponym") or ""),
            "lat": float(t["latitude"]), "lon": float(t["longitude"]), "alt": _number(t.get("altitude")),
            "country_code": "FR", "wind_ok": t.get("wind_orientations_ok") or None,
            "hike_and_fly": (t.get("hike_and_fly_description") or "").strip() or None,
            "ffvl_status": t.get("status") or None,
        })
    return out


def _is_landing(tags: dict) -> bool:
    text = " ".join(str(tags.get(k, "")) for k in ("free_flying:site", "name", "description")).lower()
    return tags.get("free_flying:site") == "landing" or any(w in text for w in ("atterrissage", "landing", "landeplatz"))


def osm_takeoffs(elements: Iterable[dict]) -> list[dict]:
    """Named paragliding take-offs from an Overpass answer (``out center tags``)."""
    out = []
    for el in elements:
        tags = el.get("tags") or {}
        if not tags.get("name") or _is_landing(tags):
            continue
        if tags.get("free_flying:site") != "takeoff" and tags.get("sport") != "free_flying":
            continue
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None:
            continue
        out.append({
            "source": "osm", "source_id": f"{el.get('type', 'node')}/{el['id']}", "name": tags["name"].strip(),
            "lat": float(lat), "lon": float(lon), "alt": _number(tags.get("ele")),
            "country_code": None, "wind_ok": tags.get("free_flying:wind_direction") or None,
            "hike_and_fly": None, "ffvl_status": None,
        })
    return out


def without_doubles(official: list[dict], others: list[dict], within: float = AUTO_M) -> list[dict]:
    """``others`` minus the ones closer than ``within`` to an ``official`` take-off."""
    index = SiteIndex(official)
    return [s for s in others if not index.near(s["lat"], s["lon"], within)]


class SiteIndex:
    """Take-offs in cells of about 1 km, to look only at the ones nearby."""

    def __init__(self, sites: Iterable[dict] = ()):
        self.cells: dict[tuple[int, int], list[dict]] = {}
        for s in sites:
            self.add(s)

    @staticmethod
    def _cell(lat: float, lon: float) -> tuple[int, int]:
        return math.floor(lat * 100), math.floor(lon * 100)

    def add(self, site: dict) -> None:
        self.cells.setdefault(self._cell(site["lat"], site["lon"]), []).append(site)

    def near(self, lat: float, lon: float, within: float) -> list[tuple[float, dict]]:
        ci, cj = self._cell(lat, lon)
        found = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for s in self.cells.get((ci + di, cj + dj), []):
                    d = metres(lat, lon, s["lat"], s["lon"])
                    if d <= within:
                        found.append((d, s))
        return sorted(found, key=lambda x: (x[0], SOURCE_RANK.get(x[1]["source"], 9)))


def attach(lat: float, lon: float, alt: Optional[float], index: SiteIndex) -> tuple[Optional[dict], Optional[float], str]:
    """The take-off an outing's take-off point belongs to: (site, distance in metres, status), where status is
    ``auto``, ``to_confirm`` or ``provisional`` (no site close enough: make one)."""
    near = index.near(lat, lon, CONFIRM_M)
    same = [x for x in near if x[0] <= SAME_SPOT_M]
    if same:  # the same spot: no altitude test (two take-offs on either side of a ridge are never this close)
        d, s = min(same, key=lambda x: (SOURCE_RANK.get(x[1]["source"], 9), x[0]))
        return s, round(d), "auto"
    for d, s in near:
        if alt is not None and s.get("alt") is not None and abs(alt - s["alt"]) > MAX_DALT_M:
            continue  # same spot on the map, but another side of the mountain
        return s, round(d), ("auto" if d <= AUTO_M else "to_confirm")
    return None, None, "provisional"


def provisional_site(outing: dict) -> dict:
    """A take-off made from an outing that no known take-off is close to."""
    name = outing.get("takeoff_name") or outing.get("summit_name") or outing.get("title") or "Take-off"
    if outing.get("takeoff_alt") is not None and name == "Take-off":
        name = f"Take-off · {round(outing['takeoff_alt']):,} m"
    return {
        "source": "provisional", "source_id": str(outing["id"]), "name": name,
        "lat": float(outing["takeoff_lat"]), "lon": float(outing["takeoff_lon"]),
        "alt": outing.get("takeoff_alt"), "country_code": outing.get("country_code"),
        "wind_ok": None, "hike_and_fly": None, "ffvl_status": None,
    }


def centre_of(points: Iterable[tuple[float, float, Optional[float]]]) -> tuple[float, float, Optional[float]]:
    """The middle of some take-off points (lat, lon, alt): the median of each, so that one outing that took off
    far from the others does not pull the take-off away. The altitude is None when none of them has one."""
    pts = list(points)
    alts = [a for _, _, a in pts if a is not None]
    return (statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts),
            statistics.median(alts) if alts else None)


def overpass_query(south: float, west: float, north: float, east: float) -> str:
    """Named paragliding sites in a box (nodes, and ways or areas by their centre)."""
    box = f"({south:.4f},{west:.4f},{north:.4f},{east:.4f})"
    return (f'[out:json][timeout:120];(nwr["sport"="free_flying"]["name"]{box};'
            f'nwr["free_flying:site"="takeoff"]["name"]{box};);out center tags;')
