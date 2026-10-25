from mbhf.sites import (SiteIndex, attach, ffvl_takeoffs, osm_takeoffs, pretty_name, provisional_site,
                        without_doubles)

# about 100 m north is 0.0009 degree of latitude
FFVL = [
    {"suid": 1, "toponym": "LA CLUSAZ - AIGUILLE DES CALVAIRES (ETE)", "flying_functions_text": "décollage",
     "city": "LA CLUSAZ", "latitude": 45.9000, "longitude": 6.4500, "altitude": 2035, "status": "actif", "wind_orientations_ok": "NW;W",
     "hike_and_fly_description": "  45 min from the car park  "},
    {"suid": 2, "toponym": "LA CLUSAZ - ATTERRISSAGE", "flying_functions_text": "atterrissage",
     "latitude": 45.9100, "longitude": 6.4300, "altitude": 1050},
]


def test_names_in_capitals_become_readable():
    assert pretty_name("LA CLUSAZ - AIGUILLE DES CALVAIRES (ETE)") == "La Clusaz - Aiguille des Calvaires (Ete)"
    assert pretty_name("COL DE L'ARPETTAZ") == "Col de l'Arpettaz"
    assert pretty_name("Planfait") == "Planfait"  # already readable: left as it is


def test_ffvl_keeps_take_offs_only():
    sites = ffvl_takeoffs(FFVL)
    assert [s["source_id"] for s in sites] == ["1"]
    s = sites[0]
    # just the take-off's name: no village, no season (Sarah, 25 October 2026)
    assert s["name"] == "Aiguille des Calvaires" and s["alt"] == 2035 and s["wind_ok"] == "NW;W"
    assert s["hike_and_fly"] == "45 min from the car park"


def test_ffvl_names_without_opening_dates():
    raw = [{"suid": 3, "toponym": "Cret-du-merle - ouvert du 1/5 au 31/10", "flying_functions_text": "décollage",
            "city": "ARACHES-LA-FRASSE", "latitude": 46.0, "longitude": 6.6}]
    assert ffvl_takeoffs(raw)[0]["name"] == "Crêt-du-Merle"


def test_osm_named_take_offs_without_landings():
    elements = [
        {"type": "node", "id": 1, "lat": 46.0, "lon": 7.0, "tags": {"sport": "free_flying", "name": "Berneuse", "ele": "2048"}},
        {"type": "way", "id": 2, "center": {"lat": 46.1, "lon": 7.1}, "tags": {"free_flying:site": "takeoff", "name": "Mauborget"}},
        {"type": "node", "id": 3, "lat": 46.2, "lon": 7.2, "tags": {"sport": "free_flying", "name": "Atterrissage Leysin"}},
        {"type": "node", "id": 4, "lat": 46.3, "lon": 7.3, "tags": {"sport": "free_flying"}},  # no name
    ]
    sites = osm_takeoffs(elements)
    assert [(s["name"], s["source_id"], s["alt"]) for s in sites] == [("Berneuse", "node/1", 2048.0), ("Mauborget", "way/2", None)]


def test_an_osm_take_off_next_to_an_ffvl_one_is_the_same():
    ffvl = ffvl_takeoffs(FFVL)
    near = {"source": "osm", "source_id": "node/9", "name": "Calvaires", "lat": 45.9003, "lon": 6.4500, "alt": None}
    far = {"source": "osm", "source_id": "node/8", "name": "Elsewhere", "lat": 45.95, "lon": 6.45, "alt": None}
    assert without_doubles(ffvl, [near, far]) == [far]


def test_attach_by_distance_and_altitude():
    index = SiteIndex(ffvl_takeoffs(FFVL))
    site, d, status = attach(45.9005, 6.4500, 2030, index)  # 56 m
    assert status == "auto" and site["source_id"] == "1" and d < 100
    site, d, status = attach(45.9015, 6.4500, 2030, index)  # 167 m
    assert status == "to_confirm" and site["source_id"] == "1"
    assert attach(45.9030, 6.4500, 2030, index)[2] == "provisional"  # 334 m
    assert attach(45.9005, 6.4500, 1800, index)[2] == "provisional"  # close, but 235 m lower: the other side


def test_an_official_take_off_within_50_m_wins_whatever_the_altitude():
    # the Mont Blanc: the FFVL gives 4 800 m, an outing took off at 4 673 m (127 m lower) and used to get a
    # provisional take-off 7 m away, so its outings and its routes were kept apart from the official one
    official = ffvl_takeoffs([{"suid": 962, "toponym": "MONT BLANC", "flying_functions_text": "décollage",
                               "latitude": 45.8327, "longitude": 6.8652, "altitude": 4800}])
    index = SiteIndex(official)
    assert attach(45.83276, 6.86522, 4673, index)[2] == "auto"
    first = {"id": "a", "takeoff_name": "Mont Blanc / Monte Bianco", "summit_name": None, "title": "x",
             "takeoff_lat": 45.83276, "takeoff_lon": 6.86522, "takeoff_alt": 4673}
    provisional = provisional_site(first)
    provisional["id"] = 1451
    index.add(provisional)  # the outing sits exactly on the provisional take-off, 7 m from the official one
    site, d, status = attach(45.83276, 6.86522, 4673, index)
    assert site["source"] == "ffvl" and status == "auto" and d < 50
    # the altitude test still separates the two sides of a ridge farther than 50 m away
    assert attach(45.9005, 6.4500, 1800, SiteIndex(ffvl_takeoffs(FFVL)))[2] == "provisional"


def test_provisional_twins_end_up_as_one_and_official_neighbours_stay_two():
    # Tête Pelouse: two provisional take-offs 24 m apart (altitudes 111 m apart): an outing on the younger one is
    # tied to the older, which leaves the younger unused (the sync removes it)
    index = SiteIndex()
    for sid, lat, alt in ((10, 45.9000, 2000), (11, 45.900216, 2111)):
        index.add({"id": sid, "source": "provisional", "lat": lat, "lon": 6.7000, "alt": alt})
    site, _, status = attach(45.900216, 6.7000, 2111, index)
    assert site["id"] == 10 and status == "auto"
    # the Suchet: two OpenStreetMap summits 40 m apart, mapped on purpose: each outing keeps the nearer one
    osm = SiteIndex()
    for sid, lat in ((1, 46.7700), (2, 46.77036)):
        osm.add({"id": sid, "source": "osm", "lat": lat, "lon": 6.45, "alt": 1590})
    assert attach(46.77036, 6.45, 1590, osm)[0]["id"] == 2 and attach(46.7700, 6.45, 1590, osm)[0]["id"] == 1


def test_a_provisional_take_off_gathers_the_next_outings():
    index = SiteIndex()
    first = {"id": "a", "takeoff_name": None, "summit_name": "Pointe de Beauregard", "title": "x",
             "takeoff_lat": 45.9105, "takeoff_lon": 6.4705, "takeoff_alt": 1636}
    site = provisional_site(first)
    assert site["name"] == "Pointe de Beauregard" and site["source"] == "provisional"
    index.add(site)
    assert attach(45.9106, 6.4706, 1630, index)[0] is site


def test_centre_of_is_the_median_so_one_far_outing_does_not_pull_it():
    from mbhf.sites import centre_of
    lat, lon, alt = centre_of([(45.9100, 6.4700, 1630), (45.9102, 6.4702, 1640), (45.9104, 6.4698, None),
                               (45.9130, 6.4740, 1700)])
    assert abs(lat - 45.9103) < 1e-9 and abs(lon - 6.4701) < 1e-9 and alt == 1640
    assert centre_of([(45.0, 6.0, None)]) == (45.0, 6.0, None)


def test_outings_around_a_provisional_take_off_become_auto_once_it_is_centred():
    from mbhf.sites import centre_of, metres
    points = [(45.9105, 6.4705), (45.9112, 6.4712), (45.9098, 6.4698), (45.9106, 6.4711), (45.9101, 6.4702)]
    first = provisional_site({"id": "a", "takeoff_name": "Pointe", "takeoff_lat": points[1][0],
                              "takeoff_lon": points[1][1], "takeoff_alt": 1636})
    # tied to the first point alone, one outing is farther than 100 m
    assert max(metres(*p, first["lat"], first["lon"]) for p in points) > 90
    lat, lon, _ = centre_of((a, b, None) for a, b in points)
    first.update(lat=lat, lon=lon)
    index = SiteIndex([first])
    assert all(attach(a, b, 1636, index)[2] == "auto" for a, b in points)


def test_provisional_twins_closer_than_150_m_are_one_take_off_but_not_the_two_of_beauregard():
    north = {"id": 1, "source": "provisional", "source_id": "a", "name": "Pointe de Beauregard",
             "lat": 45.9100, "lon": 6.4700, "alt": 1636}
    index = SiteIndex([north])
    # 120 m south, same name: one take-off (an outing's GPS scatter)
    site, _, status = attach(45.9100 - 120 / 111320, 6.4700, 1636, index, "Pointe de Beauregard")
    assert site is north and status == "auto"
    # 252 m south, same name: the south take-off, a take-off of its own
    site, _, status = attach(45.9100 - 252 / 111320, 6.4700, 1636, index, "Pointe de Beauregard")
    assert site is None and status == "provisional"
