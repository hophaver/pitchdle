"""Automatic outside reads: a new find on the dashboard gets its game card written; a new card gets its AI ratings, and a real startup its profile (filled from its website
and news), the game's automatic moderation (in the daily game, or kept out with the reason) and its social media
read, as soon as it's added; cards from before get theirs when the app starts. The profile comes first, so the
check and the AI models see the fuller card. Runs in a background thread, never on the game's path.

Each run reads every card still missing a read this setup can make, each card once. Whatever fails (an error, a
model down) stays missing for the next run instead of being retried in a loop. Reads typed in by hand, and
platforms already searched without finding anything, count as done.

Sample startups are made up, so they get AI ratings only: a social search could only find their namesakes.
"""
import logging
import re
import threading

from . import brief, opinions, reads
from .crawler import checklist, gate, pitch, profile
from .db import connect, now
from .service import get_setting, set_setting

log = logging.getLogger("pitchdle")
_state = threading.Lock()  # guards the two flags below; never held during a run
_running = False
_again = False  # a card arrived during a run: go round once more before stopping


def START(fn) -> None:
    """How a run is launched. Tests swap this for a direct call."""
    threading.Thread(target=fn, daemon=True, name="pitchdle-autoread").start()


def store(db, cid: int, results: dict) -> dict:
    """Keep each read that came back. Returns what happened per source: done (with posts found), error or skipped."""
    report = {}
    for source, result in results.items():
        if "scores" in result:
            opinions.save(db, cid, source, result["scores"], result["note"], result["meta"] | {"by": "fetched"})
            report[source] = {"done": True, "posts": result["meta"].get("posts")}
        else:
            report[source] = result
    return report


def needs_profile(comp) -> bool:
    """A real startup whose profile hasn't been filled yet, when the setup can fill it."""
    return bool(comp["is_real"]) and not comp["profile_status"] and pitch.available()


def needs_check(comp) -> bool:
    """A real startup the game's automatic moderation hasn't passed or kept out yet, once its card has what a player
    sees (gate.playable). The investor's profile and evidence aren't needed for the game."""
    # Kept out only for an incomplete card ("no pitch yet"): checked again once the card is complete.
    incomplete = comp["game_status"] == "out" and re.fullmatch(r"no .+ yet", comp["game_note"] or "")
    return bool(comp["is_real"]) and gate.playable(comp) and (not comp["game_status"] or bool(incomplete)) and pitch.available()


def gaps(db, comp) -> tuple[list[str], list[str]]:
    """The AI models and social platforms a company has no read from yet, of those this setup can ask."""
    have = {r["source"] for r in db.execute("SELECT source FROM opinions WHERE company_id = ?", (comp["id"],))}
    ready = reads.setup()
    ai = [key for key in opinions.AI if ready[key] and key not in have]
    social = [p for p in opinions.SOCIAL if p not in have and reads.can_read(p)] if comp["is_real"] else []
    return ai, social


def write_find_cards(db, st: dict) -> None:
    """New finds on the dashboard get their game card written, so they show a brief pitch, not a headline."""
    if not pitch.available():
        return
    from . import autofill  # autofill kicks these runs, so it's imported here rather than at the top
    rows = db.execute("SELECT * FROM candidates WHERE status IN ('new', 'queued') AND card IS NULL "
                      "AND COALESCE(card_error, '') = '' ORDER BY id").fetchall()
    for row in rows:
        try:
            autofill.write_find_card(db, row)
            st["read"].append(row["name"])
        except Exception as e:  # noqa: BLE001 - e.g. the find was dismissed meanwhile
            st["errors"].append(f"{row['name']}, card: {reads.short_error(e)}")
        set_setting(db, "autoread", st)


def fill(db) -> dict:
    """One run: write new finds' cards, then read every card that's missing something, including cards added while
    it runs."""
    st = {"started_at": now(), "finished_at": None, "read": [], "errors": []}
    set_setting(db, "autoread", st)
    write_find_cards(db, st)
    tried = set()
    while True:
        todo = []
        for comp in db.execute("SELECT * FROM companies ORDER BY is_real DESC, id").fetchall():
            if comp["id"] not in tried:
                ai, social = gaps(db, comp)
                if ai or social or needs_profile(comp) or needs_check(comp):
                    todo.append((comp, ai, social))
        if not todo:
            break
        for comp, ai, social in todo:
            tried.add(comp["id"])
            if needs_profile(comp):
                try:
                    filled = profile.fill(db, comp)
                    comp = db.execute("SELECT * FROM companies WHERE id = ?", (comp["id"],)).fetchone() or comp
                    try:  # the readiness checklists, with quotes, from the same sources
                        checklist.run(db, comp, (filled["sources"], filled["used"]))
                        comp = db.execute("SELECT * FROM companies WHERE id = ?", (comp["id"],)).fetchone() or comp
                    except Exception as e:  # noqa: BLE001 - the host can run it from the card, or answer by hand
                        st["errors"].append(f"{comp['name']}, checklist: {reads.short_error(e)}")
                except Exception as e:  # noqa: BLE001 - stays unfilled for the next run
                    st["errors"].append(f"{comp['name']}, profile: {reads.short_error(e)}")
            if needs_check(comp):  # its card is complete: now it joins the game, or is kept out with the reason
                try:
                    gate.check(db, comp)
                except Exception as e:  # noqa: BLE001 - stays unchecked for the next run
                    st["errors"].append(f"{comp['name']}, game check: {reads.short_error(e)}")
            if not (ai or social):
                st["read"].append(comp["name"])
                set_setting(db, "autoread", st)
                continue
            try:
                results = ((reads.rate_all(comp, only=ai, brief=brief.for_review(db, comp)) if ai else {})
                           | (reads.social_all(comp, only=social) if social else {}))
                report = store(db, comp["id"], results)
            except Exception as e:  # noqa: BLE001 - e.g. the company was deleted meanwhile
                st["errors"].append(f"{comp['name']}: {reads.short_error(e)}")
                continue
            st["read"].append(comp["name"])
            st["errors"] += [f"{comp['name']}, {opinions.OUTSIDE[k]}: {r['error']}" for k, r in report.items() if "error" in r]
            set_setting(db, "autoread", st)
    st["finished_at"], st["errors"] = now(), st["errors"][-20:]
    set_setting(db, "autoread", st)
    return st


def work() -> None:
    global _running, _again
    while True:
        try:
            conn = connect()
            try:
                fill(conn)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 - the next run tries again
            log.exception("Pitchdle: automatic reads failed")
        with _state:
            if not _again:
                _running = False
                return
            _again = False


def kick() -> bool:
    """Read whatever is missing, in the background, if any model can be asked. Returns whether a run is on."""
    global _running, _again
    if not any(reads.setup().values()) and not pitch.available():
        return False
    with _state:
        if _running:
            _again = True
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
    return (get_setting(db, "autoread") or {}) | {"running": _running}
