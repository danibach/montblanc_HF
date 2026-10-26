"""The spots of the take-off map (site/explorer.js, groupTakeoffs), run with Node: no browser, no Leaflet."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "site"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def spots(tmp_path, rows, sites):
    """groupTakeoffs(rows, sites) as JSON (the sets as sorted lists), from a copy of the page's modules."""
    for path in SITE.glob("*.js"):  # explorer.js and the modules it imports (sectors.js, ffvl.js…)
        shutil.copy(path, tmp_path / path.name)
    shutil.copytree(SITE / "i18n", tmp_path / "i18n")  # the texts of the page (site/i18n.js loads them)
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "run.mjs").write_text(
        "globalThis.window = {};  // the page reads window (Leaflet) when it loads\n"
        "const { groupTakeoffs } = await import('./explorer.js');\n"
        f"const out = groupTakeoffs({json.dumps(rows)}, {json.dumps(sites)});\n"
        "console.log(JSON.stringify(out.map((s) => ({ name: s.name, n: s.outings.length, pilots: s.pilots,"
        " ids: s.outings.map((o) => o.id).sort(), siteIds: [...s.siteIds].sort((a, b) => a - b), source: s.site && s.site.source }))));\n")
    done = subprocess.run([NODE, "run.mjs"], cwd=tmp_path, capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def outing(oid, lat, lon, site_id=None, pilot="p"):
    return {"id": oid, "takeoff_lat": lat, "takeoff_lon": lon, "takeoff_alt": 4700, "takeoff_name": "Mont Blanc / Monte Bianco",
            "user_id": pilot, "takeoff_site_id": site_id}


MONT_BLANC = [
    {"id": 962, "name": "Mont Blanc", "lat": 45.8327, "lon": 6.8652, "alt": 4800, "source": "ffvl"},
    {"id": 1451, "name": "Mont Blanc / Monte Bianco", "lat": 45.83276, "lon": 6.86522, "alt": 4673, "source": "provisional"},
]


def test_take_offs_a_few_metres_apart_are_one_spot_with_all_their_outings(tmp_path):
    # 7 m apart: the 2025 outing is tied to the official take-off, the 2023 one to a provisional take-off
    rows = [outing("o2025", 45.83253, 6.86553, 962), outing("o2023", 45.83276, 6.86522, 1451)]
    [spot] = spots(tmp_path, rows, MONT_BLANC)
    assert spot["name"] == "Mont Blanc" and spot["source"] == "ffvl"  # the official take-off keeps its name
    assert spot["ids"] == ["o2023", "o2025"] and spot["n"] == 2
    assert spot["siteIds"] == [962, 1451]  # so the routes of both are drawn


def test_a_pilot_counts_once_in_a_merged_spot(tmp_path):
    rows = [outing("a", 45.8327, 6.8652, 962, "dani"), outing("b", 45.83276, 6.86522, 1451, "dani"),
            outing("c", 45.8327, 6.8652, 962, "sarah")]
    [spot] = spots(tmp_path, rows, MONT_BLANC)
    assert spot["n"] == 3 and spot["pilots"] == 2


def test_take_offs_farther_than_50_m_stay_apart(tmp_path):
    far = {"id": 7, "name": "Plus bas", "lat": 45.8327 + 0.0006, "lon": 6.8652, "alt": 4700, "source": "osm"}  # about 67 m
    rows = [outing("a", 45.8327, 6.8652, 962), outing("b", 45.8333, 6.8652, 7)]
    found = spots(tmp_path, rows, [MONT_BLANC[0], far])
    assert sorted(s["name"] for s in found) == ["Mont Blanc", "Plus bas"]


def test_two_official_take_offs_stay_apart_even_40_m_away(tmp_path):
    # the Suchet's two summits, both mapped in OpenStreetMap on purpose
    sud = {"id": 1, "name": "Suchet Sommet sud", "lat": 46.7700, "lon": 6.4500, "alt": 1590, "source": "osm"}
    nord = {"id": 2, "name": "Suchet Sommet Nord", "lat": 46.7700 + 0.00036, "lon": 6.4500, "alt": 1590, "source": "osm"}  # 40 m
    rows = [outing("a", 46.7700, 6.4500, 1), outing("b", 46.77036, 6.4500, 2), outing("c", 46.77036, 6.4500, 2)]
    found = spots(tmp_path, rows, [sud, nord])
    assert sorted((s["name"], s["n"]) for s in found) == [("Suchet Sommet Nord", 2), ("Suchet Sommet sud", 1)]


def test_provisional_twins_become_one_spot(tmp_path):
    # Tête Pelouse: two provisional take-offs 24 m apart, made because the altitudes differed by 111 m
    a = {"id": 10, "name": "Tête Pelouse", "lat": 45.9000, "lon": 6.7000, "alt": 2000, "source": "provisional"}
    b = {"id": 11, "name": "Tête Pelouse", "lat": 45.9000 + 0.000216, "lon": 6.7000, "alt": 2111, "source": "provisional"}
    rows = [outing("a", 45.9000, 6.7000, 10), outing("b", 45.900216, 6.7000, 11), outing("c", 45.900216, 6.7000, 11)]
    [spot] = spots(tmp_path, rows, [a, b])
    assert spot["n"] == 3 and spot["siteIds"] == [10, 11] and spot["name"] == "Tête Pelouse"


def test_a_loose_outing_next_to_an_official_take_off_joins_it(tmp_path):
    rows = [outing("a", 45.8327, 6.8652, 962), outing("b", 45.83274, 6.86523, None)]
    [spot] = spots(tmp_path, rows, [MONT_BLANC[0]])
    assert spot["n"] == 2 and spot["siteIds"] == [962]
