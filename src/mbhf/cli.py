"""``mbhf analyse FILE``: run the analysis on a track file and print the outing as JSON."""

from __future__ import annotations

import argparse
import json
import sys

from .analyse import AnalysisError, analyse_bytes
from .places import fetch_overpass, overpass_query, resolve_places


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mbhf", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    an = sub.add_parser("analyse", help="analyse one track file (IGC, GPX, KML or FIT)")
    an.add_argument("file")
    an.add_argument("--places", action="store_true", help="also look up place names on OpenStreetMap")
    an.add_argument("--no-trace", action="store_true", help="leave the drawing arrays out of the output")
    args = ap.parse_args(argv)

    with open(args.file, "rb") as fh:
        data = fh.read()
    try:
        result = analyse_bytes(args.file, data)
    except AnalysisError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.places:
        query = overpass_query(result["outing"])
        if query:
            try:
                result["places"] = resolve_places(result["outing"], fetch_overpass(query))
            except OSError as exc:
                print(f"places: {exc}", file=sys.stderr)
    if args.no_trace:
        result.pop("trace", None)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
