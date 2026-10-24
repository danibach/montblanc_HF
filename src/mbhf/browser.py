"""Entry points for the web page (Python running in the participant's browser via Pyodide).

The page hands over the file's bytes and gets one JSON string back. Names come from OpenStreetMap:
the page asks ``places_query`` for the query text, sends it to Overpass itself, then gives the
answer to ``resolve_places_json``. The same functions run under normal Python, which is how the
tests check them.
"""

from __future__ import annotations

import json
from typing import Optional

from .access import parse_access
from .analyse import (AnalysisError, access_points, access_query_for, finish, prepare_bytes, snow_url_for,
                      terrain_query_for, with_terrain)
from .terrain import parse_elevations, sample_flights
from .places import overpass_query, resolve_places

GENERIC_ERROR = (
    "Something went wrong while reading this file. Check that it is the complete export of a "
    "recording."
)


_LAST: dict = {}  # the file just analysed, kept for the terrain check (one at a time)


def analyse_json(name: str, data: bytes) -> str:
    """Returns ``{"ok": true, "result": {...}}`` or ``{"ok": false, "error": "..."}``.

    ``result["terrain"]["query"]`` is what the page may ask the elevation service for, and
    ``result["terrain"]["access"]`` what it may ask Overpass for (roads and lifts near a gap that may be a
    flight), ``result["terrain"]["snow"]`` the URL of the snow there; the answers go to ``terrain_json``, which
    returns the result again with the checks applied."""
    try:
        prepared = prepare_bytes(name, bytes(data))
        result = finish(prepared)
        _LAST.clear()
        _LAST[result["file"]["sha256"]] = prepared
        result["terrain"] = {"query": terrain_query_for(prepared), "access": access_query_for(prepared),
                             "snow": snow_url_for(prepared)}
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


def terrain_json(sha256: str, response_json: str, access_json: str = "null", snow_json: str = "null") -> str:
    """The result again, after the terrain check. ``response_json`` is the elevation service's answer
    (``"null"`` when it could not be reached: the flights are then kept), ``access_json`` Overpass's answer
    about the roads and lifts and ``snow_json`` the snow service's (``"null"``: unknown)."""
    prepared = _LAST.get(sha256)
    if prepared is None:
        return json.dumps({"ok": False, "error": "Analyse the file again."})
    try:
        samples = sample_flights(prepared.track, prepared.seg)
        elevations = parse_elevations(json.loads(response_json), len(samples))
        access = parse_access(json.loads(access_json), len(access_points(prepared)))
        result = with_terrain(prepared, elevations, access, json.loads(snow_json))
    except Exception as exc:
        return json.dumps({"ok": False, "error": GENERIC_ERROR, "detail": type(exc).__name__})
    result["engine"]["where"] = "browser"
    return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
