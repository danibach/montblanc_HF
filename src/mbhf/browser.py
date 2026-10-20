"""Entry points for the web page (Python running in the participant's browser via Pyodide).

The page hands over the file's bytes and gets one JSON string back. Names come from OpenStreetMap:
the page asks ``places_query`` for the query text, sends it to Overpass itself, then gives the
answer to ``resolve_places_json``. The same functions run under normal Python, which is how the
tests check them.
"""

from __future__ import annotations

import json
from typing import Optional

from .analyse import AnalysisError, analyse_bytes
from .places import overpass_query, resolve_places

GENERIC_ERROR = (
    "Something went wrong while reading this file. Check that it is the complete export of a "
    "recording."
)


def analyse_json(name: str, data: bytes) -> str:
    """Returns ``{"ok": true, "result": {...}}`` or ``{"ok": false, "error": "..."}``."""
    try:
        result = analyse_bytes(name, bytes(data))
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
