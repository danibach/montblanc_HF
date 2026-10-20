"""The one entry point: a track file's bytes in, one outing (plain data, ready for JSON) out."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime, timedelta
from typing import Optional

from . import __version__
from .models import Point, Track, TrackError
from .outing import OutingConfig, build_outing, build_trace
from .parsers import load_track
from .segment import SegmenterConfig, segment_track

ALLOWED_EXTENSIONS = (".igc", ".gpx", ".kml", ".fit")
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


def analyse_bytes(name: str, data: bytes, max_bytes: int = MAX_FILE_BYTES) -> dict:
    """Analyse one track file. Raises ``AnalysisError`` with a message fit to show the participant."""
    shown = _display_name(name)
    ext = os.path.splitext(shown)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AnalysisError(f"{shown}: use an IGC, GPX, KML or FIT file.")
    if not data:
        raise AnalysisError(f"{shown} is empty.")
    if len(data) > max_bytes:
        raise AnalysisError(f"{shown} is larger than {max_bytes // (1024 * 1024)} MB.")

    with tempfile.TemporaryDirectory(prefix="mbhf-") as tmp:
        path = os.path.join(tmp, f"track{ext}")
        with open(path, "wb") as fh:
            fh.write(data)
        try:
            track = load_track(path)
        except TrackError as exc:
            raise AnalysisError(str(exc).replace(path, shown)) from exc
    track.source = shown

    if sum(1 for p in track.points if p.alt is not None) < 0.5 * len(track.points):
        raise AnalysisError("This track has no altitude: climbs and descents cannot be measured.")

    fixes = len(track.points)
    track = Track(points=thin(track.points), source=track.source, fmt=track.fmt, warnings=track.warnings)
    if len(track.points) < MIN_FIXES:
        raise AnalysisError("This track is too short to analyse.")

    seg = segment_track(track, SegmenterConfig())
    outing = build_outing(track, seg, OutingConfig())
    return {
        "file": {
            "name": shown,
            "format": ext[1:],
            "size": len(data),
            "sha256": sha256_hex(data),
            "fixes": fixes,
        },
        "outing": outing,
        "trace": build_trace(track, seg.labels, OutingConfig().max_trace_points),
        "engine": {"version": __version__},
    }
