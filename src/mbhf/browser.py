"""Entry points for the web page (Python running in the participant's browser via Pyodide).

The page hands over the file's bytes and gets one JSON string back. Names come from OpenStreetMap:
the page asks ``places_query`` for the query text, sends it to Overpass itself, then gives the
answer to ``resolve_places_json``. The same functions run under normal Python, which is how the
tests check them.
"""

from __future__ import annotations

import json
from typing import Optional

from datetime import datetime

from .analyse import (AnalysisError, ends_of, finish, prepare_bytes, prepare_files, read_bytes, terrain_query_for,
                      with_terrain)
from .multi import Ends, groups
from .terrain import parse_elevations, sample_flights
from .places import overpass_query, resolve_places

GENERIC_ERROR = (
    "Something went wrong while reading this file. Check that it is the complete export of a "
    "recording."
)


_LAST: dict = {}  # the file just analysed, kept for the terrain check (one at a time)


def analyse_json(name: str, data: bytes) -> str:
    """Returns ``{"ok": true, "result": {...}}`` or ``{"ok": false, "error": "..."}``.

    ``result["terrain"]["query"]`` is what the page may ask the elevation service for; the answer goes to
    ``terrain_json``, which returns the result again with the check applied."""
    return _result_json(lambda: prepare_bytes(name, bytes(data)))


_PARTS: list = []  # the files of one outing in several files, added one by one (parts_add)


def parts_clear() -> None:
    _PARTS.clear()


def parts_add(name: str, data: bytes) -> None:
    _PARTS.append((name, bytes(data)))


def analyse_parts_json() -> str:
    """``analyse_json`` for the files added with ``parts_add``, joined into one outing (multi.py)."""
    parts = list(_PARTS)
    _PARTS.clear()
    return _result_json(lambda: prepare_files(parts))


def ends_json(name: str, data: bytes) -> str:
    """When and where a file starts and ends: ``{"ok": true, "ends": {...}}`` (read only, not analysed)."""
    try:
        track, _ = read_bytes(name, bytes(data))
    except AnalysisError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": GENERIC_ERROR, "detail": type(exc).__name__}, ensure_ascii=False)
    e = ends_of(track)
    return json.dumps({"ok": True, "ends": {"t0": e.t0.isoformat(), "lat0": e.lat0, "lon0": e.lon0,
                                            "t1": e.t1.isoformat(), "lat1": e.lat1, "lon1": e.lon1}})


def groups_json(ends_list_json: str) -> str:
    """The files (by position in the list, ``None`` for a file that could not be read) that follow one another
    and make one outing: ``[[0, 2, 3], [1], …]``."""
    items = json.loads(ends_list_json)
    known = [k for k, e in enumerate(items) if e]
    ends = [Ends(datetime.fromisoformat(items[k]["t0"]), items[k]["lat0"], items[k]["lon0"],
                 datetime.fromisoformat(items[k]["t1"]), items[k]["lat1"], items[k]["lon1"]) for k in known]
    out = [[known[k] for k in g] for g in groups(ends)]
    out += [[k] for k, e in enumerate(items) if not e]
    return json.dumps(out)


def _result_json(prepare) -> str:
    try:
        prepared = prepare()
        result = finish(prepared)
        _LAST.clear()
        _LAST[result["file"]["sha256"]] = prepared
        result["terrain"] = {"query": terrain_query_for(prepared)}
    except AnalysisError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:  # never show internals; the type name helps support
        return json.dumps({"ok": False, "error": GENERIC_ERROR, "detail": type(exc).__name__}, ensure_ascii=False)
    result["engine"]["where"] = "browser"
    return json.dumps({"ok": True, "result": result}, ensure_ascii=False)


def places_query(outing_json: str) -> Optional[str]:
    return overpass_query(json.loads(outing_json))


def resolve_places_json(outing_json: str, overpass_json: str) -> str:
    return json.dumps(resolve_places(json.loads(outing_json), json.loads(overpass_json)), ensure_ascii=False)


def terrain_json(sha256: str, response_json: str) -> str:
    """The result again, after the terrain check. ``response_json`` is the elevation service's answer
    (``"null"`` when it could not be reached: the flights are then kept)."""
    prepared = _LAST.get(sha256)
    if prepared is None:
        return json.dumps({"ok": False, "error": "Analyse the file again."})
    try:
        samples = sample_flights(prepared.track, prepared.seg)
        elevations = parse_elevations(json.loads(response_json), len(samples))
        result = with_terrain(prepared, elevations)
    except Exception as exc:
        return json.dumps({"ok": False, "error": GENERIC_ERROR, "detail": type(exc).__name__})
    result["engine"]["where"] = "browser"
    return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
