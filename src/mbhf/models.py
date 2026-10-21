"""Core data structures shared by parsers, merger and segmenter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

MODES = ("bike", "walk", "flight")


class TrackError(ValueError):
    """A track file cannot be used (unreadable, no timestamps, ...)."""


@dataclass(frozen=True)
class Point:
    t: datetime                      # timezone-aware, UTC
    lat: float                       # degrees
    lon: float                       # degrees
    alt: Optional[float] = None      # metres, preferred altitude (GNSS when available)
    alt_baro: Optional[float] = None  # metres, pressure altitude (IGC only)
    hint: Optional[str] = None       # forced mode: "bike" | "walk" | "flight" | None
    src: int = 0                     # index of the source file


@dataclass
class Track:
    points: list[Point]
    source: str                      # file name
    fmt: str                         # "gpx" | "kml" | "igc" | "tcx" | "fit" | "merged"
    hint: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    @property
    def t_start(self) -> datetime:
        return self.points[0].t

    @property
    def t_end(self) -> datetime:
        return self.points[-1].t
