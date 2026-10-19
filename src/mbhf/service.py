"""Analyse uploaded tracks: the one entry point shared by the web app (and usable from scripts).

Nothing is kept: uploads are written to a private temporary directory only because the parsers
read files, and the directory is deleted before this function returns.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Optional

from .chrono import chrono_to_dict, compute_chrono
from .cli import result_to_dict
from .merge import merge_tracks
from .models import MODES, TrackError
from .parsers import load_track
from .parsers.common import parse_iso_time
from .report import build_report, render_figure
from .rules import load_ruleset
from .segment import Cuts, SegmentationError, segment_track
from .transport import LineSet, Schedule, load_lines, load_schedule

ALLOWED_EXTENSIONS = (".igc", ".gpx", ".kml", ".fit")
MAX_FIXES = 200_000


class AnalysisError(ValueError):
    """The upload cannot be analysed; the message is written for the participant."""


@dataclass
class Upload:
    filename: str
    data: bytes
    mode: Optional[str] = None      # "bike" | "walk" | "flight" | None (automatic)


@dataclass
class Analysis:
    data: dict
    png: bytes


def _display_name(name: str) -> str:
    base = os.path.basename((name or "track").replace("\\", "/"))
    return re.sub(r"[^\w.\- ()]", "_", base)[:80] or "track"


def _cut(text: str, label: str):
    text = (text or "").strip()
    if not text:
        return None
    when = parse_iso_time(text)
    if when is None:
        raise AnalysisError(
            f"{label}: cannot read {text!r} as a time. Use a form like 2026-09-12T09:41:10Z "
            "(add Z for UTC, or an offset such as +02:00)."
        )
    return when


def analyse_uploads(
    uploads: list[Upload],
    cuts: Optional[dict[str, str]] = None,
    lines: Optional[LineSet] = None,
    schedule: Optional[Schedule] = None,
    max_fixes: int = MAX_FIXES,
) -> Analysis:
    if not uploads:
        raise AnalysisError("Choose at least one track file (IGC, GPX, KML or FIT).")
    cuts = cuts or {}
    parsed_cuts = Cuts(
        walk_start=_cut(cuts.get("walk_start", ""), "Start of the walk"),
        takeoff=_cut(cuts.get("takeoff", ""), "Take-off"),
        landing=_cut(cuts.get("landing", ""), "Landing"),
        bike_return_start=_cut(cuts.get("bike_return_start", ""), "Start of the ride back"),
    )
    tracks = []
    with tempfile.TemporaryDirectory(prefix="mbhf-") as tmp:
        for idx, up in enumerate(uploads):
            shown = _display_name(up.filename)
            ext = os.path.splitext(shown)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise AnalysisError(f"{shown}: this file type is not accepted. Use IGC, GPX, KML or FIT.")
            if up.mode is not None and up.mode not in MODES:
                raise AnalysisError(f"{shown}: unknown part type {up.mode!r}.")
            if not up.data:
                raise AnalysisError(f"{shown}: the file is empty. Check the export and send it again.")
            path = os.path.join(tmp, f"track{idx}{ext}")
            with open(path, "wb") as fh:
                fh.write(up.data)
            try:
                tr = load_track(path, hint=up.mode, src=idx)
            except TrackError as exc:
                raise AnalysisError(_clean(str(exc), path, shown)) from exc
            tr.source = shown
            tracks.append(tr)

    track = tracks[0] if len(tracks) == 1 else _merge(tracks)
    if len(track.points) > max_fixes:
        raise AnalysisError(
            f"This track has {len(track.points):,} points, more than the {max_fixes:,} the service accepts. "
            "Export the days separately or at a lower recording rate."
        )
    try:
        res = segment_track(track, parsed_cuts)
    except SegmentationError as exc:
        raise AnalysisError(str(exc)) from exc
    rules = load_ruleset()
    lines = load_lines() if lines is None else lines
    schedule = load_schedule() if schedule is None else schedule
    chrono = compute_chrono(track, res, rules, lines, schedule)

    data = result_to_dict(track, res, [t.source for t in tracks], chrono)
    data["report"] = build_report(track, res, chrono, rules)
    fig = render_figure(track, res, chrono)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    return Analysis(data=data, png=buf.getvalue())


def _merge(tracks):
    try:
        return merge_tracks(tracks)
    except (TrackError, ValueError) as exc:
        raise AnalysisError(str(exc)) from exc


def _clean(message: str, path: str, shown: str) -> str:
    """Parser errors name the temporary path; show the participant's own file name instead."""
    return message.replace(path, shown)
