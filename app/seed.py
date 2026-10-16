"""Seed the database, rescore companies, and generate demo votes.

    python -m app.seed            # seed if the DB is empty
    python -m app.seed --reset    # wipe everything and reseed
    python -m app.seed --rescore  # recompute engine scores after editing weights.json
"""
import argparse
import random
from datetime import date, timedelta

from . import engine, scoring, service
from .db import connect, dumps, init_db, j, now
from .engine import AXES
from .seed_data import COMPANIES, DEMO_BIAS, DIVES


def score_company(db, cid: int) -> None:
    row = service.get_company(db, cid)
    result = engine.score(j(row["evidence"], {}))
    db.execute("UPDATE companies SET engine_axes = ?, engine_composite = ?, engine_coverage = ?, scored_at = ? "
               "WHERE id = ?", (dumps(result["axes"]), result["composite"], dumps(result["coverage"]), now(), cid))


def seed(db) -> None:
    ids = {}
    for c in COMPANIES:
        cur = db.execute(
            "INSERT INTO companies (name, sector, one_liner, claim_ask, facts, evidence, evidence_note, is_real, "
            "active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?)",
            (c["name"], c["sector"], c["one_liner"], c["claim_ask"], dumps(c["facts"]), dumps(c["evidence"]),
             c["evidence_note"], now()))
        ids[c["name"]] = cur.lastrowid
        score_company(db, cur.lastrowid)
        for o in c["opportunities"]:
            db.execute("INSERT INTO opportunities (company_id, kind, name, why, fit, stage_fit) VALUES (?, ?, ?, ?, ?, ?)",
                       (cur.lastrowid, o["kind"], o["name"], o["why"], o["fit"], o["stage_fit"]))
    today = date.today()
    for label, mode, names, days_ago in DIVES:
        day = (today - timedelta(days=days_ago)).isoformat() if days_ago is not None else None
        db.execute("INSERT INTO dives (label, date, company_ids, mode, created_at) VALUES (?, ?, ?, ?, ?)",
                   (label, day, dumps([ids[n] for n in names]), mode, now()))
    db.commit()


def seed_if_empty(db) -> bool:
    if db.execute("SELECT COUNT(*) FROM companies").fetchone()[0]:
        return False
    seed(db)
    return True


def reset(db) -> None:
    for table in ("votes", "players", "opportunities", "dives", "companies"):
        db.execute(f"DELETE FROM {table}")
    db.execute("UPDATE live_state SET dive_id = NULL, card_index = -1, phase = 'idle'")
    db.commit()
    seed(db)


def rescore_all(db) -> None:
    for r in db.execute("SELECT id FROM companies").fetchall():
        score_company(db, r["id"])
    db.commit()


def _clamp(v: float) -> int:
    return max(0, min(5, round(v)))


def demo_votes(db, dive_id: int, players: int = 30, rng_seed: int = 7) -> int:
    """Fill a dive with a believable fake room (flagged is_seed) so the wall looks alive.

    The room follows each company's demo_bias, so the designed cases light up their flags; one seed
    player ("ACE") reads every card like the engine, so Against the Current has a clear leader.
    Returns the number of votes inserted.
    """
    rng = random.Random(rng_seed)
    dive = service.get_dive(db, dive_id)
    comps = service.dive_companies(db, dive)
    pids = []
    for i in range(players):
        initials = "ACE" if i == 0 else None
        cur = db.execute("INSERT INTO players (device_token, initials, handle, is_seed, created_at) "
                         "VALUES (?, ?, ?, 1, ?)",
                         (f"seed-{dive_id}-{rng_seed}-{i}-{rng.random()}", initials, service.new_handle(rng), now()))
        pids.append(cur.lastrowid)
    inserted = 0
    for comp in comps:
        eng = j(comp["engine_axes"])
        bias = DEMO_BIAS.get(comp["name"], 0.0)
        for i, pid in enumerate(pids):
            if i == 0:
                r1 = {a: _clamp(eng[a]) for a in AXES}
            else:
                skill = rng.uniform(0.5, 1.3)
                r1 = {a: _clamp(eng[a] + bias + rng.gauss(0, skill)) for a in AXES}
            # Second look: most of the room drifts toward the fundamentals, the rest stick.
            stuck = i == 0 or rng.random() < 0.3
            r2 = r1 if stuck else {a: _clamp(r1[a] + (eng[a] - r1[a]) * rng.uniform(0.3, 0.7)) for a in AXES}
            for rnd, s, st in ((1, r1, 0), (2, r2, int(stuck))):
                db.execute(
                    "INSERT INTO votes (player_id, dive_id, company_id, round, novel, useful, plausible, investable, "
                    "stuck, points, is_seed, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                    (pid, dive_id, comp["id"], rnd, s["novel"], s["useful"], s["plausible"], s["investable"],
                     st, scoring.vote_points(s, eng), now()))
                inserted += 1
        service.ensure_bonus(db, dive_id, comp["id"], eng)
    db.commit()
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="wipe all data and reseed")
    parser.add_argument("--rescore", action="store_true", help="recompute engine scores")
    args = parser.parse_args()
    db = connect()
    init_db(db)
    if args.reset:
        reset(db)
        print("Database reset and reseeded.")
    elif args.rescore:
        rescore_all(db)
        print("Engine scores recomputed.")
    else:
        print("Seeded." if seed_if_empty(db) else "Already seeded; use --reset to start over.")


if __name__ == "__main__":
    main()
