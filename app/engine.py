"""The engine read: a deterministic score per player axis, computed from hand-authored evidence.

Runs when a company is saved or rescored, never in the game's request path. Unknown evidence is a
real state: an axis is scored from its known factors only, and coverage records what was missing.

Readiness levels follow the frameworks the challenge brief names. TRL, BRL and ocean impact are cumulative
ladders (rubric.json): a company is at level N only when every rung up to N is answered 'yes' with a quoted
source, and the first rung that isn't is the blocker. A level nobody has answered the checklist for falls back to
the 0-5 evidence factors (weights.json), pulled toward a conservative prior when few of them are known.
"""
import json
import re
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
# A short tag for grids, where only the factors that share a name across groups need one ("Market · BRL").
GROUP_SHORT = {"impact": "Impact", "brl": "BRL", "redstone": "Redstone"}

# Evidence-derived TRL (never self-claimed). Stage -> TRL 1-9.
TRL_STAGES = {
    "idea": 1, "concept": 2, "lab": 4, "prototype": 5,
    "pilot": 6, "demonstrated": 7, "deployed": 8, "commercial": 9,
}
ANSWERS = ("yes", "no", "unknown")


@lru_cache
def load_weights() -> dict:
    return json.loads(config.WEIGHTS_PATH.read_text())


@lru_cache
def load_rubric() -> dict:
    return json.loads(config.RUBRIC_PATH.read_text())


def reload() -> None:
    """Forget the cached weights and rubric, after either file is edited."""
    load_weights.cache_clear()
    load_rubric.cache_clear()


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


def factor_short(key: str) -> str:
    """The grid's label: the bare name, tagged with its group only where two groups share it."""
    if key == "trl":
        return "Tech readiness"
    if key == "patents":
        return "Patents"
    group, name = key.split(".")
    base = name.replace("_", " ").capitalize()
    shared = sum(name in names for names in FACTOR_GROUPS.values()) > 1 or name in FACTOR_GROUPS
    return f"{base} · {GROUP_SHORT[group]}" if shared else base


def factor_na(evidence: dict, key: str) -> bool:
    """Not applicable rather than unknown: no patents is normal for software, so it's no evidence either way."""
    if key != "patents":
        return False
    count = evidence.get("patents")
    return count not in (None, "") and int(count) <= 0


def factor_value(evidence: dict, key: str) -> float | None:
    """A factor on the 0-5 scale, or None when the evidence doesn't say (or it doesn't apply)."""
    if key == "trl":
        trl = TRL_number(evidence)
        return None if trl is None else (trl - 1) / 8 * 5
    if key == "patents":
        count = evidence.get("patents")
        if count is None or count == "" or int(count) <= 0:
            return None
        return min(5.0, 1.0 + 1.5 * int(count))
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
    keys = [k for k in factor_keys() if not factor_na(evidence, k)]
    na = [k for k in factor_keys() if factor_na(evidence, k)]
    unknown = [k for k in keys if factor_value(evidence, k) is None]
    return {
        "axes": axes,
        "composite": composite_of(axes, weights),
        "coverage": {
            "assessed": len(keys) - len(unknown),
            "total": len(keys),
            "unknown": [factor_label(k) for k in unknown],
            "na": [factor_label(k) for k in na],
            "by_axis": by_axis,
        },
    }


def composite_of(scores: dict, weights: dict | None = None) -> float:
    """Weighted mean of the four axes. Used for engine, player and crowd composites alike."""
    cw = (weights or load_weights())["composite"]
    return round(sum(cw[a] * float(scores[a]) for a in AXES) / sum(cw[a] for a in AXES), 1)


def shrink(raw: float | None, assessed: int, total: int, weights: dict | None = None) -> tuple[float | None, bool]:
    """A score read from too few factors, pulled toward the prior so coverage can't pass for confidence.

    Below coverage_full of the factors known, the score moves toward the prior in proportion to what's missing;
    at or above it, it's left alone. Returns (score, low_coverage). Unknown stays None.
    """
    if raw is None or not total:
        return raw, False
    weights = weights or load_weights()
    full, prior = float(weights.get("coverage_full", 0.5)), float(weights.get("prior", 2.0))
    share = assessed / total
    if share >= full:
        return raw, False
    return round(prior + (raw - prior) * share / full, 1), True


def source_rank(source: str | None) -> float:
    return float(load_rubric()["sources"]["rank"].get(source or "ai", 0.4))


def _weighted_known(evidence: dict, spec: list, weights: dict,
                    sourced: bool = False) -> tuple[float | None, int, int]:
    """Weighted mean over known factors (0-5), plus how many were assessed and total.

    Mirrors the per-axis loop in `score`: unknown factors drop out of the mean and coverage records what was
    missing. With `sourced`, a factor whose support (evidence.support) is only an AI inference counts for less
    and is capped, so a guess can't read as a strength. Returns (None, 0, total) when nothing is known.
    """
    support = evidence.get("support") or {}
    cap = float(load_rubric()["sources"].get("ai_factor_cap", 3.5)) if sourced else 5.0
    num = den = 0.0
    known = 0
    total = 0
    for key, weight in spec:
        if factor_na(evidence, key):
            continue
        total += 1
        value = factor_value(evidence, key)
        if value is None:
            continue
        src = (support.get(key) or {}).get("source") if sourced else None
        if src:
            weight *= source_rank(src)
            if src == "ai":
                value = min(value, cap)
        num += weight * value
        den += weight
        known += 1
    if not den:
        return None, 0, total
    return round(num / den, 1), known, total


# --- ladders: checklist answers -> a level and its blocker ---------------------------------------

def counts(answer: dict) -> bool:
    """A 'yes' that counts towards a ladder: the host's own, or one carrying a quote from a real source."""
    if (answer or {}).get("answer") != "yes":
        return False
    if answer.get("by") == "host":
        return True
    return bool((answer.get("quote") or "").strip()) and answer.get("source") not in (None, "", "ai")


def answers_for(evidence: dict, key: str) -> dict:
    """The checklist answers for one ladder, by rung number as a string."""
    prefix = f"{key}."
    return {k[len(prefix):]: v for k, v in (evidence.get("checklist") or {}).items()
            if k.startswith(prefix) and isinstance(v, dict)}


def ladder(evidence: dict, key: str, rubric: dict | None = None) -> dict | None:
    """One readiness ladder read from the checklist: level, blocker, source. None when nothing is answered.

    level is the highest rung N with every rung 1..N a counted 'yes'; the blocker is the first rung that isn't
    ('no' if answered no, 'unverified' if unknown or unsourced). claimed_max is the highest 'yes' anywhere, so a
    gap in the evidence shows. source is the weakest source the level stands on.
    """
    rubric = rubric or load_rubric()
    spec = rubric["ladders"].get(key)
    answers = answers_for(evidence, key)
    if not spec or not answers:
        return None
    steps, level, blocker = [], 0, None
    for rung in spec["rungs"]:
        a = answers.get(str(rung["n"])) or {}
        answer = a.get("answer") if a.get("answer") in ANSWERS else "unknown"
        counted = counts(a)
        steps.append({"n": rung["n"], "title": rung["title"], "question": rung["question"], "answer": answer,
                      "counted": counted, "quote": a.get("quote") or "", "url": a.get("url") or "",
                      "source": "host" if a.get("by") == "host" and not a.get("source") else a.get("source") or "",
                      "by": a.get("by") or ""})
        if blocker is None:
            if counted:
                level = rung["n"]
            else:
                blocker = {"n": rung["n"], "text": rung["blocker"], "kind": "no" if answer == "no" else "unverified"}
    rungs = len(spec["rungs"])
    used = [s["source"] or "host" for s in steps[:level]]
    weakest = min(used, key=source_rank) if used else None
    if level:
        value = round((level - 1) / (rungs - 1) * 5, 1)
    else:
        value = 0.0 if blocker and blocker["kind"] == "no" else None
    labels = rubric["sources"]["labels"]
    return {
        "method": "ladder", "scale": spec["scale"], "framework": spec["framework"], "rungs": rungs,
        "level": level or None, "score": value, "raw": value,
        "claimed_max": max((s["n"] for s in steps if s["answer"] == "yes"), default=0),
        "blocker": blocker, "source": weakest, "source_label": labels.get(weakest, weakest) if weakest else None,
        "confidence": source_rank(weakest) if weakest else None, "steps": steps, "low_coverage": False,
        "coverage": {"assessed": sum(s["answer"] != "unknown" for s in steps), "total": rungs},
    }


def TRL_number(evidence: dict) -> int | None:
    """Evidence-derived TRL 1-9: the TRL ladder when its checklist is answered, else the stage. Never a self-claim."""
    lad = ladder(evidence, "tech")
    if lad:
        return lad["level"]
    return TRL_STAGES.get(evidence.get("trl_stage"))


def BRL_number(evidence: dict) -> int | None:
    lad = ladder(evidence, "business")
    return lad["level"] if lad else None


def readiness(evidence: dict, weights: dict | None = None) -> dict:
    """The four named readiness levels the challenge brief asks for, plus coverage for each.

    A level with checklist answers is its ladder (level, blocker, source). Otherwise it's the weighted mean of
    its factors (or the TRL stage), shrunk toward the prior when few are known. A missing read comes back as None
    so the dashboard can show \"unknown/unevidenced\" honestly.
    """
    weights = weights or load_weights()
    rubric = load_rubric()
    out = {}
    for key, spec in weights["levels"].items():
        label = spec["label"]
        lad = ladder(evidence, key, rubric)
        if lad:
            out[key] = {"key": key, "label": label, **lad}
            if key == "tech":
                out[key]["trl"] = lad["level"]
        elif "factor" in spec:  # TRL from the stage: one factor, surfaced as 1-9
            trl = TRL_STAGES.get(evidence.get("trl_stage"))
            value = round((trl - 1) / 8 * 5, 1) if trl is not None else None
            out[key] = {"key": key, "label": label, "score": value, "raw": value, "trl": trl, "method": "stage",
                        "level": trl, "scale": "TRL", "low_coverage": False,
                        "coverage": {"assessed": 1 if trl is not None else 0, "total": 1}}
        else:
            raw, assessed, total = _weighted_known(evidence, spec["factors"], weights, sourced=True)
            value, low = shrink(raw, assessed, total, weights)
            out[key] = {"key": key, "label": label, "score": value, "raw": raw, "method": "factors",
                        "low_coverage": low, "coverage": {"assessed": assessed, "total": total}}
    return out


# --- thesis fit: gates, then a stage window, then the evidence --------------------------------------

BALTIC = {"finland", "sweden", "denmark", "germany", "poland", "estonia", "latvia", "lithuania"}
TICKET = re.compile(r"([€$£])\s?(\d+(?:[.,]\d+)?)\s?(k|m|bn|million|thousand)?\b", re.I)
TICKET_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9}
TICKET_RATE = {"€": 1.0, "$": 0.9, "£": 1.15}


def ticket_eur(text: str) -> int | None:
    """The amount a company asks for, in euros, from a line like "€800k to double its plant". None if unstated."""
    m = TICKET.search(text or "")
    if not m:
        return None
    amount = float(m.group(2).replace(",", "."))
    return round(amount * TICKET_MULT.get((m.group(3) or "").lower(), 1) * TICKET_RATE[m.group(1)])


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zåäö0-9]+", (text or "").lower()))


def _sector_hit(term: str, words: set[str]) -> bool:
    term = term.lower()
    return any(w == term or w == f"{term}s" or (len(term) >= 5 and w.startswith(term)) for w in words)


def _in_region(country: str, entry: str) -> bool:
    from .landscape import EU, NORDIC  # landscape needs only config; imported here to keep engine light
    c, e = country.strip().lower(), entry.strip().lower()
    regions = {"nordic": NORDIC, "nordics": NORDIC, "eu": EU, "europe": EU | NORDIC, "baltic": BALTIC}
    return c in regions[e] if e in regions else c == e


def _money(eur: int) -> str:
    return f"€{eur / 1e6:g}M" if eur >= 1e6 else f"€{eur / 1e3:g}k"


def gates(spec: dict, company: dict | None) -> list[dict]:
    """The hard criteria for one thesis: sector, geography, ticket size. Unknown never counts against a company:
    a gate with nothing to judge passes as 'not applied' with a note."""
    company = company or {}
    out = []
    sectors = spec.get("sectors", "*")
    if sectors and sectors != "*":
        words = _words(f"{company.get('sector') or ''} {company.get('one_liner') or ''}")
        if not words:
            out.append({"key": "sector", "status": "na", "note": "sector unknown, not applied"})
        else:
            hits = [s for s in sectors if _sector_hit(s, words)]
            out.append({"key": "sector", "status": "pass", "note": f"sector: {hits[0]}"} if hits else
                       {"key": "sector", "status": "fail",
                        "note": f"{company.get('sector') or 'its field'} is outside the blue-economy focus"})
    countries = spec.get("countries", "*")
    if countries and countries != "*":
        country = (company.get("country") or "").strip()
        if not country:
            out.append({"key": "country", "status": "na", "note": "country unknown, not applied"})
        elif any(_in_region(country, e) for e in countries):
            out.append({"key": "country", "status": "pass", "note": f"based in {country}"})
        else:
            out.append({"key": "country", "status": "fail",
                        "note": f"based in {country} (focus: {', '.join(countries)})"})
    window = spec.get("ticket_eur")
    if window and any(v is not None for v in window):
        lo, hi = (list(window) + [None, None])[:2]
        ask = ticket_eur(company.get("claim_ask") or "")
        if ask is None:
            out.append({"key": "ticket", "status": "na", "note": "ask unknown, not applied"})
        elif (lo is not None and ask < lo) or (hi is not None and ask > hi):
            band = f"{_money(lo) if lo else '–'}–{_money(hi) if hi else '–'}"
            out.append({"key": "ticket", "status": "fail", "note": f"asks {_money(ask)}, tickets are {band}"})
        else:
            out.append({"key": "ticket", "status": "pass", "note": f"asks {_money(ask)}"})
    return out


def scope(company: dict | None) -> tuple[bool, list[str]]:
    """In scope when some holder's gates all pass (unknowns pass). Returns (in_scope, why not per holder)."""
    reasons = []
    for key, spec in load_rubric()["theses"].items():
        if key.startswith("_"):
            continue
        failed = [g for g in gates(spec.get("gates") or {}, company) if g["status"] == "fail"]
        if not failed:
            return True, []
        reasons.append(f"{spec['label'].split(' ')[0]}: {'; '.join(g['note'] for g in failed)}")
    return False, reasons


def stage_window(spec: dict | None, evidence: dict) -> dict:
    """How well the company's stage sits in a holder's band: 1.0 inside the peak, falling linearly to 0 over
    `falloff` levels either side. An accelerator fits less once a company is past what it can help with."""
    if not spec:
        return {"value": 1.0, "stage": None, "note": ""}
    scale = spec.get("scale", "trl")
    stage = BRL_number(evidence) if scale == "brl" else TRL_number(evidence)
    lo, hi = spec["peak"]
    name = scale.upper()
    if stage is None:
        return {"value": 1.0, "stage": None, "note": f"{name} unknown, stage window not applied"}
    off = lo - stage if stage < lo else stage - hi if stage > hi else 0
    value = round(max(0.0, 1 - off / float(spec.get("falloff", 3))), 2)
    where = "inside" if not off else "before" if stage < lo else "past"
    return {"value": value, "stage": stage, "note": f"{name} {stage} is {where} the {lo}–{hi} band"}


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
    top = ", ".join(f"{f['label'].lower()} {f['value']:.1f}" for f in strengths[:2])
    weak = ", ".join(f"{f['label'].lower()} {f['value']:.1f}" for f in risks[::-1][:2])
    fits = f"Fits on {top}" if top else "No standout strengths"
    watch = f"watch {weak}" if weak else "no obvious weaknesses"
    return f"{fits}; {watch}.", strengths[:3], risks[::-1][:3]


def theses(evidence: dict, weights: dict | None = None, company: dict | None = None) -> dict:
    """Thesis fit for each holder (A'Pelago accelerator, Redstone investment), from rubric.json.

    Hard gates first: failing one is 'out of scope' with the reason, never a low score. Then the evidence factors'
    weighted mean (shrunk when thin), scaled by the stage window: score = soft x (0.4 + 0.6 x window).
    `company` carries sector, one_liner, country and claim_ask for the gates; without it they don't apply.
    """
    weights = weights or load_weights()
    out = {}
    for key, spec in load_rubric()["theses"].items():
        if key.startswith("_"):
            continue
        checks = gates(spec.get("gates") or {}, company)
        failed = [g for g in checks if g["status"] == "fail"]
        raw, assessed, total = _weighted_known(evidence, spec["factors"], weights, sourced=True)
        soft, low = shrink(raw, assessed, total, weights)
        window = stage_window(spec.get("window"), evidence)
        if failed:
            fit, value = "out", None
        elif soft is None:
            fit, value = "unknown", None
        else:
            fit, value = "in", round(soft * (0.4 + 0.6 * window["value"]), 1)
        why, strengths, risks = _thesis_why(evidence, value, spec["factors"], weights)
        if failed:
            why = "Out of scope: " + "; ".join(g["note"] for g in failed) + "."
        elif value is not None and window["value"] < 1:
            why = f"{why} Stage: {window['note']}."
        out[key] = {"key": key, "label": spec["label"], "description": spec["description"],
                    "score": value, "raw": raw, "fit": fit, "why": why, "strengths": strengths, "risks": risks,
                    "gates": checks, "window": window, "low_coverage": low, "criteria_note": spec.get("criteria_note", ""),
                    "coverage": {"assessed": assessed, "total": total}}
    return out


def factor_trail(evidence: dict, weights: dict | None = None) -> list[dict]:
    """Every known evidence factor with its value, label and source: the provable reasoning behind a score."""
    support = evidence.get("support") or {}
    labels = load_rubric()["sources"]["labels"]
    trail = []
    for key in factor_keys():
        value = factor_value(evidence, key)
        if value is not None:
            s = support.get(key) or {}
            trail.append({"key": key, "label": factor_label(key), "short_label": factor_short(key), "value": value,
                          "source": s.get("source") or "", "source_label": labels.get(s.get("source"), ""),
                          "quote": s.get("quote") or "", "url": s.get("url") or ""})
    return trail


def full_score(evidence: dict, weights: dict | None = None, company: dict | None = None) -> dict:
    """Everything the dashboard needs: axes, composite, the readiness levels, thesis fit, and the
    factor trail behind the numbers. Pure and deterministic — used by the host, never the game path."""
    weights = weights or load_weights()
    base = score(evidence, weights)
    base["readiness"] = readiness(evidence, weights)
    base["theses"] = theses(evidence, weights, company)
    base["factors"] = factor_trail(evidence, weights)
    return base
