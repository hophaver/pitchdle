"""Filling a real startup's profile from what's public: its website and news headlines.

Discovery only stores a headline and a website, so a real startup's card starts with no money raised, investors,
stages, vision or country. One structured OpenRouter call (on PROFILE_MODEL, else OPENROUTER_MODEL) reads the
website text and the headlines about the company and fills those in, using only what the sources say: anything
it can't find stays empty. Only empty fields are filled, so nothing the host typed is ever overwritten.
"""
import logging

from .. import config
from ..db import dumps, j, now
from . import pitch, pulse, website

log = logging.getLogger("pitchdle")

VISION_WORDS = 120  # the card's vision allows 400; a filled one stays a short paragraph
MAX_STAGES, MAX_INVESTORS = 8, 12
# Rough rates for turning a reported amount into euros; the stage line keeps the original amount.
EUR_PER = {"EUR": 1.0, "USD": 0.9, "GBP": 1.15, "CHF": 1.05, "SEK": 0.087, "NOK": 0.085, "DKK": 0.134,
           "ISK": 0.0066, "PLN": 0.23, "ILS": 0.24, "CAD": 0.66, "AUD": 0.6, "JPY": 0.006, "SGD": 0.68}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vision", "country", "raised", "stages", "investors"],
    "properties": {
        "vision": {"type": "string"},
        "country": {"type": "string"},
        "raised": {"type": ["object", "null"], "additionalProperties": False, "required": ["amount", "currency"],
                   "properties": {"amount": {"type": "number"}, "currency": {"type": "string"}}},
        "stages": {"type": "array", "items": {"type": "string"}},
        "investors": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "status", "amount", "currency"],
            "properties": {"name": {"type": "string"}, "status": {"type": "string", "enum": ["invested", "interested"]},
                           "amount": {"type": ["number", "null"]}, "currency": {"type": "string"}}}},
    },
}

SYSTEM = f"""You fill in a startup's profile for investors, from the only sources given: text from its website
and news headlines. Use those sources only. Never invent amounts, investors, dates or claims. Some headlines may be
about something else with the same name (a person, an animal, another company): ignore anything that isn't
clearly about this company. Anything the sources don't say stays empty.

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
Use British English."""


def complete(messages: list[dict]) -> dict:
    """The profile call. Tests replace this."""
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
            log.info("Pitchdle: profile for %s without its website: %s", comp["name"], e)
    hits = (j(comp["pulse"], {}) or {}).get("top_hits") or []
    if len(hits) < 5:
        try:
            hits = pulse.compute_pulse(comp["name"], limit=15)["top_hits"] or hits
        except Exception as e:  # noqa: BLE001
            log.info("Pitchdle: profile for %s without fresh headlines: %s", comp["name"], e)
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
    return {
        "vision": vision,
        "country": " ".join((raw.get("country") or "").split())[:60],
        "raised_eur": to_eur(raised["amount"], raised["currency"]) if raised else None,
        "stages": [s for s in (" ".join((x or "").split())[:80] for x in (raw.get("stages") or [])[:MAX_STAGES]) if s],
        "investors": investors,
    }


def fill(db, comp) -> dict:
    """Read the sources, ask the model, and fill whichever profile fields are still empty. Returns
    {"filled": [field, ...], "used": [source, ...]}. Raises on an API or format error, leaving the company as it
    was so the next run tries again."""
    text, used = gather(comp)
    found = clean(complete([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]))
    filled = []
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
    filled = list(updates)
    model = config.task_model("profile")
    note = (f"Filled by AI ({model}) from {' and '.join(used) or 'no sources'} on {now()[:10]}: "
            f"{', '.join(filled) if filled else 'nothing found'}. Check it before relying on it.")
    sets = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE companies SET {sets + ', ' if sets else ''}profile_status = 'ai', profile_note = ? WHERE id = ?",
               (*updates.values(), note, comp["id"]))
    db.commit()
    return {"filled": filled, "used": used, "note": note}
