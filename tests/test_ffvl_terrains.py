"""The official FFVL take-offs and landings for the map (sites.ffvl_terrains)."""
from mbhf.sites import ffvl_terrains

BASE = {"latitude": 45.92, "longitude": 6.42, "altitude": 1473, "city": "LA CLUSAZ", "status": "actif"}


def test_take_offs_and_landings_with_their_card():
    rows = ffvl_terrains([
        {**BASE, "suid": 1, "toponym": "CRET-DU-MERLE - OUVERT DU 1/5 AU 31/10", "flying_functions_text": "décollage",
         "possible_usages_text": "parapente;delta", "wind_orientations_ok": "N;O;NO", "walking_time_from_parking_minutes": 2,
         "warnings": "Ligne de télésiège à droite du décollage", "restrictions": ".",
         "description": "Balise : https://www.openwindmap.org/PP496"},
        {**BASE, "suid": 2, "toponym": "PLANFAIT - PERROIX", "flying_functions_text": "atterrissage", "possible_usages_text": "parapente"},
        {**BASE, "suid": 3, "toponym": "BOTH", "flying_functions_text": "décollage;atterrissage", "possible_usages_text": "parapente"},
        {**BASE, "suid": 4, "toponym": "LA CLUSAZ - SPEED-RIDING", "flying_functions_text": "atterrissage",
         "possible_usages_text": "speed-riding"},
        {**BASE, "suid": 5, "toponym": "TREUIL", "flying_functions_text": "treuil", "possible_usages_text": "parapente"},
    ])
    assert [(r["suid"], r["kind"]) for r in rows] == [(1, "T"), (2, "L"), (3, "TL")]  # no speed riding only, no winch
    t = rows[0]
    assert t["name"] == "Crêt-du-Merle" and t["winds"] == "N;O;NO" and t["status"] == "actif"
    assert t["info"]["walk_min"] == 2 and t["info"]["city"] == "La Clusaz" and "télésiège" in t["info"]["warnings"]
    assert "restrictions" not in t["info"]  # « . » says nothing
