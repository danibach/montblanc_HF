from mbhf.routes import Climb, central, routes_of, same_route

# about 100 m: 0.0009 degree of latitude, 0.0013 degree of longitude at 45° N
UP = [[45.90 + 0.0009 * k, 6.45] for k in range(30)]  # 2.7 km straight north


def shifted(line, dlat=0.0, dlon=0.0):
    return [[a + dlat, b + dlon] for a, b in line]


def test_the_same_way_with_a_bit_of_gps_noise():
    a = Climb("a", UP, "La Clusaz")
    b = Climb("b", shifted(UP, dlon=0.0006), "La Clusaz")  # 47 m to the east
    assert same_route(a, b)


def test_another_way_up_is_another_route():
    a = Climb("a", UP)
    b = Climb("b", shifted(UP, dlon=0.006))  # 470 m to the east, all the way
    assert not same_route(a, b)


def test_two_starts_that_meet_higher_up_are_two_routes():
    a = Climb("a", UP)
    b = Climb("b", [[45.90 + 0.0009 * k, 6.45 + 0.0001 * max(0, 12 - k) * 8] for k in range(30)])  # starts 750 m east
    assert not same_route(a, b)


def test_a_stray_fix_is_tolerated():
    # one fix 200 m off (a GPS glitch, a short detour): only the tip is farther than 150 m, well under 10 % of the way
    detour = [[lat, lon + (0.0026 if k == 15 else 0)] for k, (lat, lon) in enumerate(UP)]
    assert same_route(Climb("a", UP), Climb("b", detour))


def test_routes_named_after_their_start_with_variants():
    climbs = [Climb("a", UP, "La Clusaz"), Climb("b", shifted(UP, dlon=0.0004), "La Clusaz"),
              Climb("c", shifted(UP, dlon=0.006), "La Clusaz"), Climb("d", shifted(UP, dlat=0.02, dlon=0.02), "Les Verrier")]
    routes = routes_of(climbs)
    # a start with several ways: they are named apart (« via … » from OpenStreetMap, else « Main way », « Way 2 »)
    assert [(r["name"], r["start_place"], sorted(r["outing_ids"])) for r in routes] == [
        ("Main way", "La Clusaz", ["a", "b"]), ("Way 2", "La Clusaz", ["c"]), ("From Les Verrier", "Les Verrier", ["d"])]
    named = routes_of(climbs, via=lambda lat, lon, avoid: "Les Corbassières" if lon > UP[0][1] + 0.003 else None)
    assert [r["name"] for r in named] == ["Main way", "via Les Corbassières", "From Les Verrier"]


def test_the_central_climb_draws_the_route():
    west, mid, east = Climb("w", shifted(UP, dlon=-0.001)), Climb("m", UP), Climb("e", shifted(UP, dlon=0.001))
    assert central([west, east, mid]).id == "m"


def test_a_climb_that_links_two_routes_merges_them():
    a, c = Climb("a", UP), Climb("c", shifted(UP, dlon=0.0034))  # 265 m apart: two routes
    b = Climb("b", shifted(UP, dlon=0.0017))  # in between: within 150 m of both
    assert [sorted(r["outing_ids"]) for r in routes_of([a, c, b])] == [["a", "b", "c"]]
