"""The engine read: a deterministic score per player axis, computed from hand-authored evidence.

Runs when a company is saved or rescored, never in the game's request path. Unknown evidence is a
real state: an axis is scored from its known factors only, and coverage records what was missing.
"""
import json
from functools import lru_cache

from . import config

AXES = ("novel", "useful", "plausible", "investable")

FACTOR_GROUPS = {
    "impact": ["measurability", "problem_pressure", "solution_potential"],
    "brl": ["market", "value_prop", "business_model", "scalability"],
    "redstone": [
        "market", "product", "team", "business_model", "competition",
        "marketing", "financials", "tech", "deal_dynamics", "impact",
    ],
}
GROUP_LABELS = {"impact": "Ocean Impact", "brl": "Business Readiness", "redstone": "Redstone"}

# Evidence-derived TRL (never self-claimed). Stage -> TRL 1-9.
TRL_STAGES = {
    "idea": 1, "concept": 2, "lab": 4, "prototype": 5,
    "pilot": 6, "demonstrated": 7, "deployed": 8, "commercial": 9,
}


@lru_cache
def load_weights() -> dict:
    return json.loads(config.WEIGHTS_PATH.read_text())


def factor_keys() -> list[str]:
    keys = ["trl", "patents"]
    for group, names in FACTOR_GROUPS.items():
        keys += [f"{group}.{name}" for name in names]
    return keys


def factor_label(key: str) -> str:
    if key == "trl":
        return "Tech readiness (TRL)"
    if key == "patents":
        return "Patents"
    group, name = key.split(".")
    return f"{name.replace('_', ' ').capitalize()} ({GROUP_LABELS[group]})"


def factor_value(evidence: dict, key: str) -> float | None:
    """A factor on the 0-5 scale, or None when the evidence doesn't say."""
    if key == "trl":
        stage = evidence.get("trl_stage")
        if stage not in TRL_STAGES:
            return None
        return (TRL_STAGES[stage] - 1) / 8 * 5
    if key == "patents":
        count = evidence.get("patents")
        if count is None or count == "":
            return None
        count = int(count)
        return min(5.0, 1.0 + 1.5 * count) if count > 0 else 1.0
    group, name = key.split(".")
    value = (evidence.get(group) or {}).get(name)
    if value is None or value == "":
        return None
    return max(0.0, min(5.0, float(value)))


def score(evidence: dict, weights: dict | None = None) -> dict:
    weights = weights or load_weights()
    axes, by_axis = {}, {}
    for axis in AXES:
        spec = weights["axes"][axis]
        num = den = 0.0
        known = 0
        for key, weight in spec:
            value = factor_value(evidence, key)
            if value is None:
                continue
            num += weight * value
            den += weight
            known += 1
        axes[axis] = round(num / den, 1) if den else float(weights.get("unknown_axis_default", 2.0))
        by_axis[axis] = {"assessed": known, "total": len(spec)}
    keys = factor_keys()
    unknown = [k for k in keys if factor_value(evidence, k) is None]
    return {
        "axes": axes,
        "composite": composite_of(axes, weights),
        "coverage": {
            "assessed": len(keys) - len(unknown),
            "total": len(keys),
            "unknown": [factor_label(k) for k in unknown],
            "by_axis": by_axis,
        },
    }


def composite_of(scores: dict, weights: dict | None = None) -> float:
    """Weighted mean of the four axes. Used for engine, player and crowd composites alike."""
    cw = (weights or load_weights())["composite"]
    return round(sum(cw[a] * float(scores[a]) for a in AXES) / sum(cw[a] for a in AXES), 1)
