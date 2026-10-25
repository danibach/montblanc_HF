"""The one entry point: a track file's bytes in, one outing (plain data, ready for JSON) out."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime, timedelta
from typing import Optional

from . import __version__, advice
from .models import Point, Track, TrackError
from .outing import OutingConfig, build_outing, build_trace
from .parsers import load_track
from .parsers.common import clean_altitudes
from .segment import FLIGHT, SegmentationResult, SegmenterConfig, _build_segments, segment_track
from .terrain import apply_terrain, elevation_query, sample_flights

ALLOWED_EXTENSIONS = (".igc", ".gpx", ".kml", ".tcx", ".fit")
MAX_FILE_BYTES = 10 * 1024 * 1024
MIN_SPACING_S = 3.0          # a 1 Hz recording is thinned to one fix every 3 s: same result, faster
MIN_FIXES = 60


class AnalysisError(ValueError):
    """The file cannot be analysed; the message is written for the participant."""


def _display_name(name: str) -> str:
    base = os.path.basename((name or "track").replace("\\", "/"))
    return re.sub(r"[^\w.\- ()]", "_", base)[:80] or "track"


def thin(points: list[Point], min_spacing_s: float = MIN_SPACING_S) -> list[Point]:
    out = [points[0]]
    last = points[0].t
    gap = timedelta(seconds=min_spacing_s)
    for p in points[1:-1]:
        if p.t - last >= gap:
            out.append(p)
            last = p.t
    if len(points) > 1:
        out.append(points[-1])
    return out


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Prepared:
    """A file read and segmented, before the terrain check."""

    def __init__(self, info: dict, track: Track, seg):
        self.info, self.track, self.seg = info, track, seg
        self.notes: list[str] = []   # said with every result of this file (e.g. flights marked by hand)


def prepare_bytes(name: str, data: bytes, max_bytes: int = MAX_FILE_BYTES) -> Prepared:
    """Read and segment one track file. Raises ``AnalysisError`` with a message fit to show the participant."""
    shown = _display_name(name)
    ext = os.path.splitext(shown)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AnalysisError(f"{shown}: use an IGC, GPX, KML, TCX or FIT file.")
    if not data:
        raise AnalysisError(f"{shown} is empty.")
    if len(data) > max_bytes:
        raise AnalysisError(advice.MAX_SIZE.format(name=shown, mb=max_bytes // (1024 * 1024)))

    with tempfile.TemporaryDirectory(prefix="mbhf-") as tmp:
        path = os.path.join(tmp, f"track{ext}")
        with open(path, "wb") as fh:
            fh.write(data)
        try:
            track = load_track(path)
        except TrackError as exc:
            raise AnalysisError(advice.file_problem(shown, str(exc), data)) from exc
    track.source = shown
    cleaned, blanked = clean_altitudes(track.points)
    if blanked:
        track = Track(points=cleaned, source=track.source, fmt=track.fmt, hint=track.hint, warnings=track.warnings)

    if sum(1 for p in track.points if p.alt is not None) < 0.5 * len(track.points):
        raise AnalysisError(advice.NO_ALTITUDE)

    fixes = len(track.points)
    track = Track(points=thin(track.points), source=track.source, fmt=track.fmt, warnings=track.warnings)
    if len(track.points) < MIN_FIXES:
        raise AnalysisError(advice.TOO_SHORT)

    seg = segment_track(track, SegmenterConfig())
    info = {"name": shown, "format": ext[1:], "size": len(data), "sha256": sha256_hex(data), "fixes": fixes}
    if blanked:
        info["altitude_ignored"] = blanked
    return Prepared(info, track, seg)


def finish(prepared: Prepared, seg=None, notes: Optional[list] = None) -> dict:
    """The analysis result for a prepared file (with the segmentation the terrain check settled on)."""
    seg = seg or prepared.seg
    notes = list(prepared.notes) + list(notes or [])
    outing = build_outing(prepared.track, seg, OutingConfig())
    ignored = prepared.info.get("altitude_ignored")
    if ignored:
        notes = list(notes or []) + [f"{ignored} altitude reading{'s were' if ignored != 1 else ' was'} obviously wrong (0 m or a one-fix spike) and ignored"]
    if notes:
        outing["warnings"] = list(outing["warnings"]) + [n for n in notes if n not in outing["warnings"]]
    # the words shown when the outing does not count (None when it counts)
    outing["reason_text"] = advice.refusal(outing, prepared.track.points)
    return {
        "file": prepared.info,
        "outing": outing,
        "trace": build_trace(prepared.track, seg.labels, OutingConfig().max_trace_points),
        "engine": {"version": __version__},
    }


def with_manual_flights(prepared: Prepared, ranges_s: list) -> Prepared:
    """The same file with the flights the participant marked by hand.

    ``ranges_s`` is a list of ``[from, to]``, in seconds after the first fix of the track (the ``t0`` and ``t``
    of the trace the page draws). Every fix inside a range is a flight, whatever the engine thought; the rest
    keeps the engine's labels. The marking overrides the terrain check: the page does not run it on these flights."""
    pts = prepared.track.points
    t0 = pts[0].t
    labels = list(prepared.seg.labels)
    for lo, hi in ranges_s:
        lo, hi = float(lo), float(hi)
        if hi < lo:
            lo, hi = hi, lo
        for i, p in enumerate(pts):
            if lo <= (p.t - t0).total_seconds() <= hi:
                labels[i] = FLIGHT
    seg = SegmentationResult(segments=_build_segments(pts, labels), labels=labels, warnings=list(prepared.seg.warnings))
    marked = Prepared(prepared.info, prepared.track, seg)
    marked.notes = ["Flights marked by hand (the ground check is not applied to them)"]
    return marked


def terrain_query_for(prepared: Prepared) -> Optional[str]:
    """What the browser must ask the elevation service for this file (None: no flight to check)."""
    return elevation_query(sample_flights(prepared.track, prepared.seg))


def with_terrain(prepared: Prepared, elevations: Optional[list]) -> dict:
    """Redo the result after the terrain check, with the elevations the service gave (None: unavailable)."""
    samples = sample_flights(prepared.track, prepared.seg)
    seg, notes = apply_terrain(prepared.track, prepared.seg, samples, elevations)
    return finish(prepared, seg, notes)


def analyse_bytes(name: str, data: bytes, max_bytes: int = MAX_FILE_BYTES, elevation_fetch=None) -> dict:
    """Analyse one track file. ``elevation_fetch(samples) -> [metres] | None`` switches the terrain check on
    (the server passes ``terrain.fetch_elevations``). Raises ``AnalysisError`` with a message fit to show."""
    prepared = prepare_bytes(name, data, max_bytes)
    if elevation_fetch is None:
        return finish(prepared)
    samples = sample_flights(prepared.track, prepared.seg)
    seg, notes = apply_terrain(prepared.track, prepared.seg, samples, elevation_fetch(samples) if samples else None)
    return finish(prepared, seg, notes)
