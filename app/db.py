"""SQLite access: one connection per request, schema created on startup."""
import json
import re
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
    ("companies", "origin", "TEXT DEFAULT ''"),  # 'discovery-auto' (autofill) or 'discovery' (host-approved candidate)
    ("companies", "name_key", "TEXT DEFAULT ''"),  # name_key(name): one real company per name
    # Who stands behind the evidence: '' or 'confirmed' = the host; 'auto' = estimated from the crawl, host to
    # confirm; 'pending' = found by discovery with nothing estimable yet, awaiting the host's review.
    ("companies", "evidence_status", "TEXT DEFAULT ''"),
    # Who wrote the game card: '' = the host (or seed data); 'ai' = written by the card writer, host to check;
    # 'manual' = discovery filed it with only its headline as the pitch, so it needs a pass by hand.
    ("companies", "card_status", "TEXT DEFAULT ''"),
    ("companies", "country", "TEXT DEFAULT ''"),  # where it's based, from discovery's screen when known
    ("candidates", "screen", "TEXT"),       # the relevance screen's verdict for the last search that saw it
    ("candidates", "card", "TEXT"),         # the AI-written card, kept from the moment the host queues it
    ("candidates", "card_error", "TEXT DEFAULT ''"),  # why there's no card: needs a manual pass
]


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, definition in MIGRATIONS:
        if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.execute("CREATE INDEX IF NOT EXISTS players_user ON players (user_id)")
    for row in conn.execute("SELECT id, name FROM companies WHERE name_key IS NULL OR name_key = ''").fetchall():
        conn.execute("UPDATE companies SET name_key = ? WHERE id = ?", (name_key(row["name"]), row["id"]))
    merge_duplicate_companies(conn)
    # Two real companies can't share a name (sample companies are a separate pool and aren't covered).
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS companies_real_name ON companies (name_key) "
                 "WHERE is_real = 1 AND name_key != ''")
    conn.commit()


def merge_duplicate_companies(conn: sqlite3.Connection) -> list[str]:
    """Fold real companies that share a name into one. Earlier builds could add the same startup several times.

    Keeps the active one, then the one with most answers, then the oldest, and moves the others' answers,
    opportunities, candidate links and set places onto it. Returns the merged names.
    """
    merged = []
    for group in conn.execute("SELECT name_key FROM companies WHERE is_real = 1 AND name_key != '' "
                              "GROUP BY name_key HAVING COUNT(*) > 1").fetchall():
        rows = conn.execute(
            "SELECT c.id, c.name FROM companies c WHERE c.is_real = 1 AND c.name_key = ? ORDER BY c.active DESC, "
            "(SELECT COUNT(*) FROM votes v WHERE v.company_id = c.id) DESC, c.id", (group["name_key"],)).fetchall()
        keep, dups = rows[0]["id"], [r["id"] for r in rows[1:]]
        for dup in dups:
            conn.execute("UPDATE OR IGNORE votes SET company_id = ? WHERE company_id = ?", (keep, dup))
            if conn.execute("SELECT 1 FROM opportunities WHERE company_id = ?", (keep,)).fetchone() is None:
                conn.execute("UPDATE opportunities SET company_id = ? WHERE company_id = ?", (keep, dup))
            conn.execute("UPDATE candidates SET company_id = ? WHERE company_id = ?", (keep, dup))
        for dive in conn.execute("SELECT id, company_ids FROM dives").fetchall():
            ids = j(dive["company_ids"], [])
            folded = list(dict.fromkeys(keep if i in dups else i for i in ids))
            if folded != ids:
                conn.execute("UPDATE dives SET company_ids = ? WHERE id = ?", (dumps(folded), dive["id"]))
        conn.execute(f"DELETE FROM companies WHERE id IN ({','.join('?' * len(dups))})", dups)  # their leftovers cascade
        merged.append(rows[0]["name"])
    conn.commit()
    return merged


def name_key(name: str) -> str:
    """A company name reduced to lowercase letters and digits, so "Granarium" and "granarium." match."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def j(value, default=None):
    """Decode a JSON text column."""
    if value is None or value == "":
        return default
    return json.loads(value)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
