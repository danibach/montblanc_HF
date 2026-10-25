"""One outing in several files: a bike ride to the start, the climb, the flight, the ride home.

Files of one pilot follow one another when, taken in time order (``MultiConfig``):

* none overlaps the next (two files covering the same time are the same moment twice, a duplicate);
* the next one starts at most ``max_break_s`` after the end of the previous one (a night in a bivouac fits);
* it starts at most ``max_jump_m`` from where the previous one ended;
* all of them together last at most ``max_total_s``, and there are at most ``max_parts`` of them.

The files are then joined into one track and analysed as one (``analyse.prepare_files``): the time between
two files is a recording gap like any other, counted on foot only if a walker could have covered it
(``outing.gap_verdict``). The pilot confirms the grouping; the server joins the original files again.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .geo import haversine_m


@dataclass
class MultiConfig:
    max_break_s: float = 14 * 3600.0
    max_jump_m: float = 2000.0
    max_total_s: float = 7 * 24 * 3600.0
    max_parts: int = 10


@dataclass
class Ends:
    """Where and when a file starts and ends."""
    t0: datetime
    lat0: float
    lon0: float
    t1: datetime
    lat1: float
    lon1: float


def link_problem(a: Ends, b: Ends, cfg: Optional[MultiConfig] = None) -> Optional[str]:
    """Why file ``b`` does not follow file ``a`` (None: it does)."""
    cfg = cfg or MultiConfig()
    gap = (b.t0 - a.t1).total_seconds()
    if gap < 0:
        return "they overlap in time"
    if gap > cfg.max_break_s:
        return f"{gap / 3600:.0f} h apart (at most {cfg.max_break_s / 3600:.0f} h)"
    jump = haversine_m(a.lat1, a.lon1, b.lat0, b.lon0)
    if jump > cfg.max_jump_m:
        return f"the next one starts {jump / 1000:.1f} km from where the previous one ended (at most {cfg.max_jump_m / 1000:.0f} km)"
    return None


def chain_problem(ends: list[Ends], names: list[str], cfg: Optional[MultiConfig] = None) -> Optional[str]:
    """Why these files, in this order, are not one outing (None: they are)."""
    cfg = cfg or MultiConfig()
    if len(ends) > cfg.max_parts:
        return f"At most {cfg.max_parts} files make one outing."
    for k in range(1, len(ends)):
        why = link_problem(ends[k - 1], ends[k], cfg)
        if why:
            return f"{names[k - 1]} and {names[k]} do not follow one another: {why}."
    if (ends[-1].t1 - ends[0].t0).total_seconds() > cfg.max_total_s:
        return f"Together these files last more than {cfg.max_total_s / 86400:.0f} days."
    return None


def groups(ends: list[Ends], cfg: Optional[MultiConfig] = None) -> list[list[int]]:
    """Indexes of the files that follow one another, in time order: one list per outing (a lone file is a
    list of one). ``ends`` may be in any order; a file that overlaps others (the same outing already joined
    by hand) stays apart."""
    cfg = cfg or MultiConfig()
    order = sorted(range(len(ends)), key=lambda k: ends[k].t0)
    out: list[list[int]] = []
    for k in order:
        home = next((g for g in out if len(g) < cfg.max_parts and link_problem(ends[g[-1]], ends[k], cfg) is None
                     and (ends[k].t1 - ends[g[0]].t0).total_seconds() <= cfg.max_total_s), None)
        if home is not None:
            home.append(k)
        else:
            out.append([k])
    return out


def combined_sha256(part_hashes: list[str]) -> str:
    """The fingerprint of an outing made of several files: the SHA-256 of their own fingerprints, one per line,
    in time order (the page computes the same, site/api.js)."""
    return hashlib.sha256("\n".join(part_hashes).encode("ascii")).hexdigest()
