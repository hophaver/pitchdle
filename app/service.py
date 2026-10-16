"""Queries and payload builders shared by the API routes."""
import random
import sqlite3
from datetime import date, datetime, time, timedelta

from . import config, scoring
from .db import dumps, j, now
from .engine import AXES, composite_of, full_score as engine_full

HANDLE_EMOJI = ["🐙", "🦈", "🐳", "🐬", "🦀", "🐡", "🐠", "🦑", "🦭", "🐢", "🪼", "🦞", "🐚", "🐟"]


def new_handle(rng: random.Random | None = None) -> str:
    rng = rng or random
    return f"{rng.choice(HANDLE_EMOJI)} {rng.randint(10, 99)}"


# --- settings and mode ---------------------------------------------------------------------------

def get_setting(db, key: str, default=None):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return j(row["value"], default) if row else default


def set_setting(db, key: str, value) -> None:
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (key, dumps(value)))
    db.commit()


def get_mode(db) -> str:
    """demo = the seeded sample companies; live = real ones. Switches the game and the dashboard together."""
    return get_setting(db, "mode") or config.APP_MODE


def pool_is_real(mode: str) -> int:
    return 1 if mode == "live" else 0


LIVE_NOTICE = "We're lining up real startups for today's set. Check back soon."


def pool_notice(db, mode: str) -> str | None:
    """What a player sees when live mode has no real startups in the game yet."""
    if mode != "live":
        return None
    if db.execute("SELECT 1 FROM companies WHERE active = 1 AND is_real = 1 LIMIT 1").fetchone():
        return None
    return LIVE_NOTICE


# --- rows ---------------------------------------------------------------------------------------

def get_company(db: sqlite3.Connection, cid: int):
    return db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()


def public_card(row) -> dict:
    """What a player sees: the pitch, nothing about scores."""
    return {
        "id": row["id"], "name": row["name"], "emoji": row["emoji"] or "", "sector": row["sector"],
        "one_liner": row["one_liner"], "claim_ask": row["claim_ask"], "is_real": bool(row["is_real"]),
    }


def get_dive(db, did: int):
    return db.execute("SELECT * FROM dives WHERE id = ?", (did,)).fetchone()


def dive_companies(db, dive) -> list:
    ids = j(dive["company_ids"], [])
    rows = {r["id"]: r for r in db.execute(
        f"SELECT * FROM companies WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    return [rows[i] for i in ids if i in rows]


def dive_payload(dive) -> dict:
    return {"id": dive["id"], "label": dive["label"], "mode": dive["mode"], "date": dive["date"], "today": is_today(dive)}


def seconds_to_next_set() -> int:
    """The daily set is keyed on the server's local date, so a new one is playable from local midnight."""
    current = datetime.now()
    return int((datetime.combine(current.date() + timedelta(days=1), time.min) - current).total_seconds())


def todays_dive(db):
    """Today's daily set for the current mode; generated deterministically from that pool's active companies.

    A set made while the pool was empty (live mode before any startup was activated) is filled in once
    companies are available, so the day doesn't stay empty.
    """
    today = date.today().isoformat()
    pool = get_mode(db)
    ids = [r["id"] for r in db.execute("SELECT id FROM companies WHERE active = 1 AND is_real = ? ORDER BY id",
                                       (pool_is_real(pool),))]
    picked = random.Random(f"{today}:{pool}" if pool != "demo" else today).sample(ids, min(5, len(ids)))
    row = db.execute("SELECT * FROM dives WHERE mode = 'daily' AND date = ? AND pool = ? ORDER BY id DESC LIMIT 1",
                     (today, pool)).fetchone()
    if row:
        if not j(row["company_ids"], []) and picked:
            db.execute("UPDATE dives SET company_ids = ? WHERE id = ?", (dumps(picked), row["id"]))
            db.commit()
            return get_dive(db, row["id"])
        return row
    count = db.execute("SELECT COUNT(*) FROM dives WHERE mode = 'daily' AND pool = ?", (pool,)).fetchone()[0]
    label = f"#{count + 1}" if pool == "demo" else f"Live #{count + 1}"
    cur = db.execute("INSERT INTO dives (label, date, company_ids, mode, pool, created_at) VALUES (?, ?, ?, 'daily', ?, ?)",
                     (label, today, dumps(picked), pool, now()))
    db.commit()
    return get_dive(db, cur.lastrowid)


def scores_of(vote) -> dict:
    return {a: vote[a] for a in AXES}


# Votes with the voter's user_id and badge alongside, so crowd scores can weigh guests and members apart.
VOTES_WITH_USER = ("SELECT v.*, p.user_id, u.badge FROM votes v LEFT JOIN players p ON p.id = v.player_id "
                   "LEFT JOIN users u ON u.id = p.user_id")


def card_votes(db, dive_id: int, cid: int) -> list:
    return db.execute(f"{VOTES_WITH_USER} WHERE v.dive_id = ? AND v.company_id = ? AND v.round = 1",
                      (dive_id, cid)).fetchall()


def answered(db, pid: int, dive_id: int) -> set[int]:
    return {r["company_id"] for r in db.execute(
        "SELECT company_id FROM votes WHERE player_id = ? AND dive_id = ? AND round = 1", (pid, dive_id))}


# --- player results ------------------------------------------------------------------------------

def results(db, dive, pid: int) -> dict:
    """The player's reads next to the average of every other player's, for each card they answered in this set."""
    comps = dive_companies(db, dive)
    mine = {r["company_id"]: r for r in db.execute(
        "SELECT * FROM votes WHERE player_id = ? AND dive_id = ? AND round = 1", (pid, dive["id"]))}
    cards, leans = [], {"higher": 0, "with": 0, "lower": 0}
    for comp in comps:
        vote = mine.get(comp["id"])
        if not vote:
            continue
        you = scores_of(vote)
        # A live room is the people in it, all counted alike; everywhere else guests count for less.
        others = scoring.crowd([v for v in card_votes(db, dive["id"], comp["id"]) if v["player_id"] != pid],
                               weighted=dive["mode"] != "live")
        you_composite = composite_of(you)
        # Nobody else has answered yet: nothing to lean against.
        lean = scoring.lean(you_composite, others["composite"]) if others["n"] else None
        if lean:
            leans[lean] += 1
        cards.append({
            "card": public_card(comp),
            # Only shown after answering, so the link can't give the pitch away mid-game.
            "website": comp["website"] or "",
            "you": {"scores": you, "composite": you_composite},
            "crowd": {"n": others["n"], "means": others["means"], "composite": others["composite"]},
            "lean": lean,
        })
    return {
        "dive": dive_payload(dive),
        "total": len(comps),
        "cards": cards,
        "summary": {"leans": leans},
        # Countdown to the next daily set, shown under today's; other sets don't have one.
        "next_set_in": seconds_to_next_set() if is_today(dive) else None,
    }


def is_today(dive) -> bool:
    return dive["mode"] == "daily" and dive["date"] == date.today().isoformat()


def needs_account(dive) -> bool:
    """Daily sets from other days are for signed-in players. Today's, live rooms and undated custom sets are open."""
    return dive["mode"] == "daily" and bool(dive["date"]) and not is_today(dive)


def guest_locked(db, dive, pid: int) -> bool:
    """Whether a guest is kept out of a set. One they already started (when it was today's) stays viewable."""
    return needs_account(dive) and not answered(db, pid, dive["id"])


# --- history (signed-in players) -------------------------------------------------------------------

def streaks(days: set[str], today: date) -> tuple[int, int]:
    """(current, best) runs of consecutive days. The current run survives until today's set is missed."""
    best = run = 0
    prev = None
    for d in sorted(date.fromisoformat(x) for x in days):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    current, day = 0, today if today.isoformat() in days else today - timedelta(days=1)
    while day.isoformat() in days:
        current += 1
        day -= timedelta(days=1)
    return current, best


def history(db, pid: int) -> dict:
    """Every daily set up to today with how far the player got, plus their running stats."""
    todays_dive(db)
    today = date.today()
    # One set per day: the newest in the current mode's pool, matching todays_dive.
    by_day = {}
    for d in db.execute("SELECT * FROM dives WHERE mode = 'daily' AND date IS NOT NULL AND date <= ? AND pool = ? "
                        "ORDER BY id", (today.isoformat(), get_mode(db))):
        by_day[d["date"]] = d
    done_days, leans, sets = set(), {"higher": 0, "with": 0, "lower": 0}, []
    for day in sorted(by_day, reverse=True):
        dive = by_day[day]
        total = len(dive_companies(db, dive))
        n = len(answered(db, pid, dive["id"]))
        done = bool(total) and n >= total
        if done:
            done_days.add(day)
            for key, count in results(db, dive, pid)["summary"]["leans"].items():
                leans[key] += count
        sets.append(dive_payload(dive) | {"answered": n, "total": total, "done": done, "today": day == today.isoformat()})
    current, best = streaks(done_days, today)
    cards = db.execute("SELECT COUNT(*) FROM votes WHERE player_id = ?", (pid,)).fetchone()[0]
    return {
        "stats": {"sets": len(done_days), "cards": cards, "streak": current, "best_streak": best, "leans": leans},
        "sets": sets,
    }


# --- wall ------------------------------------------------------------------------------------------

def callout(room: dict, engine_composite: float) -> dict | None:
    """The perception-gap line for the wall and host, once the room is big enough to mean something."""
    if room["n"] < config.MIN_VOTES:
        return None
    gap = round(room["composite"] - engine_composite, 1)
    lead = f"The room averaged {room['composite']:.1f}, the engine says {engine_composite:.1f}"
    if gap >= 1.0:
        return {"kind": "story", "gap": gap, "text": f"{lead}. The pitch reads better than its fundamentals."}
    if gap <= -1.0:
        return {"kind": "substance", "gap": gap, "text": f"{lead}. Stronger fundamentals than the pitch suggests."}
    return None


# --- host overview ---------------------------------------------------------------------------------

FLAG_LABELS = {
    "story": "Story > substance",
    "substance": "Substance > story",
    "split": "Room split",
}
# Which opportunity kinds a flag pushes up the "next actions" list, and why.
FLAG_BOOST = {
    "story": ({"partner", "customer"}, "prove it with a pilot before raising"),
    "substance": ({"investor", "grant"}, "fundamentals are there; go raise"),
}


VERDICT_GAP = 1.0   # crowd vs engine this far apart: they disagree (same line as the story/substance flags)
AGREE_GAP = 0.5     # closer than this: they agree


def triangulate(crowd_n: int, crowd_c: float | None, engine_c: float, pulse: dict | None,
                min_votes: int) -> tuple[str, str]:
    """Crowd, engine and web pulse in one read: 'convergent', 'divergent' or 'unknown', with a reason."""
    if crowd_n < min_votes or crowd_c is None:
        return "unknown", f"Needs {min_votes}+ answers ({crowd_n} so far)"
    gap = round(crowd_c - engine_c, 1)
    lean = pulse["lean"] if pulse else None
    if abs(gap) >= VERDICT_GAP:
        side = "overrates" if gap > 0 else "underrates"
        reason = f"Crowd {crowd_c:.1f} vs engine {engine_c:.1f}: the room {side} it"
        if lean in ("positive", "negative"):
            web_high = lean == "positive"
            reason += f"; the web sides with the {'room' if web_high == (gap > 0) else 'engine'}"
        return "divergent", reason
    if abs(gap) >= AGREE_GAP:
        return "unknown", f"Crowd and engine lean apart (gap {gap:+.1f})"
    if pulse is None:
        return "unknown", "Crowd and engine agree. Run web pulse to triangulate"
    mean = (crowd_c + engine_c) / 2
    if lean == "negative" and mean >= 3:
        return "divergent", f"Web coverage leans negative while room and engine rate it {mean:.1f}"
    if lean == "positive" and mean < 2:
        return "divergent", f"Web coverage leans positive while room and engine rate it {mean:.1f}"
    if lean == "silent":
        return "convergent", "Crowd and engine agree; no web coverage (possible discovery gap)"
    return "convergent", f"Crowd, engine and web ({lean}) agree"


def company_insight(db, comp, real_only: bool) -> dict:
    seed_clause = " AND v.is_seed = 0" if real_only else ""
    votes = db.execute(f"{VOTES_WITH_USER} WHERE v.company_id = ? AND v.round = 1{seed_clause}", (comp["id"],)).fetchall()
    room = scoring.crowd(votes)
    engine = j(comp["engine_axes"], {})
    ec = comp["engine_composite"]
    gap = round(room["composite"] - ec, 2) if room["n"] else None

    # The named readiness levels, thesis-fit and the factor trail are pure projections of the
    # stored evidence — computed fresh so the dashboard always matches what's in evidence, and
    # so it works on its own before anyone has played.
    full = engine_full(j(comp["evidence"], {}))
    readiness_levels = full["readiness"]
    theses = full["theses"]
    factors = full["factors"]

    flags = []
    if room["n"] >= config.MIN_VOTES:
        if gap >= 1.0:
            flags.append({"key": "story", "label": FLAG_LABELS["story"],
                          "detail": f"Crowd {room['composite']:.1f} vs engine {ec:.1f} (gap +{gap:.1f})"})
        if gap <= -1.0:
            flags.append({"key": "substance", "label": FLAG_LABELS["substance"],
                          "detail": f"Crowd {room['composite']:.1f} vs engine {ec:.1f} (gap {gap:.1f})"})
        if room["consensus"] >= 1.2:
            flags.append({"key": "split", "label": FLAG_LABELS["split"],
                          "detail": f"Std-dev {room['consensus']:.1f} across {room['n']} reads"})

    flag_keys = {f["key"] for f in flags}
    actions = []
    for o in db.execute("SELECT * FROM opportunities WHERE company_id = ?", (comp["id"],)):
        score, reasons = o["fit"] or 0, []
        for key in flag_keys:
            if key in FLAG_BOOST and o["kind"] in FLAG_BOOST[key][0]:
                score += 0.3
                reasons.append(FLAG_BOOST[key][1])
        # Thesis fit also steers the "next" list: a strong accelerator fit flags the accelerator-style
        # opportunities (partners, grants, customers); a strong investment fit flags investors.
        k = o["kind"]
        thesis = ("apelago", "fits the accelerator thesis") if k in ("partner", "grant", "customer") \
            else ("redstone", "fits the investment thesis") if k == "investor" else None
        if thesis and theses[thesis[0]]["score"] is not None:
            boost = (theses[thesis[0]]["score"] - 2.5) * 0.15
            score += boost
            if boost > 0:
                reasons.append(thesis[1])
        score = round(score, 2)
        actions.append({"kind": o["kind"], "name": o["name"], "why": o["why"], "fit": o["fit"],
                        "stage_fit": o["stage_fit"], "score": score, "boosted": reasons})
    actions.sort(key=lambda a: a["score"], reverse=True)
    pulse = j(comp["pulse"])
    verdict, verdict_reason = triangulate(room["n"], room["composite"], ec, pulse, config.MIN_VOTES)

    return {
        "id": comp["id"], "name": comp["name"], "sector": comp["sector"], "is_real": bool(comp["is_real"]),
        "active": bool(comp["active"]),
        "engine": {"axes": engine, "composite": ec},
        "readiness": readiness_levels, "theses": theses, "factors": factors,
        "evidence_note": comp["evidence_note"] or "",
        "coverage": j(comp["engine_coverage"], {}),
        "crowd": {"n": room["n"], "signed_in": room["signed_in"], "means": room["means"],
                  "composite": room["composite"], "consensus": room["consensus"]},
        "gap": gap, "flags": flags, "actions": actions,
        "pulse": pulse, "verdict": verdict, "verdict_reason": verdict_reason,
    }


def overview(db, real_only: bool) -> dict:
    mode = get_mode(db)
    comps = db.execute("SELECT * FROM companies WHERE is_real = ? ORDER BY name", (pool_is_real(mode),)).fetchall()
    return {"companies": [company_insight(db, c, real_only) for c in comps], "real_only": real_only,
            "mode": mode, "autofill": get_setting(db, "autofill")}
