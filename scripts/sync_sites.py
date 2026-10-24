"""Fill the take-off register and tie every published outing to its take-off.

    SUPABASE_URL=...  SUPABASE_SERVICE_KEY=...  python scripts/sync_sites.py [--dry-run]

Run by GitHub Actions (.github/workflows/sites.yml) once a week and when asked. Steps:
1. the FFVL take-offs, from today's open-data file on data.gouv.fr (Licence Ouverte 2.0);
2. the named OpenStreetMap paragliding take-offs (ODbL) around the outings, minus those next to an FFVL one;
3. both written into ``takeoff_sites`` (updated in place: the ids stay);
4. each published outing tied by the rule of src/mbhf/sites.py (auto under 100 m, to confirm up to 200 m, else a
   provisional take-off made from it); an outing tied by hand (``manual``) is left alone;
5. provisional take-offs no outing uses any more (an official one turned up next to them) are removed;
6. the routes of every take-off are made again from the climbs (src/mbhf/routes.py) and the outings tied to them.
``--dry-run`` reads everything and prints what it would do, without writing.
New outings are tied when the server checks them (process_pending.py), with the take-offs already in the register.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from mbhf.sites import (SiteIndex, attach, ffvl_takeoffs, osm_takeoffs, overpass_query,  # noqa: E402
                        provisional_site, without_doubles)

FFVL_DATASETS = "https://www.data.gouv.fr/api/1/organizations/federation-francaise-de-vol-libre/datasets/?page_size=50"
# the main Overpass server is often busy (502): public mirrors are tried in turn
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                 "https://overpass.kumi.systems/api/interpreter")
OUTING_COLUMNS = "id,title,takeoff_name,summit_name,takeoff_lat,takeoff_lon,takeoff_alt,country_code,takeoff_site_id,takeoff_site_status,takeoff_site_m"
SITE_COLUMNS = ("source", "source_id", "name", "lat", "lon", "alt", "country_code", "wind_ok", "hike_and_fly", "ffvl_status")


def get_json(url: str, data: bytes | None = None, timeout: int = 120):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "hf-tracks (github.com/danibach/montblanc_HF)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def ffvl_file() -> list:
    """Today's « Terrains de pratique de la FFVL » (the address of the file changes with each daily update)."""
    for d in get_json(FFVL_DATASETS)["data"]:
        if d["slug"].startswith("terrains-de-pratique"):
            return get_json(d["resources"][0]["url"])
    raise RuntimeError("FFVL take-off file not found on data.gouv.fr")


def boxes(points: list[tuple[float, float]], margin: float = 0.2) -> list[tuple[float, float, float, float]]:
    """Boxes of about 1 degree around the outings, so that Overpass is asked only where people fly."""
    cells = {(int(lat // 1), int(lon // 1)) for lat, lon in points}
    out = []
    for ci, cj in sorted(cells):
        inside = [(la, lo) for la, lo in points if int(la // 1) == ci and int(lo // 1) == cj]
        out.append((min(p[0] for p in inside) - margin, min(p[1] for p in inside) - margin,
                    max(p[0] for p in inside) + margin, max(p[1] for p in inside) + margin))
    return out


def osm_around(points: list[tuple[float, float]]) -> list[dict] | None:
    """Named OSM take-offs around the outings, or None when Overpass could not answer (the sync goes on without)."""
    found = []
    for box in boxes(points):
        query = urllib.parse.urlencode({"data": overpass_query(*box)}).encode()
        for attempt, url in enumerate(OVERPASS_URLS * 2):
            try:
                found += osm_takeoffs(get_json(url, query, timeout=180).get("elements", []))
                break
            except Exception as exc:  # busy: the next server, and a longer pause once each has failed
                print(f"  Overpass {url.split('/')[2]} {box}: {exc}")
                time.sleep(5 if attempt < len(OVERPASS_URLS) - 1 else 30)
        else:
            return None
        time.sleep(2)
    unique = {s["source_id"]: s for s in found}
    return list(unique.values())


class Register:
    """The take-off register in Supabase (service key)."""

    def __init__(self, api, dry_run: bool = False):
        self.api, self.dry = api, dry_run
        self.fake_id = -1

    def select(self, table: str, query: str) -> list:
        rows, offset = [], 0
        while True:
            _, raw = self.api.request("GET", f"/rest/v1/{table}?{query}&limit=1000&offset={offset}")
            page = json.loads(raw)
            rows += page
            if len(page) < 1000:
                return rows
            offset += 1000

    def upsert(self, sites: list[dict]) -> list[dict]:
        """Write the take-offs (same source and source id: updated in place) and return them with their ids."""
        if self.dry:
            out = []
            for s in sites:
                out.append({**s, "id": self.fake_id})
                self.fake_id -= 1
            return out
        out = []
        for i in range(0, len(sites), 500):
            chunk = [{k: s.get(k) for k in SITE_COLUMNS} for s in sites[i:i + 500]]
            _, raw = self.api.request("POST", "/rest/v1/takeoff_sites?on_conflict=source,source_id", chunk,
                                      extra={"Prefer": "resolution=merge-duplicates,return=representation"})
            out += json.loads(raw)
        return out

    def tie(self, outing_id: str, site_id: int, status: str, metres) -> None:
        if not self.dry:
            self.api.patch(outing_id, {"takeoff_site_id": site_id, "takeoff_site_status": status, "takeoff_site_m": metres})

    def delete_sites(self, ids: list[int]) -> None:
        if ids and not self.dry:
            for i in range(0, len(ids), 100):
                self.api.request("DELETE", f"/rest/v1/takeoff_sites?id=in.({','.join(map(str, ids[i:i + 100]))})")


def tie_outing(outing: dict, index: SiteIndex, register: Register) -> tuple[str, dict]:
    """Tie one outing (making a provisional take-off when none is close); returns (status, site)."""
    site, metres, status = attach(outing["takeoff_lat"], outing["takeoff_lon"], outing.get("takeoff_alt"), index)
    if site is None:
        site = register.upsert([provisional_site(outing)])[0]
        index.add(site)
        metres = 0
    if (outing.get("takeoff_site_id"), outing.get("takeoff_site_status")) != (site["id"], status):
        register.tie(outing["id"], site["id"], status, metres)
    return status, site


def sync(api, dry_run: bool = False) -> None:
    register = Register(api, dry_run)
    outings = register.select("outings", f"select={OUTING_COLUMNS}&status=eq.published&takeoff_lat=not.is.null&order=created_at.asc")
    print(f"published outings with a take-off: {len(outings)}")

    ffvl = ffvl_takeoffs(ffvl_file())
    print(f"FFVL take-offs: {len(ffvl)}")
    osm = osm_around([(o["takeoff_lat"], o["takeoff_lon"]) for o in outings]) if outings else []
    if osm is None:
        print("OpenStreetMap unavailable: kept as they are this time")
        osm = []
    osm = without_doubles(ffvl, osm)
    print(f"OpenStreetMap take-offs (not next to an FFVL one): {len(osm)}")

    official = register.upsert(ffvl + osm)
    provisional = register.select("takeoff_sites", "select=*&source=eq.provisional") if not dry_run else []
    index = SiteIndex(official)
    for s in provisional:
        index.add(s)

    counts = {"auto": 0, "to_confirm": 0, "provisional": 0, "manual": 0}
    used = set()
    for o in outings:
        if o.get("takeoff_site_status") == "manual":
            counts["manual"] += 1
            used.add(o.get("takeoff_site_id"))
            continue
        status, site = tie_outing(o, index, register)
        counts[status] += 1
        used.add(site["id"])
    print("outings tied: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    unused = [s["id"] for s in provisional if s["id"] not in used]
    register.delete_sites(unused)
    print(f"provisional take-offs no longer used, removed: {len(unused)}")
    try:
        made = sum(rebuild_routes(register, site_id) for site_id in used if site_id is not None)
        print(f"routes: {made} for {len(used)} take-offs")
    except RuntimeError as exc:  # migration-2026-10-23-routes.sql not run yet: the take-offs are done anyway
        print(f"routes not made: {exc}")


def rebuild_routes(register: Register, site_id: int) -> int:
    """Make the routes of one take-off again from the climbs of its public outings (src/mbhf/routes.py), and tie
    the outings to them. Returns how many routes."""
    from mbhf.routes import Climb, routes_of

    rows = register.select("outings", f"select=id,climb,start_place&takeoff_site_id=eq.{site_id}"
                                      "&status=eq.published&verified=is.true&hidden=is.false")
    climbs = [Climb(r["id"], r["climb"]["line"], r.get("start_place"))
              for r in rows if len((r.get("climb") or {}).get("line") or []) > 1]
    routes = routes_of(climbs)
    if register.dry:
        return len(routes)
    # the take-off's routes are made again: the old ones go (their outings lose their route_id until just below)
    register.api.request("DELETE", f"/rest/v1/routes?takeoff_site_id=eq.{site_id}")
    if not routes:
        return 0
    _, raw = register.api.request("POST", "/rest/v1/routes", [
        {"takeoff_site_id": site_id, "name": r["name"], "start_place": r["start_place"], "line": r["line"],
         "outing_count": len(r["outing_ids"])} for r in routes], extra={"Prefer": "return=representation"})
    for route, row in zip(routes, json.loads(raw)):
        register.api.request("PATCH", f"/rest/v1/outings?id=in.({','.join(route['outing_ids'])})", {"route_id": row["id"]},
                             extra={"Prefer": "return=minimal"})
    return len(routes)


def main() -> int:
    from process_pending import Api  # same folder

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="read and report, write nothing")
    args = ap.parse_args()
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY are required", file=sys.stderr)
        return 1
    sync(Api(url, key), args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
