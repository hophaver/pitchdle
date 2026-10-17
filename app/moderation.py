"""Moderation: every investor sign-up waits for a moderator (players are in at once). How much a member's answers
count in crowd scores follows from their account kind (scoring.vote_weights).

Moderators are members an admin has promoted, and sign in with their own account; admins get in with the
admin password. Whoever acts is recorded on each review.
"""
from dataclasses import dataclass
from statistics import fmean

from . import accounts, config, service
from .db import j, now
from .engine import AXES, composite_of


@dataclass(frozen=True)
class Staff:
    """Who is acting on /moderate: a moderator's own account, or the admin login."""
    name: str  # a moderator's username, or "admin"
    admin: bool = False


class ModerationError(ValueError):
    pass


class NotAllowed(ModerationError):
    """Something only an admin may do."""


def get_user(db, uid: int):
    return db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def check_manageable(user, staff: Staff) -> None:
    """Moderator accounts, a moderator's own included, are changed by admins only."""
    if user["is_moderator"] and not staff.admin:
        raise NotAllowed("Only an admin can change a moderator's account.")


def review(db, user, status: str, staff: Staff) -> None:
    """Let a sign-up in or turn it down. A turned-down sign-up can still be let in later."""
    if user["status"] == "approved":
        raise ModerationError(f"{user['username']} is already a member. Delete them instead.")
    db.execute("UPDATE users SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
               (status, staff.name, now(), user["id"]))
    db.commit()


def set_moderator(db, user, moderator: bool, staff: Staff) -> None:
    """Admins make members moderators, or take it back. It counts from their next request on."""
    if not staff.admin:
        raise NotAllowed("Only an admin can make or remove moderators.")
    if user["status"] != "approved":
        raise ModerationError("Only members can moderate. Approve the sign-up first.")
    db.execute("UPDATE users SET is_moderator = ? WHERE id = ?", (int(moderator), user["id"]))
    db.commit()


def activity(db, uid: int | None = None) -> dict[int, dict]:
    """How each member has played, for moderators judging their reads.

    Besides answers, sets and the last play: engine_gap is the average distance (0-5) between a member's overall
    read of a card and the engine's evidence-based one, and flat_share is the share of their answers that gave all
    four calls the same number (like 3-3-3-3), which can mean they're clicking through.
    """
    sql = """SELECT p.user_id, v.dive_id, v.created_at, v.novel, v.useful, v.plausible, v.investable,
                    c.engine_composite
             FROM votes v JOIN players p ON p.id = v.player_id JOIN companies c ON c.id = v.company_id
             WHERE p.user_id IS NOT NULL"""
    rows = db.execute(sql + " AND p.user_id = ?", (uid,)) if uid is not None else db.execute(sql)
    acc = {}
    for r in rows:
        a = acc.setdefault(r["user_id"], {"answers": 0, "sets": set(), "last": "", "gaps": [], "flat": 0})
        scores = {x: r[x] for x in AXES}
        a["answers"] += 1
        a["sets"].add(r["dive_id"])
        a["last"] = max(a["last"], r["created_at"] or "")
        a["flat"] += len(set(scores.values())) == 1
        if r["engine_composite"] is not None:
            a["gaps"].append(abs(composite_of(scores) - r["engine_composite"]))
    return {user_id: {"answers": a["answers"], "sets": len(a["sets"]), "last_played": a["last"] or None,
                      "engine_gap": round(fmean(a["gaps"]), 2) if a["gaps"] else None,
                      "flat_share": round(a["flat"] / a["answers"], 2)}
            for user_id, a in acc.items()}


NO_ACTIVITY = {"answers": 0, "sets": 0, "last_played": None, "engine_gap": None, "flat_share": None}


def user_payload(user, played: dict | None) -> dict:
    return {
        "id": user["id"], "username": user["username"], "created_at": user["created_at"],
        "status": user["status"], "kind": user["kind"] or "player", "profile": j(user["profile"], {}),
        "reviewed_by": user["reviewed_by"], "reviewed_at": user["reviewed_at"],
        "is_moderator": bool(user["is_moderator"]), "is_test": accounts.is_test(user),
        **(played or NO_ACTIVITY),
    }


def member(db, uid: int) -> dict:
    return user_payload(get_user(db, uid), activity(db, uid).get(uid))


def overview(db) -> dict:
    """Every account (waiting, members and turned down), with what moderators need to judge them."""
    played = activity(db)
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC, id DESC").fetchall()
    return {
        "users": [user_payload(u, played.get(u["id"])) for u in users],
        "guests": accounts.guest_count(db),
        "weights": weights(),
        "weight_defaults": dict(DEFAULT_WEIGHTS),
    }


# --- how much each kind of answer counts ------------------------------------------------------------------
# The four numbers scoring.vote_weights reads from config. .env sets the defaults; the admin changes them on the
# moderation page, and the change is saved in the settings table and put back into config at startup.
WEIGHT_ATTRS = {"player": "PLAYER_WEIGHT", "investor": "INVESTOR_WEIGHT", "guest": "GUEST_WEIGHT",
                "guest_max_share": "GUEST_MAX_SHARE"}
DEFAULT_WEIGHTS = {k: getattr(config, attr) for k, attr in WEIGHT_ATTRS.items()}


def weights() -> dict:
    return {k: getattr(config, attr) for k, attr in WEIGHT_ATTRS.items()}


def _apply(values: dict) -> None:
    for k, attr in WEIGHT_ATTRS.items():
        if isinstance(values.get(k), (int, float)):
            setattr(config, attr, float(values[k]))


def load_weights(db) -> None:
    """Put the saved weights (if any) over the .env defaults."""
    _apply(service.get_setting(db, "vote_weights", {}) or {})


def save_weights(db, values: dict) -> dict:
    service.set_setting(db, "vote_weights", {k: float(values[k]) for k in WEIGHT_ATTRS})
    _apply(values)
    return weights()
