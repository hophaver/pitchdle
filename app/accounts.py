"""Player accounts: username + password, cookie sessions, and folding a guest's answers into an account.

Deliberately light (nothing emailed: a forgotten password is a request for a new one, which a moderator approves).
Accounts exist so a crowd score can trust signed-in players more than anonymous devices, and so players keep their
history across days and devices. There are two kinds: a player signs up with a username and password and is in at
once; an investor gives the full profile and waits for a moderator (see moderation.py), can't log in until one
approves it, and then counts for more. Admins are the accounts ADMINS in .env names, and only those.
"""
import hashlib
import hmac
import re
import secrets

from . import config
from .db import dumps, now

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,20}$")
PASSWORD_MIN = 4
_ITERATIONS = 100_000


KINDS = ("player", "investor")


class AccountError(ValueError):
    pass


class NotApproved(AccountError):
    """The right password, but a moderator hasn't let the account in (yet)."""


NOT_APPROVED = {
    "pending": "Your sign-up is still waiting for a moderator. Keep playing as a guest until then.",
    "rejected": "A moderator didn't approve this sign-up.",
}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS).hex()
    return f"{salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    salt, _, digest = stored.partition("$")
    attempt = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS).hex()
    return hmac.compare_digest(attempt, digest)


def is_test(user) -> bool:
    return bool(config.TEST_USERNAME) and user["username"].lower() == config.TEST_USERNAME.lower()


def public_user(user) -> dict:
    return {"id": user["id"], "username": user["username"], "created_at": user["created_at"], "is_test": is_test(user),
            "is_moderator": bool(user["is_moderator"]), "is_admin": bool(user["is_admin"]),
            "kind": user["kind"] or "player"}


def is_admin_name(username: str) -> bool:
    return username.strip().lower() in {name.lower() for name in config.ADMINS}


def _from_env(db, username: str, password: str):
    """An account .env sets up: created, or its password brought in line, and approved."""
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if user is None:
        user = _create(db, username, password, None, "approved", "player")
    elif not check_password(password, user["password_hash"]):
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user["id"]))
    db.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user["id"],))
    return user


def ensure_test_accounts(db) -> None:
    """Create the test account and the test moderator from .env, or bring their passwords and standing in line."""
    for username, password, moderator in ((config.TEST_USERNAME, config.TEST_PASSWORD, False),
                                          (config.TEST_MODERATOR_USERNAME, config.TEST_MODERATOR_PASSWORD, True)):
        if not username or not password:
            continue
        user = _from_env(db, username, password)
        if moderator:
            db.execute("UPDATE users SET is_moderator = 1 WHERE id = ?", (user["id"],))
        db.commit()


def ensure_admins(db) -> list[str]:
    """Make exactly the accounts in ADMINS admins, on startup: any other account loses it. A name with a password
    gets its account made, or its password brought in line; a listed account is let in if it was waiting. Returns
    what couldn't be done, to log."""
    db.execute("UPDATE users SET is_admin = 0")
    problems = []
    for username, password in config.ADMINS.items():
        try:
            user = _from_env(db, username, password) if password else \
                db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        except AccountError as e:
            problems.append(f"ADMINS: can't set up '{username}': {e}")
            continue
        if user is None:
            problems.append(f"ADMINS: no account '{username}' yet, and nobody can sign up with that name. Give it a "
                            f"password in ADMINS to create it.")
            continue
        db.execute("UPDATE users SET is_admin = 1, status = 'approved' WHERE id = ?", (user["id"],))
    db.commit()
    return problems


def reset_player_data(db, uid: int) -> int:
    """Wipe an account's answers (test account only), keeping the account. Returns how many were removed."""
    removed = db.execute("DELETE FROM votes WHERE player_id IN (SELECT id FROM players WHERE user_id = ?)", (uid,)).rowcount
    db.commit()
    return removed


def player_for(db, user):
    """The signed-in player's own row, created the first time it's needed."""
    row = db.execute("SELECT * FROM players WHERE user_id = ? ORDER BY id LIMIT 1", (user["id"],)).fetchone()
    if row is None:
        db.execute("INSERT INTO players (user_id, handle, created_at) VALUES (?, ?, ?)",
                   (user["id"], user["username"], now()))
        db.commit()
        row = db.execute("SELECT * FROM players WHERE user_id = ? ORDER BY id LIMIT 1", (user["id"],)).fetchone()
    return row


def register(db, username: str, password: str, profile: dict | None = None, status: str = "pending",
             kind: str = "player"):
    """A new account. Investor sign-ups wait for a moderator; players start out approved. Names in ADMINS are kept
    for the admins."""
    if is_admin_name(username):
        raise AccountError("That username is taken.")
    return _create(db, username, password, profile, status, kind)


def _create(db, username: str, password: str, profile: dict | None, status: str, kind: str):
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise AccountError("Username: 3-20 letters, numbers, dots, dashes or underscores.")
    if len(password) < PASSWORD_MIN:
        raise AccountError(f"Password: at least {PASSWORD_MIN} characters.")
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        raise AccountError("That username is taken.")
    if kind not in KINDS:
        raise AccountError("Pick player or investor.")
    uid = db.execute("INSERT INTO users (username, password_hash, status, profile, kind, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (username, hash_password(password), status, dumps(profile or {}), kind, now())).lastrowid
    db.commit()
    return db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def set_password(db, uid: int, password: str) -> None:
    """A new password, set by a moderator who then tells the member. Their old logins end, and a request for a new
    password still waiting is dropped: this answers it."""
    if len(password) < PASSWORD_MIN:
        raise AccountError(f"Password: at least {PASSWORD_MIN} characters.")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), uid))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM password_requests WHERE user_id = ? AND status = 'pending'", (uid,))
    db.commit()


# --- forgotten passwords ----------------------------------------------------------------------------------------
# A member who forgot their password picks a new one on /play, and a moderator approves or declines it on /moderate
# (moderation.answer_request). Their old password works until then. Only the hash is kept, so nobody sees it.

def request_password(db, username: str, password: str, note: str = "") -> None:
    """Ask for a new password. A newer request replaces one still waiting."""
    user = db.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if user is None:
        raise AccountError("There's no account with that username.")
    if user["status"] == "rejected":
        raise NotApproved(NOT_APPROVED["rejected"])
    if len(password) < PASSWORD_MIN:
        raise AccountError(f"Password: at least {PASSWORD_MIN} characters.")
    db.execute("DELETE FROM password_requests WHERE user_id = ? AND status = 'pending'", (user["id"],))
    db.execute("INSERT INTO password_requests (user_id, password_hash, note, status, created_at) "
               "VALUES (?, ?, ?, 'pending', ?)", (user["id"], hash_password(password), note, now()))
    db.commit()


REQUEST_HINTS = {
    "pending": "That's the new password you asked for: it works once a moderator approves it. Until then, log in "
               "with your old one.",
    "declined": "A moderator declined the new password you asked for. Log in with your old one, or ask again.",
}


def _request_hint(db, user, password: str) -> str | None:
    """Why the password from their last request doesn't open the account (yet), if that's what they typed."""
    last = db.execute("SELECT * FROM password_requests WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                      (user["id"],)).fetchone()
    if last and last["status"] in REQUEST_HINTS and check_password(password, last["password_hash"]):
        return REQUEST_HINTS[last["status"]]
    return None


def authenticate(db, username: str, password: str):
    user = db.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if not user or not check_password(password, user["password_hash"]):
        hint = user and _request_hint(db, user, password)
        if hint:
            raise NotApproved(hint)
        raise AccountError("Wrong username or password.")
    if user["status"] != "approved":
        raise NotApproved(NOT_APPROVED.get(user["status"], NOT_APPROVED["pending"]))
    return user


def staff_login(db, username: str, password: str):
    """The moderator or admin account these credentials open, or None."""
    try:
        user = authenticate(db, username, password)
    except AccountError:
        return None
    return user if user["is_moderator"] or user["is_admin"] else None


def start_session(db, user) -> str:
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, user["id"], now()))
    db.commit()
    return token


def end_session(db, token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        db.commit()


def user_for_session(db, token: str | None):
    if not token:
        return None
    return db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                      "WHERE s.token = ? AND u.status = 'approved'", (token,)).fetchone()


def claim_guest(db, user, device_token: str | None) -> int:
    """Move a guest device's answers and submissions onto the account. Returns how many answers moved.

    Where the account already answered the same card, the account's answer stands and the guest's is dropped.
    """
    if not device_token:
        return 0
    guest = db.execute("SELECT id FROM players WHERE device_token = ? AND user_id IS NULL AND is_seed = 0",
                       (device_token,)).fetchone()
    if not guest:
        return 0
    pid = player_for(db, user)["id"]
    moved = db.execute("UPDATE OR IGNORE votes SET player_id = ? WHERE player_id = ?", (pid, guest["id"])).rowcount
    db.execute("DELETE FROM votes WHERE player_id = ?", (guest["id"],))
    db.execute("UPDATE submissions SET player_id = ? WHERE player_id = ?", (pid, guest["id"]))
    db.commit()
    return moved


def delete_user(db, uid: int) -> bool:
    """Remove an account with its answers, sessions and any A'Pelago evaluations it gave as a moderator.
    Its startup submissions stay, unattributed."""
    user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        return False
    db.execute("DELETE FROM opinions WHERE source = 'apelago' AND author = ?", (user["username"],))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM password_requests WHERE user_id = ?", (uid,))
    pids = [r["id"] for r in db.execute("SELECT id FROM players WHERE user_id = ?", (uid,))]
    for pid in pids:
        db.execute("DELETE FROM votes WHERE player_id = ?", (pid,))
        db.execute("UPDATE submissions SET player_id = NULL WHERE player_id = ?", (pid,))
    db.execute("DELETE FROM players WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()
    return True


def list_users(db) -> list[dict]:
    """Every account with how much it has played, for the host's Players tab."""
    return [dict(r) for r in db.execute("""
        SELECT u.id, u.username, u.created_at, u.kind, u.status,
               COUNT(v.id) AS answers,
               COUNT(DISTINCT v.dive_id) AS sets,
               MAX(v.created_at) AS last_played
        FROM users u
        LEFT JOIN players p ON p.user_id = u.id
        LEFT JOIN votes v ON v.player_id = p.id
        GROUP BY u.id ORDER BY u.created_at DESC, u.id DESC""")]


def guest_count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM players WHERE user_id IS NULL AND is_seed = 0").fetchone()[0]
