"""Check the built website in a real browser (Chromium via Playwright), with a pretend Supabase.

    python scripts/build_site.py --out _site
    pip install playwright && playwright install chromium
    python scripts/check_site.py _site [--shots folder]

Supabase, OpenStreetMap (Overpass), the map tiles and Cloudflare are replaced by canned answers, so
nothing leaves the machine. The numbers shown by the page must equal those of the normal Python
analysis of the same track. Screenshots go to the folder given by --shots.
"""
import base64, functools, http.server, json, os, re, socket, socketserver, sys, tempfile, threading
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), os.path.join(ROOT, "tests")]
from synth import as_track, gpx_bytes, hike_and_fly, slow_ski_descent, two_flights  # noqa: E402
from mbhf.analyse import analyse_bytes  # noqa: E402
from mbhf.places import resolve_places  # noqa: E402
from mbhf.rows import outing_row  # noqa: E402

SITE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else os.path.join(ROOT, "_site")
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else tempfile.mkdtemp(prefix="site-check-")
os.makedirs(SHOTS, exist_ok=True)

# ---------------------------------------------------------------- data

UID = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
REF = "fjwsmdglbnmmelfamyol"


def node(i, lat, lon, **tags):
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": tags}


def overpass_for(outing):
    s, t, k = outing["start"], outing["summit"], outing["takeoff"]
    return {"elements": [
        {"type": "relation", "id": 1, "tags": {"boundary": "administrative", "admin_level": "2", "name": "France", "name:en": "France", "ISO3166-1:alpha2": "FR"}},
        {"type": "relation", "id": 2, "tags": {"boundary": "administrative", "admin_level": "8", "name": "Servoz"}},
        node(10, s["lat"] + 0.0005, s["lon"] + 0.0005, place="hamlet", name="Les Granges"),
        node(20, t["lat"] + 0.0003, t["lon"], natural="peak", name="Pointe Haute", ele=str(int(t["alt"]) + 3)),
        node(22, k["lat"] + 0.0003, k["lon"], natural="saddle", name="Col du Test", ele=str(int(k["alt"]) - 5)),
    ]}


def build_row(rid, user, name, gen, title_places=True):
    res = analyse_bytes("a.gpx", gpx_bytes(as_track(gen)))
    places = resolve_places(res["outing"], overpass_for(res["outing"]))
    row = outing_row(res, places)
    row.update({"id": rid, "user_id": user, "status": "published", "reject_reason": None, "hidden": False, "verified": rid.endswith("1"),
                "created_at": "2026-09-12T20:00:00Z", "file_path": f"{user}/{rid}.gpx",
                "profiles": {"id": user, "display_name": name}})
    row["trace_public"] = row["trace"]  # what visitors are sent (src/mbhf/privacy.py); the whole one here, for the checks
    return res, row


RES1, ROW1 = build_row("aaaaaaaa-0000-0000-0000-000000000001", UID, "Alice", hike_and_fly())
RES2, ROW2 = build_row("aaaaaaaa-0000-0000-0000-000000000002", OTHER, "Bruno", two_flights())
ROW3 = {"id": "aaaaaaaa-0000-0000-0000-000000000003", "user_id": UID, "status": "pending", "title": None, "outing_date": None,
        "created_at": "2026-10-20T09:00:00Z", "file_path": f"{UID}/x.gpx", "profiles": {"display_name": "Alice"}, "reject_reason": None}
ROWS = [ROW1, ROW2]
NATIVE = RES1["outing"]
GPX = os.path.join(SHOTS, "day.gpx")
open(GPX, "wb").write(gpx_bytes(as_track(hike_and_fly())))
NOTIME = os.path.join(SHOTS, "no-time.gpx")
SKI = os.path.join(SHOTS, "ski.gpx")
open(SKI, "wb").write(gpx_bytes(as_track(slow_ski_descent())))
open(NOTIME, "wb").write(gpx_bytes(as_track(hike_and_fly()), with_time=False))
print("screenshots:", SHOTS)

# ---------------------------------------------------------------- pretend servers

calls = []
CORS = {"access-control-allow-origin": "*", "access-control-expose-headers": "content-range,content-type"}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def flat_terrain_png(size=512):
    """A terrain tile of Mapterhorn's kind (terrarium: height = R * 256 + G + B / 256 - 32768) at 1 000 m."""
    import struct
    import zlib
    r, g, b = divmod(1000 + 32768, 256)[0], (1000 + 32768) % 256, 0
    row = b"\x00" + bytes([r, g, b]) * size
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))


TERRAIN = flat_terrain_png()
# the map's own style (site/basemaps.js) is built on OpenFreeMap's: a minimal one with the same vector source
OFM_STYLE = {"version": 8, "glyphs": "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
             "sources": {"openmaptiles": {"type": "vector", "tiles": ["https://tiles.openfreemap.org/planet/{z}/{x}/{y}.pbf"], "maxzoom": 14}},
             "layers": [{"id": "background", "type": "background", "paint": {"background-color": "#f6f3ee"}}]}


def openfreemap(route):
    if "/styles/" in route.request.url:
        return j(route, OFM_STYLE)
    return route.fulfill(status=200, content_type="application/x-protobuf", body=b"")  # empty vector tiles and glyphs


def j(route, body, status=200, headers=None):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body), headers={**CORS, **(headers or {})})


def supabase(route, request):
    u = urlparse(request.url)
    q = parse_qs(u.query)
    if request.method == "OPTIONS":
        return route.fulfill(status=204, headers={**CORS, "access-control-allow-methods": "*",
                             "access-control-allow-headers": request.headers.get("access-control-request-headers", "*")})
    calls.append((request.method, u.path, u.query))
    wants_object = "pgrst.object" in request.headers.get("accept", "")
    if u.path == "/rest/v1/rpc/outing_filters":
        return j(route, {"years": [2026], "countries": [{"code": "FR", "name": "France"}]})
    if u.path == "/rest/v1/rpc/ranking":
        body = request.post_data_json or {}
        rows = [{"user_id": UID, "display_name": "Alice", "outings": 1, "dplus": ROW1["dplus_m"], "dminus": ROW1["dminus_m"], "walk_km": ROW1["walk_km"], "flight_km": ROW1["flight_free_km"], "score": ROW1["score"]}]
        if body.get("p_year") != 2025:
            rows.append({"user_id": OTHER, "display_name": "Bruno", "outings": 1, "dplus": ROW2["dplus_m"], "dminus": ROW2["dminus_m"], "walk_km": ROW2["walk_km"], "flight_km": ROW2["flight_free_km"], "score": ROW2["score"]})
        return j(route, sorted(rows, key=lambda r: -r["score"]))
    if u.path == "/rest/v1/rpc/map_outings":
        # like the SQL function: only the verified outings (ROW1), not the one waiting for the server (ROW2)
        return j(route, [[r["id"], r["takeoff_lat"], r["takeoff_lon"], r["takeoff_alt"], r["takeoff_name"], r["title"], r["outing_date"],
                          r["dplus_m"], r["walk_km"], r["start_place"], r["profiles"]["display_name"], r["summit_alt"],
                          r["user_id"], None]  # no stored climb: the page reads the track
                         for r in ROWS if r["verified"] and r["takeoff_lat"] is not None])
    if u.path in ("/rest/v1/rpc/map_takeoff_sites", "/rest/v1/rpc/map_routes", "/rest/v1/rpc/map_ffvl"):
        return j(route, [])  # no take-off register, routes nor FFVL sites: the map groups the outings itself
    if u.path == "/rest/v1/outings" and request.method == "GET" and q.get("id", [""])[0].startswith("in."):
        ids = q["id"][0][4:-1].replace('"', "").split(",")
        return j(route, [{"id": r["id"], "trace": r["trace"], "flights": r["flights"]} for r in ROWS if r["id"] in ids])
    if u.path == "/rest/v1/profiles":
        pid = q.get("id", [""])[0].replace("eq.", "")
        name = {UID: "Alice", OTHER: "Bruno"}.get(pid)
        return j(route, [{"id": pid, "display_name": name}] if name else [])
    if u.path == "/rest/v1/outings" and request.method == "GET":
        oid = q.get("id", [""])[0].replace("eq.", "")
        if oid:
            row = next((r for r in ROWS + [ROW3] if r["id"] == oid), None)
            return j(route, [row] if row else [])
        if q.get("outing_date", [""])[0].startswith("eq."):
            return j(route, [])  # same-flight check before publishing: this pilot has no other outing that day
        uid = q.get("user_id", [""])[0].replace("eq.", "")
        if uid:
            rows = [r for r in ROWS if r["user_id"] == uid] + ([ROW3] if uid == UID else [])
            return j(route, rows, headers={"content-range": f"0-{max(len(rows) - 1, 0)}/{len(rows)}"})
        return j(route, ROWS, headers={"content-range": f"0-{len(ROWS) - 1}/{len(ROWS)}"})
    if u.path == "/rest/v1/outings" and request.method == "POST":
        calls.append(("BODY", "outings", request.post_data))
        return j(route, {"id": "new-outing"} if wants_object else [{"id": "new-outing"}], 201)
    if u.path.startswith("/storage/v1/object/track-files/") and request.method == "POST":
        return j(route, {"Key": u.path})
    if u.path == "/auth/v1/otp":
        return j(route, {})
    return j(route, {"message": f"not mocked: {request.method} {u.path}"}, 404)


def elevation_answer(route):
    # a terrain far below the flight: the descent is in the air
    n = len(route.request.url.split("latitude=")[1].split("&")[0].split(","))
    calls.append(("ELEVATION", n))
    return j(route, {"elevation": [100.0] * n})


def session_script():
    payload = base64.urlsafe_b64encode(json.dumps({"sub": UID, "role": "authenticated", "exp": 4102444800}).encode()).decode().rstrip("=")
    token = f"eyJhbGciOiJIUzI1NiJ9.{payload}.sig"
    sess = {"access_token": token, "token_type": "bearer", "expires_in": 3600, "expires_at": 4102444800, "refresh_token": "r",
            "user": {"id": UID, "aud": "authenticated", "role": "authenticated", "email": "alice@example.com", "app_metadata": {}, "user_metadata": {}, "created_at": "2026-01-01T00:00:00Z"}}
    return f"localStorage.setItem('sb-{REF}-auth-token', {json.dumps(json.dumps(sess))});"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


sock = socket.socket(); sock.bind(("127.0.0.1", 0)); PORT = sock.getsockname()[1]; sock.close()
socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), functools.partial(Quiet, directory=SITE))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/"

problems = []


def check(cond, label):
    print(("ok    " if cond else "FAIL  ") + label)
    if not cond:
        problems.append(label)


def comma(n):
    return f"{int(round(n)):,}"


def new_page(browser, signed_in=False, width=1280, height=900, locale="en-US"):
    ctx = browser.new_context(viewport={"width": width, "height": height}, accept_downloads=True, locale=locale)
    if signed_in:
        ctx.add_init_script(session_script())
    page = ctx.new_page()
    external, logs = [], []
    page.route(re.compile(r"https://[^/]*supabase\.co/.*"), supabase)
    page.route(re.compile(r"https://overpass-api\.de/.*"), lambda r: j(r, overpass_for(NATIVE)))
    page.route(re.compile(r"https://api\.open-meteo\.com/v1/elevation.*"), elevation_answer)
    page.route(re.compile(r"https://[^/]*tile\.opentopomap\.org/.*"), lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    # the backgrounds of the take-off map (site/basemaps.js)
    page.route(re.compile(r"https://tiles\.openfreemap\.org/.*"), openfreemap)
    page.route(re.compile(r"https://tiles\.mapterhorn\.com/.*"), lambda r: r.fulfill(status=200, content_type="image/png", body=TERRAIN))
    page.route(re.compile(r"https://(data\.geopf\.fr|wmts\.geo\.admin\.ch|tiles\.opensnowmap\.org)/.*"), lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    page.route(re.compile(r"https://challenges\.cloudflare\.com/.*"), lambda r: r.fulfill(
        status=200, content_type="application/javascript",
        body="window.turnstile={render:function(e,o){e.textContent='[captcha]';o.callback('test-token')},reset:function(){}};"))
    page.on("request", lambda r: None if r.url.startswith((BASE, "blob:", "data:")) or re.match(r"https://([^/]*supabase\.co|overpass-api\.de|api\.open-meteo\.com|[^/]*tile\.opentopomap\.org|challenges\.cloudflare\.com|tiles\.openfreemap\.org|tiles\.mapterhorn\.com|data\.geopf\.fr|wmts\.geo\.admin\.ch|tiles\.opensnowmap\.org)/", r.url) else external.append(r.url))
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    return page, external, logs


with sync_playwright() as p:
    b = p.chromium.launch()

    # ============ anonymous visitor
    page, external, logs = new_page(b)
    # All outings: cards with their map by default, the sortable table under « List »
    page.goto(BASE + "#/all")
    page.wait_for_selector(".all-cards .climb-card", timeout=30000)
    check(page.locator(".all-cards .climb-card").count() == 2 and page.locator(".view-pick button[aria-pressed=true]").inner_text() == "Cards", "All: the outings as cards")
    page.wait_for_selector(".all-cards .cc-map.leaflet-container path", timeout=15000)
    check(True, "All: a card shows its track on the map")
    page.click(".view-pick button:has-text('List')")
    page.wait_for_selector("tbody tr", timeout=30000)
    check("view=list" in page.url, "All: « List » shows the table, kept in the address")
    rows = page.locator("tbody tr")
    check(rows.count() == 2, f"list shows the 2 published outings ({rows.count()})")
    check(page.inner_text("main").count("Validation pending") == 1, "only the unverified outing carries the badge")
    first = rows.nth(0).inner_text()
    check("Alice" in first and comma(ROW1["dplus_m"]) in first and "Score" not in page.inner_text("thead"), "list row: pilot and D+, no score column " + first.replace("\t", " | ")[:80])
    check(page.locator("#f-year option").count() == 2 and page.locator("#f-country option").count() == 2, "year and country filters filled")
    check("Sign in" in page.inner_text("#account"), "anonymous: Sign in link")
    check(page.locator("#nav a[data-route=help]").count() == 1 and page.locator("#cta").inner_text().strip() == "Upload my track", "menu: Help, and the upload button beside it")
    page.click("#nav a[data-route=help]")
    page.wait_for_selector(".help details", timeout=15000)
    check(page.inner_text("#nav a[aria-current]") == "Help", "Help page: Help lit in the menu")
    # questions and answers: one topic at a time, a search through all of them
    check(page.locator(".help section:not([hidden])").count() == 1 and page.locator(".help-nav button").count() == 6, "Help: six topics, one shown")
    page.click(".help-nav button[data-topic=numbers]")
    numbers = page.evaluate("document.querySelector('.help section:not([hidden])').textContent")  # answers folded too
    check(all(w in numbers for w in ("D+", "D−", "FAI")), "Help: the numbers explained")
    page.fill("#help-search", "several at once")
    check(page.locator(".help details:visible").count() == 1 and page.locator(".help details[open]:visible").count() == 1, "Help: the search finds and opens one answer")
    page.fill("#help-search", "")
    check("score" not in page.evaluate("document.querySelector('.help').textContent").lower(), "Help: no score")
    check(page.url.endswith("#/help"), "Help: the topics keep the address")
    page.goto(BASE + "#/all?view=list")
    page.wait_for_selector("tbody tr", timeout=30000)
    check("Country" not in page.inner_text("thead") and "Pilot" in page.inner_text("thead"), "All: no Country column, Pilot column kept")
    check("Hike (km)" in page.inner_text("thead") and "Fly (km)" in page.inner_text("thead"), "All: distances shown")
    page.screenshot(path=f"{SHOTS}/1-list.png")

    # the home page: the question, a search, the map, the latest outings (only the ones the server checked)
    page.goto(BASE)
    page.wait_for_selector(".warm-hero", timeout=30000)
    check(page.inner_text("h1") == "Where shall we fly?" and page.inner_text("#nav a[aria-current]") == "Home", "home: the question, Home lit")
    check(page.locator(".map-card").count() == 1 and "Open the map" in page.inner_text(".map-card"), "home: the map card")
    latest = page.locator(".home > .climb-cards > .climb-card")
    check(latest.count() == 1, "home: the latest outing, only the verified one (%d)" % latest.count())
    check("object" not in latest.first.inner_text().lower(), "home: a latest outing's card shows only its pilot, title and numbers")
    page.click("#nav-more summary")
    check(page.locator("#nav-more a[href='#/all']").is_visible() and page.locator("#nav-more a[href='#/ranking']").count() == 0, "menu: Explore opens on All outings; no Pilots for now")
    page.click("#nav-more summary")
    word = (ROW1.get("takeoff_name") or ROW1["title"])[:4]
    page.fill(".warm-search input", word)
    page.press(".warm-search input", "Enter")
    page.wait_for_selector("#m-results li[role=option]", timeout=15000)
    check(page.url.endswith("#/map") and page.input_value("#m-search") == word, "home: the search opens the map with its results")
    page.goto(BASE)
    page.wait_for_selector(".climb-card", timeout=30000)
    page.click(".climb-card")
    page.wait_for_selector(".stat.big", timeout=30000)
    check(page.locator("#nav a[aria-current]").count() == 0, "outing page: no entry lit in the menu")
    check(page.inner_text(".stat.big b") == f"{comma(NATIVE['dplus_m'])} m" and "Score" not in page.inner_text(".stats"), f"outing page D+ {page.inner_text('.stat.big b')} = Python {comma(NATIVE['dplus_m'])} m, no score")
    check("Pointe Haute" in page.inner_text("h1"), "title from the summit name: " + page.inner_text("h1"))
    page.wait_for_selector(".leaflet-container path.leaflet-interactive", timeout=15000)
    check(page.locator(".leaflet-container path.leaflet-interactive").count() >= 3, "map: track drawn in several parts (%d)" % page.locator(".leaflet-container path.leaflet-interactive").count())
    check(page.locator(".profile-svg polyline").count() >= 2, "profile drawn in several parts")
    box = page.locator(".profile-svg").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
    check("UTC" in page.inner_text(".readout") and " m · " in page.inner_text(".readout"), "profile read-out: " + page.inner_text(".readout"))
    check("Servoz" in page.inner_text(".places") or "Les Granges" in page.inner_text(".places"), "places block shows OSM names")
    with page.expect_download() as dl:
        page.click("text=Download GPX")
    gpx = open(dl.value.path(), encoding="utf-8").read()
    check(gpx.count("<trkpt") == len(RES1["trace"]["t"]) and "<ele>" in gpx, f"GPX download has {gpx.count('<trkpt')} points")
    page.screenshot(path=f"{SHOTS}/2-outing.png", full_page=True)

    page.goto(BASE + "#/ranking")
    page.wait_for_selector(".pilot-card", timeout=15000)
    cards = page.locator(".pilot-card")
    check(cards.count() == 2, "pilots: one card each (%d)" % cards.count())
    check("Alice" in cards.nth(0).inner_text() and "score" not in page.inner_text(".pilot-cards").lower() and "#" not in page.inner_text(".pilot-cards"), "pilots: by name, no rank, no score")
    check(f"{ROW1['walk_km']:.1f} km on foot" in cards.nth(0).inner_text() and f"{ROW1['flight_free_km']:.1f} km in flight" in cards.nth(0).inner_text(), "pilots: a pilot's km on foot and in flight")
    page.fill("#f-pilot", "bru")
    check(page.locator(".pilot-card").count() == 1 and "Bruno" in page.inner_text(".pilot-cards"), "pilots: the search keeps the matching cards")
    page.fill("#f-pilot", "")
    page.select_option("#f-year", "2026")
    page.wait_for_function("location.hash.includes('year=2026')")
    page.screenshot(path=f"{SHOTS}/3-ranking.png")

    page.goto(BASE + "#/map")
    page.wait_for_selector(".map-wide canvas.leaflet-heatmap-layer", timeout=15000)
    # the map opens on the current season when it has outings (ROW1's date decides), otherwise on all seasons
    now_winter = datetime.now().month in (11, 12, 1, 2, 3, 4)
    row_winter = int(ROW1["outing_date"][5:7]) in (11, 12, 1, 2, 3, 4)
    expected = ("winter" if now_winter else "summer") if now_winter == row_winter else ""
    season = lambda: page.get_attribute("#m-season button[aria-pressed=true]", "data-value")
    check(season() == expected, f"map opens on the current season ({expected or 'all seasons'})")
    page.click("#m-season button[data-value='']")
    # the tools above the map: search, season, filters; the legend under them; the scale at the top of the map
    check(page.locator(".map-toolbar #m-search").count() == 1 and page.locator(".map-toolbar #m-filters").count() == 1, "map: the tools in one bar")
    check(page.locator(".map-legend .heat-legend").count() == 1 and page.locator(".map-legend .key").count() == 3 and "few" not in page.inner_text(".map-legend") and "climb" not in page.inner_text(".map-legend"), "map: the legend above the map (heat map, itinerary, take-off, car park)")
    check(page.locator(".leaflet-top.leaflet-right .leaflet-control-scale").count() == 1, "map: the scale at the top")
    check(page.locator("#m-who").count() == 0, "map: no « My tracks » for a visitor")
    spots_n = lambda: page.inner_text("#m-count-spots")
    # the « Map » panel (site/basemaps.js): map style, what is shown, terrain
    page.click(".map-button")
    panel = page.locator(".map-panel").inner_text()
    check(all(w in panel for w in ("Topo", "Winter", "Satellite", "Heat map", "Take-offs", "Slopes", "More maps")),
          "map: the Map panel offers the styles and the switches")
    page.locator(".mp-row", has_text="Heat map").locator("input").click()
    check(page.locator(".heat-legend").is_hidden(), "map: switching the heat map off hides its legend")
    page.locator(".mp-row", has_text="Heat map").locator("input").click()
    page.click(".mp-close")
    check(page.locator(".map-panel").is_hidden(), "map: the Map panel closes")
    page.click(".map-wide .map-full-button")
    check("map-full" in (page.get_attribute(".map-wide", "class") or ""), "map: full screen")
    page.keyboard.press("Escape")
    check("map-full" not in (page.get_attribute(".map-wide", "class") or ""), "map: Escape leaves full screen")
    check(page.inner_text(".heat-legend").strip() == "Heat map", "map: heat map legend")
    winter = int(ROW1["outing_date"][5:7]) in (11, 12, 1, 2, 3, 4)
    page.click("#m-season button[data-value=winter]")
    check(spots_n() == ("1" if winter else "0"), "map: season filter")
    page.click("#m-season button[data-value='']")
    page.click("#m-filters")  # the year and climb filters sit in a panel under « Filters »
    page.select_option("#m-dplus", "0-500")  # ROW1 climbs more than 500 m
    check(spots_n() == "0" and "(1)" in page.inner_text("#m-filters") and "0 outings" in page.inner_text("#m-filters-pop"), "map: climb D+ filter, counted on the button")
    page.click("#m-filters-pop .fp-foot button.link")
    check(spots_n() == "1" and "(1)" not in page.inner_text("#m-filters"), "map: Clear empties the filters")
    page.click(".map-legend")
    check(page.locator("#m-filters-pop").is_hidden(), "map: a click elsewhere closes the filters")
    name = ROW1.get("takeoff_name") or ROW1["title"]
    page.fill("#m-search", name[:4])
    page.wait_for_selector("#m-results li[role=option]", timeout=5000)
    check(name in page.inner_text("#m-results"), f"map search finds {name!r} from {name[:4]!r}")
    page.fill("#m-search", "")
    page.locator(".tk.spot").first.click()
    page.wait_for_selector(".out-list li", timeout=15000)
    check(page.locator(".start-group").count() == 1 and "From " in page.inner_text(".start-group summary"), "take-off clicked: outings grouped by start place")
    check(page.locator(".out-list li").count() == 1 and "Alice" in page.inner_text(".out-list"), "take-off clicked: its outing is listed")
    check(page.locator(".spot-more").count() <= 1 and page.locator(".side details.spot-more[open]").count() == 0, "take-off clicked: more about it folded")
    # only the itineraries are drawn: an outing's climb appears while it is hovered or kept lit, never a flight
    check(page.locator(".leaflet-overlay-pane path.leaflet-interactive").count() == 0, "take-off clicked: no pilot's climb drawn by itself")
    page.locator(".out-list li").first.click()
    check(page.locator(".out-list li.on").count() == 1 and page.locator(".leaflet-overlay-pane path.leaflet-interactive").count() == 1, "outing clicked: kept lit, its climb drawn, no flight")
    page.screenshot(path=f"{SHOTS}/3b-map.png")

    page.goto(BASE + f"#/user/{UID}")
    page.wait_for_selector(".stats", timeout=15000)
    check(page.inner_text("h1") == "Alice" and comma(ROW1["dplus_m"]) in page.inner_text(".stats") and "score" not in page.inner_text(".stats").lower(), "user page: name and totals, no score")
    check("Waiting" not in page.inner_text("main"), "user page of someone else: no private uploads")
    stats_text = page.inner_text(".stats")
    check("Total distance on flight" in stats_text and "Countries" not in stats_text and "Longest free distance" not in stats_text, "user page: flight distance total, no Countries")
    check(page.locator("#f-year").count() == 1 and page.locator("#f-country").count() == 1, "user page: year and country filters")
    check(page.locator("thead button.sort").count() >= 6 and "Country" not in page.inner_text("thead"), "user page: outings sortable, no Country column")
    check(page.locator("#nav a[aria-current]").count() == 0, "user page: no entry lit in the menu")

    page.goto(BASE + "#/upload")
    page.wait_for_selector(".notice-info", timeout=15000)
    check("Sign in" in page.inner_text(".notice-info"), "upload asks to sign in")
    page.goto(BASE + "#/login")
    page.fill("#email", "alice@example.com")
    page.wait_for_function("document.querySelector('#captcha').textContent.includes('captcha')")
    page.click("form button.primary")
    page.wait_for_selector(".notice-ok", timeout=15000)
    check("alice@example.com" in page.inner_text(".notice-ok"), "sign-in link message: " + page.inner_text(".notice-ok")[:70])
    page.screenshot(path=f"{SHOTS}/4-login.png")
    errs = [l for l in logs if l.startswith(("error", "pageerror"))]
    check(not errs, "no console error (visitor)" + ("" if not errs else ": " + " || ".join(errs)[:500]))
    check(not external, "no request to any other site (visitor)" + ("" if not external else ": " + ", ".join(external[:4])))

    # ============ signed-in participant
    page, external, logs = new_page(b, signed_in=True)
    page.goto(BASE + "#/upload")
    page.wait_for_selector("#track", timeout=30000)
    check("Alice" in page.inner_text("#account"), "signed in as Alice")
    page.wait_for_selector("#engine-status[data-state=ready]", timeout=90000)
    check(True, "engine ready: " + page.inner_text("#engine-status"))

    page.set_input_files("#track", NOTIME)
    page.wait_for_selector(".notice-error", timeout=60000)
    check("timestamp" in page.inner_text(".notice-error"), "file without time refused: " + page.inner_text(".notice-error")[:90])

    # a track without a flight: listed at the bottom, with a button to mark the flight by hand on a map
    page.set_input_files("#track", SKI)
    page.wait_for_selector("#refused .refused-item", timeout=60000)
    check("Without a flight (1)" in page.inner_text("#refused h2") and "ski.gpx" in page.inner_text("#refused .refused-item"),
          "no-flight track listed below the result: " + page.inner_text("#refused .why").replace("\n", " ")[:80])
    check("flight" in page.inner_text("#refused .why").lower(), "the list gives the reason")
    page.screenshot(path=f"{SHOTS}/5a-refused.png", full_page=True)
    page.click("#refused a.button")
    page.wait_for_selector(".map-tall .leaflet-container, .map-tall.leaflet-container", timeout=15000)
    check(page.url.endswith("#/mark") and page.is_disabled("#mark-recalc"), "the button opens the map tool; recalculate waits for a flight")
    # click the take-off and the landing of the descent (the last part of the track)
    # the engine drew the ski descent as a vehicle ride (grey): take its two ends
    ends = page.evaluate("""() => {
      const map = document.querySelector('.map-tall')._map; let best = null;
      map.eachLayer((l) => { if (l.options && l.options.color === '#8796a3' && l.getLatLngs) {
        const p = l.getLatLngs(); if (!best || p.length > best.length) best = p; } });
      return best && [[best[0].lat, best[0].lng], [best[best.length - 1].lat, best[best.length - 1].lng]]; }""")
    check(ends is not None, "the descent is drawn as a vehicle ride")
    a, z = ends
    page.evaluate("""([a, z]) => { const m = document.querySelector('.map-tall')._map;
      m.fitBounds([a, z], { padding: [80, 80], animate: false }); }""", [a, z])
    page.wait_for_timeout(400)
    def click_at(ll):
        xy = page.evaluate("""(ll) => { const box = document.querySelector('.map-tall'); const p = box._map.latLngToContainerPoint(ll);
          const r = box.getBoundingClientRect(); return [r.left + p.x, r.top + p.y]; }""", ll)
        page.mouse.click(xy[0], xy[1])
    click_at(a)
    check("Now click the landing" in page.inner_text("#view .hint[role=status]"), "first click sets the take-off")
    click_at(z)
    check(page.locator(".mark-list li").count() == 1 and not page.is_disabled("#mark-recalc"), "second click marks a flight: " + page.inner_text(".mark-list").replace("\n", " "))
    page.screenshot(path=f"{SHOTS}/5b-mark.png", full_page=True)
    page.click("#mark-recalc")
    page.wait_for_selector("#mark-result .notice", timeout=60000)
    check("climbed on foot" in page.inner_text("#mark-result .notice-ok") if page.locator("#mark-result .notice-ok").count() else False,
          "recalculated with the hand-marked flight: " + page.inner_text("#mark-result").replace("\n", " ")[:120])
    page.click("#mark-publish")
    page.wait_for_selector("#mark-result .notice-ok:has-text('Published')", timeout=30000)
    marked = [json.loads(c[2]) for c in calls if c[0] == "BODY" and c[1] == "outings"]
    check(len(marked) == 1 and marked[0].get("manual_flights") and len(marked[0]["manual_flights"][0]) == 2,
          "publishing sends the marked flights: " + json.dumps(marked[0].get("manual_flights") if marked else None)[:60])
    check(marked and marked[0].get("status") == "published" and not ({"verified", "hidden", "user_id"} & set(marked[0])), "marked outing published like any other")
    calls.clear()  # the checks below count the uploads of the normal track
    page.click("text=Back to the list")
    page.wait_for_selector("#view h1:has-text('Upload a track')", timeout=15000)
    check(page.locator("#refused .refused-item").count() == 0, "back on Upload: the published track left the list")

    page.set_input_files("#track", GPX)
    page.wait_for_selector("#publish", timeout=60000)
    page.wait_for_selector("#preview .stat.big", timeout=60000)
    check(page.inner_text("#preview .stat.big b") == f"{comma(NATIVE['dplus_m'])} m", f"preview D+ {page.inner_text('#preview .stat.big b')} = Python {comma(NATIVE['dplus_m'])} m")
    stats = page.inner_text("#preview .stats")
    check(comma(NATIVE["dplus_m"]) in stats and comma(NATIVE["dminus_m"]) in stats, "preview D+ and D-")
    check("Pointe Haute" in page.inner_text("#preview h2"), "preview names the summit from OSM: " + page.inner_text("#preview h2"))
    page.wait_for_selector("#preview .leaflet-container path.leaflet-interactive", timeout=15000)
    check(any(c[0] == "ELEVATION" and c[1] >= 8 for c in calls), "terrain asked for about the flight's points")
    check(not page.is_disabled("#publish"), "publish enabled")
    page.screenshot(path=f"{SHOTS}/5-preview.png", full_page=True)
    page.click("#publish")
    page.wait_for_selector("#preview .notice-ok:has-text('Published')", timeout=30000)
    check("Validation pending" in page.inner_text("#preview .notice-ok").replace("\n", " "), "after publish: " + page.inner_text("#preview .notice-ok")[:60])
    posted = [c for c in calls if c[0] == "POST" and c[1].startswith("/storage/v1/object/track-files/")]
    inserted = [c for c in calls if c[0] == "BODY" and c[1] == "outings"]
    check(len(posted) == 1 and posted[0][1].split("/")[5] == UID, "file stored in the person's own folder")
    body = json.loads(inserted[0][2]) if inserted else {}
    check(body.get("status") == "published" and not ({"verified", "hidden", "user_id", "analysed_at", "reject_reason"} & set(body)),
          "published at once, never sends verified/hidden/user_id: " + ",".join(sorted(body))[:200])
    check(body.get("score") == body.get("dplus_m", 0) + body.get("dminus_m", 0) and body.get("score") == NATIVE["score"],
          "sent result equals the browser analysis")
    check("i_start" not in json.dumps(body.get("flights")), "flights sent without trace indexes")
    check(len(body.get("file_sha256", "")) == 64 and body.get("file_format") == "gpx", "hash and format of the file")

    page.goto(BASE + f"#/user/{UID}")
    page.wait_for_selector("h2", timeout=15000)
    check("Processing" in page.inner_text("main"), "own page shows the pending upload")
    check("Delete my account" in page.inner_text("main"), "own page offers account deletion")
    check(page.locator("#account a[href='#/me']").count() == 1, "own page: reached from the account bar")
    # signed in, the language and « Sign out » are in the menu of the pilot's name, not in the header
    check(page.locator("#lang-pick select").count() == 0, "signed in: no language selector in the header")
    page.click("#account .account-menu summary")
    menu = page.inner_text("#account .nav-menu")
    check("Sign out" in menu and page.locator("#account .nav-menu select").count() == 1, "signed in: the name's menu holds the page, the language and Sign out")
    # the pilot page drawn before stays until #/me is drawn: mark it, then wait for the new one
    page.evaluate("document.querySelector('.stats').dataset.before = '1'")
    page.click("#account a[href='#/me']")
    page.wait_for_selector(".stats:not([data-before])", timeout=15000)
    check(page.inner_text("h1") == "Alice" and "Total distance on flight" in page.inner_text(".stats") and page.locator("#f-year").count() == 1, "My H&Fs is the pilot page: name, totals, filters")
    page.select_option("#f-year", "2026")
    # read the address from here: a waiting function given as text would be refused by the page's script policy
    for _ in range(50):
        if "#/me?year=2026" in page.url:
            break
        page.wait_for_timeout(100)
    check("#/me?year=2026" in page.url, "My H&Fs: the filters stay on #/me (" + page.url.split("#")[-1] + ")")
    page.goto(BASE + "#/map")
    page.wait_for_selector(".map-wide canvas.leaflet-heatmap-layer", timeout=15000)
    page.click("#m-season button[data-value='']")
    page.click("#m-who button[data-value=mine]")
    check(page.inner_text("#m-count-spots") == "1", "map: « My tracks » keeps one's own outings")
    page.screenshot(path=f"{SHOTS}/6-me.png", full_page=True)
    errs = [l for l in logs if l.startswith(("error", "pageerror")) and "404" not in l]
    check(not errs, "no console error (participant)" + ("" if not errs else ": " + " || ".join(errs)[:500]))
    check(not external, "no request to any other site (participant)" + ("" if not external else ": " + ", ".join(external[:4])))

    # ============ languages (site/i18n.js): the browser's language, else English; the selector keeps a choice
    for locale, lang, nav, listed in [("de-CH", "de", "Karte", "Touren"), ("fr-CH", "fr", "Carte", "Sorties"),
                                      ("it-IT", "it", "Mappa", "Uscite"), ("es-ES", "en", "Map", "Outings")]:
        page, external, logs = new_page(b, locale=locale)
        page.goto(BASE + "#/all?view=list")
        page.wait_for_selector("tbody tr", timeout=30000)
        check(page.evaluate("document.documentElement.lang") == lang, f"language {locale}: page is in {lang}")
        check(nav in page.inner_text("#nav") and listed in page.inner_text("h1"), f"language {locale}: menu and title in {lang}")
        errs = [l for l in logs if l.startswith(("error", "pageerror")) and "404" not in l]
        check(not errs, f"language {locale}: no console error" + ("" if not errs else ": " + " || ".join(errs)[:300]))
        if locale == "de-CH":
            page.select_option("#lang-pick select", "fr")
            page.wait_for_selector('html[lang="fr"]', state="attached")
            check("Sorties" in page.inner_text("h1") and "Carte" in page.inner_text("#nav"), "selector: switching to French redraws the page")
            page.reload()
            page.wait_for_selector("tbody tr", timeout=30000)
            check(page.evaluate("document.documentElement.lang") == "fr", "selector: the choice is kept after a reload")

    # ============ phone
    page, external, logs = new_page(b, width=390, height=844)
    page.goto(BASE + "#/all?view=list")
    page.wait_for_selector("tbody tr", timeout=30000)
    check(page.evaluate("document.documentElement.scrollWidth") <= 390, "phone: list has no sideways scroll of the page")
    page.goto(BASE + f"#/outing/{ROW1['id']}")
    page.wait_for_selector(".stat.big", timeout=30000)
    check(page.evaluate("document.documentElement.scrollWidth") <= 390, "phone: outing page has no sideways scroll")
    page.screenshot(path=f"{SHOTS}/7-phone-outing.png", full_page=True)
    page.goto(BASE)
    page.wait_for_selector(".warm-hero", timeout=30000)
    check(page.evaluate("document.documentElement.scrollWidth") <= 390, "phone: home page has no sideways scroll")
    page.screenshot(path=f"{SHOTS}/7a-phone-home.png", full_page=True)
    page.goto(BASE + "#/map")
    page.wait_for_selector(".map-wide canvas.leaflet-heatmap-layer", timeout=15000)
    check(page.evaluate("document.documentElement.scrollWidth") <= 390, "phone: map page has no sideways scroll")
    page.screenshot(path=f"{SHOTS}/8-phone-map.png")
    b.close()

print("\nRESULT:", "all good" if not problems else f"{len(problems)} problem(s): " + "; ".join(problems))
httpd.shutdown()
sys.exit(1 if problems else 0)
