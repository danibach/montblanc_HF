"""Check the built website in a real browser (Chromium via Playwright).

    python scripts/build_site.py --out _site
    pip install playwright && playwright install chromium
    python scripts/check_site.py _site

Uses a synthetic track (tests/synth_cyl.py); the result must equal the normal Python analysis.
Screenshots go to the folder given by --shots (default: a temporary folder).
"""
import json, os, sys, tempfile, threading, http.server, socketserver, functools, socket
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), os.path.join(ROOT, "tests")]
from synth_cyl import cyl_day, to_track  # noqa: E402
from test_browser import gpx_bytes  # noqa: E402
from mbhf.browser import analyse_json  # noqa: E402

SITE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_site")
HERE = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else tempfile.mkdtemp(prefix="site-check-")
os.makedirs(HERE, exist_ok=True)
open(f"{HERE}/journee.gpx", "wb").write(gpx_bytes(to_track(cyl_day())))
open(f"{HERE}/sans-heure.gpx", "wb").write(gpx_bytes(to_track(cyl_day()), with_time=False))
native = json.loads(analyse_json([("journee.gpx", open(f"{HERE}/journee.gpx", "rb").read(), None)]))["result"]
print("captures :", HERE)

class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
sock = socket.socket(); sock.bind(("127.0.0.1", 0)); PORT = sock.getsockname()[1]; sock.close()
socketserver.TCPServer.allow_reuse_address = True
httpd = socketserver.TCPServer(("127.0.0.1", PORT), functools.partial(H, directory=SITE))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/"

external, problems = [], []
def check(cond, label):
    print(("ok  " if cond else "ÉCHEC ") + label)
    if not cond: problems.append(label)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.on("request", lambda r: None if r.url.startswith(BASE) or r.url.startswith("blob:") or r.url.startswith("data:") else external.append(r.url))
    page = ctx.new_page()
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    page.goto(BASE)
    page.wait_for_selector("#engine-status[data-state=ready]", timeout=60000)
    check(True, "moteur prêt : " + page.inner_text("#engine-status"))

    # --- fichier sans heure : message en français ---
    page.set_input_files("#track-0", f"{HERE}/sans-heure.gpx")
    page.click("#submit")
    page.wait_for_selector("#form-error:not([hidden])", timeout=30000)
    msg = page.inner_text("#form-error")
    check("horodatage" in msg, "fichier sans heure refusé : " + msg[:90])

    # --- vraie analyse ---
    page.set_input_files("#track-0", f"{HERE}/journee.gpx")
    page.click("#submit")
    page.wait_for_selector("#result:not([hidden]) .big-time", timeout=60000)
    big = page.inner_text(".big-time")
    check(big == native["chrono"]["climb_hms"], f"chrono navigateur {big} = natif {native['chrono']['climb_hms']}")
    check(page.locator("#plan-wrap svg polyline").count() >= 3, "trace dessinée en plusieurs parties : %d" % page.locator("#plan-wrap svg polyline").count())
    check(page.locator("table").first.locator("tbody tr").count() == len(native["report"]["places"]), "tableau des lieux complet")
    check("en attente de validation" in page.inner_text(".notice-pending"), "message « en attente de validation » affiché")
    page.screenshot(path=f"{HERE}/1-resultat.png", full_page=False)
    page.locator("#trace-panel").screenshot(path=f"{HERE}/2-trace.png")

    # --- clic simple sur le profil : lecture du point ---
    prof = page.locator("#profile-wrap svg")
    box = prof.bounding_box()
    prof.click(position={"x": box["width"] * 0.5, "y": box["height"] * 0.5})
    check(page.inner_text("#readout").startswith("Point choisi"), "lecture d'un point : " + page.inner_text("#readout"))

    # --- corriger le décollage en cliquant sur le profil ---
    page.click("button[data-pick=takeoff]")
    check(page.is_visible("#pick-banner"), "bandeau de placement visible")
    # 95 % de la durée : pendant le vol / après, ici juste après le décollage détecté
    tr = native["trace"]; T = tr["t"][-1]
    want_sec = (native_tk := (__import__("datetime").datetime.fromisoformat(native["transitions"]["takeoff"]).timestamp() - __import__("datetime").datetime.fromisoformat(tr["t0"]).timestamp())) + 240
    m_l, m_r = 58, 14
    W = box["width"]
    x = m_l + want_sec / T * (W - m_l - m_r)
    prof.click(position={"x": x, "y": box["height"] * 0.5})
    state = page.inner_text("#cut-takeoff-state")
    check(state == "choisie, à recalculer", "décollage choisi : " + state)
    picked = page.input_value("#cut-takeoff")
    check(not page.is_disabled("#recompute"), "bouton recalculer actif")
    page.locator("#cuts-section").screenshot(path=f"{HERE}/3-transition-choisie.png")
    page.click("#recompute")
    page.wait_for_selector("#cut-status:has-text('recalculé')", timeout=60000)
    check(page.inner_text("#cut-takeoff-state") == "fixée par vous", "après recalcul : " + page.inner_text("#cut-takeoff-state"))
    rows = page.locator("table").first.locator("tbody tr")
    row = [rows.nth(i).inner_text() for i in range(rows.count()) if "Décollage" in rows.nth(i).inner_text()][0]
    check("fixée par vous" in row and picked[:5] in row, f"tableau : décollage fixé ({picked}) -> " + row.replace("\n", " | ")[:120])
    page.locator("#cuts-section").screenshot(path=f"{HERE}/4-apres-recalcul.png")

    # --- heure saisie hors trace ---
    page.fill("#cut-landing", "03:00:00")
    check("en dehors de la trace" in page.inner_text("#cut-status"), "heure hors trace refusée : " + page.inner_text("#cut-status"))

    # --- retour à la détection automatique ---
    page.click("text=Revenir à la détection automatique")
    page.wait_for_selector("#cut-status:has-text('détection automatique')", timeout=60000)
    check(page.inner_text("#cut-takeoff-state") == "détectée", "détection automatique rétablie")
    check(page.inner_text(".big-time") == native["chrono"]["climb_hms"], "chrono identique après retour")

    # --- téléchargement JSON ---
    with page.expect_download() as dl:
        page.click("text=Télécharger le résultat (JSON)")
    data = json.load(open(dl.value.path()))
    check(data["chrono"] == native["chrono"], "JSON téléchargé = résultat natif (chrono)")

    # --- mobile ---
    m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    m.on("request", lambda r: None if r.url.startswith(BASE) or r.url.startswith("blob:") or r.url.startswith("data:") else external.append(r.url))
    mp = m.new_page()
    mp.goto(BASE)
    mp.wait_for_selector("#engine-status[data-state=ready]", timeout=60000)
    mp.screenshot(path=f"{HERE}/5-mobile-accueil.png")
    mp.set_input_files("#track-0", f"{HERE}/journee.gpx")
    mp.click("#submit")
    mp.wait_for_selector("#result:not([hidden]) .big-time", timeout=60000)
    sw = mp.locator("html").evaluate("e => e.scrollWidth")
    check(sw <= 390, f"mobile sans défilement horizontal de la page ({sw}px)")
    mp.locator("#trace-panel").screenshot(path=f"{HERE}/6-mobile-trace.png")
    mp.locator("#cuts-section").screenshot(path=f"{HERE}/7-mobile-transitions.png")
    b.close()

errs = [l for l in logs if l.startswith(("error", "pageerror"))]
check(not errs, "aucune erreur dans la console" + ("" if not errs else " : " + " || ".join(errs)[:400]))
check(not external, "aucune requête vers un autre site" + ("" if not external else " : " + ", ".join(external[:5])))
print("\nRÉSULTAT :", "tout est bon" if not problems else f"{len(problems)} problème(s)")
httpd.shutdown()
sys.exit(1 if problems else 0)
