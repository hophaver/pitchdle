"""Automatic moderation for the game: whether a real startup's card is fit to show players.

A tracked startup joins the daily game by itself once its card has what a player sees (name, field, pitch and
ask), but only if one small call on OPENROUTER_MODEL passes that card. The investor's profile (vision, facts,
evidence) is not needed and not judged. It keeps out funds, news
sites and misparsed headline names, pitches that don't say what the product does, hype with no product behind it,
anything offensive or unsafe, and companies outside the event's fields. A card that fails stays on the dashboard,
out of the game, with the reason.
"""
from .. import config
from . import pitch

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok", "reason"],
          "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}}}


def system() -> str:
    fields = ", ".join(config.DISCOVER_FIELDS) or "the blue economy"
    return f"""You moderate cards for a public game where players rate real startups from their card. Decide if this
card is fit to show players. ok is true only if all hold:
- it is an operating startup or young company with its own product, not a fund, accelerator, publisher, news site,
  event, university, public body or a name misparsed from a headline;
- the pitch says concretely what the product does, in words a player understands (not just a headline or slogan);
- nothing in it is offensive, unsafe, a scam or plainly misleading;
- its business relates to the event's fields: {fields}, or the ocean, water, ships and the maritime world.
reason: under 12 words, why it fails, or empty if ok."""


PLAYER_FIELDS = {"name": "a name", "sector": "a field", "one_liner": "a pitch", "claim_ask": "an ask"}


def missing(comp) -> list[str]:
    """What the card a player sees still lacks."""
    return [what for key, what in PLAYER_FIELDS.items() if not (comp[key] or "").strip()]


def playable(comp) -> bool:
    return not missing(comp)


def card_text(comp) -> str:
    return "\n".join([f"Name: {comp['name']}", f"Field: {comp['sector'] or '-'}", f"Pitch: {comp['one_liner'] or '-'}",
                      f"Ask: {comp['claim_ask'] or '-'}"])


def complete(messages: list[dict]) -> dict:
    """The check call. Tests replace this."""
    return pitch._post("game_check", SCHEMA, messages, task="gate")


def check(db, comp) -> dict:
    """Pass or keep out one company, and put it in or take it out of the game accordingly. Raises on an API error,
    leaving it unchecked (and out of the game if it was never in) for the next run."""
    if missing(comp):
        verdict = {"ok": False, "reason": f"no {' or '.join(m.split(' ', 1)[1] for m in missing(comp))} yet"}
    else:
        raw = complete([{"role": "system", "content": system()}, {"role": "user", "content": card_text(comp)}])
        verdict = {"ok": bool(raw.get("ok")), "reason": " ".join((raw.get("reason") or "").split())[:120]}
    db.execute("UPDATE companies SET game_status = ?, game_note = ?, active = ? WHERE id = ?",
               ("in" if verdict["ok"] else "out", "" if verdict["ok"] else verdict["reason"] or "not fit for the game",
                int(verdict["ok"]), comp["id"]))
    db.commit()
    return verdict
