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
from .multi import Ends, chain_problem, combined_sha256
from .outing import OutingConfig, build_outing, build_trace
from .parsers import load_track
from .parsers.common import clean_altitudes, drop_jumps
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
    track, info = read_bytes(name, data, max_bytes)
    return _prepare(track, info)


def read_bytes(name: str, data: bytes, max_bytes: int = MAX_FILE_BYTES) -> tuple[Track, dict]:
    """Read one track file (altitudes cleaned, not yet thinned nor segmented) and describe it."""
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
    kept, jumped = drop_jumps(track.points)
    cleaned, blanked = clean_altitudes(kept)
    if blanked or jumped:
        track = Track(points=cleaned, source=track.source, fmt=track.fmt, hint=track.hint, warnings=track.warnings)

    if sum(1 for p in track.points if p.alt is not None) < 0.5 * len(track.points):
        raise AnalysisError(advice.NO_ALTITUDE)

    info = {"name": shown, "format": ext[1:], "size": len(data), "sha256": sha256_hex(data), "fixes": len(track.points)}
    if blanked:
        info["altitude_ignored"] = blanked
    if jumped:
        info["position_ignored"] = jumped
    editor = advice.editor_of(data)
    if editor:
        info["editor"] = editor
    return track, info


def _prepare(track: Track, info: dict) -> Prepared:
    track = Track(points=thin(track.points), source=track.source, fmt=track.fmt, warnings=track.warnings)
    if len(track.points) < MIN_FIXES:
        raise AnalysisError(advice.TOO_SHORT)
    return Prepared(info, track, segment_track(track, SegmenterConfig()))


def ends_of(track: Track) -> Ends:
    a, b = track.points[0], track.points[-1]
    return Ends(a.t, a.lat, a.lon, b.t, b.lat, b.lon)


def prepare_files(parts: list[tuple[str, bytes]], max_bytes: int = MAX_FILE_BYTES) -> Prepared:
    """Read several files of one outing (multi.py: they must follow one another), join them in time order
    and segment the whole. ``info["parts"]`` describes each file; ``info["sha256"]`` is their combined
    fingerprint. Raises ``AnalysisError`` with a message fit to show the participant."""
    if len(parts) == 1:
        return prepare_bytes(parts[0][0], parts[0][1], max_bytes)
    read = sorted((read_bytes(n, d, max_bytes) for n, d in parts), key=lambda r: r[0].points[0].t)
    names = [info["name"] for _, info in read]
    why = chain_problem([ends_of(t) for t, _ in read], names)
    if why:
        raise AnalysisError(f"These files are not one outing. {why}")
    points = [p for t, _ in read for p in t.points]
    track = Track(points=points, source=" + ".join(names), fmt=read[0][0].fmt,
                  warnings=[w for t, _ in read for w in t.warnings])
    infos = [info for _, info in read]
    info = {"name": " + ".join(names), "format": infos[0]["format"], "size": sum(i["size"] for i in infos),
            "sha256": combined_sha256([i["sha256"] for i in infos]), "fixes": sum(i["fixes"] for i in infos),
            "parts": infos}
    for key in ("altitude_ignored", "position_ignored"):
        if sum(i.get(key, 0) for i in infos):
            info[key] = sum(i.get(key, 0) for i in infos)
    editors = [i["editor"] for i in infos if i.get("editor")]
    if editors:
        info["editor"] = editors[0]
    return _prepare(track, info)


def finish(prepared: Prepared, seg=None, notes: Optional[list] = None) -> dict:
    """The analysis result for a prepared file (with the segmentation the terrain check settled on)."""
    seg = seg or prepared.seg
    notes = list(prepared.notes) + list(notes or [])
    outing = build_outing(prepared.track, seg, OutingConfig())
    ignored = prepared.info.get("altitude_ignored")
    if ignored:
        notes = list(notes or []) + [f"{ignored} altitude reading{'s were' if ignored != 1 else ' was'} obviously wrong (0 m or a one-fix spike) and ignored"]
    jumped = prepared.info.get("position_ignored")
    if jumped:
        notes = list(notes or []) + [f"{jumped} position{'s' if jumped != 1 else ''} far away and back at an impossible speed (a receiver error) ignored"]
    if notes:
        outing["warnings"] = list(outing["warnings"]) + [n for n in notes if n not in outing["warnings"]]
    # the words shown when the outing does not count (None when it counts)
    outing["reason_text"] = advice.refusal(outing, prepared.track.points, editor=prepared.info.get("editor"))
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


MAX_MANUAL_FLIGHTS = 20
MAX_MANUAL_SECONDS = 3 * 24 * 3600


def clean_manual_ranges(value) -> list:
    """The hand-marked flights as sent by a browser, checked: ``[[from, to], ...]`` in seconds after the first fix.
    Raises ``AnalysisError`` when it is not that (the server never trusts what a browser sends)."""
    bad = AnalysisError("The flights marked by hand are not valid.")
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_MANUAL_FLIGHTS:
        raise bad
    out = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise bad
        a, b = item
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (a, b)):
            raise bad
        if not (0 <= a <= MAX_MANUAL_SECONDS and 0 <= b <= MAX_MANUAL_SECONDS) or a == b:
            raise bad
        out.append([float(a), float(b)])
    return out


def analyse_bytes(name: str, data: bytes, max_bytes: int = MAX_FILE_BYTES, elevation_fetch=None, manual_ranges=None) -> dict:
    """Analyse one track file. ``elevation_fetch(samples) -> [metres] | None`` switches the terrain check on
    (the server passes ``terrain.fetch_elevations``). Raises ``AnalysisError`` with a message fit to show."""
    return _analyse(prepare_bytes(name, data, max_bytes), elevation_fetch, manual_ranges)


def analyse_files(parts: list[tuple[str, bytes]], max_bytes: int = MAX_FILE_BYTES, elevation_fetch=None,
                  manual_ranges=None) -> dict:
    """Analyse an outing made of several files (``prepare_files``), as ``analyse_bytes`` does one. Hand-marked
    flights are in seconds after the first fix of the first file (the joined track's own start)."""
    return _analyse(prepare_files(parts, max_bytes), elevation_fetch, manual_ranges)


def _analyse(prepared: Prepared, elevation_fetch=None, manual_ranges=None) -> dict:
    if manual_ranges:
        # flights marked by the participant on the map override the automatic ground check (decided 25 Oct 2026)
        return finish(with_manual_flights(prepared, clean_manual_ranges(manual_ranges)))
    if elevation_fetch is None:
        return finish(prepared)
    samples = sample_flights(prepared.track, prepared.seg)
    seg, notes = apply_terrain(prepared.track, prepared.seg, samples, elevation_fetch(samples) if samples else None)
    return finish(prepared, seg, notes)
