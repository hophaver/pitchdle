"""Crowd statistics over stored votes, and how one player's read compares with the crowd's."""
import math

from . import config
from .engine import AXES, composite_of

# How far a player's composite can sit from the crowd's and still count as "with the crowd".
LEAN_THRESHOLD = 0.5


def largest_remainder(counts: list[float]) -> list[int]:
    """Whole-number percentages that always add up to 100 (or all zero). Counts may be weighted."""
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


def signed_in(vote) -> bool:
    """Whether a vote came from a signed-in player (rows carry user_id when joined with players)."""
    try:
        return vote["user_id"] is not None
    except (KeyError, IndexError):
        return False


def badge_of(vote) -> str:
    """The voter's moderator badge: '' for none (and for guests), or high, low or muted."""
    try:
        return vote["badge"] or ""
    except (KeyError, IndexError):
        return ""


def badge_weight(badge: str) -> float:
    return {"high": config.HIGH_PRIORITY_WEIGHT, "low": config.LOW_PRIORITY_WEIGHT, "muted": 0.0}.get(badge, 1.0)


def vote_weights(votes: list) -> list[float]:
    """How much each vote counts towards a crowd score: members by their badge, guests weighed down to blunt bot farms.

    Members count 1, scaled by the badge a moderator gave them (high or low priority; muted is 0). Guests count
    GUEST_WEIGHT each, shrinking further as guests pile up so that together they never make up more than
    GUEST_MAX_SHARE of the total. With no member weight to weigh them against, guests count 1 each.
    """
    members = [badge_weight(badge_of(v)) if signed_in(v) else None for v in votes]
    member_total = sum(w for w in members if w is not None)
    guests = members.count(None)
    if not guests or not member_total:
        return [1.0 if w is None else w for w in members]
    share = min(max(config.GUEST_MAX_SHARE, 0.0), 0.99)
    guest = min(config.GUEST_WEIGHT, share / (1 - share) * member_total / guests)
    return [guest if w is None else w for w in members]


def crowd(votes: list, weighted: bool = True) -> dict:
    """Aggregate votes (rows or dicts with the four axis columns).

    Weighted, guests count for less and members by their badge; unweighted counts everyone alike, as a live
    room does. Either way a muted member's answers are left out entirely, from the counts too.
    """
    weights = vote_weights(votes) if weighted else [0.0 if badge_of(v) == "muted" else 1.0 for v in votes]
    counted = [(v, w) for v, w in zip(votes, weights) if w > 0]
    votes, weights = [v for v, _ in counted], [w for _, w in counted]
    n = len(votes)
    dist = {a: [0.0] * 6 for a in AXES}
    for v, w in zip(votes, weights):
        for a in AXES:
            dist[a][int(v[a])] += w
    if not n:
        return {"n": 0, "signed_in": 0, "means": None, "dist": dist, "share": {a: [0] * 6 for a in AXES},
                "mode": None, "composite": None, "composites": [], "consensus": None}
    total = sum(weights)
    means = {a: round(sum(w * v[a] for v, w in zip(votes, weights)) / total, 2) for a in AXES}
    composites = [composite_of({a: v[a] for a in AXES}) for v in votes]
    centre = sum(w * c for c, w in zip(composites, weights)) / total
    return {
        "n": n,
        "signed_in": sum(signed_in(v) for v in votes),
        "means": means,
        "dist": dist,
        "share": {a: largest_remainder(dist[a]) for a in AXES},
        # Most common answer; ties go to the one closest to the mean.
        "mode": {a: max(range(6), key=lambda b: (dist[a][b], -abs(b - means[a]))) for a in AXES},
        "composite": composite_of(means),
        "composites": composites,
        "consensus": round(math.sqrt(sum(w * (c - centre) ** 2 for c, w in zip(composites, weights)) / total), 2)
        if n > 1 else 0.0,
    }


def lean(you: float, crowd_value: float) -> str:
    """Where a player sits relative to the crowd: higher, with, or lower."""
    diff = you - crowd_value
    if diff >= LEAN_THRESHOLD:
        return "higher"
    if diff <= -LEAN_THRESHOLD:
        return "lower"
    return "with"
