import io

import pytest
from synth_cyl import cyl_day, to_track
from test_transport import TRAM, UNKNOWN

pytest.importorskip("flask")
pytest.importorskip("matplotlib")

from mbhf.transport import LineSet
from mbhf.web import create_app


def gpx_bytes(track) -> bytes:
    rows = "".join(
        f'<trkpt lat="{p.lat:.6f}" lon="{p.lon:.6f}"><ele>{p.alt:.1f}</ele><time>{p.t.strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>'
        for p in track.points
    )
    return (
        '<?xml version="1.0"?><gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{rows}</trkseg></trk></gpx>"
    ).encode()


@pytest.fixture(scope="module")
def day_gpx():
    return gpx_bytes(to_track(cyl_day()))


@pytest.fixture()
def client():
    app = create_app(lines=LineSet([]), schedule=UNKNOWN)
    return app.test_client()


def post(client, files, **form):
    data = {"track": [(io.BytesIO(b), name) for name, b in files], "mode": [""] * len(files), **form}
    return client.post("/analyse", data=data, content_type="multipart/form-data")


def test_the_form_page_and_its_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Analyser ma trace" in r.data
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "unsafe-inline" not in csp
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["Referrer-Policy"] == "no-referrer"
    assert client.get("/healthz").json == {"status": "ok"}


def test_a_valid_track_gives_the_time_the_places_and_the_graph(client, day_gpx):
    r = post(client, [("my day.gpx", day_gpx)])
    assert r.status_code == 200
    html = r.data.decode()
    assert "Lieux détectés" in html and "Décollage" in html and "Dernière sortie du cylindre du Nid d" in html
    assert 'src="data:image/png;base64,' in html
    assert "Résultat provisoire" in html                      # no line data loaded in this fixture
    assert r.headers["Cache-Control"] == "no-store"


def test_no_file_is_a_clear_error(client):
    r = client.post("/analyse", data={}, content_type="multipart/form-data")
    assert r.status_code == 400 and b"Choisissez au moins un fichier" in r.data


def test_wrong_extension_empty_file_and_untimed_kml_are_explained(client):
    assert b"pas accept" in post(client, [("notes.txt", b"hello")]).data
    assert b"le fichier est vide" in post(client, [("a.gpx", b"")]).data
    kml = b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><LineString><coordinates>6.7,45.8,1000 6.71,45.81,1010</coordinates></LineString></Placemark></Document></kml>'
    r = post(client, [("Rando-Vol.kml", kml)])
    assert r.status_code == 400
    assert b"horodatages sont obligatoires" in r.data and b"Rando-Vol.kml" in r.data
    assert b"/tmp" not in r.data and b"mbhf-" not in r.data  # no temporary path leaks


def test_a_hostile_file_name_is_escaped(client):
    r = post(client, [("<script>alert(1)</script>.txt", b"x")])
    assert b"<script>alert(1)" not in r.data


def test_a_bad_manual_time_is_refused_and_kept_in_the_form(client, day_gpx):
    r = post(client, [("d.gpx", day_gpx)], takeoff="tomorrow morning")
    assert r.status_code == 400 and b"impossible de lire" in r.data and b"tomorrow morning" in r.data


def test_oversized_uploads_get_a_clear_message():
    app = create_app(lines=LineSet([]), schedule=UNKNOWN)
    app.config["MAX_CONTENT_LENGTH"] = 1000
    r = app.test_client().post(
        "/analyse", data={"track": (io.BytesIO(b"x" * 5000), "big.gpx")}, content_type="multipart/form-data"
    )
    assert r.status_code == 413 and b"d\xc3\xa9passent" in r.data


def test_a_tram_ride_is_shown_as_flagged():
    app = create_app(lines=TRAM, schedule=UNKNOWN)
    r = post(app.test_client(), [("ride.gpx", gpx_bytes(to_track(cyl_day(ascent_a_s=3600))))])
    html = r.data.decode()
    assert r.status_code == 200 and "Cette trace est signalée" in html and "Voies et remontées pendant la montée" in html
    assert "Résultat provisoire" not in html                  # the check ran


def test_two_files_with_their_modes(client):
    from mbhf.models import Track

    tr = to_track(cyl_day())
    cut = next(i for i, p in enumerate(tr.points) if p.alt > 4500)
    walk = Track(points=tr.points[:cut], source="w", fmt="gpx")
    rest = Track(points=tr.points[cut:], source="f", fmt="gpx")
    data = {"track": [(io.BytesIO(gpx_bytes(walk)), "walk.gpx"), (io.BytesIO(gpx_bytes(rest)), "flight.gpx")],
            "mode": ["walk", "flight"]}
    r = client.post("/analyse", data=data, content_type="multipart/form-data")
    assert r.status_code == 200 and "Lieux détectés".encode() in r.data
