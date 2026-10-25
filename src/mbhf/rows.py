"""Turn an analysis (and the OpenStreetMap names) into the columns of the ``outings`` table."""

from __future__ import annotations

from typing import Optional

from .titles import outing_title

GENERIC_TITLE = "Hike & Fly outing"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fallback_title(date: Optional[str], summit_alt: Optional[float]) -> str:
    """A title when OpenStreetMap gave no name: "Hike & Fly · 29 Sep 2021 · 1,606 m"."""
    parts = ["Hike & Fly"]
    try:
        y, m, d = str(date)[:10].split("-")
        parts.append(f"{int(d)} {_MONTHS[int(m) - 1]} {int(y)}")
    except (ValueError, IndexError):
        pass
    if summit_alt is not None:
        parts.append(f"{round(summit_alt):,} m")
    return " · ".join(parts)


def has_names(places: Optional[dict]) -> bool:
    """True when the lookup gave at least one usable name or the country."""
    p = places or {}
    return bool(p.get("country") or p.get("start_place") or p.get("summit") or p.get("takeoff") or p.get("commune"))


def place_title(places: Optional[dict], date: Optional[str], summit_alt: Optional[float]) -> str:
    """« {take-off} from {start} » (src/mbhf/titles.py) from the OpenStreetMap names; the server job then gives the
    name of the take-off of the register (scripts/sync_sites.py)."""
    p = places or {}
    takeoff = p.get("takeoff") or {}
    site = takeoff.get("name") if takeoff.get("kind") == "site" else None  # a mapped paragliding take-off, as pilots call it
    main = site or (p.get("summit") or {}).get("name")
    return (outing_title(main, p.get("start_place"), p.get("commune")) or p.get("start_place")
            or fallback_title(date, summit_alt))


def outing_row(result: dict, places: Optional[dict]) -> dict:
    """The values the analysis job writes for one outing. ``places`` is None when OSM was unreachable."""
    o = result["outing"]
    places = places or {}
    country = places.get("country") or {}
    summit = places.get("summit") or {}
    takeoff = places.get("takeoff") or {}

    def pick(point: Optional[dict], key: str):
        return point.get(key) if point else None

    title = place_title(places, o["date"], pick(o["summit"], "alt"))
    return {
        "analysed_at": None,  # set by the job (server clock)
        "engine_version": result["engine"]["version"],
        "score_version": o["score_version"],
        "title": title,
        "outing_date": o["date"],
        "started_at": o["started_at"],
        "duration_s": o["duration_s"],
        "country_code": country.get("code"),
        "country_name": country.get("name"),
        "start_lat": pick(o["start"], "lat"), "start_lon": pick(o["start"], "lon"), "start_alt": pick(o["start"], "alt"),
        "start_place": places.get("start_place"),
        "start_commune": places.get("commune"),
        "summit_name": summit.get("name"),
        "summit_osm_id": summit.get("osm_id"),
        "summit_lat": pick(o["summit"], "lat"), "summit_lon": pick(o["summit"], "lon"), "summit_alt": pick(o["summit"], "alt"),
        "takeoff_name": takeoff.get("name"),
        "takeoff_lat": pick(o["takeoff"], "lat"), "takeoff_lon": pick(o["takeoff"], "lon"), "takeoff_alt": pick(o["takeoff"], "alt"),
        "landing_lat": pick(o["landing"], "lat"), "landing_lon": pick(o["landing"], "lon"), "landing_alt": pick(o["landing"], "alt"),
        "dplus_m": o["dplus_m"],
        "dminus_m": o["dminus_m"],
        "walk_km": o["walk_km"],
        "flight_free_km": o["flight_free_km"],
        "flight_path_km": o["flight_path_km"],
        "score": o["score"],
        "flights": [
            {k: v for k, v in f.items() if k not in ("i_start", "i_end")} for f in o["flights"]
        ],
        "trace": result["trace"],
        "warnings": o["warnings"],
        "places_pending": not has_names(places),
    }
