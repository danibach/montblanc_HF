"""What a participant sees: detected places, transitions, and the figure.

``build_report`` turns a segmented track and its chrono into plain data (dicts of numbers and
text) that the web page, the JSON output and the tests all share. ``render_figure`` draws the
altitude profile, the ground speed and the map, with the detected places marked.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .chrono import Chrono
from .geo import haversine_m
from .models import Point, Track
from .rules import RuleSet
from .segment import SegmentationResult

LOCAL_TZ = ZoneInfo("Europe/Paris")

ROLE_START_LABEL = {
    "bike_out": "Start of the ride out",
    "ascent": "Start of the walk up",
    "flight": "Take-off",
    "walk_after_landing": "Landing",
    "bike_return": "Start of the ride back",
}
ROLE_TITLE = {
    "bike_out": "Ride out (bike)",
    "ascent": "Walk up",
    "flight": "Flight",
    "walk_after_landing": "Walk after landing",
    "bike_return": "Ride back (bike)",
}
MODE_COLOUR = {"bike": "#3b6ea5", "walk": "#4f8a4b", "flight": "#d9512c"}


def position_at(track: Track, t: datetime) -> Optional[tuple[float, float, Optional[float]]]:
    """Latitude, longitude and altitude at instant t, interpolated between the surrounding fixes."""
    pts = track.points
    if not pts or t < pts[0].t or t > pts[-1].t:
        return None
    lo, hi = 0, len(pts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if pts[mid].t <= t:
            lo = mid
        else:
            hi = mid
    a, b = pts[lo], pts[hi]
    span = (b.t - a.t).total_seconds()
    f = 0.0 if span <= 0 else min(1.0, max(0.0, (t - a.t).total_seconds() / span))
    alt = None if a.alt is None or b.alt is None else a.alt + (b.alt - a.alt) * f
    return a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f, alt


def _place(lat: float, lon: float, alt: Optional[float]) -> dict:
    return {
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "alt_m": None if alt is None else round(alt),
        "map_url": f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=15/{lat:.5f}/{lon:.5f}",
    }


def _when(t: datetime) -> dict:
    local = t.astimezone(LOCAL_TZ)
    return {
        "utc": t.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds"),
        "local": local.isoformat(timespec="seconds"),
        "local_hms": local.strftime("%H:%M:%S"),
        "local_date": local.strftime("%a %d %b %Y"),
    }


def _landmark(rules: RuleSet, lat: float, lon: float) -> Optional[str]:
    for name, cyl in (("Nid d'Aigle", rules.nid_d_aigle), ("Mont-Blanc summit", rules.summit)):
        if haversine_m(lat, lon, cyl.lat, cyl.lon) <= cyl.radius_m + 150:
            return name
    return None


def _event(key: str, label: str, t: datetime, pos, rules: RuleSet, **extra) -> dict:
    ev = {"key": key, "label": label, **_when(t), **extra}
    if pos is not None:
        ev.update(_place(*pos))
        ev["near"] = _landmark(rules, pos[0], pos[1])
    return ev


def build_report(track: Track, res: SegmentationResult, chrono: Chrono, rules: RuleSet) -> dict:
    pts = track.points
    first, last = pts[0], pts[-1]
    top = max((p for p in pts if p.alt is not None), key=lambda p: p.alt, default=None)

    places: list[dict] = []
    first_role = res.segments[0].role
    places.append(
        _event("start", "Start of the track", first.t, (first.lat, first.lon, first.alt), rules,
               note=ROLE_TITLE[first_role], confidence=None)
    )
    for s in res.segments[1:]:
        p = pts[s.i_start]
        places.append(
            _event(
                f"transition_{s.role}",
                ROLE_START_LABEL[s.role],
                p.t,
                (p.lat, p.lon, p.alt),
                rules,
                confidence=s.confidence,
                gap_s=round(s.boundary_gap_s),
                user_fixed=s.user_fixed_start,
            )
        )
    for key, label, t in (
        ("nid_exit", "Last exit from the Nid d'Aigle cylinder (clock starts)", chrono.nid_exit),
        ("summit_enter", "First entry into the summit cylinder on foot (clock stops)", chrono.summit_enter),
        ("summit_exit", "Final exit from the summit cylinder", chrono.summit_final_exit),
    ):
        if t is not None:
            places.append(_event(key, label, t, position_at(track, t), rules, confidence=None))
    places.append(_event("end", "End of the track", last.t, (last.lat, last.lon, last.alt), rules, confidence=None))
    places.sort(key=lambda e: e["utc"])

    total = max(1.0, (last.t - first.t).total_seconds())
    parts = []
    for s in res.segments:
        parts.append(
            {
                "role": s.role,
                "title": ROLE_TITLE[s.role],
                "mode": s.mode,
                "start": _when(s.t_start),
                "end": _when(s.t_end),
                "duration_s": round(s.duration_s),
                "share": round(s.duration_s / total, 4),
                "distance_km": round(s.distance_m / 1000, 1),
                "ascent_m": None if s.ascent_m is None else round(s.ascent_m),
                "descent_m": None if s.descent_m is None else round(s.descent_m),
                "mean_speed_kmh": round(s.mean_speed_kmh, 1),
                "confidence": s.confidence,
                "colour": MODE_COLOUR[s.mode],
            }
        )

    return {
        "track": {
            "fixes": len(pts),
            "start": _when(first.t),
            "end": _when(last.t),
            "duration_s": round(total),
            "highest": None if top is None else {**_place(top.lat, top.lon, top.alt), **_when(top.t)},
        },
        "places": places,
        "parts": parts,
    }


# ---------------------------------------------------------------------------------------------
# figure
# ---------------------------------------------------------------------------------------------
def render_figure(track: Track, res: SegmentationResult, chrono: Chrono, tz=LOCAL_TZ, dpi: int = 110):
    """Altitude profile, ground speed and map, with the detected places marked. Returns a Figure."""
    from matplotlib.figure import Figure

    from .segment import SegmenterConfig, compute_features

    pts = track.points
    feats = compute_features(pts, SegmenterConfig())
    times = [p.t.astimezone(tz) for p in pts]
    ink = "#0f2a35"
    fig = Figure(figsize=(11, 12.5), dpi=dpi, facecolor="white")
    ax_alt, ax_spd, ax_map = fig.subplots(3, 1, gridspec_kw={"height_ratios": [2.2, 1.5, 3.6]})

    seen: set[str] = set()
    for s in res.segments:
        sl = slice(s.i_start, s.i_end + 1)
        colour = MODE_COLOUR[s.mode]
        label = None if s.mode in seen else {"bike": "Bike", "walk": "On foot", "flight": "Flight"}[s.mode]
        seen.add(s.mode)
        ax_alt.plot(times[sl], [p.alt for p in pts[sl]], color=colour, lw=1.6, label=label)
        ax_spd.plot(times[sl], [f.v for f in feats[sl]], color=colour, lw=0.9)
        ax_map.plot([p.lon for p in pts[sl]], [p.lat for p in pts[sl]], color=colour, lw=1.6)
        if s.i_start > 0:
            for ax in (ax_alt, ax_spd):
                ax.axvline(times[s.i_start], color="#7a8b94", ls="--", lw=0.8)
            p = pts[s.i_start]
            ax_map.plot(p.lon, p.lat, "o", ms=7, mfc="white", mec=ink, mew=1.4, zorder=5)
            if p.alt is not None:
                ax_alt.annotate(
                    ROLE_START_LABEL[s.role], (times[s.i_start], p.alt), xytext=(6, 8),
                    textcoords="offset points", fontsize=8.5, color=ink,
                )

    first, last = pts[0], pts[-1]
    ax_map.plot(first.lon, first.lat, "s", ms=8, color=ink, zorder=6, label="Start")
    ax_map.plot(last.lon, last.lat, "X", ms=8, color=ink, zorder=6, label="End")
    for t, name, marker in ((chrono.nid_exit, "Nid d'Aigle exit", "D"), (chrono.summit_enter, "Summit entry", "*")):
        if t is None:
            continue
        pos = position_at(track, t)
        if pos is None:
            continue
        ax_map.plot(pos[1], pos[0], marker, ms=11 if marker == "*" else 8, color="#f2b705", mec=ink, mew=1.0, zorder=7, label=name)
        if pos[2] is not None:
            ax_alt.plot(t.astimezone(tz), pos[2], marker, ms=11 if marker == "*" else 8, color="#f2b705", mec=ink, mew=1.0, zorder=7)

    ax_alt.set_ylabel("Altitude (m)")
    ax_spd.set_ylabel("Ground speed (km/h)")
    ax_map.set_xlabel("Longitude")
    ax_map.set_ylabel("Latitude")
    ax_map.set_aspect(1 / max(0.2, math.cos(math.radians(first.lat))))
    for ax in (ax_alt, ax_spd, ax_map):
        ax.grid(True, color="#e3e9ec", lw=0.6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    ax_alt.legend(loc="upper left", fontsize=8.5, frameon=False)
    ax_map.legend(loc="best", fontsize=8.5, frameon=False)
    import matplotlib.dates as mdates

    for ax in (ax_alt, ax_spd):
        locator = mdates.AutoDateLocator(tz=tz)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=tz))
    ax_spd.set_xlabel(f"Time ({tz.key})" if hasattr(tz, "key") else "Time")
    fig.tight_layout()
    return fig
