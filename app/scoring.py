"""Game maths: points, tiles, Against the Current bonus, depth zones, read tiers and crowd stats."""
import math
import statistics

from . import config
from .engine import AXES, composite_of

ZONES = [
    (0, "Sunlight", "☀️"),
    (200, "Twilight", "🌗"),
    (1000, "Midnight", "🌑"),
    (4000, "Abyss", "🦑"),
    (6000, "Hadal", "🕳️"),
]

TIERS = [
    # key, emoji, name, label, minimum share of the room beaten (%)
    ("surface", "🫧", "Surface", "Floating with the crowd", 0),
    ("reef", "🐠", "Reef", "Solid read", 40),
    ("twilight", "🐡", "Twilight", "Sharper than most", 70),
    ("deep", "🦑", "Deep read", "Most divers never got this deep", 90),
]
TOP_TIER = ("one", "🐋", "One in the room", "Nobody read it better", 100)
TOP_TIER_MIN_VOTES = 20


def axis_points(guess: float, engine: float, k: float | None = None) -> float:
    return 250 * math.exp(-abs(guess - engine) / (k or config.DECAY_K))


def vote_points(scores: dict, engine_axes: dict) -> int:
    return round(sum(axis_points(scores[a], engine_axes[a]) for a in AXES))


def tile(guess: int, engine: float) -> dict:
    err = abs(guess - engine)
    if err <= 0.5:
        return {"value": guess, "color": "green", "arrow": "✓"}
    arrow = "↑" if engine > guess else "↓"
    if err <= 1.5:
        return {"value": guess, "color": "yellow", "arrow": arrow}
    return {"value": guess, "color": "grey", "arrow": arrow * 2}


def card_points(r1_points: int, r2_points: int | None, bonus: int | None) -> int:
    """Round 1 counts in full; improvement in round 2 counts at half value; plus any bonus."""
    revised = 0.5 * max(0, (r2_points if r2_points is not None else r1_points) - r1_points)
    return round(r1_points + revised) + (bonus or 0)


def zone(depth: float) -> dict:
    current = ZONES[0]
    for z in ZONES:
        if depth >= z[0]:
            current = z
    return {"name": current[1], "emoji": current[2], "from": current[0]}


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
    """Aggregate round votes (rows or dicts with the four axis columns)."""
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
        # Most common bucket; ties go to the bucket closest to the mean.
        "mode": {a: max(range(6), key=lambda b: (dist[a][b], -abs(b - means[a]))) for a in AXES},
        "composite": composite_of(means),
        "composites": composites,
        "consensus": round(statistics.pstdev(composites), 2) if n > 1 else 0.0,
    }


def against_current_bonus(scores: dict, engine_axes: dict, room: dict) -> tuple[int | None, list[str]]:
    """Krillion-style rarity bonus, but only for reads that are right while the room is wrong.

    Returns (None, []) when the room is too small to judge yet.
    """
    if room["n"] < config.MIN_VOTES:
        return None, []
    total, axes = 0.0, []
    for a in AXES:
        x = engine_axes[a]
        if abs(scores[a] - x) <= 0.5 and abs(room["means"][a] - x) > 1.0:
            within = sum(c for b, c in enumerate(room["dist"][a]) if abs(b - x) <= 0.5) / room["n"]
            total += 250 * (1 - within)
            axes.append(a)
    return round(total), axes


def read_tier(mine: int, everyone: list[int]) -> dict | None:
    """Tier from the share of the room you beat on this card. `everyone` includes you."""
    n = len(everyone)
    if n < config.MIN_VOTES:
        return None
    beat = 100 * sum(1 for p in everyone if p < mine) / max(1, n - 1)
    if n >= TOP_TIER_MIN_VOTES and mine == max(everyone) and everyone.count(mine) == 1:
        key, emoji, name, label, _ = TOP_TIER
    else:
        key, emoji, name, label, _ = [t for t in TIERS if beat >= t[4]][-1]
    return {"key": key, "emoji": emoji, "name": name, "label": label, "beat": round(beat)}


TIER_ORDER = {t[0]: i for i, t in enumerate(TIERS)} | {TOP_TIER[0]: len(TIERS)}
