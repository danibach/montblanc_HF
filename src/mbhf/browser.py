"""Entry point for the in-browser page (Python running in the participant's browser via Pyodide).

The page sends the files' bytes and the transitions the participant pinned; it gets back one JSON
string. Nothing leaves the participant's device: this module only calls ``analyse_uploads``.
The same function runs under normal Python, which is how the tests check it.
"""

from __future__ import annotations

import json
from typing import Iterable, Optional

from . import __version__
from .service import AnalysisError, Upload, analyse_uploads

CUT_KEYS = ("walk_start", "takeoff", "landing", "bike_return_start")

GENERIC_ERROR = (
    "Un problème est survenu pendant l'analyse de ce fichier. Vérifiez qu'il s'agit de l'export "
    "complet d'un enregistrement, ou envoyez-le aux organisateurs."
)


def analyse_json(files: Iterable[tuple[str, bytes, Optional[str]]], cuts: Optional[dict] = None) -> str:
    """Analyse ``files`` (name, content, mode or None) with optional pinned transitions.

    Returns ``{"ok": true, "result": {...}}`` or ``{"ok": false, "error": "<message in French>"}``.
    """
    uploads = [Upload(filename=name, data=bytes(data), mode=(mode or None)) for name, data, mode in files]
    clean_cuts = {k: str((cuts or {}).get(k) or "").strip() for k in CUT_KEYS}
    try:
        result = analyse_uploads(uploads, clean_cuts, lang="fr", figure=False, trace=True)
    except AnalysisError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:  # never show internals; the type name helps support
        return json.dumps({"ok": False, "error": GENERIC_ERROR, "detail": type(exc).__name__}, ensure_ascii=False)
    data = result.data
    data["engine"] = {"mbhf_version": __version__, "where": "browser"}
    return json.dumps({"ok": True, "result": data}, ensure_ascii=False)
