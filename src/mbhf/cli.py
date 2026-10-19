"""Command line: ``mbhf segment``.

Examples
--------
Automatic, one file holding the whole adventure::

    mbhf segment day.gpx --json result.json --plot result.png

Separate files, each pinned to its mode (the program then only finds the transitions
inside files that are not pinned)::

    mbhf segment bike=ride_out.gpx walk=ascent.gpx flight=flight.igc bike=ride_back.gpx

Fix a transition by hand after looking at the plot (times in UTC unless an offset is given)::

    mbhf segment day.gpx --takeoff 2026-09-12T09:41:10Z
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Optional

from . import __version__
from .chrono import Chrono, chrono_to_dict, compute_chrono
from .merge import merge_tracks
from .models import MODES, Track, TrackError
from .parsers import load_track
from .parsers.common import parse_iso_time
from .rules import load_ruleset
from .segment import Cuts, SegmentationError, SegmentationResult, segment_track
from .transport import import_osm, load_lines, load_schedule


def _split_hint(arg: str) -> tuple[Optional[str], str]:
    if "=" in arg:
        head, tail = arg.split("=", 1)
        if head in MODES:
            return head, tail
        if head == "auto":
            return None, tail
    return None, arg


def _time_arg(text: str, name: str) -> object:
    when = parse_iso_time(text)
    if when is None:
        raise SystemExit(f"--{name}: cannot read {text!r} as an ISO 8601 time (e.g. 2026-09-12T09:41:10Z)")
    return when


def _transitions(res: SegmentationResult) -> dict[str, Optional[str]]:
    """Transition instants in the form accepted back by the --walk-start/... options."""
    out: dict[str, Optional[str]] = {
        "walk_start": None,
        "takeoff": None,
        "landing": None,
        "bike_return_start": None,
    }
    segs = res.segments
    for idx, s in enumerate(segs):
        if s.role == "ascent" and idx > 0:
            out["walk_start"] = s.t_start.isoformat()
        elif s.role == "flight":
            if idx > 0:
                out["takeoff"] = s.t_start.isoformat()
            if idx + 1 < len(segs):
                out["landing"] = segs[idx + 1].t_start.isoformat()
        elif s.role == "bike_return" and idx > 0:
            out["bike_return_start"] = s.t_start.isoformat()
    return out


def result_to_dict(track: Track, res: SegmentationResult, files: list[str], chrono: Optional[Chrono] = None) -> dict:
    return {
        "mbhf_version": __version__,
        "files": files,
        "fixes": len(track.points),
        "warnings": track.warnings + res.warnings,
        "transitions": _transitions(res),
        "chrono": None if chrono is None else chrono_to_dict(chrono),
        "segments": [
            {
                "role": s.role,
                "mode": s.mode,
                "start": s.t_start.isoformat(),
                "end": s.t_end.isoformat(),
                "first_fix": s.i_start,
                "last_fix": s.i_end,
                "duration_s": round(s.duration_s, 1),
                "distance_km": round(s.distance_m / 1000, 3),
                "ascent_m": None if s.ascent_m is None else round(s.ascent_m),
                "descent_m": None if s.descent_m is None else round(s.descent_m),
                "mean_speed_kmh": round(s.mean_speed_kmh, 1),
                "confidence": s.confidence,
                "gap_before_s": round(s.boundary_gap_s, 1),
                "start_fixed_by_user": s.user_fixed_start,
            }
            for s in res.segments
        ],
    }


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def print_summary(data: dict, out=sys.stdout) -> None:
    print(f"{data['fixes']} fixes from {len(data['files'])} file(s)", file=out)
    print(f"{'part':<20}{'start (UTC)':<22}{'duration':>9}{'km':>8}{'km/h':>7}{'+m':>7}{'-m':>7}  confidence", file=out)
    for s in data["segments"]:
        flag = " (fixed)" if s["start_fixed_by_user"] else ""
        print(
            f"{s['role']:<20}{s['start'][:19].replace('T', ' '):<22}"
            f"{_hms(s['duration_s']):>9}{s['distance_km']:>8.1f}{s['mean_speed_kmh']:>7.1f}"
            f"{'' if s['ascent_m'] is None else s['ascent_m']:>7}"
            f"{'' if s['descent_m'] is None else s['descent_m']:>7}  {s['confidence']}{flag}",
            file=out,
        )
    ch = data.get("chrono")
    if ch:
        state = "provisional: tram/lift check not performed" if ch["provisional"] else "tram/lift check performed"
        print(f"\nClimb chrono, Nid d'Aigle -> summit (ruleset {ch['ruleset']}; {state}):", file=out)
        if ch["climb_hms"]:
            print(
                f"  {ch['climb_hms']}   (last exit Nid d'Aigle {ch['nid_d_aigle_last_exit'][:19]}, "
                f"summit entry {ch['summit_first_entry_on_foot'][:19]} UTC, +-{ch['uncertainty_s']:.0f} s)",
                file=out,
            )
        print(
            f"  ranking: {'yes' if ch['ranking_eligible'] else 'no'}   "
            f"HF/BHF conditions (on foot to the summit, take-off from it): {'yes' if ch['hf_conditions_met'] else 'no'}",
            file=out,
        )
        for msg in ch["problems"]:
            print(f"  ! {msg}", file=out)
        for msg in ch["notes"]:
            print(f"  note: {msg}", file=out)
    if data["warnings"]:
        print("\nWarnings:", file=out)
        for w in data["warnings"]:
            print(f"  - {w}", file=out)


def make_plot(track: Track, res: SegmentationResult, path: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("plotting needs matplotlib (pip install matplotlib)") from exc
    from .segment import compute_features, SegmenterConfig

    colours = {"bike": "#1f77b4", "walk": "#2ca02c", "flight": "#d62728"}
    pts = track.points
    feats = compute_features(pts, SegmenterConfig())
    t = [p.t for p in pts]
    fig, (ax_alt, ax_spd, ax_map) = plt.subplots(3, 1, figsize=(11, 12), gridspec_kw={"height_ratios": [2, 2, 3]})
    for s in res.segments:
        sl = slice(s.i_start, s.i_end + 1)
        c = colours[s.mode]
        ax_alt.plot(t[sl], [p.alt for p in pts[sl]], color=c, lw=1.2, label=s.role)
        ax_spd.plot(t[sl], [f.v for f in feats[sl]], color=c, lw=0.8)
        ax_map.plot([p.lon for p in pts[sl]], [p.lat for p in pts[sl]], color=c, lw=1.2)
        if s.i_start > 0:
            for ax in (ax_alt, ax_spd):
                ax.axvline(s.t_start, color="grey", ls="--", lw=0.8)
    ax_alt.set_ylabel("altitude (m)")
    ax_spd.set_ylabel("ground speed (km/h)")
    ax_map.set_xlabel("longitude")
    ax_map.set_ylabel("latitude")
    ax_map.set_aspect(1 / max(0.2, math.cos(math.radians(pts[0].lat))))
    handles, labels = ax_alt.get_legend_handles_labels()
    ax_alt.legend(handles, labels, loc="upper left", fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def cmd_segment(args: argparse.Namespace) -> int:
    tracks = []
    for idx, arg in enumerate(args.files):
        hint, path = _split_hint(arg)
        tracks.append(load_track(path, hint=hint, src=idx))
    track = tracks[0] if len(tracks) == 1 else merge_tracks(tracks)
    cuts = Cuts(
        walk_start=_time_arg(args.walk_start, "walk-start") if args.walk_start else None,
        takeoff=_time_arg(args.takeoff, "takeoff") if args.takeoff else None,
        landing=_time_arg(args.landing, "landing") if args.landing else None,
        bike_return_start=_time_arg(args.bike_return_start, "bike-return-start") if args.bike_return_start else None,
    )
    res = segment_track(track, cuts)
    rules = load_ruleset(args.rules)
    chrono = compute_chrono(track, res, rules, load_lines(args.lines), load_schedule(args.schedule))
    data = result_to_dict(track, res, [t.source for t in tracks], chrono)
    print_summary(data)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        print(f"\nJSON written to {args.json}")
    if args.plot:
        make_plot(track, res, args.plot)
        print(f"Plot written to {args.plot}")
    return 0


def cmd_import_osm(args: argparse.Namespace) -> int:
    data = import_osm(args.file, args.tram_match)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    kinds: dict[str, int] = {}
    for ln in data["lines"]:
        kinds[ln["kind"]] = kinds.get(ln["kind"], 0) + 1
    print(f"{data['note']}: " + ", ".join(f"{n} {k} way(s)" for k, n in sorted(kinds.items())))
    print(f"written to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mbhf", description="Mont-Blanc Hike & Fly track tools")
    p.add_argument("--version", action="version", version=f"mbhf {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("segment", help="split a track into bike / walk / flight parts")
    s.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="track file (IGC, GPX, KML, FIT); prefix with bike=, walk=, flight= to pin it to a mode",
    )
    s.add_argument("--rules", help="ruleset JSON file (default: the packaged draft ruleset)")
    s.add_argument("--lines", help="tram and lift geometry JSON (default: the packaged OpenStreetMap extract)")
    s.add_argument("--schedule", help="tram timetable JSON (default: the packaged draft timetable)")
    s.add_argument("--json", help="write the result as JSON")
    s.add_argument("--plot", help="write a diagnostic plot (PNG)")
    s.add_argument("--walk-start", help="fix the start of the ascent on foot (ISO 8601 time)")
    s.add_argument("--takeoff", help="fix the take-off instant (ISO 8601 time)")
    s.add_argument("--landing", help="fix the landing instant (ISO 8601 time)")
    s.add_argument("--bike-return-start", help="fix the start of the ride back (ISO 8601 time)")
    s.set_defaults(func=cmd_segment)
    o = sub.add_parser("import-osm", help="turn an OpenStreetMap export (Overpass JSON or GeoJSON) into the line file")
    o.add_argument("file", help="export from overpass-turbo (GeoJSON) or Overpass 'out geom' JSON")
    o.add_argument("--out", required=True, help="output JSON (e.g. src/mbhf/data/transport-osm.json)")
    o.add_argument("--tram-match", default="tramway du mont", help="text identifying the tram line in name/ref/operator")
    o.set_defaults(func=cmd_import_osm)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (TrackError, SegmentationError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
