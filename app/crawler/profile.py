"""Filling a real startup's card from what's public: its website and news headlines.

Discovery only stores a headline and a website, so a real startup starts with no money raised, investors, stages,
vision or country, and no evidence: its readiness, thesis fit and call stay unknown. One structured OpenRouter
call (on OPENROUTER_MODEL, the cheap model every task but the reviews uses) reads the website text and the
headlines about the company and fills both in:

- the profile, using only what the sources say; anything it can't find stays empty.
- the evidence: each engine factor scored 0-5 against the definitions below, or left unknown when the sources
  don't speak to it, plus the tech stage (from pilots and deployments, never a claim) and patents. It's marked as
  estimated by AI until the host confirms it.

Only empty fields are filled, and evidence the host confirmed is never touched, so nothing typed by hand is lost.
"""
import logging

from .. import config, engine
from ..db import dumps, j, now
from . import pitch, pulse, website

log = logging.getLogger("pitchdle")

VISION_WORDS = 120  # the card's vision allows 400; a filled one stays a short paragraph
MAX_STAGES, MAX_INVESTORS = 8, 12
# Rough rates for turning a reported amount into euros; the stage line keeps the original amount.
EUR_PER = {"EUR": 1.0, "USD": 0.9, "GBP": 1.15, "CHF": 1.05, "SEK": 0.087, "NOK": 0.085, "DKK": 0.134,
           "ISK": 0.0066, "PLN": 0.23, "ILS": 0.24, "CAD": 0.66, "AUD": 0.6, "JPY": 0.006, "SGD": 0.68}

# What each evidence factor means, with what 0 and 5 look like. The keys mirror engine.FACTOR_GROUPS.
FACTORS = {
    "impact": {
        "measurability": "how measurable its ocean or climate benefit is. 0 = no benefit claimed, 5 = measured and independently verified.",
        "problem_pressure": "how big and urgent the ocean problem it tackles is. 0 = trivial, 5 = severe, large and pressing.",
        "solution_potential": "how much of that problem it could solve if it works. 0 = negligible, 5 = a large share.",
    },
    "brl": {
        "market": "evidence that customers want it. 0 = none, 5 = paying customers and proven, sizeable demand.",
        "value_prop": "how clear and validated its value to customers is. 0 = unclear, 5 = validated with customers.",
        "business_model": "how validated the way it makes money is. 0 = none stated, 5 = recurring revenue proven.",
        "scalability": "how well it can grow beyond its first customers. 0 = bespoke one-offs, 5 = clearly scalable.",
    },
    # Redstone's investment factors, with their 1/3/5 anchors, from rubric.json: one definition for every reader.
    "redstone": {name: f"{f['def']} 1 = {f['anchors']['1']}, 3 = {f['anchors']['3']}, 5 = {f['anchors']['5']}."
                 for name, f in engine.load_rubric()["investment"]["factors"].items()},
}
assert {g: list(f) for g, f in FACTORS.items()} == engine.FACTOR_GROUPS  # keep the two in step

TRL_HELP = ("idea (only an idea), concept (designed, not built), lab (works in the lab), prototype (a working "
            "prototype), pilot (a pilot with real users or in the field), demonstrated (proven in operation), "
            "deployed (in use by paying customers), commercial (sold at scale)")


def _nullable(kind: str) -> dict:
    return {"type": [kind, "null"]}


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vision", "country", "raised", "stages", "investors", "evidence"],
    "properties": {
        "vision": {"type": "string"},
        "country": {"type": "string"},
        "raised": {"type": ["object", "null"], "additionalProperties": False, "required": ["amount", "currency"],
                   "properties": {"amount": {"type": "number"}, "currency": {"type": "string"}}},
        "stages": {"type": "array", "items": {"type": "string"}},
        "investors": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "status", "amount", "currency"],
            "properties": {"name": {"type": "string"}, "status": {"type": "string", "enum": ["invested", "interested"]},
                           "amount": _nullable("number"), "currency": {"type": "string"}}}},
        "evidence": {
            "type": "object", "additionalProperties": False,
            "required": ["trl_stage", "patents", "basis", *FACTORS],
            "properties": {
                "trl_stage": {"type": "string", "enum": ["", *engine.TRL_STAGES]},
                "patents": _nullable("integer"),
                "basis": {"type": "string"},
                **{group: {"type": "object", "additionalProperties": False, "required": list(names),
                           "properties": {name: _nullable("number") for name in names}}
                   for group, names in FACTORS.items()},
            }},
    },
}


def _factor_lines() -> str:
    labels = {"impact": "Ocean impact", "brl": "Business readiness", "redstone": "Investment (Redstone's lens)"}
    out = []
    for group, names in FACTORS.items():
        out.append(f"  {group} ({labels[group]}):")
        out += [f"    - {name}: {text}" for name, text in names.items()]
    return "\n".join(out)


SYSTEM = f"""You fill in a startup's card for investors, from the only sources given: text from its website and
news headlines. Use those sources only. Never invent amounts, investors, dates, customers or claims. Some headlines
may be about something else with the same name (a person, an animal, another company): ignore anything that isn't
clearly about this company. Anything the sources don't say stays empty.

Profile:
- vision: what the company does and is trying to achieve, in its own terms, as one plain paragraph of at most
  {VISION_WORDS} words. No hype words. Empty if the sources say too little.
- country: the country it is headquartered or founded in, in English ("Finland"). Empty if unclear.
- raised: the total money it has raised so far, as stated (the sum of the rounds the sources name), with its
  ISO currency code (EUR, USD, GBP, SEK, NOK, ...). null if no amount is stated.
- stages: the incubation programmes, accelerators, grants and funding rounds it has passed, oldest first, each
  as a short line with the amount and year when stated, like "Seed round: $5M (2025)" or "Y Combinator (W24)".
  At most {MAX_STAGES}. Empty list if none are named.
- investors: the investors the sources name. status "invested" for those that put money in, "interested" only
  if the sources say so. amount and currency only when the sources give that investor's own amount, else null
  and "". At most {MAX_INVESTORS}.

Evidence: score each factor 0 to 5 (halves allowed) as an analyst would, from what the sources show, not from
what the company claims about itself. Use null for any factor the sources don't give you enough to judge: an
honest unknown is better than a guess, and never fill gaps with a middling number. Be candid: most early startups
score low on proof.
{_factor_lines()}
  trl_stage: how far the technology has got, from evidence such as pilots, deployments and customers, never a
    self-claim: {TRL_HELP}. Empty if the sources don't show it.
  patents: the number of granted patents the sources state, else null.
  basis: one or two sentences on what the scores rest on (which facts from the sources).
Use British English."""


def complete(messages: list[dict]) -> dict:
    """The fill call. Tests replace this."""
    return pitch._post("profile", SCHEMA, messages, task="profile")


def gather(comp) -> tuple[str, list[str]]:
    """The sources for one company as text for the model, and what they were (for the note). A dead website or
    feed just means fewer sources."""
    used, lines = [], [f"Company name: {comp['name']}"]
    if comp["sector"]:
        lines.append(f"Field: {comp['sector']}")
    if comp["one_liner"]:
        lines.append(f"Its card's pitch: {comp['one_liner']}")
    if comp["website"]:
        try:
            page = website.fetch(comp["website"])
            if page.get("description"):
                lines += ["", f"Website description: {page['description']}"]
            if page.get("text"):
                lines += ["", "Website text (truncated):", page["text"][:6000]]
            used.append("website")
        except Exception as e:  # noqa: BLE001
            log.info("Pitchdle: filling %s without its website: %s", comp["name"], e)
    hits = (j(comp["pulse"], {}) or {}).get("top_hits") or []
    if len(hits) < 5:
        try:
            hits = pulse.compute_pulse(comp["name"], limit=15)["top_hits"] or hits
        except Exception as e:  # noqa: BLE001
            log.info("Pitchdle: filling %s without fresh headlines: %s", comp["name"], e)
    titles = [h["title"] + (f" ({h['published']})" if h.get("published") else "") for h in hits if h.get("title")]
    note = comp["evidence_note"] or ""
    if note.startswith(("Auto-found", "Found by discovery")):
        titles.insert(0, note.split(": ", 1)[-1].split(" Card text written by AI")[0])
    if titles:
        lines += ["", "Headlines:"] + [f"- {t}" for t in dict.fromkeys(titles)]
        used.append(f"{len(titles)} headline{'s' if len(titles) != 1 else ''}")
    return "\n".join(lines), used


def to_eur(amount, currency: str) -> int | None:
    if amount is None or amount <= 0:
        return None
    rate = EUR_PER.get((currency or "EUR").upper().strip())
    return round(amount * rate) if rate else None


def clean_evidence(raw: dict) -> tuple[dict, str]:
    """The model's evidence in the shape the engine reads: only the factors it scored, kept to 0-5 in halves."""
    out = {}
    for group, names in FACTORS.items():
        scores = {}
        for name in names:
            v = (raw.get(group) or {}).get(name)
            if isinstance(v, (int, float)):
                scores[name] = round(max(0.0, min(5.0, float(v))) * 2) / 2
        if scores:
            out[group] = scores
    if raw.get("trl_stage") in engine.TRL_STAGES:
        out["trl_stage"] = raw["trl_stage"]
    if isinstance(raw.get("patents"), int) and raw["patents"] >= 0:
        out["patents"] = raw["patents"]
    return out, " ".join((raw.get("basis") or "").split())[:400]


def clean(raw: dict) -> dict:
    """The model's answer, trimmed to what the card holds."""
    vision = " ".join((raw.get("vision") or "").split())
    words = vision.split()
    if len(words) > VISION_WORDS:
        vision = " ".join(words[:VISION_WORDS]).rstrip(",;:") + "…"
    raised = raw.get("raised") or None
    investors = []
    for i in (raw.get("investors") or [])[:MAX_INVESTORS]:
        name = " ".join((i.get("name") or "").split())[:80]
        if name:
            investors.append({"name": name, "status": "interested" if i.get("status") == "interested" else "invested",
                              "amount_eur": to_eur(i.get("amount"), i.get("currency"))})
    evidence, basis = clean_evidence(raw.get("evidence") or {})
    return {
        "vision": vision,
        "country": " ".join((raw.get("country") or "").split())[:60],
        "raised_eur": to_eur(raised["amount"], raised["currency"]) if raised else None,
        "stages": [s for s in (" ".join((x or "").split())[:80] for x in (raw.get("stages") or [])[:MAX_STAGES]) if s],
        "investors": investors,
        "evidence": evidence,
        "basis": basis,
    }


def merge_evidence(have: dict, found: dict) -> dict:
    """What's already there wins; the AI's scores fill the gaps."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in have.items()}
    for key, value in found.items():
        if isinstance(value, dict):
            out[key] = value | out.get(key, {})
        elif out.get(key) in (None, ""):
            out[key] = value
    return out


def fill(db, comp) -> dict:
    """Read the sources, ask the model, and fill whichever profile fields are still empty, and the evidence unless
    the host confirmed it. Returns {"filled": [field, ...], "used": [source, ...], "note": ..., "sources": the text read}. Raises on an API
    or format error, leaving the company as it was so the next run tries again."""
    from .. import seed  # seed imports the crawler package; imported here to keep that one-way

    text, used = gather(comp)
    found = clean(complete([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]))
    updates = {}
    if found["vision"] and not (comp["vision"] or "").strip():
        updates["vision"] = found["vision"]
    if found["country"] and not (comp["country"] or "").strip():
        updates["country"] = found["country"]
    if found["raised_eur"] is not None and comp["raised_eur"] is None:
        updates["raised_eur"] = found["raised_eur"]
    if found["stages"] and not j(comp["stages"], []):
        updates["stages"] = dumps(found["stages"])
    if found["investors"] and not j(comp["investors"], []):
        updates["investors"] = dumps(found["investors"])
    have = j(comp["evidence"], {}) or {}
    # Evidence the host stands behind (confirmed, and not empty) stays exactly as it is.
    confirmed = (comp["evidence_status"] or "confirmed") == "confirmed" and any(have.get(g) for g in FACTORS)
    merged = merge_evidence(have, found["evidence"])
    if merged != have and not confirmed:
        updates["evidence"] = dumps(merged)
        updates["evidence_status"] = "ai"
        basis = f"Evidence estimated by AI ({config.OPENROUTER_MODEL}): {found['basis'] or 'from its website and news'}"
        updates["evidence_note"] = f"{comp['evidence_note'] or ''} {basis}".strip()
    filled = [k for k in updates if k not in ("evidence_status", "evidence_note")]
    note = (f"Filled by AI ({config.OPENROUTER_MODEL}) from {' and '.join(used) or 'no sources'} on {now()[:10]}: "
            f"{', '.join(filled) if filled else 'nothing found'}. Check it before relying on it.")
    sets = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE companies SET {sets + ', ' if sets else ''}profile_status = 'ai', profile_note = ? WHERE id = ?",
               (*updates.values(), note, comp["id"]))
    if "evidence" in updates:
        seed.score_company(db, comp["id"])  # readiness, thesis fit and the call follow from the new evidence
    db.commit()
    return {"filled": filled, "used": used, "note": note, "sources": text}
