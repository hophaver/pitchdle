"""Moderation: every sign-up waits for a moderator, and approved members carry a badge that sets how much
their answers count in crowd scores (scoring.vote_weights does the counting).

Moderators are members an admin has promoted, and sign in with their own account; admins get in with the
admin password. Whoever acts is recorded on each review and badge.
"""
from dataclasses import dataclass
from statistics import fmean

from . import accounts, config
from .db import j, now
from .engine import AXES, composite_of

BADGES = ("", "high", "low", "muted")  # '' is no badge: a member who counts 1


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


def review(db, user, status: str, badge: str, staff: Staff) -> None:
    """Let a sign-up in, optionally with a badge, or turn it down. A turned-down sign-up can still be let in later."""
    if user["status"] == "approved":
        raise ModerationError(f"{user['username']} is already a member. Change their badge or delete them instead.")
    stamp = now()
    db.execute("UPDATE users SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
               (status, staff.name, stamp, user["id"]))
    if status == "approved" and badge:
        db.execute("UPDATE users SET badge = ?, badge_by = ?, badge_at = ? WHERE id = ?",
                   (badge, staff.name, stamp, user["id"]))
    db.commit()


def set_badge(db, user, badge: str, staff: Staff) -> None:
    if user["status"] != "approved":
        raise ModerationError("Only members have badges. Approve the sign-up first.")
    check_manageable(user, staff)
    db.execute("UPDATE users SET badge = ?, badge_by = ?, badge_at = ? WHERE id = ?",
               (badge, staff.name, now(), user["id"]))
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
        "status": user["status"], "profile": j(user["profile"], {}),
        "reviewed_by": user["reviewed_by"], "reviewed_at": user["reviewed_at"],
        "badge": user["badge"] or "", "badge_by": user["badge_by"], "badge_at": user["badge_at"],
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
        "weights": {"high": config.HIGH_PRIORITY_WEIGHT, "low": config.LOW_PRIORITY_WEIGHT,
                    "guest": config.GUEST_WEIGHT, "guest_max_share": config.GUEST_MAX_SHARE},
    }
