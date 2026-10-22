"""What to tell the participant when a track is refused: the cause, and what to do about it.

One place for every message, so the browser (Pyodide) and the server job show the same words. Nothing here
changes a result: the reasons are found by the analysis; this module only puts them into words (English, like
the site). The wording follows the proposal of 21 October 2026 (Notion, « Points ouverts et idées »).
"""

from __future__ import annotations

from typing import Optional

from .models import Point
from .outing import OutingConfig

# A recording that ends this close to its highest point holds no descent: it was stopped at the take-off
# (15 of the 29 refusals of the iSmoothRun batch ended 0 to 14 m below their top).
ENDS_AT_TOP_M = 30.0
# A recording that starts this close to its highest point holds no climb: it was started at the top
# (2025-06-19, started at the 4,091 m summit; 2026-09-04, an IGC started at the take-off).
STARTS_AT_TOP_M = 50.0

MAX_SIZE = "{name} is larger than {mb} MB. Export only this activity, not a whole year."
NO_POINTS = "{name}: the file contains no track points, the export is empty. Export it again."
ROUTE_ONLY = ("{name}: this file holds a route, not a track, and only track points are read. "
              "Export it again as a track, or upload the original recording of your device or app.")
NO_TIMES = ("{name}: this file has no timestamps, so the track cannot be timed. "
            "Export it with time stamps (a plain KML line has none).")
DAMAGED = "{name}: this file is damaged or incomplete. Export it again from your app or device."
NO_ALTITUDE = "This track has no altitude. Turn on altitude recording (GPS or barometer) and record again."
TOO_SHORT = ("Too few points to analyse (about 3 minutes minimum). "
             "If your device records rarely, shorten the recording interval.")
OUR_SIDE = "Something went wrong on our side. Try again; if it persists, report it."
NO_FLIGHT = "No flight found: no descent fast and steady enough for a wing. Check that the file covers the whole flight."
ENDS_AT_TOP = ("The recording ends at its highest point ({alt} m): no descent was recorded. "
               "Keep recording until you land.")
STARTS_AT_TOP = ("The recording starts at {alt} m, near the highest point: the climb is not in the file, "
                 "so the outing does not count.")
TOO_LITTLE_CLIMB = "Only {dplus} m of climbing on foot were recorded ({need} m needed). The climb must be in the file."


def _m(value: float) -> str:
    return f"{round(value):,}"


def file_problem(name: str, detail: str, data: bytes = b"") -> str:
    """The message for a file the parsers could not read (``detail``: the parser's own words)."""
    text = detail.lower()
    if "no track points" in text:
        # a GPX route (<rtept>): a planner's route, or a recording some sites export as a route (2018 Mont-Blanc file)
        return (ROUTE_ONLY if b"<rtept" in data else NO_POINTS).format(name=name)
    if "timestamp" in text:
        return NO_TIMES.format(name=name)
    return DAMAGED.format(name=name)


def refusal(outing: dict, points: list[Point], cfg: Optional[OutingConfig] = None) -> Optional[str]:
    """Why a rejected outing does not count and what to do, or None when it counts."""
    if outing.get("status") == "ok":
        return None
    cfg = cfg or OutingConfig()
    alts = [p.alt for p in points if p.alt is not None]
    top = max(alts) if alts else None
    if outing.get("reason") == "no_flight":
        ground = next((w for w in outing.get("warnings", []) if "follows the ground" in w), None)
        if ground:
            return ground  # the terrain check's own words, with its advice
        if top is not None and top - alts[-1] <= ENDS_AT_TOP_M:
            return ENDS_AT_TOP.format(alt=_m(top))
        return NO_FLIGHT
    if outing.get("reason") == "too_little_climb":
        if top is not None and top - alts[0] <= STARTS_AT_TOP_M:
            return STARTS_AT_TOP.format(alt=_m(alts[0]))
        return TOO_LITTLE_CLIMB.format(dplus=_m(outing.get("dplus_m") or 0), need=_m(cfg.min_walk_climb_m))
    return "This track does not count."
