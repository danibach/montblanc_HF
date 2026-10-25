"""Median route lines, provisional take-off twins and outing titles (25 October 2026)."""
import math

from mbhf.routes import Climb, median_line, routes_of
from mbhf.sites import SiteIndex, attach, same_name
from mbhf.titles import clean_name, outing_title

LAT0, LON0 = 45.90, 6.43
M_LAT, M_LON = 1 / 110540.0, 1 / (111320.0 * math.cos(math.radians(LAT0)))


def way(offset_m, wiggle_m=0.0, n=60, east_m=0.0):
    """A climb 3 km north, ``offset_m`` east of the others, with a zigzag of ``wiggle_m``."""
    return [[LAT0 + k * 50 * M_LAT, LON0 + (east_m + offset_m + (wiggle_m if k % 2 else -wiggle_m)) * M_LON] for k in range(n)]


def test_the_median_line_runs_down_the_middle_of_the_climbs():
    climbs = [Climb(str(k), way(off, wiggle_m=20)) for k, off in enumerate((-30, -10, 0, 10, 30))]
    line = median_line(climbs)
    east = [(p[1] - LON0) / M_LON for p in line[1:-1]]
    assert max(abs(e) for e in east) < 15          # every climb strays 30 m and zigzags 20 m; the median does not
    assert abs((line[-1][0] - LAT0) / M_LAT - 59 * 50) < 30  # it still reaches the take-off


def test_one_climb_is_its_own_line_and_two_ways_stay_two_routes():
    assert median_line([Climb("a", way(0))]) == way(0)
    same = [Climb(str(k), way(off)) for k, off in enumerate((0, 40, 80))]
    other = [Climb("x", way(0, east_m=400)), Climb("y", way(30, east_m=400))]
    routes = routes_of(same + other)
    assert sorted(len(r["outing_ids"]) for r in routes) == [2, 3]


def test_ski_zigzags_80_percent_close_are_one_route():
    # the same way up, 80 % of the points within 150 m (Beauregard from La Clusaz: 104 m at 80 %)
    a = way(0)
    b = [[p[0], p[1] + (220 if k % 5 == 0 else 60) * M_LON] for k, p in enumerate(way(0))]
    assert len(routes_of([Climb("a", a), Climb("b", b)])) == 1


def test_provisional_twins_of_the_same_name_are_one_take_off():
    older = {"id": 1428, "source": "provisional", "name": "Pointe de Beauregard", "lat": 45.89349, "lon": 6.407655, "alt": 1633.5}
    younger = {"id": 2885, "source": "provisional", "name": "Pointe de Beauregard", "lat": 45.89452, "lon": 6.40475, "alt": 1623}
    index = SiteIndex([older, younger])
    # the two take-offs of the Pointe de Beauregard (north and south, 252 m apart) stay two: Dani, 25 October 2026
    assert attach(45.89452, 6.40475, 1625, SiteIndex([older]), "Pointe de Beauregard")[2] == "provisional"
    assert attach(45.89452, 6.40475, 1625, index, "Pointe de Beauregard")[0]["id"] == 2885
    # an outing 100 m from the older one, same name: the same take-off
    near = (older["lat"] + 100 / 111320, older["lon"])
    site, d, status = attach(near[0], near[1], 1633, SiteIndex([older]), "Pointe de Beauregard")
    assert site["id"] == 1428 and status == "auto" and 90 < d < 110
    # another name 100 m away is tied by distance alone (the twin rule needs the same name)
    assert attach(near[0], near[1], 1633, SiteIndex([older]), "Tête de Cabeau")[2] == "auto"
    # and 108 m higher or lower is another spot (La Tournette, summit and shoulder)
    assert attach(near[0], near[1], 1740, SiteIndex([older]), "Pointe de Beauregard")[2] == "provisional"
    assert same_name("Le Môle", "le mole") and not same_name("", "")


def test_speed_riding_only_take_offs_are_left_out():
    from mbhf.sites import ffvl_takeoffs
    base = {"flying_functions_text": "décollage", "latitude": 45.9, "longitude": 6.45, "altitude": 1500}
    sites = ffvl_takeoffs([{**base, "suid": 1, "toponym": "LA CLUSAZ - SPEED-RIDING", "possible_usages_text": "speed-riding"},
                           {**base, "suid": 2, "toponym": "PLAN PRAZ", "possible_usages_text": "parapente;speed-riding"},
                           {**base, "suid": 3, "toponym": "LAC", "possible_usages_text": "kite eau"}])
    assert [s["source_id"] for s in sites] == ["2"]


def test_titles():
    assert clean_name("LA CLUSAZ - AIGUILLE DES CALVAIRES (ETE)", ("La Clusaz",)) == "Aiguille des Calvaires"
    assert clean_name("La Clusaz - Cret du Loup (Ete 1er Mai au 31 Octobre)", ("La Clusaz",)) == "Crêt du Loup"
    assert clean_name("Cret-du-merle - ouvert du 1/5 au 31/10") == "Crêt-du-Merle"
    assert clean_name('Suchet "Sommet sud"') == "Suchet Sommet Sud"
    assert clean_name("Mont Blanc / Monte Bianco") == "Mont Blanc"
    assert clean_name("Décollage FFVL de Planpraz - Brévent Sud") == "Planpraz – Brévent Sud"
    assert clean_name("Decorum") == "Decorum"
    assert outing_title("Pointe de Beauregard", "Les Verrier") == "Pointe de Beauregard"
    assert outing_title("Crozet - les deux potes", "Crozet", "Crozet") == "Les Deux Potes"
    assert outing_title("Varan", "Varan") == "Varan"
    assert outing_title(None, "Passy") is None
