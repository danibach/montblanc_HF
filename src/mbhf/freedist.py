"""FAI free distance: the longest route from a start point through up to three turn points to a finish.

The points must be taken in the order they were flown (start, turn 1, turn 2, turn 3, finish), each
on the track. The search runs on at most ``coarse`` evenly spaced fixes with dynamic programming,
then each chosen point is moved to the best nearby real fix.
"""

from __future__ import annotations

from typing import Sequence

from .geo import haversine_m


def _leg(coords: Sequence[tuple[float, float]], a: int, b: int) -> float:
    return haversine_m(coords[a][0], coords[a][1], coords[b][0], coords[b][1])


def free_distance(
    coords: Sequence[tuple[float, float]], max_turnpoints: int = 3, coarse: int = 240
) -> tuple[float, list[int]]:
    """Return (distance in metres, indices into ``coords`` of start, turn points, finish)."""
    n = len(coords)
    if n < 2:
        return 0.0, [0] if n else []
    if n > coarse:
        idx = sorted({round(k * (n - 1) / (coarse - 1)) for k in range(coarse)})
    else:
        idx = list(range(n))
    m = len(idx)
    dist = [[0.0] * m for _ in range(m)]
    for a in range(m):
        for b in range(a + 1, m):
            dist[a][b] = _leg(coords, idx[a], idx[b])

    legs = max_turnpoints + 1
    prev = [0.0] * m
    pointers: list[list[int]] = []
    for _ in range(legs):
        cur = [0.0] * m
        ptr = [0] * m
        for j in range(m):
            best, arg = prev[j], j  # zero-length leg: fewer turn points
            for i in range(j):
                v = prev[i] + dist[i][j]
                if v > best:
                    best, arg = v, i
            cur[j] = best
            ptr[j] = arg
        pointers.append(ptr)
        prev = cur
    j = max(range(m), key=lambda x: prev[x])
    path = [j]
    for ptr in reversed(pointers):
        j = ptr[j]
        path.append(j)
    path.reverse()
    chosen = [idx[k] for k in path]

    # keep the order, drop repeats
    chosen = sorted(set(chosen))
    if len(chosen) < 2:
        chosen = [0, n - 1]
    chosen = _refine(coords, chosen, max(1, (n - 1) // max(1, m - 1)))
    total = sum(_leg(coords, chosen[k], chosen[k + 1]) for k in range(len(chosen) - 1))
    return total, chosen


def _refine(coords: Sequence[tuple[float, float]], chosen: list[int], radius: int) -> list[int]:
    n = len(coords)
    pts = list(chosen)
    for _ in range(2):
        for k in range(len(pts)):
            lo = (pts[k - 1] + 1) if k > 0 else 0
            hi = (pts[k + 1] - 1) if k < len(pts) - 1 else n - 1
            best_i, best_v = pts[k], -1.0
            for cand in range(max(lo, pts[k] - radius), min(hi, pts[k] + radius) + 1):
                v = 0.0
                if k > 0:
                    v += _leg(coords, pts[k - 1], cand)
                if k < len(pts) - 1:
                    v += _leg(coords, cand, pts[k + 1])
                if v > best_v:
                    best_i, best_v = cand, v
            pts[k] = best_i
    return pts
