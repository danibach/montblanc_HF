import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from sync_sites import rename_unnamed  # noqa: E402


class FakeRegister:
    def __init__(self):
        self.written = []

    def upsert(self, sites):
        self.written += sites
        return sites


def outing(oid, takeoff_name=None, summit_name=None):
    return {"id": oid, "takeoff_name": takeoff_name, "summit_name": summit_name,
            "takeoff_lat": 45.81, "takeoff_lon": 6.787, "takeoff_alt": 3530}


def test_a_take_off_made_before_its_names_takes_them():
    # the Dômes de Miage (30 October 2026): made as « Take-off · 3,530 m » before Overpass named the outing
    site = {"id": 7102, "source": "provisional", "source_id": "a", "name": "Take-off · 3,530 m"}
    named = {"id": 9, "source": "provisional", "source_id": "b", "name": "Pointe de Beauregard"}
    reg = FakeRegister()
    n = rename_unnamed(reg, [outing("a", "Dômes de Miage - Pointe Sud-Ouest"), outing("b", "Autre nom")],
                       {"a": 7102, "b": 9}, {7102: site, 9: named})
    assert n == 1 and site["name"] == "Dômes de Miage – Pointe Sud-Ouest"
    assert named["name"] == "Pointe de Beauregard"  # a take-off with a name keeps it


def test_still_no_name_stays_as_it_is():
    site = {"id": 1, "source": "provisional", "source_id": "a", "name": "Take-off · 1,480 m"}
    reg = FakeRegister()
    assert rename_unnamed(reg, [outing("a")], {"a": 1}, {1: site}) == 0 and not reg.written
