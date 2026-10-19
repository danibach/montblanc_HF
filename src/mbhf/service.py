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
from .i18n import msg, translate
from .merge import merge_tracks
from .models import MODES, TrackError
from .parsers import load_track
from .parsers.common import parse_iso_time
from .report import build_report, build_trace, render_figure
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


def _cut(text: str, key: str, lang: str):
    text = (text or "").strip()
    if not text:
        return None
    when = parse_iso_time(text)
    if when is None:
        raise AnalysisError(msg(lang, "bad_time", label=msg(lang, key), text=text))
    return when


def analyse_uploads(
    uploads: list[Upload],
    cuts: Optional[dict[str, str]] = None,
    lines: Optional[LineSet] = None,
    schedule: Optional[Schedule] = None,
    max_fixes: int = MAX_FIXES,
    lang: str = "en",
    figure: bool = True,
    trace: bool = False,
) -> Analysis:
    """Analyse the uploads. ``lang`` ("en" or "fr") is the language of every message and label.

    ``figure=False`` skips the matplotlib figure (``png`` is then empty): the in-browser page draws
    its own graphs and does not ship matplotlib. ``trace=True`` adds ``data["trace"]``, compact
    arrays of the track (see ``build_trace``) for such a page.
    """
    if not uploads:
        raise AnalysisError(msg(lang, "no_file"))
    cuts = cuts or {}
    parsed_cuts = Cuts(
        walk_start=_cut(cuts.get("walk_start", ""), "cut_walk_start", lang),
        takeoff=_cut(cuts.get("takeoff", ""), "cut_takeoff", lang),
        landing=_cut(cuts.get("landing", ""), "cut_landing", lang),
        bike_return_start=_cut(cuts.get("bike_return_start", ""), "cut_bike_return_start", lang),
    )
    tracks = []
    with tempfile.TemporaryDirectory(prefix="mbhf-") as tmp:
        for idx, up in enumerate(uploads):
            shown = _display_name(up.filename)
            ext = os.path.splitext(shown)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise AnalysisError(msg(lang, "bad_ext", name=shown))
            if up.mode is not None and up.mode not in MODES:
                raise AnalysisError(msg(lang, "bad_mode", name=shown, mode=up.mode))
            if not up.data:
                raise AnalysisError(msg(lang, "empty", name=shown))
            path = os.path.join(tmp, f"track{idx}{ext}")
            with open(path, "wb") as fh:
                fh.write(up.data)
            try:
                tr = load_track(path, hint=up.mode, src=idx)
            except TrackError as exc:
                raise AnalysisError(translate(lang, _clean(str(exc), path, shown))) from exc
            tr.source = shown
            tracks.append(tr)

    track = tracks[0] if len(tracks) == 1 else _merge(tracks, lang)
    if len(track.points) > max_fixes:
        raise AnalysisError(msg(lang, "too_many", n=len(track.points), max=max_fixes))
    try:
        res = segment_track(track, parsed_cuts)
    except SegmentationError as exc:
        raise AnalysisError(translate(lang, str(exc))) from exc
    rules = load_ruleset()
    lines = load_lines() if lines is None else lines
    schedule = load_schedule() if schedule is None else schedule
    chrono = compute_chrono(track, res, rules, lines, schedule)

    data = result_to_dict(track, res, [t.source for t in tracks], chrono)
    data["report"] = build_report(track, res, chrono, rules, lang)
    if lang == "fr":
        _translate_data(data, lang)
    if trace:
        data["trace"] = build_trace(track)
    if not figure:
        return Analysis(data=data, png=b"")
    fig = render_figure(track, res, chrono, lang=lang)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    return Analysis(data=data, png=buf.getvalue())


def _translate_data(data: dict, lang: str) -> None:
    """French messages for the lists a participant reads; keys and codes stay as they are."""
    data["warnings"] = [translate(lang, w) for w in data["warnings"]]
    ch = data.get("chrono")
    if not ch:
        return
    ch["problems"] = [translate(lang, m) for m in ch["problems"]]
    # The per-stretch lines repeat the transport section, so they are not repeated as notes.
    ch["notes"] = [
        translate(lang, n) for n in ch["notes"] if not re.match(r"^(tram|lift|review): ", n)
    ]
    tp = ch.get("transport")
    if tp:
        tp["notes"] = [translate(lang, n) for n in tp["notes"]]
        for st in tp["stretches"]:
            st["reason"] = translate(lang, st["reason"])


def _merge(tracks, lang: str = "en"):
    try:
        return merge_tracks(tracks)
    except (TrackError, ValueError) as exc:
        raise AnalysisError(translate(lang, str(exc))) from exc


def _clean(message: str, path: str, shown: str) -> str:
    """Parser errors name the temporary path; show the participant's own file name instead."""
    return message.replace(path, shown)
