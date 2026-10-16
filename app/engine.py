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


def _weighted_known(evidence: dict, spec: list, weights: dict) -> tuple[float | None, int, int]:
    """Weighted mean over known factors (0-5), plus how many were assessed and total.

    Mirrors the per-axis loop in `score`: unknown factors drop out of the mean and coverage records
    what was missing. Returns (None, 0, total) when nothing is known for this spec.
    """
    num = den = 0.0
    known = 0
    for key, weight in spec:
        value = factor_value(evidence, key)
        if value is None:
            continue
        num += weight * value
        den += weight
        known += 1
    if not den:
        return None, 0, len(spec)
    return round(num / den, 1), known, len(spec)


def TRL_number(evidence: dict) -> int | None:
    """Evidence-derived TRL 1-9, or None when the stage isn't given. Never a self-claim."""
    stage = evidence.get("trl_stage")
    return TRL_STAGES.get(stage)


def readiness(evidence: dict, weights: dict | None = None) -> dict:
    """The four named readiness levels the challenge brief asks for, plus coverage for each.

    Each level is a weighted mean of its factors (or the TRL factor directly). A missing read comes
    back as None so the dashboard can show \"unknown/unevidenced\" honestly.
    """
    weights = weights or load_weights()
    out = {}
    for key, spec in weights["levels"].items():
        label = spec["label"]
        if "factor" in spec:  # TRL: one factor, surfaced as 1-9
            trl = TRL_number(evidence)
            score = round((trl - 1) / 8 * 5, 1) if trl is not None else None
            out[key] = {"key": key, "label": label, "score": score, "trl": trl,
                        "coverage": {"assessed": 1 if trl is not None else 0, "total": 1}}
        else:
            score, assessed, total = _weighted_known(evidence, spec["factors"], weights)
            out[key] = {"key": key, "label": label, "score": score,
                        "coverage": {"assessed": assessed, "total": total}}
    return out


def _thesis_why(evidence: dict, score: float | None, spec: list, weights: dict) -> tuple[str, list, list]:
    """A short, evidence-grounded reason for a thesis score: top strengths and top risks.

    Strengths and risks are the factors pulling the score up or down, from the actual values.
    """
    scored = []
    for key, weight in spec:
        value = factor_value(evidence, key)
        if value is None:
            continue
        scored.append({"key": key, "label": factor_label(key), "value": value, "weight": weight})
    scored.sort(key=lambda f: (f["value"] - 2.5) * f["weight"], reverse=True)
    strengths = [f for f in scored if f["value"] >= 3.5]
    risks = [f for f in scored if f["value"] <= 2.0]
    if score is None:
        return "Not enough evidence to assess fit.", strengths[:3], risks[:3]
    top = ", ".join(f"{f['label'].lower()} {f['value']:.1f}" for f in strengths[:2]) or "nothing rated high"
    weak = ", ".join(f"{f['label'].lower()} at {f['value']:.1f}" for f in risks[:2]) or "no obvious weaknesses"
    return f"Fits on {top}; watch {weak}.", strengths[:3], risks[:3]


def theses(evidence: dict, weights: dict | None = None) -> dict:
    """Thesis-fit for each holder (A'Pelago accelerator, Redstone investment): score + why + causes."""
    weights = weights or load_weights()
    out = {}
    for key, spec in weights["theses"].items():
        score, assessed, total = _weighted_known(evidence, spec["factors"], weights)
        why, strengths, risks = _thesis_why(evidence, score, spec["factors"], weights)
        out[key] = {"key": key, "label": spec["label"], "description": spec["description"],
                    "score": score, "why": why, "strengths": strengths, "risks": risks,
                    "coverage": {"assessed": assessed, "total": total}}
    return out


def factor_trail(evidence: dict, weights: dict | None = None) -> list[dict]:
    """Every known evidence factor with its value and label — the provable reasoning behind a score."""
    weights = weights or load_weights()
    trail = []
    for key in factor_keys():
        value = factor_value(evidence, key)
        if value is not None:
            trail.append({"key": key, "label": factor_label(key), "value": value})
    return trail


def full_score(evidence: dict, weights: dict | None = None) -> dict:
    """Everything the dashboard needs: axes, composite, the readiness levels, thesis fit, and the
    factor trail behind the numbers. Pure and deterministic — used by the host, never the game path."""
    weights = weights or load_weights()
    base = score(evidence, weights)
    base["readiness"] = readiness(evidence, weights)
    base["theses"] = theses(evidence, weights)
    base["factors"] = factor_trail(evidence, weights)
    return base
