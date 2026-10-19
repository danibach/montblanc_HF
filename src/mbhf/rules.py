"""The challenge rules that the code needs: cylinders and accepted formats.

The values live in a JSON file (``data/ruleset-draft.json`` by default) so that a rules change
does not need a code change, and every result can name the ruleset version it was computed with.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Optional


@dataclass(frozen=True)
class Cylinder:
    name: str
    lat: float
    lon: float
    radius_m: float
    alt_min_m: float
    alt_max_m: float


@dataclass(frozen=True)
class RuleSet:
    version: str
    accepted_formats: tuple[str, ...]
    nid_d_aigle: Cylinder
    summit: Cylinder


def _cyl(name: str, d: dict) -> Cylinder:
    try:
        cyl = Cylinder(
            name=name,
            lat=float(d["lat"]),
            lon=float(d["lon"]),
            radius_m=float(d["radius_m"]),
            alt_min_m=float(d["alt_min_m"]),
            alt_max_m=float(d["alt_max_m"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"ruleset: cylinder {name!r} is incomplete or invalid ({exc})") from exc
    if cyl.radius_m <= 0 or cyl.alt_min_m >= cyl.alt_max_m:
        raise ValueError(f"ruleset: cylinder {name!r} has an impossible radius or altitude band")
    return cyl


def load_ruleset(path: Optional[str] = None) -> RuleSet:
    """Load a ruleset from ``path``, or the packaged draft ruleset."""
    if path is None:
        text = resources.files("mbhf").joinpath("data/ruleset-draft.json").read_text(encoding="utf-8")
    else:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    data = json.loads(text)
    cyls = data["cylinders"]
    return RuleSet(
        version=str(data["ruleset"]),
        accepted_formats=tuple(data.get("accepted_formats", ())),
        nid_d_aigle=_cyl("nid_d_aigle", cyls["nid_d_aigle"]),
        summit=_cyl("summit", cyls["summit"]),
    )
