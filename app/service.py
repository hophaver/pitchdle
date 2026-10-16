"""Queries and payload builders shared by the API routes."""
import random
import sqlite3
from datetime import date

from . import config, scoring
from .db import dumps, j, now
from .engine import AXES, composite_of

HANDLE_EMOJI = ["🐙", "🦈", "🐳", "🐬", "🦀", "🐡", "🐠", "🦑", "🦭", "🐢", "🪼", "🦞", "🐚", "🐟"]


def new_handle(rng: random.Random | None = None) -> str:
    rng = rng or random
    return f"{rng.choice(HANDLE_EMOJI)} {rng.randint(10, 99)}"


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
    return {"id": dive["id"], "label": dive["label"], "mode": dive["mode"], "date": dive["date"]}


def todays_dive(db):
    """The daily set for today; generated deterministically from active companies if missing."""
    today = date.today().isoformat()
    row = db.execute("SELECT * FROM dives WHERE mode = 'daily' AND date = ? ORDER BY id DESC LIMIT 1",
                     (today,)).fetchone()
    if row:
        return row
    ids = [r["id"] for r in db.execute("SELECT id FROM companies WHERE active = 1 ORDER BY id")]
    picked = random.Random(today).sample(ids, min(5, len(ids)))
    count = db.execute("SELECT COUNT(*) FROM dives WHERE mode = 'daily'").fetchone()[0]
    cur = db.execute("INSERT INTO dives (label, date, company_ids, mode, created_at) VALUES (?, ?, ?, 'daily', ?)",
                     (f"#{count + 1}", today, dumps(picked), now()))
    db.commit()
    return get_dive(db, cur.lastrowid)


def scores_of(vote) -> dict:
    return {a: vote[a] for a in AXES}


def card_votes(db, dive_id: int, cid: int) -> list:
    return db.execute("SELECT * FROM votes WHERE dive_id = ? AND company_id = ? AND round = 1",
                      (dive_id, cid)).fetchall()


def answered(db, pid: int, dive_id: int) -> set[int]:
    return {r["company_id"] for r in db.execute(
        "SELECT company_id FROM votes WHERE player_id = ? AND dive_id = ? AND round = 1", (pid, dive_id))}


# --- player results ------------------------------------------------------------------------------

def results(db, dive, pid: int) -> dict:
    """The player's reads next to the crowd's, for every card they answered in this set."""
    comps = dive_companies(db, dive)
    mine = {r["company_id"]: r for r in db.execute(
        "SELECT * FROM votes WHERE player_id = ? AND dive_id = ? AND round = 1", (pid, dive["id"]))}
    cards, leans, axes_with = [], {"higher": 0, "with": 0, "lower": 0}, 0
    for comp in comps:
        vote = mine.get(comp["id"])
        if not vote:
            continue
        you = scores_of(vote)
        room = scoring.crowd(card_votes(db, dive["id"], comp["id"]))
        you_composite = composite_of(you)
        lean = scoring.lean(you_composite, room["composite"])
        leans[lean] += 1
        axes = []
        for a in AXES:
            same = abs(you[a] - room["means"][a]) < scoring.LEAN_THRESHOLD
            axes_with += same
            axes.append({"axis": a, "you": you[a], "crowd": room["means"][a], "share": room["share"][a],
                         "lean": scoring.lean(you[a], room["means"][a])})
        cards.append({
            "card": public_card(comp),
            "you": {"scores": you, "composite": you_composite},
            "crowd": {"n": room["n"], "composite": room["composite"]},
            "lean": lean,
            "axes": axes,
        })
    return {
        "dive": dive_payload(dive),
        "total": len(comps),
        "cards": cards,
        "summary": {"leans": leans, "axes_with": axes_with, "axes_total": len(cards) * len(AXES)},
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


def company_insight(db, comp, real_only: bool) -> dict:
    seed_clause = " AND is_seed = 0" if real_only else ""
    votes = db.execute(f"SELECT * FROM votes WHERE company_id = ? AND round = 1{seed_clause}", (comp["id"],)).fetchall()
    room = scoring.crowd(votes)
    engine = j(comp["engine_axes"], {})
    ec = comp["engine_composite"]
    gap = round(room["composite"] - ec, 2) if room["n"] else None

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
        actions.append({"kind": o["kind"], "name": o["name"], "why": o["why"], "fit": o["fit"],
                        "stage_fit": o["stage_fit"], "score": round(score, 2), "boosted": reasons})
    actions.sort(key=lambda a: a["score"], reverse=True)

    return {
        "id": comp["id"], "name": comp["name"], "sector": comp["sector"], "is_real": bool(comp["is_real"]),
        "active": bool(comp["active"]),
        "engine": {"axes": engine, "composite": ec},
        "coverage": j(comp["engine_coverage"], {}),
        "crowd": {"n": room["n"], "means": room["means"], "composite": room["composite"],
                  "consensus": room["consensus"]},
        "gap": gap, "flags": flags, "actions": actions,
    }


def overview(db, real_only: bool) -> dict:
    comps = db.execute("SELECT * FROM companies ORDER BY name").fetchall()
    return {"companies": [company_insight(db, c, real_only) for c in comps], "real_only": real_only}
