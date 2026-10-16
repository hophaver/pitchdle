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
CREATE TABLE IF NOT EXISTS players (
  id           INTEGER PRIMARY KEY,
  device_token TEXT UNIQUE,
  initials     TEXT,
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
  round       INTEGER,
  novel       INTEGER,
  useful      INTEGER,
  plausible   INTEGER,
  investable  INTEGER,
  stuck       INTEGER DEFAULT 0,
  points      INTEGER,
  bonus       INTEGER,
  bonus_axes  TEXT,
  is_seed     INTEGER DEFAULT 0,
  created_at  TEXT,
  UNIQUE (player_id, dive_id, company_id, round)
);
CREATE INDEX IF NOT EXISTS votes_card ON votes (dive_id, company_id, round);
CREATE TABLE IF NOT EXISTS live_state (
  id               INTEGER PRIMARY KEY CHECK (id = 1),
  dive_id          INTEGER,
  card_index       INTEGER DEFAULT -1,
  phase            TEXT DEFAULT 'idle',
  phase_started_at REAL
);
INSERT OR IGNORE INTO live_state (id, phase) VALUES (1, 'idle');
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


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
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
