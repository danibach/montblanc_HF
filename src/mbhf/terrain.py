"""Tell a flight from a descent on the ground (ski, bike, running) by the height above the terrain.

A skier or a rider follows the ground: the height above it stays near zero. A wing is in the air, often
hundreds of metres above the valley. So for each stretch labelled "flight" we take a few dozen fixes, ask
a terrain model for the ground altitude under each, and look at how much of the stretch is clearly above it.

    samples = sample_flights(track, seg)              # fixes to look up
    query = elevation_query(samples)                  # text for the elevation service
    elevations = parse_elevations(response)           # its answer
    seg, notes = apply_terrain(track, seg, samples, elevations)

The browser makes the request itself (like Overpass); the server uses ``fetch_elevations``. Nothing here
needs a key. If the service cannot be reached, nothing changes: the flight is kept.

Thresholds are first guesses (the terrain model has a 30-90 m resolution and GPS altitude drifts by
10-30 m): ``TerrainConfig``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .models import Track
from .segment import FLIGHT, VEHICLE, SegmentationResult, _build_segments

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
MAX_COORDINATES = 100  # the service takes at most 100 per request
USER_AGENT = "mbhf-hikeandfly/0.3 (https://github.com/danibach/montblanc_HF)"


@dataclass
class TerrainConfig:
    # a fix is "in the air" when it is more than this above the ground
    air_height_m: float = 60.0
    # a stretch is a flight when at least this share of its fixes are in the air
    min_air_share: float = 0.35
    # fewer valid fixes than this: no verdict, the flight is kept
    min_samples: int = 6
    # fixes to look up per flight: one every ``every_s`` seconds, between these bounds
    every_s: float = 40.0
    min_per_flight: int = 8
    max_per_flight: int = 45


def sample_flights(track: Track, seg: SegmentationResult, cfg: Optional[TerrainConfig] = None) -> list[dict]:
    """Fixes spread along each flight: ``[{"flight": k, "i": index, "lat", "lon", "alt"}]``."""
    cfg = cfg or TerrainConfig()
    flights = [(k, s) for k, s in enumerate(seg.segments) if s.mode == "flight"]
    counts = []
    for _, s in flights:
        n = int(s.duration_s / cfg.every_s)
        counts.append(max(cfg.min_per_flight, min(cfg.max_per_flight, n)))
    total = sum(counts)
    if total > MAX_COORDINATES:  # a long track with several flights: thin each one out
        counts = [max(4, c * MAX_COORDINATES // total) for c in counts]
    out: list[dict] = []
    for (k, s), n in zip(flights, counts):
        span = s.i_end - s.i_start
        idx = sorted({s.i_start + round(span * m / max(1, n - 1)) for m in range(n)})
        for i in idx:
            p = track.points[i]
            if p.alt is not None:
                out.append({"flight": k, "i": i, "lat": p.lat, "lon": p.lon, "alt": p.alt})
    return out[:MAX_COORDINATES]


def elevation_query(samples: list[dict]) -> Optional[str]:
    """The query string for the elevation service, or None when there is nothing to look up."""
    if not samples:
        return None
    lat = ",".join(f"{s['lat']:.4f}" for s in samples)
    lon = ",".join(f"{s['lon']:.4f}" for s in samples)
    return f"latitude={lat}&longitude={lon}"


def parse_elevations(response, expected: int) -> Optional[list[Optional[float]]]:
    """The service's answer as a list of metres (None where unknown), or None if it is not usable."""
    try:
        values = response["elevation"]
    except (KeyError, TypeError):
        return None
    if not isinstance(values, list) or len(values) != expected:
        return None
    out: list[Optional[float]] = []
    for v in values:
        out.append(float(v) if isinstance(v, (int, float)) and v == v else None)
    return out


def fetch_elevations(samples: list[dict], timeout: float = 20.0) -> Optional[list[Optional[float]]]:
    """Server side: ask the elevation service. None if it cannot be reached or answers nonsense."""
    query = elevation_query(samples)
    if not query:
        return None
    req = urllib.request.Request(f"{ELEVATION_URL}?{query}", headers={"User-Agent": USER_AGENT})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return parse_elevations(json.loads(resp.read()), len(samples))
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(1.5 * (attempt + 1))
    return None


def air_share(samples: list[dict], elevations: list[Optional[float]], cfg: TerrainConfig) -> Optional[float]:
    """Share of the fixes more than ``air_height_m`` above the ground; None when too few can be judged."""
    heights = [s["alt"] - e for s, e in zip(samples, elevations) if e is not None]
    if len(heights) < cfg.min_samples:
        return None
    return sum(1 for h in heights if h > cfg.air_height_m) / len(heights)


def apply_terrain(
    track: Track,
    seg: SegmentationResult,
    samples: list[dict],
    elevations: Optional[list[Optional[float]]],
    cfg: Optional[TerrainConfig] = None,
) -> tuple[SegmentationResult, list[str]]:
    """Relabel the "flights" that follow the ground as vehicle. Returns the new segmentation and notes."""
    cfg = cfg or TerrainConfig()
    if not samples:
        return seg, []
    if elevations is None or len(elevations) != len(samples):
        return seg, ["Terrain check not available: flights are kept as found."]
    labels = list(seg.labels)
    notes: list[str] = []
    changed = False
    for k, s in enumerate(seg.segments):
        if s.mode != "flight":
            continue
        idx = [n for n, sm in enumerate(samples) if sm["flight"] == k]
        share = air_share([samples[n] for n in idx], [elevations[n] for n in idx], cfg)
        if share is not None and share < cfg.min_air_share:
            for i in range(s.i_start, s.i_end + 1):
                labels[i] = VEHICLE
            changed = True
            notes.append("A fast descent follows the ground (ski, bike or run), so it is not counted as a flight.")
    if not changed:
        return seg, notes
    return SegmentationResult(segments=_build_segments(track.points, labels), labels=labels, warnings=seg.warnings), notes
