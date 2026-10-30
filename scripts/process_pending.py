"""Analyse the outings waiting in Supabase and publish (or reject) them.

    SUPABASE_URL=...  SUPABASE_SERVICE_KEY=...  python scripts/process_pending.py [--count-only]

Run by GitHub Actions (.github/workflows/process.yml) every ten minutes and when asked. An outing is shown
at once on the browser's analysis ("validation pending"); this job recomputes it from the original file,
marks it verified, or rejects it. The service
key is a secret of the repository: never put it in a file. The script reads the original file from
the private storage, runs the same analysis as the participant's browser, looks the place names up on
OpenStreetMap, and writes the result into the outing's row.

Only the standard library is needed to count (``--count-only``); the analysis needs ``pip install .``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BATCH = 20
TO_CHECK = "verified=is.false&status=in.(pending,published)"
PUBLISHED = "verified=is.true&status=eq.published"
PLACE_COLUMNS = ("id,outing_date,start_lat,start_lon,summit_lat,summit_lon,summit_alt,"
                 "takeoff_lat,takeoff_lon,takeoff_alt")


def no_names_filter() -> str:
    """Outings still without any name. Only the first day after analysis: an outing in a place that OpenStreetMap
    does not name would otherwise be retried (and trigger the job) for ever."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    return f"{PUBLISHED}&places_pending=is.true&analysed_at=gt.{urllib.parse.quote(since)}"


class Api:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key

    def headers(self, extra=None) -> dict:
        h = {"apikey": self.key}
        if not self.key.startswith("sb_secret_"):
            h["Authorization"] = f"Bearer {self.key}"
        h.update(extra or {})
        return h

    def request(self, method: str, path: str, body=None, extra=None):
        data = None if body is None else json.dumps(body).encode()
        headers = self.headers({"Content-Type": "application/json", **(extra or {})})
        req = urllib.request.Request(f"{self.url}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return resp, raw
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path} -> {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc

    def select(self, query: str) -> list:
        _, raw = self.request("GET", f"/rest/v1/outings?{query}")
        return json.loads(raw)

    def count(self, query: str) -> int:
        resp, raw = self.request("GET", f"/rest/v1/outings?select=id&{query}&limit=1", extra={"Prefer": "count=exact"})
        total = resp.headers.get("content-range", "*/0").split("/")[-1]
        return int(total) if total.isdigit() else 0

    def patch(self, outing_id: str, values: dict) -> None:
        self.request("PATCH", f"/rest/v1/outings?id=eq.{outing_id}", values, extra={"Prefer": "return=minimal"})

    def download(self, path: str) -> bytes:
        quoted = urllib.parse.quote(path)
        _, raw = self.request("GET", f"/storage/v1/object/track-files/{quoted}")
        return raw


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def waiting(api: Api) -> tuple[int, int]:
    return api.count(TO_CHECK), api.count(no_names_filter())


def reject(api: Api, outing_id: str, reason: str) -> None:
    print(f"  rejected: {reason}")
    api.patch(outing_id, {"status": "rejected", "reject_reason": reason[:300], "analysed_at": now()})


def look_up_places(outing: dict, attempts: int = 2, timeout: float = 40.0):
    from mbhf.places import fetch_overpass, overpass_query, resolve_places

    query = overpass_query(outing)
    if not query:
        return None
    try:
        return resolve_places(outing, fetch_overpass(query, attempts=attempts, timeout=timeout))
    except OSError as exc:
        print(f"  places unavailable: {exc}")
        return None


def to_check(api: Api) -> list:
    """The outings to check. Without the column manual_flights (migration-2026-10-25-manual-flights.sql) or
    file_parts (migration-2026-10-25-file-parts.sql) not run yet, the job still works, without them."""
    base = f"{TO_CHECK}&order=created_at.asc&limit={BATCH}"
    cols = "id,user_id,created_at,file_path,file_format"
    for extra in (",manual_flights,file_parts", ",manual_flights", ",file_parts", ""):
        try:
            return api.select(f"{base}&select={cols}{extra}")
        except RuntimeError as exc:
            if not extra:
                raise
            print(f"  {extra[1:]} not read (migration not run?): {exc}")
    return []


def process_pending(api: Api) -> None:
    from mbhf.analyse import AnalysisError, analyse_files
    from mbhf.rows import outing_row
    from mbhf.terrain import fetch_elevations
    from mbhf.duplicates import duplicate_message, same_flight
    from mbhf.advice import OUR_SIDE

    for row in to_check(api):
        print(f"outing {row['id']} ({row['file_path']})")
        parts = row.get("file_parts") or [{"path": row["file_path"], "format": row["file_format"]}]
        try:
            files = [(f"track{k}.{p['format']}", api.download(p["path"])) for k, p in enumerate(parts)]
        except (RuntimeError, KeyError, TypeError) as exc:
            reject(api, row["id"], OUR_SIDE)
            print(f"  file not read from storage: {exc}")
            continue
        try:
            # flights the participant marked on the map replace the automatic detection and the ground check (for an
            # outing in several files, in seconds after the first fix of the first file)
            result = analyse_files(files, elevation_fetch=fetch_elevations, manual_ranges=row.get("manual_flights"))
        except AnalysisError as exc:
            reject(api, row["id"], str(exc))
            continue
        except Exception as exc:  # a bug must not block the queue
            print(f"  analysis crashed: {type(exc).__name__}: {exc}")
            reject(api, row["id"], OUR_SIDE)
            continue

        sha = result["file"]["sha256"]
        # the same file (or, for an outing in several files, one of them) already counted in another outing
        hashes = [sha] + [p["sha256"] for p in result["file"].get("parts", [])]
        twins = api.select(f"file_sha256=in.({','.join(hashes)})&status=eq.published&id=neq.{row['id']}&select=id&limit=1")
        if twins:
            reject(api, row["id"], "This track was already submitted.")
            continue
        outing = result["outing"]
        if outing["status"] != "ok":
            # the cause and what to do, in the same words as the participant's browser (src/mbhf/advice.py)
            reject(api, row["id"], outing.get("reason_text") or "This track does not count.")
            continue
        # The same flight sent from another file (the watch's FIT and its Strava export): it counts once, in the
        # outing sent first.
        others = api.select(f"user_id=eq.{row['user_id']}&outing_date=eq.{outing['date']}&status=in.(pending,published)"
                            f"&created_at=lt.{urllib.parse.quote(row['created_at'])}&select=id,title,outing_date,flights")
        twin = next((o for o in others if same_flight(outing["flights"], o.get("flights"))), None)
        if twin:
            reject(api, row["id"], duplicate_message(twin.get("title"), twin.get("outing_date")))
            continue

        values = outing_row(result, look_up_places(outing))
        values.update({"analysed_at": now(), "file_sha256": sha, "file_size": result["file"]["size"],
                       "status": "published", "reject_reason": None, "verified": True})
        try:
            api.patch(row["id"], values)
        except RuntimeError as exc:  # e.g. the announced hash was not the real one and the file is a twin
            print(f"  {exc}")
            reject(api, row["id"], "This track was already submitted.")
            continue
        print(f"  published: score {outing['score']} (D+ {outing['dplus_m']}, D- {outing['dminus_m']})")
        climb = save_climb(api, row["id"], values["trace"], outing["flights"])
        save_public(api, row["id"], values["trace"], climb)
        tie_takeoff(api, row["id"], values)


def tie_takeoff(api: Api, outing_id: str, values: dict) -> None:
    """Tie the outing to its take-off in the register (scripts/sync_sites.py), with the take-offs already known
    around it. Apart from the rest: an error here (for example the register is not there yet,
    migration-2026-10-23-takeoff-sites.sql not run) must never reject an outing."""
    try:
        from sync_sites import Register, rebuild_routes, tie_outing, title_from_site
        from mbhf.sites import SiteIndex

        lat, lon = values.get("takeoff_lat"), values.get("takeoff_lon")
        if lat is None or lon is None:
            return
        register = Register(api)
        near = register.select("takeoff_sites", f"select=*&lat=gte.{lat - 0.01}&lat=lte.{lat + 0.01}"
                                                f"&lon=gte.{lon - 0.015}&lon=lte.{lon + 0.015}")
        status, site = tie_outing({**values, "id": outing_id}, SiteIndex(near), register)
        print(f"  take-off: {site['name']} ({status})")
        title = title_from_site(site, values)  # the highest summit on foot, else the register's take-off name (src/mbhf/titles.py)
        if title and title != values.get("title"):
            api.patch(outing_id, {"title": title})
        # its routes made again with this climb (routes table: migration-2026-10-23-routes.sql)
        try:
            print(f"  routes at this take-off: {rebuild_routes(register, site['id'])}")
        except Exception as exc:
            print(f"  routes not made: {exc}")
    except Exception as exc:
        print(f"  take-off not tied: {exc}")


def save_climb(api: Api, outing_id: str, trace, flights) -> None:
    """The climb drawn on the take-off map. Written apart: an error here (for example the column is not there
    yet, migration-2026-10-21-map-outings.sql not run) must never reject an outing."""
    from mbhf.climb import climb_of

    try:
        climb = climb_of(trace, flights)
        api.patch(outing_id, {"climb": climb})
        return climb
    except Exception as exc:
        print(f"  climb not saved: {exc}")
        return None


def save_public(api: Api, outing_id: str, trace, climb, itinerary=None) -> None:
    """What visitors see of the outing (src/mbhf/privacy.py): its trace and its climb without the start near home and
    the way back after landing. Written apart, like the climb (migration-2026-10-29-private-starts.sql)."""
    from mbhf.privacy import public_parts

    try:
        api.patch(outing_id, public_parts(trace, climb, itinerary))
    except Exception as exc:
        print(f"  public parts not saved: {exc}")


def fill_public(api: Api) -> int:
    """The public parts of published outings that have none yet (the outings published before they existed)."""
    done = 0
    try:
        rows = api.select(f"{PUBLISHED}&trace_public=is.null&trace=not.is.null&select=id,trace,climb&order=created_at.asc&limit={BATCH}")
    except Exception as exc:  # the migration is not run yet
        print(f"public parts not filled in: {exc}")
        return 0
    for row in rows:
        save_public(api, row["id"], row["trace"], row.get("climb") or None)
        done += 1
    print(f"public parts filled in: {done}")
    return done


OLD_CLIMB = "climb=not.is.null&climb->>v=is.null&trace=not.is.null"  # made before src/mbhf/climb.py's VERSION


def refresh_climbs(api: Api) -> int:
    """Make again, BATCH at a time, the climbs made with an older rule (climb.VERSION: a short GPS gap no longer cuts
    a climb), and their public parts, cut up to the outing's itinerary when other climbs take it as the sync does."""
    from mbhf.climb import VERSION, climb_of

    done = 0
    rows = api.select(f"{PUBLISHED}&{OLD_CLIMB}&select=id,trace,flights,route_id&order=created_at.asc&limit={BATCH}")
    for row in rows:
        climb = climb_of(row["trace"], row["flights"]) or {"v": VERSION}  # none: marked, so that it is not read again
        api.patch(row["id"], {"climb": climb})
        itinerary = None
        if row.get("route_id"):
            _, raw = api.request("GET", f"/rest/v1/routes?select=line,outing_count&id=eq.{row['route_id']}")
            route = (json.loads(raw) or [None])[0]
            if route and (route.get("outing_count") or 0) >= 2:
                itinerary = route["line"]
        save_public(api, row["id"], row["trace"], climb if climb.get("line") else None, itinerary)
        done += 1
    print(f"climbs made again with the rule of today: {done}")
    return done


def fill_climbs(api: Api) -> None:
    """Compute the climb of every published outing that has none yet, from its stored trace."""
    from mbhf.climb import VERSION, climb_of

    done = 0
    while True:
        rows = api.select(f"{PUBLISHED}&climb=is.null&trace=not.is.null&select=id,trace,flights&order=created_at.asc&limit={BATCH}")
        if not rows:
            break
        for row in rows:
            # an outing without a climb gets an empty object, so that it is not read again
            api.patch(row["id"], {"climb": climb_of(row["trace"], row["flights"]) or {"v": VERSION}})
            done += 1
    print(f"climbs filled in: {done}")


def retry_places(api: Api, relabel: bool = False, budget_s: float = 0.0) -> None:
    """Fill in the names of outings still waiting for them.

    With ``relabel``, every published outing is first marked as waiting, then done a few at a time. The mark is the
    bookmark: an outing leaves the waiting list once its names are written, so a run that is stopped (or runs out of
    ``budget_s`` seconds) is simply started again and continues where it stopped.
    """
    from mbhf.rows import has_names, place_title

    if relabel:
        api.request("PATCH", f"/rest/v1/outings?{PUBLISHED}", {"places_pending": True}, extra={"Prefer": "return=minimal"})
    where = f"{PUBLISHED}&places_pending=is.true" if relabel else no_names_filter()
    started, skipped = time.monotonic(), 0
    while True:
        rows = api.select(f"{where}&select={PLACE_COLUMNS}&order=created_at.asc&limit={BATCH}&offset={skipped}")
        if not rows:
            print(f"done; {skipped} outing(s) left waiting (Overpass gave no answer)")
            return
        for row in rows:
            if budget_s and time.monotonic() - started > budget_s:
                print("time budget used up: run it again to continue")
                return
            outing = {
                "start": {"lat": row["start_lat"], "lon": row["start_lon"]} if row["start_lat"] is not None else None,
                "summit": {"lat": row["summit_lat"], "lon": row["summit_lon"], "alt": row["summit_alt"]} if row["summit_lat"] is not None else None,
                "takeoff": {"lat": row["takeoff_lat"], "lon": row["takeoff_lon"], "alt": row["takeoff_alt"]} if row["takeoff_lat"] is not None else None,
            }
            places = look_up_places(outing, attempts=1, timeout=25.0) if relabel else look_up_places(outing)
            if not has_names(places):
                skipped += 1  # Overpass gave nothing: stays waiting
                continue
            summit = places.get("summit") or {}
            takeoff = places.get("takeoff") or {}
            country = places.get("country") or {}
            api.patch(row["id"], {
                "places_pending": False,
                "title": place_title(places, row["outing_date"], row["summit_alt"]),
                "country_code": country.get("code"), "country_name": country.get("name"),
                "start_place": places.get("start_place"), "start_commune": places.get("commune"),
                "summit_name": summit.get("name"), "summit_osm_id": summit.get("osm_id"),
                "takeoff_name": takeoff.get("name"),
            })
            print(f"  places filled in for {row['id']}")
            if relabel:
                time.sleep(1)  # be polite with Overpass
        if not relabel:
            return  # the next run continues with the rest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count-only", action="store_true", help="print how many outings wait, and stop")
    ap.add_argument("--relabel", action="store_true", help="look the names up again for every published outing, and stop")
    ap.add_argument("--climbs", action="store_true", help="compute the climb (take-off map) of published outings without one, and stop")
    args = ap.parse_args()
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY are required", file=sys.stderr)
        return 1
    api = Api(url, key)
    if args.relabel:
        retry_places(api, relabel=True, budget_s=float(os.environ.get("RELABEL_BUDGET_S", "0")))
        return 0
    if args.climbs:
        fill_climbs(api)
        return 0
    pending, no_names = waiting(api)
    try:
        no_public = api.count(f"{PUBLISHED}&trace_public=is.null&trace=not.is.null")
        old_climbs = api.count(f"{PUBLISHED}&{OLD_CLIMB}")
    except Exception:  # the migration is not run yet
        no_public = old_climbs = 0
    print(f"waiting: {pending} new, {no_names} without place names, {no_public} without a public part, "
          f"{old_climbs} climbs of an older rule")
    if args.count_only:
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as fh:
                fh.write(f"count={pending + no_names + no_public + old_climbs}\n")
        return 0
    if pending:
        process_pending(api)
    if no_names:
        retry_places(api)
    if no_public:
        fill_public(api)
    if old_climbs:
        refresh_climbs(api)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    raise SystemExit(main())
