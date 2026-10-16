"""Player accounts: username + password, cookie sessions, and folding a guest's answers into an account.

Deliberately light (no email, no reset). Accounts exist so a crowd score can trust signed-in players more
than anonymous devices, and so players keep their history across days and devices.
"""
import hashlib
import hmac
import re
import secrets

from . import config
from .db import now

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,20}$")
PASSWORD_MIN = 4
_ITERATIONS = 100_000


class AccountError(ValueError):
    pass


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
    return {"id": user["id"], "username": user["username"], "created_at": user["created_at"], "is_test": is_test(user)}


def ensure_test_account(db) -> None:
    """Create the TEST_USERNAME account from .env, or bring its password in line with TEST_PASSWORD."""
    if not config.TEST_USERNAME or not config.TEST_PASSWORD:
        return
    user = db.execute("SELECT * FROM users WHERE username = ?", (config.TEST_USERNAME,)).fetchone()
    if user is None:
        register(db, config.TEST_USERNAME, config.TEST_PASSWORD)
    elif not check_password(config.TEST_PASSWORD, user["password_hash"]):
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(config.TEST_PASSWORD), user["id"]))
        db.commit()


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


def register(db, username: str, password: str):
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise AccountError("Username: 3-20 letters, numbers, dots, dashes or underscores.")
    if len(password) < PASSWORD_MIN:
        raise AccountError(f"Password: at least {PASSWORD_MIN} characters.")
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        raise AccountError("That username is taken.")
    uid = db.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                     (username, hash_password(password), now())).lastrowid
    db.commit()
    return db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def authenticate(db, username: str, password: str):
    user = db.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if not user or not check_password(password, user["password_hash"]):
        raise AccountError("Wrong username or password.")
    return user


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
    return db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
                      (token,)).fetchone()


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
    """Remove an account with its answers and sessions. Its startup submissions stay, unattributed."""
    if not db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
        return False
    db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
    pids = [r["id"] for r in db.execute("SELECT id FROM players WHERE user_id = ?", (uid,))]
    for pid in pids:
        db.execute("DELETE FROM votes WHERE player_id = ?", (pid,))
        db.execute("UPDATE submissions SET player_id = NULL WHERE player_id = ?", (pid,))
    db.execute("DELETE FROM players WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()
    return True


def list_users(db) -> list[dict]:
    return [dict(r) for r in db.execute("""
        SELECT u.id, u.username, u.created_at,
               COUNT(v.id) AS answers,
               COUNT(DISTINCT v.dive_id) AS sets,
               MAX(v.created_at) AS last_played
        FROM users u
        LEFT JOIN players p ON p.user_id = u.id
        LEFT JOIN votes v ON v.player_id = p.id
        GROUP BY u.id ORDER BY u.created_at DESC, u.id DESC""")]


def guest_count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM players WHERE user_id IS NULL AND is_seed = 0").fetchone()[0]
