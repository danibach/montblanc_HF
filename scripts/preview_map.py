"""Look at the take-off map (page "Map") on your own computer, before it is merged and deployed.

    python3 scripts/preview_map.py           # made-up outings around Annecy and Chamonix
    python3 scripts/preview_map.py --real    # the live site's public outings, read-only
    python3 scripts/preview_map.py --crowded # plus a made-up take-off with 120 outings
    python3 scripts/preview_map.py --real --sites  # and tied to the take-off register (FFVL, OSM), in memory
    then open http://127.0.0.1:8765/#/map

A copy of site/ is served with a pretend Supabase on the same address, so the database needs nothing (no
migration, no column): ``map_outings()`` is answered here. With ``--real``, the verified public outings are read
from the live site with its public key, exactly what any visitor can read, and nothing is written; their climbs
are computed here with src/mbhf/climb.py, as the server job will store them. Stop with Ctrl-C.
Only the standard library is needed; the first run downloads the Supabase browser library (as build_site.py).
"""

from __future__ import annotations

import argparse
import http.server
import json
import math
import random
import re
import shutil
import socketserver
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mbhf.climb import climb_of  # noqa: E402

SUPABASE_JS = "https://unpkg.com/@supabase/supabase-js@2.118.0/dist/umd/supabase.js"  # as SUPABASE_JS_VERSION in build_site.py
CONFIG = (ROOT / "site" / "config.js").read_text(encoding="utf-8")
LIVE_URL = re.search(r"SUPABASE_URL: '([^']+)'", CONFIG).group(1)
LIVE_KEY = re.search(r"SUPABASE_PUBLISHABLE_KEY: '([^']+)'", CONFIG).group(1)

# made-up take-offs: name, lat, lon, alt, outings, ways up as (start offset lat, lon, start alt, start place)
SITES = [
    ("Planfait", 45.8433, 6.2167, 1350, 9, [(-0.020, -0.012, 480, "Talloires"), (-0.004, 0.022, 900, "Le Villard")]),
    ("Col de la Forclaz", 45.8135, 6.2440, 1250, 6, [(-0.018, -0.020, 460, "Doussard"), (0.016, 0.010, 1050, "Montmin")]),
    ("Planpraz", 45.9237, 6.8694, 2000, 12, [(-0.0200, 0.0090, 1040, "Chamonix"), (-0.012, -0.022, 1300, "Les Houches")]),
    ("Brévent", 45.9340, 6.8380, 2520, 4, [(-0.030, 0.012, 1040, "Chamonix")]),
    ("Plaine Joux", 45.9590, 6.7430, 1360, 3, [(-0.015, -0.010, 640, "Passy")]),
    ("Col des Frêtes", 45.8930, 6.4420, 1500, 2, [(-0.018, 0.006, 900, "Les Clefs")]),
]
# --crowded adds a busy take-off, to see the map past 30 climbs (heat instead of lines, groups, pages of 20)
CROWDED = ("Pointe de Beauregard", 45.9105, 6.4705, 1636, 120,
           [(-0.014, -0.010, 1010, "Les Verrier"), (-0.012, 0.016, 1050, "La Clusaz"), (0.018, 0.004, 1100, "Le Grand-Bornand")])
PILOTS = ["Alice", "Bruno", "Chloé", "Dani", "Sarah"]


def made_up(crowded: bool = False) -> tuple[list, dict]:
    """Outings (the columns of map_outings()) and their tracks, a few with a drive before the walk."""
    rng = random.Random(4)
    outings, tracks = [], {}
    for name, lat, lon, alt, n, ways in SITES + ([CROWDED] if crowded else []):
        for k in range(n):
            dlat, dlon, alt0, place = ways[k % len(ways)]
            oid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{name}/{k}"))
            t0 = datetime(2026, 1, 10, 7, 0, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 300))
            tlat, tlon = lat + rng.uniform(-0.0004, 0.0004), lon + rng.uniform(-0.0004, 0.0004)
            slat, slon = tlat + dlat, tlon + dlon
            bend = rng.uniform(0.25, 0.5) * (1 if k % 2 else -1)
            t, la, lo, al, m = [], [], [], [], []
            sec = 0
            if k % 5 == 4:  # a drive to the start: never drawn
                for i in range(10):
                    f = i / 10
                    t.append(sec); la.append(slat - 0.02 * (1 - f)); lo.append(slon - 0.01 * (1 - f)); al.append(alt0 - 150 * (1 - f)); m.append(2)
                    sec += 30
            for i in range(81):
                f = i / 80
                off = math.sin(math.pi * f) * bend
                t.append(sec)
                la.append(round(slat + (tlat - slat) * f - dlon * off * 0.4 + rng.uniform(-0.0002, 0.0002), 5))
                lo.append(round(slon + (tlon - slon) * f + dlat * off * 0.4 + rng.uniform(-0.0002, 0.0002), 5))
                al.append(round(alt0 + (alt - alt0) * f))
                m.append(0)
                sec += rng.randint(70, 110)
            sec += 900  # preparing the wing
            takeoff_t = t0 + timedelta(seconds=sec)
            for i in range(1, 31):
                f = i / 30
                t.append(sec); la.append(round(tlat - 0.01 * f, 5)); lo.append(round(tlon + 0.03 * f, 5)); al.append(round(alt - (alt - 500) * f)); m.append(1)
                sec += 40
            track = {"trace": {"t0": t0.isoformat(), "t": t, "lat": la, "lon": lo, "alt": al, "m": m},
                     "flights": [{"takeoff": {"lat": tlat, "lon": tlon, "alt": alt, "t": takeoff_t.isoformat()}, "drop_m": alt - 500}]}
            tracks[oid] = track
            pilot = rng.choice(PILOTS)
            # a quarter have no stored climb yet, as before the job has filled them in: the page reads their track
            climb = None if rng.random() < 0.25 else (climb_of(track["trace"], track["flights"]) or {})
            outings.append([oid, tlat, tlon, alt, name, name, t0.date().isoformat(), alt - alt0 + rng.randint(0, 60),
                            round(5.6 + rng.uniform(0, 2), 1), place, pilot, alt + rng.randint(0, 80), pilot, climb])
    outings.sort(key=lambda r: r[6], reverse=True)
    return outings, tracks


def live_get(path: str):
    req = urllib.request.Request(f"{LIVE_URL}/rest/v1/{path}", headers={"apikey": LIVE_KEY, "Authorization": f"Bearer {LIVE_KEY}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def live() -> tuple[list, dict]:
    """The live site's verified public outings, read-only, with the climbs the server job will store."""
    cols = ("id,user_id,takeoff_lat,takeoff_lon,takeoff_alt,takeoff_name,title,outing_date,dplus_m,walk_km,"
            "start_place,summit_alt,summit_name,country_code,profiles(display_name)")
    rows = live_get(f"outings?select={cols}&status=eq.published&verified=is.true&hidden=is.false"
                    "&takeoff_lat=not.is.null&order=outing_date.desc&limit=5000")
    tracks = {}
    ids = [r["id"] for r in rows]
    for i in range(0, len(ids), 25):
        for t in live_get(f"outings?select=id,trace,flights&id=in.({','.join(ids[i:i + 25])})"):
            tracks[t["id"]] = t
    outings = []
    for r in rows:
        t = tracks.get(r["id"]) or {}
        outings.append([r["id"], r["takeoff_lat"], r["takeoff_lon"], r["takeoff_alt"], r["takeoff_name"], r["title"],
                        r["outing_date"], r["dplus_m"], r["walk_km"], r["start_place"],
                        (r.get("profiles") or {}).get("display_name"), r["summit_alt"], r["user_id"],
                        climb_of(t.get("trace"), t.get("flights")) or {}])
    live.rows = rows  # for --sites
    return outings, tracks


def register_in_memory(rows: list[dict], outings: list, with_osm: bool = True) -> list:
    """--sites: the take-off register as scripts/sync_sites.py will fill it (FFVL and OpenStreetMap, read only), and
    every outing tied by the same rule, in memory only. Adds the take-off id and tie status to ``outings``."""
    from sync_sites import Register, ffvl_file, osm_around, tie_outing
    from mbhf.sites import SiteIndex, ffvl_takeoffs, without_doubles

    register = Register(None, dry_run=True)
    ties = {}
    register.tie = lambda outing_id, site_id, status, metres: ties.__setitem__(outing_id, (site_id, status))
    ffvl = ffvl_takeoffs(ffvl_file())
    osm = osm_around([(r["takeoff_lat"], r["takeoff_lon"]) for r in rows]) if with_osm else None
    print(f"FFVL take-offs: {len(ffvl)}; OpenStreetMap: {'unavailable' if osm is None else len(osm)}", flush=True)
    index = SiteIndex(register.upsert(ffvl + without_doubles(ffvl, osm or [])))
    used = {}
    for r in sorted(rows, key=lambda r: r["outing_date"] or ""):
        status, site = tie_outing(r, index, register)
        used[site["id"]] = site
    counts = {}
    for o in outings:
        site_id, status = ties[o[0]]
        o += [site_id, status]
        key = f"{used[site_id]['source']} {status}"
        counts[key] = counts.get(key, 0) + 1
    print("outings tied: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())), flush=True)
    return [[s["id"], s["name"], s["lat"], s["lon"], s["alt"], s["source"], s.get("wind_ok"), s.get("hike_and_fly")]
            for s in used.values()]


def copy_site(dest: Path, port: int) -> Path:
    site = dest / "site"
    shutil.copytree(ROOT / "site", site)
    cache = Path(tempfile.gettempdir()) / "hf-preview-supabase.js"
    if not cache.exists():
        urllib.request.urlretrieve(SUPABASE_JS, cache)
    shutil.copy2(cache, site / "vendor" / "supabase.js")
    cfg = site / "config.js"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(LIVE_URL, f"http://127.0.0.1:{port}"), encoding="utf-8")
    return site


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", action="store_true", help="the live site's public outings (read-only) instead of made-up ones")
    ap.add_argument("--crowded", action="store_true", help="add a made-up take-off with 120 outings from 3 start places")
    ap.add_argument("--sites", action="store_true", help="with --real: tie the outings to the take-off register (FFVL, OSM), in memory")
    ap.add_argument("--no-osm", action="store_true", help="with --sites: FFVL only (when Overpass is down)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    outings, tracks = live() if args.real else made_up(args.crowded)
    sites = register_in_memory(live.rows, outings, not args.no_osm) if args.real and args.sites else []
    site = copy_site(Path(tempfile.mkdtemp(prefix="hf-preview-")), args.port)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(site), **k)

        def log_message(self, *a):
            pass

        def send_json(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length") or 0))
            if self.path.startswith("/rest/v1/rpc/map_outings"):
                return self.send_json(outings)
            self.send_json(sites if self.path.startswith("/rest/v1/rpc/map_takeoff_sites") else {})

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/rest/v1/outings":  # the tracks of outings without a stored climb
                ids = urllib.parse.parse_qs(u.query).get("id", [""])[0]
                ids = ids[len("in.("):-1].replace('"', "").split(",") if ids.startswith("in.(") else []
                return self.send_json([{"id": i, **tracks[i]} for i in ids if i in tracks])
            if u.path.startswith(("/rest/", "/auth/")):
                return self.send_json([])
            super().do_GET()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), Handler) as httpd:
        kind = "public outings of the live site (read-only)" if args.real else "made-up outings"
        print(f"{len(outings)} {kind}\nopen http://127.0.0.1:{args.port}/#/map   (Ctrl-C to stop)", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
