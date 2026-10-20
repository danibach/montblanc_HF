from mbhf.places import overpass_query, resolve_places

OUTING = {
    "start": {"lat": 45.9000, "lon": 6.8000, "alt": 1000},
    "summit": {"lat": 45.9200, "lon": 6.8500, "alt": 2202},
    "takeoff": {"lat": 45.9195, "lon": 6.8490, "alt": 2186},
}


def node(i, lat, lon, **tags):
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": tags}


def rel(i, **tags):
    return {"type": "relation", "id": i, "tags": tags}


RESPONSE = {
    "elements": [
        rel(1, boundary="administrative", admin_level="2", name="France", **{"name:en": "France", "ISO3166-1:alpha2": "FR"}),
        rel(2, boundary="administrative", admin_level="8", name="Servoz"),
        node(10, 45.9005, 6.8010, place="hamlet", name="Les Granges"),
        node(11, 45.9500, 6.9000, place="village", name="Far Village"),
        node(20, 45.9201, 6.8503, natural="peak", name="Pointe Haute", ele="2205"),
        node(21, 45.9203, 6.8505, natural="peak", name="Wrong Height", ele="3400"),
        node(22, 45.9196, 6.8491, natural="saddle", name="Col du Test", ele="2190"),
    ]
}


def test_query_mentions_every_point():
    q = overpass_query(OUTING)
    assert "is_in(45.90000,6.80000)" in q and "out tags center;" in q
    assert q.count("natural") == 2 and "45.92000,6.85000" in q and "45.91950,6.84900" in q


def test_no_start_no_query():
    assert overpass_query({"start": None}) is None


def test_names_are_picked_by_distance_and_height():
    p = resolve_places(OUTING, RESPONSE)
    assert p["country"] == {"code": "FR", "name": "France"}
    assert p["commune"] == "Servoz"
    assert p["start_place"] == "Les Granges"
    assert p["summit"]["name"] == "Pointe Haute" and p["summit"]["osm_id"] == 20 and p["summit"]["ele"] == 2205
    # the saddle is closer to the take-off, but the peak matches better; here only the saddle is in range
    assert p["takeoff"]["name"] in ("Col du Test", "Pointe Haute")


def test_a_peak_of_the_wrong_height_is_ignored():
    resp = {"elements": [node(21, 45.9203, 6.8505, natural="peak", name="Wrong Height", ele="3400")]}
    assert resolve_places(OUTING, resp)["summit"] is None


def test_empty_answer_leaves_everything_empty():
    p = resolve_places(OUTING, {"elements": []})
    assert p == {"country": None, "commune": None, "start_place": None, "summit": None, "takeoff": None}


def test_takeoff_falls_back_to_a_nearby_place():
    resp = {"elements": [node(10, 45.9190, 6.8480, place="hamlet", name="Chalet Alpage")]}
    p = resolve_places(OUTING, resp)
    assert p["takeoff"] == {"name": "Chalet Alpage", "osm_id": 10, "kind": "place"}
