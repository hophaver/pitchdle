"""Crowd statistics over stored votes, and how one player's read compares with the crowd's."""
import math
import statistics

from .engine import AXES, composite_of

# How far a player's composite can sit from the crowd's and still count as "with the crowd".
LEAN_THRESHOLD = 0.5


def largest_remainder(counts: list[int]) -> list[int]:
    """Whole-number percentages that always add up to 100 (or all zero)."""
    total = sum(counts)
    if not total:
        return [0] * len(counts)
    raw = [c * 100 / total for c in counts]
    floors = [math.floor(r) for r in raw]
    short = 100 - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in order[:short]:
        floors[i] += 1
    return floors


def crowd(votes: list) -> dict:
    """Aggregate votes (rows or dicts with the four axis columns)."""
    n = len(votes)
    dist = {a: [0] * 6 for a in AXES}
    for v in votes:
        for a in AXES:
            dist[a][int(v[a])] += 1
    if not n:
        return {"n": 0, "means": None, "dist": dist, "share": {a: [0] * 6 for a in AXES},
                "mode": None, "composite": None, "composites": [], "consensus": None}
    means = {a: round(sum(v[a] for v in votes) / n, 2) for a in AXES}
    composites = [composite_of({a: v[a] for a in AXES}) for v in votes]
    return {
        "n": n,
        "means": means,
        "dist": dist,
        "share": {a: largest_remainder(dist[a]) for a in AXES},
        # Most common answer; ties go to the one closest to the mean.
        "mode": {a: max(range(6), key=lambda b: (dist[a][b], -abs(b - means[a]))) for a in AXES},
        "composite": composite_of(means),
        "composites": composites,
        "consensus": round(statistics.pstdev(composites), 2) if n > 1 else 0.0,
    }


def lean(you: float, crowd_value: float) -> str:
    """Where a player sits relative to the crowd: higher, with, or lower."""
    diff = you - crowd_value
    if diff >= LEAN_THRESHOLD:
        return "higher"
    if diff <= -LEAN_THRESHOLD:
        return "lower"
    return "with"
