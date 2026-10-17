"""Seed the database, rescore companies, and generate demo votes.

    python -m app.seed            # seed if the DB is empty
    python -m app.seed --reset    # wipe everything and reseed
    python -m app.seed --rescore  # recompute engine scores after editing weights.json
"""
import argparse
import random
from datetime import date, timedelta

from . import engine, service
from .db import connect, dumps, init_db, j, now
from .engine import AXES
from .seed_data import COMPANIES, DEMO_BIAS, DIVES, PROFILES


def score_company(db, cid: int) -> None:
    row = service.get_company(db, cid)
    result = engine.score(j(row["evidence"], {}))
    db.execute("UPDATE companies SET engine_axes = ?, engine_composite = ?, engine_coverage = ?, scored_at = ? "
               "WHERE id = ?", (dumps(result["axes"]), result["composite"], dumps(result["coverage"]), now(), cid))


def seed(db) -> None:
    ids = {}
    for c in COMPANIES:
        p = PROFILES[c["name"]]
        cur = db.execute(
            "INSERT INTO companies (name, emoji, sector, one_liner, claim_ask, facts, evidence, evidence_note, is_real, "
            "active, vision, stages, raised_eur, investors, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?, ?, ?)",
            (c["name"], c["emoji"], c["sector"], c["one_liner"], c["claim_ask"], dumps(c["facts"]), dumps(c["evidence"]),
             c["evidence_note"], p["vision"], dumps(p["stages"]), p["raised_eur"], dumps(p["investors"]), now()))
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


def fill_profiles(db) -> int:
    """Give sample companies from before card profiles existed their profile. Only fills ones never saved since
    (vision still NULL), so nothing an admin wrote is overwritten. Returns how many were filled."""
    filled = 0
    for name, p in PROFILES.items():
        filled += db.execute(
            "UPDATE companies SET vision = ?, stages = ?, raised_eur = ?, investors = ? "
            "WHERE name = ? AND is_real = 0 AND vision IS NULL",
            (p["vision"], dumps(p["stages"]), p["raised_eur"], dumps(p["investors"]), name)).rowcount
    db.commit()
    return filled


def seed_if_empty(db) -> bool:
    if db.execute("SELECT COUNT(*) FROM companies").fetchone()[0]:
        return False
    seed(db)
    return True


def reset(db) -> None:
    for table in ("votes", "sessions", "players", "users", "opportunities", "opinions", "dives", "candidates",
                  "companies", "settings"):
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
    """Fill a set with a believable fake room (flagged is_seed) so the wall and results look alive.

    The room follows each company's demo_bias, so the designed cases light up their flags.
    Returns the number of votes inserted.
    """
    rng = random.Random(rng_seed)
    dive = service.get_dive(db, dive_id)
    comps = service.dive_companies(db, dive)
    pids = []
    for i in range(players):
        cur = db.execute("INSERT INTO players (device_token, handle, is_seed, created_at) VALUES (?, ?, 1, ?)",
                         (f"seed-{dive_id}-{rng_seed}-{i}-{rng.random()}", service.new_handle(rng), now()))
        pids.append(cur.lastrowid)
    inserted = 0
    for comp in comps:
        eng = j(comp["engine_axes"])
        bias = DEMO_BIAS.get(comp["name"], 0.0)
        for pid in pids:
            skill = rng.uniform(0.5, 1.3)
            s = {a: _clamp(eng[a] + bias + rng.gauss(0, skill)) for a in AXES}
            db.execute(
                "INSERT INTO votes (player_id, dive_id, company_id, round, novel, useful, plausible, investable, "
                "is_seed, created_at) VALUES (?, ?, ?, 1, ?, ?, ?, ?, 1, ?)",
                (pid, dive_id, comp["id"], s["novel"], s["useful"], s["plausible"], s["investable"], now()))
            inserted += 1
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
