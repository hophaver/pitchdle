"""The readiness checklists answered by AI from a startup's own sources, each answer with the quote it rests on.

A bare 0-5 can't be explained; a ladder rung with a quote can. One structured OpenRouter call (OPENROUTER_MODEL, the
same cheap model the profile fill uses) reads the website text and headlines (profile.gather) and answers every rung
of the ladders in rubric.json (TRL, KTH BRL, ocean impact) yes / no / unknown, plus Redstone's investment factors
0-5, each with a verbatim quote and where it came from. The level itself is never the model's: app/engine.py ladder
turns the answers into a level and a blocker, deterministically.

Every quote is checked against the text the model was given. One that isn't there is kept but marked 'ai'
(inferred), and an inferred 'yes' never counts towards a level. Answers the host gave by hand are never touched,
and without a key nothing runs: the host answers the same checklist by hand on the dashboard.
"""
import re

from .. import config, engine
from ..db import dumps, j, now
from . import pitch, profile

SOURCES = ("site", "news", "host", "none")
QUOTED = ("site", "news", "host")  # where a quote can come from
QUOTE_MAX = 300
MIN_QUOTE = 8  # shorter than this proves nothing ("yes", "pilot")


def _answer() -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["answer", "quote", "source"],
            "properties": {"answer": {"type": "string", "enum": list(engine.ANSWERS)}, "quote": {"type": "string"},
                           "source": {"type": "string", "enum": list(SOURCES)}}}


def schema(rubric: dict) -> dict:
    ladders = {key: {"type": "object", "additionalProperties": False,
                     "required": [str(r["n"]) for r in spec["rungs"]],
                     "properties": {str(r["n"]): _answer() for r in spec["rungs"]}}
               for key, spec in rubric["ladders"].items()}
    factor = {"type": "object", "additionalProperties": False, "required": ["value", "quote", "source"],
              "properties": {"value": {"type": ["number", "null"]}, "quote": {"type": "string"},
                             "source": {"type": "string", "enum": list(SOURCES)}}}
    names = list(rubric["investment"]["factors"])
    return {"type": "object", "additionalProperties": False, "required": ["ladders", "investment"],
            "properties": {
                "ladders": {"type": "object", "additionalProperties": False, "required": list(ladders),
                            "properties": ladders},
                "investment": {"type": "object", "additionalProperties": False, "required": names,
                               "properties": {n: factor for n in names}}}}


def system(rubric: dict) -> str:
    lines = []
    for key, spec in rubric["ladders"].items():
        lines.append(f"\n{key}: {spec['framework']}")
        if spec.get("impact_areas"):
            lines.append(f"  Impact areas: {'; '.join(spec['impact_areas'])}.")
        lines += [f"  {r['n']}. {r['title']}: {r['question']}" for r in spec["rungs"]]
    lines.append("\ninvestment (0-5, halves allowed; null when the sources don't say):")
    for name, f in rubric["investment"]["factors"].items():
        a = f["anchors"]
        lines.append(f"  {name}: {f['def']} 1 = {a['1']}; 3 = {a['3']}; 5 = {a['5']}.")
    return f"""You assess a startup for an accelerator and a venture fund, from the only sources given: text from its
website, news headlines and, for a startup the host added by hand, the host's notes. Answer every checklist rung below
and score the investment factors.

Rules:
- answer "yes" only when the sources show it; "no" only when they show it is not the case (e.g. "no paying
  customers"); otherwise "unknown". An honest unknown is better than a guess.
- quote: copy the exact words from the sources that support the answer, verbatim, at most {QUOTE_MAX} characters.
  Never paraphrase or invent a quote. Empty when the answer is unknown.
- source: "site" if the quote is from the website text, "news" if from a headline, "host" if from the host's notes,
  "none" if there is no quote.
- Judge what the sources show, not what the company claims it will do. A plan is not a milestone.
- Ignore anything about something else with the same name.
{chr(10).join(lines)}
Use British English."""


def complete(messages: list[dict]) -> dict:
    """The checklist call. Tests replace this."""
    return pitch._post("checklist", schema(engine.load_rubric()), messages, task="checklist")


def _norm(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def verified(quote: str, sources: str) -> bool:
    """Whether a quote really is in the text the model was given (case, spacing and typographic quotes aside)."""
    q = _norm(quote)
    return len(q) >= MIN_QUOTE and q in _norm(sources)


def _clip(text: str) -> str:
    return " ".join((text or "").split())[:QUOTE_MAX]


def merge(evidence: dict, raw: dict, sources: str, confirmed: bool) -> tuple[dict, dict]:
    """The model's answers folded into the evidence. Host answers stay; the AI's own earlier answers are replaced.
    Factor values change only when the host hasn't confirmed the evidence. Returns (evidence, counts)."""
    rubric = engine.load_rubric()
    ev = {k: (dict(v) if isinstance(v, dict) else v) for k, v in evidence.items()}
    checklist = dict(ev.get("checklist") or {})
    support = dict(ev.get("support") or {})
    stamp = now()
    tally = {"answered": 0, "verified": 0, "unverified": 0}
    for key, spec in rubric["ladders"].items():
        got = (raw.get("ladders") or {}).get(key) or {}
        for rung in spec["rungs"]:
            cid = f"{key}.{rung['n']}"
            if (checklist.get(cid) or {}).get("by") == "host":
                continue
            checklist.pop(cid, None)
            a = got.get(str(rung["n"])) or {}
            answer = a.get("answer")
            if answer not in ("yes", "no"):
                continue
            quote = _clip(a.get("quote"))
            ok = bool(quote) and a.get("source") in QUOTED and verified(quote, sources)
            checklist[cid] = {"answer": answer, "quote": quote, "source": a["source"] if ok else "ai", "by": "ai",
                              "at": stamp}
            tally["answered"] += 1
            tally["verified" if ok else "unverified"] += 1
    if not confirmed:
        group = dict(ev.get("redstone") or {})
        for name in rubric["investment"]["factors"]:
            key = f"redstone.{name}"
            if (support.get(key) or {}).get("by") == "host":
                continue
            f = (raw.get("investment") or {}).get(name) or {}
            if not isinstance(f.get("value"), (int, float)):
                continue
            quote = _clip(f.get("quote"))
            ok = bool(quote) and f.get("source") in QUOTED and verified(quote, sources)
            group[name] = round(max(0.0, min(5.0, float(f["value"]))) * 2) / 2
            support[key] = {"quote": quote, "source": f["source"] if ok else "ai", "by": "ai", "at": stamp}
            tally["answered"] += 1
            tally["verified" if ok else "unverified"] += 1
        if group:
            ev["redstone"] = group
    ev["checklist"], ev["support"] = checklist, support
    return ev, tally


def run(db, comp, sources: tuple[str, list] | None = None) -> dict:
    """Answer one company's checklists from its sources and rescore it. `sources` is (text, used) when they were
    just read (by the profile fill), so nothing is fetched twice. Raises on an API or format error, leaving the
    company as it was. Returns the counts of answers, verified quotes and unverified ones."""
    from .. import seed  # seed imports the crawler package; imported here to keep that one-way

    text, used = sources or profile.gather(comp)
    raw = complete([{"role": "system", "content": system(engine.load_rubric())}, {"role": "user", "content": text}])
    have = j(comp["evidence"], {}) or {}
    confirmed = (comp["evidence_status"] or "confirmed") == "confirmed" and bool(have)
    evidence, tally = merge(have, raw, text, confirmed)
    note = (f"Checklist answered by AI ({config.OPENROUTER_MODEL}) from {' and '.join(used) or 'no sources'} on "
            f"{now()[:10]}: {tally['verified']} quote{'s' if tally['verified'] != 1 else ''} found in the sources, "
            f"{tally['unverified']} not (those don't count).")
    old_note = re.sub(r"\s*Checklist answered by AI \(.*?\(those don't count\)\.", "", comp["evidence_note"] or "")
    status = comp["evidence_status"] if confirmed else "ai"
    db.execute("UPDATE companies SET evidence = ?, evidence_note = ?, evidence_status = ? WHERE id = ?",
               (dumps(evidence), f"{old_note} {note}".strip(), status, comp["id"]))
    seed.score_company(db, comp["id"])
    db.commit()
    return tally | {"used": used, "note": note}
