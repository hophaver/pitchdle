"""SQLite access: one connection per request, schema created on startup."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id               INTEGER PRIMARY KEY,
  name             TEXT NOT NULL,
  emoji            TEXT DEFAULT '',
  sector           TEXT DEFAULT '',
  one_liner        TEXT DEFAULT '',
  claim_ask        TEXT DEFAULT '',
  website          TEXT DEFAULT '',
  facts            TEXT DEFAULT '[]',
  evidence         TEXT DEFAULT '{}',
  evidence_note    TEXT DEFAULT '',
  engine_axes      TEXT,
  engine_composite REAL,
  engine_coverage  TEXT,
  scored_at        TEXT,
  crawl            TEXT,
  is_real          INTEGER DEFAULT 0,
  active           INTEGER DEFAULT 1,
  created_at       TEXT
);
CREATE TABLE IF NOT EXISTS opportunities (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER REFERENCES companies(id) ON DELETE CASCADE,
  kind        TEXT,
  name        TEXT,
  why         TEXT,
  fit         REAL DEFAULT 0.5,
  stage_fit   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS dives (
  id          INTEGER PRIMARY KEY,
  label       TEXT,
  date        TEXT,
  company_ids TEXT,
  mode        TEXT DEFAULT 'daily',
  created_at  TEXT
);
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  created_at    TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token       TEXT PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  TEXT
);
-- A guest is a device (device_token, user_id NULL). A signed-in player has one row of their own
-- (user_id set, no device token), and a guest's answers move onto it when they log in.
CREATE TABLE IF NOT EXISTS players (
  id           INTEGER PRIMARY KEY,
  device_token TEXT UNIQUE,
  user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
  handle       TEXT,
  is_seed      INTEGER DEFAULT 0,
  last_seen    REAL,
  created_at   TEXT
);
CREATE TABLE IF NOT EXISTS votes (
  id          INTEGER PRIMARY KEY,
  player_id   INTEGER REFERENCES players(id) ON DELETE CASCADE,
  dive_id     INTEGER REFERENCES dives(id) ON DELETE CASCADE,
  company_id  INTEGER REFERENCES companies(id) ON DELETE CASCADE,
  round       INTEGER DEFAULT 1,  -- always 1 now; kept so older databases still load
  novel       INTEGER,
  useful      INTEGER,
  plausible   INTEGER,
  investable  INTEGER,
  is_seed     INTEGER DEFAULT 0,
  created_at  TEXT,
  UNIQUE (player_id, dive_id, company_id, round)
);
CREATE INDEX IF NOT EXISTS votes_card ON votes (dive_id, company_id, round);
CREATE TABLE IF NOT EXISTS submissions (
  id          INTEGER PRIMARY KEY,
  player_id   INTEGER REFERENCES players(id) ON DELETE SET NULL,
  name        TEXT,
  sector      TEXT,
  one_liner   TEXT,
  claim_ask   TEXT,
  website     TEXT,
  created_at  TEXT
);
CREATE TABLE IF NOT EXISTS live_state (
  id               INTEGER PRIMARY KEY CHECK (id = 1),
  dive_id          INTEGER,
  card_index       INTEGER DEFAULT -1,
  phase            TEXT DEFAULT 'idle',
  phase_started_at REAL
);
INSERT OR IGNORE INTO live_state (id, phase) VALUES (1, 'idle');
-- Startups found on the open web, waiting for the host. Kept apart from companies until approved.
CREATE TABLE IF NOT EXISTS candidates (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  name_key      TEXT NOT NULL UNIQUE,
  url           TEXT DEFAULT '',
  source        TEXT,
  snippet       TEXT DEFAULT '',
  sector_query  TEXT DEFAULT '',
  country_tag   TEXT DEFAULT '',
  engine_hint   TEXT,
  pulse         TEXT,
  status        TEXT DEFAULT 'new',  -- new | queued | approved | dismissed
  company_id    INTEGER REFERENCES companies(id) ON DELETE SET NULL,
  created_at    TEXT
);
-- Small key/value store for runtime switches: the demo/live mode and the autofill status.
CREATE TABLE IF NOT EXISTS settings (
  key    TEXT PRIMARY KEY,
  value  TEXT
);
"""


def connect() -> sqlite3.Connection:
    path = Path(config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    """FastAPI dependency. Write endpoints commit explicitly."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


# Columns added after the first release: (table, column, definition).
MIGRATIONS = [
    ("companies", "emoji", "TEXT DEFAULT ''"),
    ("players", "user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE"),
    ("companies", "pulse", "TEXT"),
    ("dives", "pool", "TEXT DEFAULT 'demo'"),
    ("companies", "origin", "TEXT DEFAULT ''"),  # 'discovery-auto' for startups the live-mode autofill found  # which companies a set draws on: demo (sample) or live (real)
    # Sign-up review. Accounts from before it count as approved; new sign-ups are inserted as 'pending'.
    ("users", "status", "TEXT DEFAULT 'approved'"),  # pending | approved | rejected
    ("users", "profile", "TEXT DEFAULT '{}'"),  # what they told moderators when signing up
    ("users", "reviewed_by", "TEXT"),
    ("users", "reviewed_at", "TEXT"),
    ("users", "badge", "TEXT DEFAULT ''"),  # '' | high | low | muted: how much their answers count
    ("users", "badge_by", "TEXT"),
    ("users", "badge_at", "TEXT"),
    ("users", "is_moderator", "INTEGER DEFAULT 0"),  # set by an admin on /moderate
]


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, definition in MIGRATIONS:
        if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.execute("CREATE INDEX IF NOT EXISTS players_user ON players (user_id)")
    conn.commit()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def j(value, default=None):
    """Decode a JSON text column."""
    if value is None or value == "":
        return default
    return json.loads(value)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
