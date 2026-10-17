"""Update all cards: look again at every real startup's website and news for anything new, as cheaply as possible.

Per company, cheapest first:
1. Read the sources again (website and fresh headlines) and fingerprint them. Unchanged since the last run: done,
   with no model call.
2. Changed: one call on the default model (OPENROUTER_MODEL) compares the card with the sources. It patches facts
   that moved (minor) and says whether anything major happened: a funding round, a stage or readiness step, a pivot,
   a team or legal change, or major press or an award.
3. Major only: the readiness checklist is answered again and the expensive reviewers (AI models and social media)
   read the card afresh. The company also becomes eligible for one more daily game (service.eligible_ids).

Runs in the background like autoread; its progress sits in the "refresh" setting for the dashboard to poll.
"""
import logging
import re
import threading

from . import autoread, brief, config, opinions, reads
from .crawler import checklist, pitch, profile, pulse
from .db import connect, dumps, j, now
from .service import get_setting, set_setting

log = logging.getLogger("pitchdle")

KINDS = {"funding": "new funding", "stage": "readiness step", "pivot": "pivot or business change",
         "team_legal": "team or legal change", "press_award": "major press or award"}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["changed", "major", "kinds", "summary", "raised", "stages", "investors", "vision"],
    "properties": {
        "changed": {"type": "boolean"},
        "major": {"type": "boolean"},
        "kinds": {"type": "array", "items": {"type": "string", "enum": list(KINDS)}},
        "summary": {"type": "string"},
        "raised": {"anyOf": [{"type": "null"}, {
            "type": "object", "additionalProperties": False, "required": ["amount", "currency"],
            "properties": {"amount": {"type": "number"}, "currency": {"type": "string"}}}]},
        "stages": {"type": "array", "items": {"type": "string"}},
        "investors": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "status", "amount", "currency"],
            "properties": {"name": {"type": "string"}, "status": {"type": "string", "enum": ["invested", "interested"]},
                           "amount": {"type": ["number", "null"]}, "currency": {"type": "string"}}}},
        "vision": {"type": "string"},
    },
}

SYSTEM = """You keep a startup's card up to date. You get what the card says now, then the company's current
sources (website text and recent headlines). Use the sources only; never invent numbers, names or dates.

Say whether the sources show anything the card doesn't have yet (changed), and whether any of it is major:
- funding: a new funding round, raise, or investor
- stage: a new pilot, product launch, certification or other step up in technology or business readiness
- pivot: a new market, product or business model
- team_legal: a founder or CEO change, acquisition, merger, shutdown or bankruptcy
- press_award: major press coverage, a prize, or acceptance into a notable accelerator
Wording changes, small news and things the card already says are not major. When unsure, it's not major.

summary: one short sentence on what's new, empty if nothing.
raised: the total raised so far if the sources state a larger or newer figure than the card, else null.
stages: the full updated list of programmes and rounds passed, in order, or [] if unchanged.
investors: investors the sources name that the card doesn't list yet, or [].
vision: a better vision sentence only if the company's stated direction changed, else ""."""

_state = threading.Lock()
_running = False


def START(fn) -> None:
    """How a run is launched. Tests swap this for a direct call."""
    threading.Thread(target=fn, daemon=True, name="pitchdle-refresh").start()


def fingerprint_sources(text: str) -> str:
    """A fingerprint that ignores the order headlines come back in and their dates, so only new content counts."""
    lines = sorted({re.sub(r"\s*\([^)]*\)$", "", line.strip()) for line in text.splitlines() if line.strip()})
    return brief.fingerprint("\n".join(lines))


def card_text(comp) -> str:
    raised = comp["raised_eur"]
    parts = [f"Name: {comp['name']}", f"Pitch: {comp['one_liner'] or ''}", f"Vision: {comp['vision'] or ''}",
             f"Raised so far: {'not disclosed' if raised is None else f'EUR {raised:,}'}",
             "Stages passed: " + ("; ".join(j(comp["stages"], [])) or "none listed"),
             "Investors: " + ("; ".join(i.get("name", "") for i in j(comp["investors"], [])) or "none listed")]
    return "\n".join(parts)


def complete(messages: list[dict]) -> dict:
    """The update call. Tests replace this."""
    return pitch._post("update", SCHEMA, messages, task="update")


def patches(comp, found: dict) -> dict:
    """The card's columns to change. Facts only grow: a figure never goes down and nothing listed is dropped."""
    out = {}
    raised = found.get("raised")
    if raised:
        eur = profile.to_eur(raised.get("amount"), raised.get("currency"))
        if eur and (comp["raised_eur"] is None or eur > comp["raised_eur"]):
            out["raised_eur"] = eur
    have_stages = j(comp["stages"], [])
    stages = [s for s in (" ".join((x or "").split())[:80] for x in found.get("stages") or []) if s][:profile.MAX_STAGES]
    if stages and len(stages) > len(have_stages) and stages != have_stages:
        out["stages"] = dumps(stages)
    have = j(comp["investors"], [])
    names = {(i.get("name") or "").lower() for i in have}
    new = [{"name": " ".join(i["name"].split())[:80], "status": i.get("status") or "invested",
            "amount_eur": profile.to_eur(i.get("amount"), i.get("currency"))}
           for i in found.get("investors") or [] if (i.get("name") or "").strip() and i["name"].lower() not in names]
    if new:
        out["investors"] = dumps((have + new)[:profile.MAX_INVESTORS])
    vision = " ".join((found.get("vision") or "").split())
    if vision and vision != (comp["vision"] or ""):
        out["vision"] = vision
    return out


def update_one(db, comp) -> dict:
    """Check one company. Returns {"status": unchanged | minor | major | none, "summary", "kinds"}."""
    try:  # fresh headlines, so gather() reads this week's news rather than what was stored
        db.execute("UPDATE companies SET pulse = ? WHERE id = ?", (dumps(pulse.compute_pulse(comp["name"])), comp["id"]))
        db.commit()
        comp = db.execute("SELECT * FROM companies WHERE id = ?", (comp["id"],)).fetchone()
    except Exception as e:  # noqa: BLE001 - the stored headlines will do
        log.info("Pitchdle: refreshing %s without fresh headlines: %s", comp["name"], e)
    text, used = profile.gather(comp)
    key = fingerprint_sources(text)
    if key == (comp["source_key"] or ""):
        return {"status": "unchanged"}
    found = complete([{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": f"The card now:\n{card_text(comp)}\n\nCurrent sources:\n{text}"}])
    kinds = [k for k in found.get("kinds") or [] if k in KINDS]
    major = bool(found.get("major") and kinds)
    summary = " ".join((found.get("summary") or "").split())[:240]
    updates = patches(comp, found)
    status = "major" if major else "minor" if (updates or found.get("changed")) else "none"
    if status != "none" and summary:
        updates["update_note"] = f"{now()[:10]}: {summary}"
    if major:
        updates["major_update_at"] = now()
    sets = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE companies SET {sets + ', ' if sets else ''}source_key = ? WHERE id = ?",
               (*updates.values(), key, comp["id"]))
    db.commit()
    if major:
        comp = db.execute("SELECT * FROM companies WHERE id = ?", (comp["id"],)).fetchone()
        reread(db, comp, (text, used))
    return {"status": status, "summary": summary, "kinds": kinds}


def reread(db, comp, sources) -> None:
    """After a major update: the checklist again, then every reviewer that can be asked, overwriting the old reads."""
    checklist.run(db, comp, sources)
    comp = db.execute("SELECT * FROM companies WHERE id = ?", (comp["id"],)).fetchone()
    ready = reads.setup()
    ai = [k for k in opinions.AI if ready[k]]
    social = [p for p in opinions.SOCIAL if reads.can_read(p)]
    results = ((reads.rate_all(comp, only=ai, brief=brief.for_review(db, comp)) if ai else {})
               | (reads.social_all(comp, only=social) if social else {}))
    autoread.store(db, comp["id"], results)


def run(db) -> dict:
    st = {"started_at": now(), "finished_at": None, "total": 0, "checked": 0, "unchanged": 0, "minor": 0,
          "major": 0, "updated": [], "errors": []}
    comps = db.execute("SELECT * FROM companies WHERE is_real = 1 ORDER BY id").fetchall()
    st["total"] = len(comps)
    set_setting(db, "refresh", st)
    for comp in comps:
        try:
            result = update_one(db, comp)
            if result["status"] in ("minor", "major"):
                st[result["status"]] += 1
                st["updated"].append({"id": comp["id"], "name": comp["name"], "major": result["status"] == "major",
                                      "summary": result["summary"]})
            elif result["status"] == "unchanged":
                st["unchanged"] += 1
        except Exception as e:  # noqa: BLE001 - the next run tries it again
            st["errors"].append(f"{comp['name']}: {reads.short_error(e)}")
        st["checked"] += 1
        set_setting(db, "refresh", st)
    st["finished_at"], st["errors"] = now(), st["errors"][-20:]
    set_setting(db, "refresh", st)
    return st


def work() -> None:
    global _running
    try:
        conn = connect()
        try:
            run(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("Pitchdle: updating cards failed")
    finally:
        with _state:
            _running = False


def kick() -> bool:
    """Start a run unless one is on. Returns False when no model can be asked."""
    global _running
    if not pitch.available():
        return False
    with _state:
        if _running:
            return True
        _running = True
    try:
        START(work)
    except Exception:
        with _state:
            _running = False
        raise
    return True


def status(db) -> dict:
    return (get_setting(db, "refresh") or {}) | {"running": _running, "available": pitch.available(),
                                                 "model": config.OPENROUTER_MODEL}
