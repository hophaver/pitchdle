"""Queries and payload builders shared by the API routes."""
import random
import sqlite3
from datetime import date, datetime, time, timedelta

from . import config, landscape, opinions, scoring
from .db import dumps, j, name_key, now
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
    """What a player sees: the pitch and the startup's profile, nothing about anyone's scores."""
    return {
        "id": row["id"], "name": row["name"], "emoji": row["emoji"] or "", "sector": row["sector"],
        "one_liner": row["one_liner"], "claim_ask": row["claim_ask"], "is_real": bool(row["is_real"]),
        "vision": row["vision"] or "", "website": row["website"] or "", "stages": j(row["stages"], []),
        "raised_eur": row["raised_eur"], "investors": j(row["investors"], []),
    }


def play_card(db, row) -> dict:
    """The card a player rates: the pitch, the profile, and what A'Pelago, the AI models and social media make of it,
    so the call is a weighed one. The crowd's read waits for the results, and the engine stays off the phones."""
    return public_card(row) | {"opinions": opinions.for_card(db, row["id"], None, None),
                               "quiet": opinions.quiet(db, row["id"])}


def get_dive(db, did: int):
    return db.execute("SELECT * FROM dives WHERE id = ?", (did,)).fetchone()


def dive_companies(db, dive) -> list:
    """A set's companies, in order. Only ever its own pool's: a demo set yields sample companies and a live set
    real ones, whatever ids it holds, so the two can never mix in a game, the wall or results."""
    ids = j(dive["company_ids"], [])
    rows = {r["id"]: r for r in db.execute(
        f"SELECT * FROM companies WHERE id IN ({','.join('?' * len(ids))}) AND is_real = ?",
        [*ids, pool_is_real(dive["pool"] or "demo")])} if ids else {}
    return [rows[i] for i in ids if i in rows]


def outside_pool(db, ids: list[int], pool: str) -> list[int]:
    """The ids that aren't companies of this pool (missing ones included)."""
    inside = {r["id"] for r in db.execute(
        f"SELECT id FROM companies WHERE id IN ({','.join('?' * len(ids))}) AND is_real = ?",
        [*ids, pool_is_real(pool)])} if ids else set()
    return [i for i in ids if i not in inside]


def in_mode(db, dive) -> bool:
    """Whether a set belongs to the current mode. Players only ever reach the current mode's sets."""
    return (dive["pool"] or "demo") == get_mode(db)


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
    cur = db.execute("INSERT INTO dives (label, date, company_ids, mode, pool, created_at) VALUES (?, ?, ?, 'daily', ?, ?)",
                     (daily_label(db, pool), today, dumps(picked), pool, now()))
    db.commit()
    return get_dive(db, cur.lastrowid)


def daily_label(db, pool: str) -> str:
    count = db.execute("SELECT COUNT(*) FROM dives WHERE mode = 'daily' AND pool = ?", (pool,)).fetchone()[0]
    return f"#{count + 1}" if pool == "demo" else f"Live #{count + 1}"


def generate_dives(db, count: int, cards: int = 5) -> list:
    """Queue the next `count` daily games for the current mode, one per day on the first days from today that have no
    game yet. Each takes the `cards` in-game companies shown least so far (in any of the mode's games), so every
    company gets its turn before one repeats; ties are broken at random. Returns the new games, oldest first."""
    pool = get_mode(db)
    ids = [r["id"] for r in db.execute("SELECT id FROM companies WHERE active = 1 AND is_real = ? ORDER BY id",
                                       (pool_is_real(pool),))]
    if not ids:
        raise ValueError("No companies are in the game yet: activate some first.")
    shown = {i: 0 for i in ids}
    taken = set()
    for row in db.execute("SELECT date, company_ids FROM dives WHERE pool = ?", (pool,)):
        taken.add(row["date"])
        for i in j(row["company_ids"], []):
            if i in shown:
                shown[i] += 1
    rng = random.Random()
    day, made = date.today(), []
    while len(made) < count:
        if day.isoformat() not in taken:
            picked = sorted(ids, key=lambda i: (shown[i], rng.random()))[:min(cards, len(ids))]
            for i in picked:
                shown[i] += 1
            cur = db.execute("INSERT INTO dives (label, date, company_ids, mode, pool, created_at) "
                             "VALUES (?, ?, ?, 'daily', ?, ?)", (daily_label(db, pool), day.isoformat(), dumps(picked), pool, now()))
            made.append(get_dive(db, cur.lastrowid))
        day += timedelta(days=1)
    db.commit()
    return made


def scores_of(vote) -> dict:
    return {a: vote[a] for a in AXES}


# Votes with the voter's user_id and account kind alongside, so crowd scores can weigh guests, players and
# investors apart.
VOTES_WITH_USER = ("SELECT v.*, p.user_id, u.kind FROM votes v LEFT JOIN players p ON p.id = v.player_id "
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
        others = scoring.crowd([v for v in card_votes(db, dive["id"], comp["id"]) if v["player_id"] != pid])
        you_composite = composite_of(you)
        # Nobody else has answered yet: nothing to lean against.
        lean = scoring.lean(you_composite, others["composite"]) if others["n"] else None
        if lean:
            leans[lean] += 1
        cards.append({
            "card": public_card(comp),
            "you": {"scores": you, "composite": you_composite},
            "crowd": {"n": others["n"], "means": others["means"], "composite": others["composite"]},
            "lean": lean,
            # A'Pelago's, the AI models' and social media's reads, only now that the player has given theirs.
            "opinions": opinions.for_card(db, comp["id"], you, others),
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


# --- host overview ---------------------------------------------------------------------------------

FLAG_LABELS = {
    "story": "Story > substance",
    "substance": "Substance > story",
    "split": "Room split",
}
# Which opportunity kinds a flag pushes up the "next actions" list, and why.
FLAG_BOOST = {
    "story": ({"partner", "client"}, "prove it with a pilot before raising"),
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


def outside_read(tiles: list[dict]) -> dict:
    """The outside world's read on the four calls' average: the AI models' mean and social media's mean, each
    counting once. None where nobody has read it yet."""
    means = {}
    for group in ("ai", "social"):
        rows = [t for t in tiles if t["group"] == group]
        if rows:
            means[group] = round(sum(sum(t["scores"][a] for a in AXES) / len(AXES) for t in rows) / len(rows), 2)
    composite = round(sum(means.values()) / len(means), 2) if means else None
    return {"ai": means.get("ai"), "social": means.get("social"), "composite": composite,
            "n": sum(t["group"] in ("ai", "social") for t in tiles)}


READ_LABEL = {"crowd": "Crowd", "engine": "Evidence", "outside": "Outside"}
# What it means when the first read sits well above the second.
GAP_MEANING = {
    ("crowd", "engine"): "the pitch outsells the evidence",
    ("engine", "crowd"): "stronger than its pitch",
    ("outside", "engine"): "its reputation runs ahead of the evidence",
    ("engine", "outside"): "the evidence is ahead of its reputation",
    ("crowd", "outside"): "the room likes it more than the outside world",
    ("outside", "crowd"): "the outside world likes it more than the room",
}


def divergence(points: dict) -> dict:
    """Where the crowd, the evidence and the outside world part ways: the widest gap among the reads that exist,
    and what it means. Reads that aren't in yet are left out, never guessed."""
    known = {k: v for k, v in points.items() if v is not None}
    missing = [READ_LABEL[k].lower() for k in points if k not in known]
    if len(known) < 2:
        return {"max_gap": None, "high": None, "low": None, "points": points, "diverges": False,
                "text": f"Needs two reads to compare ({', '.join(missing)} not in yet)."}
    high = max(known, key=known.get)
    low = min(known, key=known.get)
    gap = round(known[high] - known[low], 1)
    if gap >= VERDICT_GAP:
        text = f"{READ_LABEL[high]} {known[high]:.1f} vs {READ_LABEL[low].lower()} {known[low]:.1f}: {GAP_MEANING[(high, low)]}."
    else:
        names = [READ_LABEL[k].lower() for k in known]
        text = f"{', '.join(names[:-1])} and {names[-1]} agree within {gap:.1f}.".capitalize()
    if missing:
        text += f" No {' or '.join(missing)} read yet."
    return {"max_gap": gap, "high": high, "low": low, "points": points, "diverges": gap >= VERDICT_GAP, "text": text}


REVIEW = {
    "ai": ("Estimated by AI · host confirms",
           "Every factor its website and news speak to was scored by AI; the rest stay unknown. Readiness, thesis "
           "fit and the call follow from those estimates until the host confirms the evidence."),
    "auto": ("Auto-estimated · host confirms",
             "Found by discovery. Only the tech stage is estimated, from its headlines or site; every other factor "
             "stays unknown until the host reviews the evidence in Admin."),
    "pending": ("Awaiting host evidence review",
                "Found by discovery, not yet evidence-backed. Nothing in its headlines or site could be scored, so "
                "readiness and thesis fit stay unknown until the host adds evidence in Admin."),
}


def review_state(comp) -> dict:
    """Whether a company's engine read is backed by evidence the host checked, for the dashboard and exports."""
    status = comp["evidence_status"] if comp["evidence_status"] in REVIEW else "confirmed"
    label, detail = REVIEW.get(status, ("Evidence reviewed by the host", ""))
    return {"status": status, "pending": status != "confirmed", "label": label, "detail": detail}


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
    company = {"sector": comp["sector"], "one_liner": comp["one_liner"], "claim_ask": comp["claim_ask"],
               "country": comp["country"] or ""}
    full = engine_full(j(comp["evidence"], {}), company=company)
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
    tech = readiness_levels["tech"]
    # Hand-picked opportunities (seed data, the host's own) and the landscape's matches, ranked together.
    pool = [{"kind": KIND.get(o["kind"], o["kind"]), "name": o["name"], "why": o["why"], "fit": o["fit"] or 0,
             "stage_fit": o["stage_fit"], "url": "", "reasons": [], "source": "manual"}
            for o in db.execute("SELECT * FROM opportunities WHERE company_id = ?", (comp["id"],))]
    picked = {name_key(o["name"]) for o in pool}
    company = company | {"facts": j(comp["facts"], [])}
    pool += [m for m in landscape.match(company, tech.get("trl")) if name_key(m["name"]) not in picked]
    actions = []
    for o in pool:
        score, boosted = o["fit"], []
        for key in flag_keys:
            if key in FLAG_BOOST and o["kind"] in FLAG_BOOST[key][0]:
                score += 0.3
                boosted.append(FLAG_BOOST[key][1])
        # Thesis fit also steers the list: a strong accelerator fit lifts the accelerator-style opportunities
        # (partners, grants, clients); a strong investment fit lifts investors.
        thesis = ("apelago", "fits the accelerator thesis") if o["kind"] in ("partner", "grant", "client") \
            else ("redstone", "fits the investment thesis") if o["kind"] == "investor" else None
        if thesis and theses[thesis[0]]["score"] is not None:
            boost = (theses[thesis[0]]["score"] - 2.5) * 0.15
            score += boost
            if boost > 0:
                boosted.append(thesis[1])
        actions.append(o | {"score": round(score, 2), "boosted": boosted})
    actions.sort(key=lambda a: (-a["score"], a["name"]))
    pulse = j(comp["pulse"])
    verdict, verdict_reason = triangulate(room["n"], room["composite"], ec, pulse, config.MIN_VOTES)
    tiles = opinions.for_card(db, comp["id"], None, room if room["n"] else None)
    outside = outside_read(tiles)
    coverage = j(comp["engine_coverage"], {})
    engine_known = ec if coverage.get("assessed") else None

    out = {
        "id": comp["id"], "name": comp["name"], "sector": comp["sector"], "is_real": bool(comp["is_real"]),
        "one_liner": comp["one_liner"] or "", "claim_ask": comp["claim_ask"] or "", "website": comp["website"] or "",
        "country": comp["country"] or "",
        "active": bool(comp["active"]), "origin": comp["origin"] or "", "review": review_state(comp),
        "engine": {"axes": engine, "composite": ec},
        "readiness": readiness_levels, "theses": theses, "factors": factors,
        "evidence_note": comp["evidence_note"] or "",
        "coverage": coverage,
        "crowd": {"n": room["n"], "signed_in": room["signed_in"], "means": room["means"],
                  "composite": room["composite"], "consensus": room["consensus"]},
        "gap": gap, "flags": flags, "actions": actions,
        "pulse": pulse, "verdict": verdict, "verdict_reason": verdict_reason,
        # What an investor's card shows: the profile, and what the crowd, A'Pelago, the AI models and social media
        # make of it.
        "emoji": comp["emoji"] or "", "vision": comp["vision"] or "", "stages": j(comp["stages"], []),
        "raised_eur": comp["raised_eur"], "investors": j(comp["investors"], []),
        "profile": {"status": comp["profile_status"] or "", "note": comp["profile_note"] or ""},
        # In the daily game or not, and why: the automatic moderation's verdict (crawler/gate.py).
        "game": {"status": comp["game_status"] or "", "note": comp["game_note"] or ""},
        "opinions": tiles,
        # The two reads nobody else has, against the evidence on one scale: the game's crowd and the outside
        # world (AI models and social media). divergence says where they part ways.
        "outside": outside,
        "divergence": divergence({"crowd": room["composite"] if room["n"] else None, "engine": engine_known,
                                  "outside": outside["composite"]}),
        "quiet": opinions.quiet(db, comp["id"]),
    }
    return out | {"call": call(out), "next": next_move(out)}


# Older opportunity rows say "customer"; the landscape says "client".
KIND = {"customer": "client"}

BACK_AT, AVOID_BELOW = 3.5, 2.5


def call(c: dict) -> dict:
    """Back, watch, avoid, or needs evidence, with the reasons. Driven by the best thesis fit, then tempered by
    what the room and the web say. Without any evidenced thesis factor it never guesses: needs evidence."""
    scored = [t for t in c["theses"].values() if t["score"] is not None]
    if c["theses"] and all(t.get("fit") == "out" for t in c["theses"].values()):
        return {"key": "avoid", "label": "Out of scope", "scope": "out",
                "reasons": [f"{t['label'].split(' ')[0]}: {t['why'].removeprefix('Out of scope: ')}"
                            for t in c["theses"].values()]}
    if not scored:
        return {"key": "evidence", "label": "Needs evidence",
                "reasons": [c["review"]["label"] if c["review"]["pending"] else "No thesis factor evidenced yet"]}
    best = max(scored, key=lambda t: t["score"])
    key = "back" if best["score"] >= BACK_AT else "avoid" if best["score"] < AVOID_BELOW else "watch"
    reasons = [f"{best['label']} fit {best['score']:.1f}"]
    soften = lambda k: "watch" if k == "back" else k
    flags = {f["key"]: f for f in c["flags"]}
    if "story" in flags:
        key = soften(key)
        reasons.append(f"Pitch outsells the evidence ({flags['story']['detail']})")
    if "substance" in flags:
        reasons.append(f"Stronger than its pitch ({flags['substance']['detail']})")
    if c["pulse"] and c["pulse"]["lean"] == "negative":
        key = soften(key)
        reasons.append("Web coverage leans negative")
    if c["review"]["pending"]:
        key = soften(key)
        reasons.append("Evidence not yet confirmed by the host")
    labels = {"back": "Back", "watch": "Watch", "avoid": "Avoid"}
    return {"key": key, "label": labels[key], "reasons": reasons}


# What closes each readiness gap, and which kind of opportunity helps with it.
MOVES = {
    "ocean_impact": ("Measure and prove its impact", "partner"),
    "business": ("Win a paying pilot", "client"),
    "tech": ("De-risk the technology", "grant"),
    "investment": ("Get investment-ready", "investor"),
}


def next_move(c: dict) -> dict | None:
    """The weakest readiness level and the top opportunity that addresses it: the lowest evidenced one, or an
    unknown one when everything evidenced is fine. When every level is strong, raise. None when nothing is evidenced."""
    levels = [lv for lv in c["readiness"].values() if lv["score"] is not None]
    if not levels:
        return None
    weakest = min(levels, key=lambda lv: lv["score"])
    # What's evidenced looks fine but a level is still unknown: that's the gap, not raising money.
    unknown = [c["readiness"][k] for k in ("business", "investment", "ocean_impact", "tech") if c["readiness"][k]["score"] is None]
    if unknown and weakest["score"] >= AVOID_BELOW:
        weakest = unknown[0]
    text, kind = MOVES[weakest["key"]]
    if weakest["score"] is not None and weakest["score"] >= BACK_AT:
        text, kind = "Raise the next round", "investor"
    with_whom = next((a for a in c["actions"] if a["kind"] == kind), None) or (c["actions"] or [None])[0]
    return {"gap": weakest["key"], "gap_label": weakest["label"], "gap_score": weakest["score"], "text": text,
            "with": with_whom["name"] if with_whom else None, "url": with_whom["url"] if with_whom else ""}


def overview(db, real_only: bool) -> dict:
    mode = get_mode(db)
    comps = db.execute("SELECT * FROM companies WHERE is_real = ? ORDER BY name", (pool_is_real(mode),)).fetchall()
    return {"companies": [company_insight(db, c, real_only) for c in comps], "real_only": real_only,
            "mode": mode, "autofill": get_setting(db, "autofill")}
