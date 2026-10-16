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


def display_name(player) -> str:
    return player["initials"] or player["handle"]


# --- rows ---------------------------------------------------------------------------------------

def get_company(db: sqlite3.Connection, cid: int):
    return db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()


def public_card(row) -> dict:
    """What a player may see before guessing: no engine values, no facts."""
    return {
        "id": row["id"], "name": row["name"], "sector": row["sector"],
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
    """The daily dive for today; generated deterministically from active companies if missing."""
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


def round_votes(db, dive_id: int, cid: int, rnd: int = 1) -> list:
    return db.execute("SELECT * FROM votes WHERE dive_id = ? AND company_id = ? AND round = ?",
                      (dive_id, cid, rnd)).fetchall()


def player_votes(db, pid: int, dive_id: int, cid: int) -> dict:
    rows = db.execute("SELECT * FROM votes WHERE player_id = ? AND dive_id = ? AND company_id = ?",
                      (pid, dive_id, cid)).fetchall()
    return {r["round"]: r for r in rows}


def progress(db, pid: int, dive_id: int) -> dict:
    out = {}
    for r in db.execute("SELECT company_id, round FROM votes WHERE player_id = ? AND dive_id = ?", (pid, dive_id)):
        out.setdefault(r["company_id"], {"r1": False, "r2": False})[f"r{r['round']}"] = True
    return out


# --- scoring over stored votes --------------------------------------------------------------------

def ensure_bonus(db, dive_id: int, cid: int, engine_axes: dict) -> None:
    """Set the Against the Current bonus once, judged against the room at this moment."""
    votes = round_votes(db, dive_id, cid, 1)
    pending = [v for v in votes if v["bonus"] is None]
    if not pending:
        return
    room = scoring.crowd(votes)
    if room["n"] < config.MIN_VOTES:
        return
    for v in pending:
        bonus, axes = scoring.against_current_bonus(scores_of(v), engine_axes, room)
        db.execute("UPDATE votes SET bonus = ?, bonus_axes = ? WHERE id = ?", (bonus, dumps(axes), v["id"]))
    db.commit()


def card_points_by_player(db, dive_id: int, cid: int) -> dict[int, int]:
    rows = db.execute("SELECT player_id, round, points, bonus FROM votes WHERE dive_id = ? AND company_id = ?",
                      (dive_id, cid)).fetchall()
    r1 = {r["player_id"]: r for r in rows if r["round"] == 1}
    r2 = {r["player_id"]: r["points"] for r in rows if r["round"] == 2}
    return {pid: scoring.card_points(v["points"], r2.get(pid), v["bonus"]) for pid, v in r1.items()}


def dive_scores(db, dive_id: int) -> dict[int, dict]:
    """Per player in a dive: depth (sum of card points), bonus metres, and how much they moved in round 2."""
    rows = db.execute("SELECT * FROM votes WHERE dive_id = ?", (dive_id,)).fetchall()
    cards: dict[tuple, dict] = {}
    for r in rows:
        cards.setdefault((r["player_id"], r["company_id"]), {})[r["round"]] = r
    out: dict[int, dict] = {}
    for (pid, _cid), rounds in cards.items():
        if 1 not in rounds:
            continue
        r1, r2 = rounds[1], rounds.get(2)
        s = out.setdefault(pid, {"depth": 0, "bonus": 0, "moved": 0, "cards": 0, "against": 0})
        s["depth"] += scoring.card_points(r1["points"], r2["points"] if r2 else None, r1["bonus"])
        s["bonus"] += r1["bonus"] or 0
        s["against"] += 1 if (r1["bonus"] or 0) > 0 else 0
        s["moved"] += sum(abs(r2[a] - r1[a]) for a in AXES) if r2 else 0
        s["cards"] += 1
    return out


# --- reveal ----------------------------------------------------------------------------------------

def room_sheet(you: dict, room: dict, engine: dict) -> dict:
    rows = []
    for a in AXES:
        share, mine, mode, x = room["share"][a], you[a], room["mode"][a], engine[a]
        right = abs(mine - x) <= 0.5
        with_crowd = mine == mode
        if with_crowd and right:
            kind, text = "with_right", f"{share[mine]}% of the room said {mine}, like you, and the engine agrees ({x:g})."
        elif with_crowd:
            kind, text = "with_wrong", f"You went with the crowd: {share[mine]}% said {mine}. The engine reads it at {x:g}."
        elif right:
            kind, text = "against_right", (f"Against the current: only {share[mine]}% said {mine} like you, "
                                           f"and that's the engine's read ({x:g}).")
        else:
            kind, text = "against_wrong", (f"{share[mine]}% said {mine} like you. Most said {mode} "
                                           f"({share[mode]}%); the engine says {x:g}.")
        rows.append({"axis": a, "share": share, "you": mine, "mode": mode, "engine": x,
                     "mean": room["means"][a], "kind": kind, "text": text})
    focus = max(AXES, key=lambda a: abs(room["means"][a] - engine[a]))
    return {"axes": rows, "focus": focus}


def callout(room: dict, engine_composite: float) -> dict | None:
    """The perception-gap line, once the room is big enough to mean something."""
    if room["n"] < config.MIN_VOTES:
        return None
    gap = round(room["composite"] - engine_composite, 1)
    lead = f"The room averaged {room['composite']:.1f}, the engine says {engine_composite:.1f}"
    if gap >= 1.0:
        pct = round(100 * sum(1 for c in room["composites"] if c >= engine_composite + 1) / room["n"])
        return {"kind": "story", "gap": gap,
                "text": f"{lead}: this pitch reads better than its fundamentals. "
                        f"{pct}% of divers rated it at least a point above the engine."}
    if gap <= -1.0:
        pct = round(100 * sum(1 for c in room["composites"] if c <= engine_composite - 1) / room["n"])
        return {"kind": "substance", "gap": gap,
                "text": f"{lead}: stronger fundamentals than the pitch suggests. "
                        f"{pct}% of divers rated it at least a point below the engine."}
    return None


def reveal(db, dive, comp, pid: int) -> dict:
    engine = j(comp["engine_axes"])
    ensure_bonus(db, dive["id"], comp["id"], engine)
    mine = player_votes(db, pid, dive["id"], comp["id"])
    r1, r2 = mine[1], mine.get(2)
    you1 = scores_of(r1)
    you2 = scores_of(r2) if r2 else None
    room = scoring.crowd(round_votes(db, dive["id"], comp["id"], 1))
    points = card_points_by_player(db, dive["id"], comp["id"])
    coverage = j(comp["engine_coverage"], {})
    return {
        "company": public_card(comp) | {"facts": j(comp["facts"], []), "coverage": coverage},
        "engine": {"axes": engine, "composite": comp["engine_composite"]},
        "you": {
            "r1": you1, "r2": you2, "stuck": bool(r2 and r2["stuck"]),
            "composite": composite_of(you1),
            "tiles": [scoring.tile(you1[a], engine[a]) | {"axis": a} for a in AXES],
            "tiles_r2": [scoring.tile(you2[a], engine[a]) | {"axis": a} for a in AXES] if you2 else None,
        },
        "points": {
            "r1": r1["points"], "r2": r2["points"] if r2 else None,
            "bonus": r1["bonus"], "bonus_axes": j(r1["bonus_axes"], []),
            "card": points[pid],
        },
        "tier": scoring.read_tier(points[pid], list(points.values())),
        "room": {"n": room["n"], "composite": room["composite"], "means": room["means"]},
        "sheet": room_sheet(you1, room, engine) if room["n"] >= config.MIN_VOTES else None,
        "callout": callout(room, comp["engine_composite"]),
        "depth": dive_scores(db, dive["id"]).get(pid, {}).get("depth", 0),
        "min_votes": config.MIN_VOTES,
    }


def summary(db, dive, pid: int) -> dict:
    comps = dive_companies(db, dive)
    done = progress(db, pid, dive["id"])
    cards = [reveal(db, dive, c, pid) for c in comps if done.get(c["id"], {}).get("r1")]
    scores = dive_scores(db, dive["id"])
    me = scores.get(pid, {"depth": 0, "against": 0})
    depths = sorted(scores.items(), key=lambda kv: kv[1]["depth"], reverse=True)
    rank = next((i + 1 for i, (p, _) in enumerate(depths) if p == pid), None)
    return {
        "dive": dive_payload(dive),
        "total_cards": len(comps),
        "depth": me["depth"],
        "zone": scoring.zone(me["depth"]),
        "rank": rank,
        "of": len(depths),
        "against": me["against"],
        "room": [{"depth": s["depth"], "me": p == pid} for p, s in depths],
        "cards": cards,
    }


def leaderboard(db, dive_id: int, limit: int = 10) -> dict:
    scores = dive_scores(db, dive_id)
    names = {p["id"]: display_name(p) for p in db.execute("SELECT * FROM players")}

    def board(key):
        ranked = sorted(((p, s) for p, s in scores.items() if s[key] > 0), key=lambda kv: kv[1][key], reverse=True)
        return [{"name": names.get(p, "?"), "value": s[key]} for p, s in ranked[:limit]]

    return {"deepest": board("depth"), "current": board("bonus"), "moved": board("moved")}


# --- host overview ---------------------------------------------------------------------------------

FLAG_RULES = {
    "story": "Story > substance",
    "substance": "Substance > story",
    "helps": "Transparency helps",
    "hurts": "Transparency hurts",
    "split": "Room split",
}
# Which opportunity kinds a flag pushes up the "next actions" list, and why.
FLAG_BOOST = {
    "story": ({"partner", "customer"}, "prove it with a pilot before raising"),
    "substance": ({"investor", "grant"}, "fundamentals are there; go raise"),
    "hurts": ({"partner", "customer"}, "facts undercut the pitch; get traction first"),
    "helps": ({"investor"}, "facts sell it; lead with them in investor meetings"),
}


def company_insight(db, comp, real_only: bool) -> dict:
    seed_clause = " AND is_seed = 0" if real_only else ""
    votes = db.execute(f"SELECT * FROM votes WHERE company_id = ?{seed_clause}", (comp["id"],)).fetchall()
    r1 = [v for v in votes if v["round"] == 1]
    r2 = {(v["player_id"], v["dive_id"]): v for v in votes if v["round"] == 2}
    room = scoring.crowd(r1)
    engine = j(comp["engine_axes"], {})
    ec = comp["engine_composite"]
    pairs = [(v, r2[(v["player_id"], v["dive_id"])]) for v in r1 if (v["player_id"], v["dive_id"]) in r2]
    sensitivity = None
    if pairs:
        per_axis = {a: round(sum(b[a] - a1[a] for a1, b in pairs) / len(pairs), 2) for a in AXES}
        sensitivity = {"axes": per_axis, "composite": composite_of(per_axis), "n": len(pairs)}

    gap = round(room["composite"] - ec, 2) if room["n"] else None
    flags = []
    if room["n"] >= config.MIN_VOTES:
        if gap >= 1.0:
            flags.append({"key": "story", "label": FLAG_RULES["story"],
                          "detail": f"Crowd {room['composite']:.1f} vs engine {ec:.1f} (gap +{gap:.1f})"})
        if gap <= -1.0:
            flags.append({"key": "substance", "label": FLAG_RULES["substance"],
                          "detail": f"Crowd {room['composite']:.1f} vs engine {ec:.1f} (gap {gap:.1f})"})
        if sensitivity and sensitivity["n"] >= config.MIN_VOTES:
            if sensitivity["composite"] >= 0.4:
                flags.append({"key": "helps", "label": FLAG_RULES["helps"],
                              "detail": f"Second look moved the room +{sensitivity['composite']:.1f}"})
            if sensitivity["composite"] <= -0.4:
                flags.append({"key": "hurts", "label": FLAG_RULES["hurts"],
                              "detail": f"Second look moved the room {sensitivity['composite']:.1f}"})
        if room["consensus"] >= 1.2:
            flags.append({"key": "split", "label": FLAG_RULES["split"],
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

    names = {p["id"]: display_name(p) for p in db.execute("SELECT id, initials, handle FROM players")}
    contrarians = [{"name": names.get(v["player_id"], "?"), "bonus": v["bonus"], "axes": j(v["bonus_axes"], [])}
                   for v in r1 if (v["bonus"] or 0) > 0]
    contrarians.sort(key=lambda c: c["bonus"], reverse=True)

    return {
        "id": comp["id"], "name": comp["name"], "sector": comp["sector"], "is_real": bool(comp["is_real"]),
        "active": bool(comp["active"]),
        "engine": {"axes": engine, "composite": ec},
        "coverage": j(comp["engine_coverage"], {}),
        "crowd": {"n": room["n"], "means": room["means"], "composite": room["composite"],
                  "consensus": room["consensus"]},
        "gap": gap, "sensitivity": sensitivity, "flags": flags,
        "actions": actions, "contrarians": contrarians,
    }


def overview(db, real_only: bool) -> dict:
    comps = db.execute("SELECT * FROM companies ORDER BY name").fetchall()
    return {"companies": [company_insight(db, c, real_only) for c in comps], "real_only": real_only}
