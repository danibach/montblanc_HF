"""The same flight sent twice from two different files (the watch's FIT and its Strava export, say).

Two files of one flight have different fingerprints, so the file hash does not catch them. But one pilot
cannot fly twice at the same time: when a flight of the new outing and a flight of one of the pilot's
outings already counted overlap in time for at least ``MIN_OVERLAP`` of the shorter one, it is the same
flight and the new outing is refused. Two flights from the same take-off on the same day (morning and
afternoon) do not overlap and both count.

The browser does the same test in ``site/api.js`` (``sameFlightAs``) before sending the file.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

MIN_OVERLAP = 0.5


def _span(flight: dict) -> Optional[tuple[float, float]]:
    try:
        t0 = datetime.fromisoformat(flight["takeoff"]["t"]).timestamp()
        t1 = datetime.fromisoformat(flight["landing"]["t"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return None
    return (t0, t1) if t1 > t0 else None


def same_flight(flights_a: Iterable[dict], flights_b: Iterable[dict], min_overlap: float = MIN_OVERLAP) -> bool:
    """True when a flight of ``flights_a`` and a flight of ``flights_b`` are the same flight."""
    spans_b = [s for s in map(_span, flights_b or []) if s]
    for a in filter(None, map(_span, flights_a or [])):
        for b in spans_b:
            overlap = min(a[1], b[1]) - max(a[0], b[0])
            if overlap > 0 and overlap >= min_overlap * min(a[1] - a[0], b[1] - b[0]):
                return True
    return False


def duplicate_message(title: Optional[str], date: Optional[str]) -> str:
    """The reason shown to the pilot (the same words as in site/api.js)."""
    what = f"“{title}”" if title else "another of your outings"
    when = f" ({date})" if date else ""
    return (f"This flight is already in {what}{when}, sent from another file. "
            "The same flight counts once: to replace it, delete that outing first.")
