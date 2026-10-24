from mbhf.sites import (SiteIndex, attach, ffvl_takeoffs, osm_takeoffs, pretty_name, provisional_site,
                        without_doubles)

# about 100 m north is 0.0009 degree of latitude
FFVL = [
    {"suid": 1, "toponym": "LA CLUSAZ - AIGUILLE DES CALVAIRES (ETE)", "flying_functions_text": "décollage",
     "latitude": 45.9000, "longitude": 6.4500, "altitude": 2035, "status": "actif", "wind_orientations_ok": "NW;W",
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
    assert s["name"] == "La Clusaz - Aiguille des Calvaires (Ete)" and s["alt"] == 2035 and s["wind_ok"] == "NW;W"
    assert s["hike_and_fly"] == "45 min from the car park"


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
