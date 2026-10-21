"""Track file parsers: IGC, GPX, KML, TCX and FIT. Timestamps are mandatory."""

from __future__ import annotations

import os
from typing import Optional

from ..models import MODES, Track, TrackError
from .fit import parse_fit
from .gpx import parse_gpx
from .igc import parse_igc
from .kml import parse_kml
from .tcx import parse_tcx

MAX_FILE_BYTES = 200 * 1024 * 1024  # generous; uploads should be limited lower by the web layer

_PARSERS = {".gpx": parse_gpx, ".kml": parse_kml, ".igc": parse_igc, ".fit": parse_fit, ".tcx": parse_tcx}


def load_track(path: str, hint: Optional[str] = None, src: int = 0) -> Track:
    """Load one track file. ``hint`` forces every point of the file to a mode."""
    if hint is not None and hint not in MODES:
        raise TrackError(f"unknown mode hint {hint!r}; expected one of {MODES}")
    ext = os.path.splitext(path)[1].lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise TrackError(f"{path}: unsupported format {ext!r}; use IGC, GPX, KML, TCX or FIT")
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise TrackError(f"{path}: cannot read file ({exc})") from exc
    if size > MAX_FILE_BYTES:
        raise TrackError(f"{path}: file too large ({size} bytes)")
    return parser(path, hint=hint, src=src)
