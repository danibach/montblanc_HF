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


def look_up_places(outing: dict):
    from mbhf.places import fetch_overpass, overpass_query, resolve_places

    query = overpass_query(outing)
    if not query:
        return None
    try:
        return resolve_places(outing, fetch_overpass(query))
    except OSError as exc:
        print(f"  places unavailable: {exc}")
        return None


def process_pending(api: Api) -> None:
    from mbhf.analyse import AnalysisError, analyse_bytes
    from mbhf.rows import outing_row
    from mbhf.terrain import fetch_elevations

    for row in api.select(f"{TO_CHECK}&select=id,file_path,file_format&order=created_at.asc&limit={BATCH}"):
        print(f"outing {row['id']} ({row['file_path']})")
        try:
            data = api.download(row["file_path"])
        except RuntimeError as exc:
            reject(api, row["id"], "The file could not be read from storage.")
            print(f"  {exc}")
            continue
        try:
            result = analyse_bytes(f"track.{row['file_format']}", data, elevation_fetch=fetch_elevations)
        except AnalysisError as exc:
            reject(api, row["id"], str(exc))
            continue
        except Exception as exc:  # a bug must not block the queue
            print(f"  analysis crashed: {type(exc).__name__}: {exc}")
            reject(api, row["id"], "This file could not be analysed.")
            continue

        sha = result["file"]["sha256"]
        twins = api.select(f"file_sha256=eq.{sha}&status=eq.published&id=neq.{row['id']}&select=id&limit=1")
        if twins:
            reject(api, row["id"], "This track was already submitted.")
            continue
        outing = result["outing"]
        if outing["status"] != "ok":
            messages = {
                "no_flight": "No flight found in this track.",
                "too_little_climb": "Not enough climbing on foot before the flight (at least 200 m).",
            }
            reason = messages.get(outing["reason"], "This track does not count.")
            if outing["reason"] == "no_flight" and any("follows the ground" in w for w in outing["warnings"]):
                reason = next(w for w in outing["warnings"] if "follows the ground" in w)
            reject(api, row["id"], reason)
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


def retry_places(api: Api, relabel: bool = False) -> None:
    """Fill in the names of outings still waiting for them; with ``relabel``, redo every published outing."""
    from mbhf.rows import has_names, place_title

    where = PUBLISHED if relabel else no_names_filter()
    offset = 0
    while True:
        rows = api.select(f"{where}&select={PLACE_COLUMNS}&order=created_at.asc&limit={BATCH}&offset={offset}")
        if not rows:
            return
        offset += BATCH
        for row in rows:
            outing = {
                "start": {"lat": row["start_lat"], "lon": row["start_lon"]} if row["start_lat"] is not None else None,
                "summit": {"lat": row["summit_lat"], "lon": row["summit_lon"], "alt": row["summit_alt"]} if row["summit_lat"] is not None else None,
                "takeoff": {"lat": row["takeoff_lat"], "lon": row["takeoff_lon"], "alt": row["takeoff_alt"]} if row["takeoff_lat"] is not None else None,
            }
            places = look_up_places(outing)
            if not has_names(places):
                continue  # Overpass gave nothing: left as it is (retried for a day when still pending)
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
                time.sleep(2)  # be polite with Overpass
        if not relabel:
            return  # the next run continues with the rest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count-only", action="store_true", help="print how many outings wait, and stop")
    ap.add_argument("--relabel", action="store_true", help="look the names up again for every published outing, and stop")
    args = ap.parse_args()
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY are required", file=sys.stderr)
        return 1
    api = Api(url, key)
    if args.relabel:
        retry_places(api, relabel=True)
        return 0
    pending, no_names = waiting(api)
    print(f"waiting: {pending} new, {no_names} without place names")
    if args.count_only:
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as fh:
                fh.write(f"count={pending + no_names}\n")
        return 0
    if pending:
        process_pending(api)
    if no_names:
        retry_places(api)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    raise SystemExit(main())
