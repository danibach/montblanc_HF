"""The participant-facing web app (in French): upload tracks, get the climbing time, places and graphs.

Run locally::

    pip install -e ".[web]"
    flask --app mbhf.web:create_app run

In production use a WSGI server, e.g. ``gunicorn "mbhf.web:create_app()"`` (see the Dockerfile).
Nothing is stored: uploads live in memory and in a temporary directory deleted before the
response is sent. The server never logs file names or contents.
"""

from __future__ import annotations

import base64
import json
from typing import Optional

from flask import Flask, Response, render_template, request

from ..i18n import CONFIDENCE_FR, KIND_FR, VERDICT_FR
from ..service import AnalysisError, Upload, analyse_uploads
from ..transport import LineSet, Schedule, load_lines, load_schedule

MAX_UPLOAD_BYTES = 60 * 1024 * 1024
LANG = "fr"
MODE_CHOICES = (
    ("", "Toute la journée, parties détectées automatiquement"),
    ("bike", "Trajet à vélo seulement"),
    ("walk", "Marche seulement"),
    ("flight", "Vol seulement"),
)
CUT_FIELDS = ("walk_start", "takeoff", "landing", "bike_return_start")

CSP = (
    "default-src 'none'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'; connect-src 'none'"
)


def _hms(seconds) -> str:
    if seconds is None:
        return ""
    s = int(round(seconds))
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _dur(seconds) -> str:
    """Short duration for tables: 7 h 52 min, 28 min, 40 s."""
    if seconds is None:
        return ""
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600} h {(s % 3600) // 60:02d} min"
    if s >= 60:
        if s < 600 and s % 60:
            return f"{s // 60} min {s % 60:02d} s"
        return f"{s // 60} min"
    return f"{s} s"


def _num(value) -> str:
    """12.5 -> 12,5"""
    return str(value).replace(".", ",")


def create_app(lines: Optional[LineSet] = None, schedule: Optional[Schedule] = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.jinja_env.filters["hms"] = _hms
    app.jinja_env.filters["dur"] = _dur
    app.jinja_env.filters["num"] = _num
    app.jinja_env.filters["verdict"] = lambda v: VERDICT_FR.get(v, v)
    app.jinja_env.filters["kind"] = lambda v: KIND_FR.get(v, v)
    app.jinja_env.filters["confidence"] = lambda v: CONFIDENCE_FR.get(v, v)
    lines = load_lines() if lines is None else lines
    schedule = load_schedule() if schedule is None else schedule

    def page_index(error: Optional[str] = None, cuts: Optional[dict] = None, status: int = 200):
        html = render_template(
            "index.html", error=error, cuts=cuts or {}, modes=MODE_CHOICES, max_mb=MAX_UPLOAD_BYTES // (1024 * 1024)
        )
        return Response(html, status=status)

    @app.get("/")
    def index():
        return page_index()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/analyse")
    def analyse():
        cuts = {k: (request.form.get(k) or "").strip() for k in CUT_FIELDS}
        files = request.files.getlist("track")
        modes = request.form.getlist("mode")
        uploads = []
        for i, f in enumerate(files):
            if not f or not f.filename:
                continue
            mode = (modes[i] if i < len(modes) else "") or None
            uploads.append(Upload(filename=f.filename, data=f.read(), mode=mode))
        try:
            result = analyse_uploads(uploads, cuts, lines, schedule, lang=LANG)
        except AnalysisError as exc:
            return page_index(error=str(exc), cuts=cuts, status=400)
        except Exception as exc:  # never show internals, never log file content
            app.logger.error("analysis failed: %s", type(exc).__name__)
            return page_index(
                error="Un problème est survenu pendant l'analyse de ce fichier. Vérifiez qu'il s'agit de "
                "l'export complet d'un enregistrement, ou envoyez-le aux organisateurs.",
                cuts=cuts,
                status=500,
            )
        d = result.data
        html = render_template(
            "result.html",
            d=d,
            r=d["report"],
            c=d["chrono"],
            figure="data:image/png;base64," + base64.b64encode(result.png).decode("ascii"),
            json_text=json.dumps(d).replace("<", "\\u003c"),
        )
        return Response(html, headers={"Cache-Control": "no-store"})

    @app.errorhandler(413)
    def too_large(_exc):
        return page_index(
            error=f"Ces fichiers dépassent {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo au total. "
            "Envoyez un enregistrement à la fois, ou exportez avec une fréquence d'enregistrement plus basse.",
            status=413,
        )

    @app.after_request
    def secure(resp: Response) -> Response:
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    return app
