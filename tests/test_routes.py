from mbhf.routes import Access, Climb, joins, routes_of, same_route

# about 100 m: 0.0009 degree of latitude, 0.0013 degree of longitude at 45° N
UP = [[45.90 + 0.0009 * k, 6.45] for k in range(30)]  # 2.7 km straight north


def shifted(line, dlat=0.0, dlon=0.0):
    return [[a + dlat, b + dlon] for a, b in line]


def way(points, highway="path", **tags):
    return {"type": "way", "tags": {"highway": highway, **tags}, "geometry": [{"lat": a, "lon": b} for a, b in points]}


def parking(lat, lon):
    return {"type": "node", "lat": lat, "lon": lon, "tags": {"amenity": "parking"}}


def test_the_same_way_with_a_bit_of_gps_noise():
    a = Climb("a", UP, "La Clusaz")
    b = Climb("b", shifted(UP, dlon=0.0006), "La Clusaz")  # 47 m to the east
    assert same_route(a, b)


def test_another_way_up_is_another_route():
    a = Climb("a", UP)
    b = Climb("b", shifted(UP, dlon=0.006))  # 470 m to the east, all the way
    assert not same_route(a, b)


def test_a_stray_fix_is_tolerated():
    # one fix 200 m off (a GPS glitch, a short detour): well under 10 % of the way
    detour = [[lat, lon + (0.0026 if k == 15 else 0)] for k, (lat, lon) in enumerate(UP)]
    assert same_route(Climb("a", UP), Climb("b", detour))


def test_two_starts_that_meet_and_go_on_together_are_one_route():
    # starts 750 m apart, the same way from a third of the climb on: one itinerary (29 October 2026)
    b = [[45.90 + 0.0009 * k, 6.45 + 0.0001 * max(0, 12 - k) * 8] for k in range(30)]
    assert joins(Climb("b", b), Climb("a", UP))
    assert [sorted(r["outing_ids"]) for r in routes_of([Climb("a", UP), Climb("b", b)])] == [["a", "b"]]


def test_ways_that_only_meet_near_the_take_off_stay_two_routes():
    # every climb ends at the take-off: two ways 470 m apart that meet for the last 300 m are still two
    other = [[lat, lon + (0.006 if k < 27 else 0)] for k, (lat, lon) in enumerate(UP)]
    assert not same_route(Climb("a", UP), Climb("b", other))
    assert len(routes_of([Climb("a", UP), Climb("b", other)])) == 2


def test_ways_that_part_for_good_stay_two_routes():
    part = [[lat, lon + (0.005 if k >= 15 else 0)] for k, (lat, lon) in enumerate(UP)]  # half the way 400 m east
    assert not same_route(Climb("a", UP), Climb("b", part))


def test_a_climb_that_links_two_routes_merges_them():
    a, c = Climb("a", UP), Climb("c", shifted(UP, dlon=0.0034))  # 265 m apart: two routes
    b = Climb("b", shifted(UP, dlon=0.0017))  # in between: within 150 m of both
    assert [sorted(r["outing_ids"]) for r in routes_of([a, c, b])] == [["a", "b", "c"]]


def test_the_route_starts_at_the_most_used_start_and_is_named_after_it():
    # Les Moillats joins the way higher up; two climbs leave from the lower start
    climbs = [Climb("a", UP, "Les Esserts"), Climb("c", shifted(UP, dlon=0.0003), "Les Esserts"),
              Climb("b", UP[14:], "Les Moillats")]
    route, = routes_of(climbs)
    assert route["name"] == "From Les Esserts" and route["start_place"] == "Les Esserts"
    assert abs(route["line"][0][0] - UP[0][0]) < 0.0005  # drawn from that start: the walk-in is kept


def test_the_most_used_start_wins_over_a_lower_one():
    climbs = [Climb("low", UP, "Le Bas"), Climb("h1", UP[14:], "Le Haut"), Climb("h2", shifted(UP[14:], dlon=0.0003), "Le Haut")]
    route, = routes_of(climbs)
    assert route["start_place"] == "Le Haut" and abs(route["line"][0][0] - UP[14][0]) < 0.0005


def test_a_start_keeps_the_name_pilots_use():
    near_perroix = [[45.852 + 0.0009 * k, 6.212] for k in range(20)]
    route, = routes_of([Climb("a", near_perroix, "Les Esserts")])
    assert route["name"] == "From Perroix"
    route, = routes_of([Climb("a", UP, "Les Esserts")])  # elsewhere, Les Esserts stays Les Esserts
    assert route["name"] == "From Les Esserts"


def test_an_itinerary_never_starts_at_a_house():
    # the climb leaves a house in a field 400 m west of the path, then goes up the path; a parking stands at the
    # foot of the path, 60 m from where the climb joins it
    house = [[45.90, 6.45 - 0.0052 + 0.0013 * k] for k in range(4)]
    climb = Climb("a", house + UP, "Chez moi")
    access = Access([way(UP), way(shifted(UP[:3], dlon=-0.0008), "service", service="driveway"),
                     parking(45.90 - 0.0005, 6.45)], lat0=45.9)
    route, = routes_of([climb], access=access)
    start = route["line"][0]
    assert abs(start[1] - 6.45) < 0.0002 and start[0] < 45.90  # the parking, not the house
    assert abs(route["line"][1][1] - 6.45) < 0.0005  # then the path
    assert route["outing_ids"] == ["a"]


def test_a_climb_that_leaves_the_paths_higher_up_keeps_its_way():
    # La Tournette (30 October 2026): the path for the first 1.6 km, then the snow off the paths to the top. The
    # itinerary starts at the foot of the path, not at the summit's path 130 m below the take-off
    access = Access([way(UP[:17]), way(UP[-2:])], lat0=45.9)
    assert access.junction(UP) == 0
    house = [[45.90, 6.45 - 0.0052 + 0.0013 * k] for k in range(4)]
    assert access.junction(house + UP) == len(house)  # the way in from a house is still cut
    route, = routes_of([Climb("a", house + UP)], access=access)
    assert abs(route["line"][0][1] - 6.45) < 0.0002 and abs(route["line"][-1][0] - UP[-1][0]) < 0.0005


def test_a_start_is_named_after_the_official_landing_next_to_it():
    # Col de la Forclaz (30 October 2026): the climbs leave from the hamlet Le Vorget, 300 m from the FFVL landing
    # of Doussard: pilots say « from Doussard »
    doussard = {"name": "Doussard", "lat": UP[0][0] - 0.0027, "lon": UP[0][1]}  # 300 m below the start
    route, = routes_of([Climb("a", UP, "Le Vorget")], landings=[doussard])
    assert route["name"] == "From Doussard" and route["start_place"] == "Doussard"
    far = {**doussard, "lat": UP[0][0] - 0.0063}  # 700 m: too far, the hamlet keeps its name
    route, = routes_of([Climb("a", UP, "Le Vorget")], landings=[far])
    assert route["name"] == "From Le Vorget"


def test_landings_pilots_call_otherwise():
    at = lambda name: {"name": name, "lat": UP[0][0] - 0.0009, "lon": UP[0][1]}
    route, = routes_of([Climb("a", UP, "Talloires")], landings=[at("Planfait – Perroix")])
    assert route["name"] == "From Perroix"
    route, = routes_of([Climb("a", UP, "Saint-André-les-Alpes")], landings=[at("Aerogliss")])
    assert route["name"] == "From Saint-André-les-Alpes"


def test_private_ways_are_not_the_public_network():
    access = Access([way(UP, "service", service="driveway"), way(shifted(UP, dlon=0.003), access="private")], lat0=45.9)
    assert access.junction(UP) == 0 and not access.on_network((0.0, 0.0))


def test_no_parking_near_the_start_keeps_the_start():
    access = Access([way(UP), parking(45.90 - 0.003, 6.45)], lat0=45.9)  # 330 m below: too far
    route, = routes_of([Climb("a", UP)], access=access)
    assert abs(route["line"][0][0] - UP[0][0]) < 0.0002


def test_routes_named_after_their_start_with_variants():
    climbs = [Climb("a", UP, "La Clusaz"), Climb("b", shifted(UP, dlon=0.0004), "La Clusaz"),
              Climb("c", shifted(UP, dlon=0.006), "La Clusaz"), Climb("d", shifted(UP, dlat=0.02, dlon=0.02), "Les Verrier")]
    routes = routes_of(climbs)
    # a start with several ways: they are named apart (« via … » from OpenStreetMap, else « Main way », « Way 2 »)
    assert [(r["name"], r["start_place"], sorted(r["outing_ids"])) for r in routes] == [
        ("Main way", "La Clusaz", ["a", "b"]), ("Way 2", "La Clusaz", ["c"]), ("From Les Verrier", "Les Verrier", ["d"])]
    named = routes_of(climbs, via=lambda lat, lon, avoid: "Les Corbassières" if lon > UP[0][1] + 0.003 else None)
    assert [r["name"] for r in named] == ["Main way", "via Les Corbassières", "From Les Verrier"]
