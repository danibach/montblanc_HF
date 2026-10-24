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
from synth import as_track, gpx_bytes, hike_and_fly, two_flights  # noqa: E402
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
open(NOTIME, "wb").write(gpx_bytes(as_track(hike_and_fly()), with_time=False))
print("screenshots:", SHOTS)

# ---------------------------------------------------------------- pretend servers

calls = []
CORS = {"access-control-allow-origin": "*", "access-control-expose-headers": "content-range,content-type"}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


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
        rows = [{"user_id": UID, "display_name": "Alice", "outings": 1, "dplus": ROW1["dplus_m"], "dminus": ROW1["dminus_m"], "score": ROW1["score"]}]
        if body.get("p_year") != 2025:
            rows.append({"user_id": OTHER, "display_name": "Bruno", "outings": 1, "dplus": ROW2["dplus_m"], "dminus": ROW2["dminus_m"], "score": ROW2["score"]})
        return j(route, sorted(rows, key=lambda r: -r["score"]))
    if u.path == "/rest/v1/rpc/map_outings":
        # like the SQL function: only the verified outings (ROW1), not the one waiting for the server (ROW2)
        return j(route, [[r["id"], r["takeoff_lat"], r["takeoff_lon"], r["takeoff_alt"], r["takeoff_name"], r["title"], r["outing_date"],
                          r["dplus_m"], r["walk_km"], r["start_place"], r["profiles"]["display_name"], r["summit_alt"],
                          r["user_id"], None]  # no stored climb: the page reads the track
                         for r in ROWS if r["verified"] and r["takeoff_lat"] is not None])
    if u.path in ("/rest/v1/rpc/map_takeoff_sites", "/rest/v1/rpc/map_routes"):
        return j(route, [])  # no take-off register nor routes: the map groups the outings itself
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


def new_page(browser, signed_in=False, width=1280, height=900):
    ctx = browser.new_context(viewport={"width": width, "height": height}, accept_downloads=True)
    if signed_in:
        ctx.add_init_script(session_script())
    page = ctx.new_page()
    external, logs = [], []
    page.route(re.compile(r"https://[^/]*supabase\.co/.*"), supabase)
    page.route(re.compile(r"https://overpass-api\.de/.*"), lambda r: j(r, overpass_for(NATIVE)))
    page.route(re.compile(r"https://api\.open-meteo\.com/v1/elevation.*"), elevation_answer)
    page.route(re.compile(r"https://[^/]*tile\.opentopomap\.org/.*"), lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    page.route(re.compile(r"https://challenges\.cloudflare\.com/.*"), lambda r: r.fulfill(
        status=200, content_type="application/javascript",
        body="window.turnstile={render:function(e,o){e.textContent='[captcha]';o.callback('test-token')},reset:function(){}};"))
    page.on("request", lambda r: None if r.url.startswith((BASE, "blob:", "data:")) or re.match(r"https://([^/]*supabase\.co|overpass-api\.de|api\.open-meteo\.com|[^/]*tile\.opentopomap\.org|challenges\.cloudflare\.com)/", r.url) else external.append(r.url))
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    return page, external, logs


with sync_playwright() as p:
    b = p.chromium.launch()

    # ============ anonymous visitor
    page, external, logs = new_page(b)
    page.goto(BASE + "#/all")
    page.wait_for_selector("tbody tr", timeout=30000)
    rows = page.locator("tbody tr")
    check(rows.count() == 2, f"list shows the 2 published outings ({rows.count()})")
    check(page.inner_text("main").count("Validation pending") == 1, "only the unverified outing carries the badge")
    first = rows.nth(0).inner_text()
    check("Alice" in first and comma(ROW1["score"]) in first, "list row: pilot and score " + first.replace("\t", " | ")[:80])
    check(page.locator("#f-year option").count() == 2 and page.locator("#f-country option").count() == 2, "year and country filters filled")
    check("Sign in" in page.inner_text("#account"), "anonymous: Sign in link")
    check("Country" not in page.inner_text("thead") and "Pilot" in page.inner_text("thead"), "All: no Country column, Pilot column kept")
    check("Hike (km)" in page.inner_text("thead") and "Fly (km)" in page.inner_text("thead"), "All: distances shown")
    page.screenshot(path=f"{SHOTS}/1-list.png")

    page.goto(BASE)
    page.wait_for_selector("tbody tr", timeout=30000)
    check(page.url.endswith("#/all"), "anonymous: the entry page sends the visitor to All")
    page.click("tbody tr:first-child a[href^='#/outing']")
    page.wait_for_selector(".stat.big", timeout=30000)
    check(page.locator("#nav a[aria-current]").count() == 0, "outing page: no entry lit in the menu")
    check(page.inner_text(".stat.big b") == comma(NATIVE["score"]), f"outing page score {page.inner_text('.stat.big b')} = Python {comma(NATIVE['score'])}")
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
    page.wait_for_selector("tbody tr", timeout=15000)
    check(page.locator("tbody tr").count() == 2 and "Alice" in page.locator("tbody tr").nth(0).inner_text() or "Bruno" in page.locator("tbody tr").nth(0).inner_text(), "ranking: 2 pilots")
    best = max(ROW1["score"], ROW2["score"])
    check(comma(best) in page.locator("tbody tr").nth(0).inner_text(), "ranking: best score first")
    page.select_option("#f-year", "2026")
    page.wait_for_function("location.hash.includes('year=2026')")
    page.screenshot(path=f"{SHOTS}/3-ranking.png")

    page.goto(BASE + "#/map")
    page.wait_for_selector(".map-wide canvas.leaflet-heatmap-layer", timeout=15000)
    # the map opens on the current season when it has outings (ROW1's date decides), otherwise on all seasons
    now_winter = datetime.now().month in (11, 12, 1, 2, 3, 4)
    row_winter = int(ROW1["outing_date"][5:7]) in (11, 12, 1, 2, 3, 4)
    expected = ("winter" if now_winter else "summer") if now_winter == row_winter else ""
    check(page.input_value("#m-season") == expected, f"map opens on the current season ({expected or 'all seasons'})")
    page.select_option("#m-season", "")
    check("1 take-off spot, 1 confirmed outing" in page.inner_text(".side"), "map counts only the verified outing: " + page.inner_text(".side")[:90])
    check(page.locator(".leaflet-control-layers input[type=checkbox]").count() == 2, "map: heat map and take-offs can be switched")
    check("pilots" in page.inner_text(".heat-legend"), "map: heat map legend")
    winter = int(ROW1["outing_date"][5:7]) in (11, 12, 1, 2, 3, 4)
    page.select_option("#m-season", "winter")
    check(("1 take-off spot," if winter else "0 take-off spots,") in page.inner_text(".side"), "map: season filter")
    page.select_option("#m-season", "")
    page.click(".climb-filters summary")  # the climb filters sit in a closed <details>
    page.select_option("#m-dplus", "0-500")  # ROW1 climbs more than 500 m
    check("0 take-off spots," in page.inner_text(".side"), "map: climb D+ filter")
    page.select_option("#m-dplus", "")
    name = ROW1.get("takeoff_name") or ROW1["title"]
    page.fill("#m-search", name[:4])
    page.wait_for_selector("#m-results li[role=option]", timeout=5000)
    check(name in page.inner_text("#m-results"), f"map search finds {name!r} from {name[:4]!r}")
    page.fill("#m-search", "")
    page.locator(".tk.spot").first.click()
    page.wait_for_selector(".out-list li", timeout=15000)
    check(page.locator(".start-group").count() == 1 and "From " in page.inner_text(".start-group summary"), "take-off clicked: outings grouped by start place")
    check(page.locator(".out-list li").count() == 1 and "Alice" in page.inner_text(".out-list"), "take-off clicked: its outing is listed")
    check(page.locator(".leaflet-overlay-pane path.leaflet-interactive").count() == 1, "take-off clicked: one climb drawn, no flight")
    page.locator(".out-list li").first.click()
    check(page.locator(".out-list li.on").count() == 1, "outing clicked: kept lit")
    page.screenshot(path=f"{SHOTS}/3b-map.png")

    page.goto(BASE + f"#/user/{UID}")
    page.wait_for_selector(".stat.big", timeout=15000)
    check(page.inner_text("h1") == "Alice" and page.inner_text(".stat.big b") == comma(ROW1["score"]), "user page: name and total score")
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

    page.set_input_files("#track", GPX)
    page.wait_for_selector("#publish", timeout=60000)
    page.wait_for_selector("#preview .stat.big", timeout=60000)
    check(page.inner_text("#preview .stat.big b") == comma(NATIVE["score"]), f"preview score {page.inner_text('#preview .stat.big b')} = Python {comma(NATIVE['score'])}")
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
    page.screenshot(path=f"{SHOTS}/6-me.png", full_page=True)
    errs = [l for l in logs if l.startswith(("error", "pageerror")) and "404" not in l]
    check(not errs, "no console error (participant)" + ("" if not errs else ": " + " || ".join(errs)[:500]))
    check(not external, "no request to any other site (participant)" + ("" if not external else ": " + ", ".join(external[:4])))

    # ============ phone
    page, external, logs = new_page(b, width=390, height=844)
    page.goto(BASE + "#/all")
    page.wait_for_selector("tbody tr", timeout=30000)
    check(page.evaluate("document.documentElement.scrollWidth") <= 390, "phone: list has no sideways scroll of the page")
    page.goto(BASE + f"#/outing/{ROW1['id']}")
    page.wait_for_selector(".stat.big", timeout=30000)
    check(page.evaluate("document.documentElement.scrollWidth") <= 390, "phone: outing page has no sideways scroll")
    page.screenshot(path=f"{SHOTS}/7-phone-outing.png", full_page=True)
    page.goto(BASE + "#/map")
    page.wait_for_selector(".map-wide canvas.leaflet-heatmap-layer", timeout=15000)
    check(page.evaluate("document.documentElement.scrollWidth") <= 390, "phone: map page has no sideways scroll")
    page.screenshot(path=f"{SHOTS}/8-phone-map.png")
    b.close()

print("\nRESULT:", "all good" if not problems else f"{len(problems)} problem(s): " + "; ".join(problems))
httpd.shutdown()
sys.exit(1 if problems else 0)
