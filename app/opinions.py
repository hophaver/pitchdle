"""Opinions on a startup besides the players': A'Pelago's own, AI models' and social media's.

Every opinion uses the players' four calls on the same 0-5 scale, so a result card can set them side by side.
Players only see them after answering, so nothing anchors their own read.
"""
from statistics import fmean

from .db import dumps, j, now
from .engine import AXES

APELAGO = "apelago"  # one row per representative: a moderator, or the admin login
AI = {"claude": "Claude", "gpt": "GPT", "grok": "Grok"}
SOCIAL = {"x": "X", "threads": "Threads", "linkedin": "LinkedIn", "reddit": "Reddit", "bluesky": "Bluesky"}
OUTSIDE = AI | SOCIAL  # fetched from Admin, or entered there by hand
LABELS = {"you": "You", "crowd": "Everyone", APELAGO: "A'Pelago"} | OUTSIDE


def scores_of(row) -> dict | None:
    if any(row[a] is None for a in AXES):
        return None
    return {a: round(row[a], 2) for a in AXES}


def save(db, cid: int, source: str, scores: dict | None, note: str = "", meta: dict | None = None,
         author: str = "") -> None:
    """Add or replace one opinion. scores=None records a look that found nothing (a social search without posts)."""
    values = [None if scores is None else float(scores[a]) for a in AXES]
    db.execute(
        "INSERT INTO opinions (company_id, source, author, novel, useful, plausible, investable, note, meta, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (company_id, source, author) DO UPDATE SET "
        "novel = excluded.novel, useful = excluded.useful, plausible = excluded.plausible, "
        "investable = excluded.investable, note = excluded.note, meta = excluded.meta, updated_at = excluded.updated_at",
        (cid, source, author, *values, note, dumps(meta or {}), now()))
    db.commit()


def remove(db, cid: int, source: str, author: str = "") -> bool:
    removed = db.execute("DELETE FROM opinions WHERE company_id = ? AND source = ? AND author = ?",
                         (cid, source, author)).rowcount
    db.commit()
    return bool(removed)


def outside(db, cid: int) -> dict[str, dict]:
    """The AI and social opinions on one company, by source."""
    return {r["source"]: {"scores": scores_of(r), "note": r["note"] or "", "meta": j(r["meta"], {}),
                          "updated_at": r["updated_at"]}
            for r in db.execute("SELECT * FROM opinions WHERE company_id = ? AND source != ?", (cid, APELAGO))}


def evaluations(db, cid: int) -> list:
    return db.execute("SELECT * FROM opinions WHERE company_id = ? AND source = ? ORDER BY updated_at, id",
                      (cid, APELAGO)).fetchall()


def apelago(db, cid: int) -> dict | None:
    """A'Pelago's opinion: the average of its representatives' evaluations."""
    rows = evaluations(db, cid)
    if not rows:
        return None
    return {"n": len(rows), "means": {a: round(fmean(r[a] for r in rows), 2) for a in AXES},
            "reps": [r["author"] for r in rows]}


def quiet(db, cid: int) -> list[str]:
    """The platforms searched without finding a post about the company."""
    empty = {r["source"] for r in db.execute("SELECT source FROM opinions WHERE company_id = ? AND novel IS NULL",
                                             (cid,))}
    return [label for key, label in SOCIAL.items() if key in empty]


def for_card(db, cid: int, you: dict | None, crowd: dict | None) -> list[dict]:
    """Every opinion that has scores, in the order a result card shows them.

    A'Pelago's comments stay with the staff; AI reasons and social summaries come along as notes.
    """
    tiles = []

    def add(key: str, group: str, scores: dict | None, count: int | None = None, note: str = "") -> None:
        if scores:
            tiles.append({"key": key, "label": LABELS[key], "group": group, "scores": scores, "count": count,
                          "note": note})

    add("you", "people", you)
    add("crowd", "people", crowd and crowd["means"], crowd and crowd["n"])
    ap = apelago(db, cid)
    add(APELAGO, "people", ap and ap["means"], ap and ap["n"])
    found = outside(db, cid)
    for key in OUTSIDE:
        if key in found:
            o = found[key]
            add(key, "ai" if key in AI else "social", o["scores"], o["meta"].get("posts"), o["note"])
    return tiles
