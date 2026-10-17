"""Live-mode autofill: find real startups on open feeds and put them on the host dashboard.

Driven by the DISCOVER_* settings in .env (fields, region, depth, cap, exclusions). Found startups become
real companies that are *inactive*: the host sees them on the dashboard and activates the ones that
belong in the game. Runs in a background thread, never on a player's request path, and every failure is
recorded in the status rather than raised.
"""
import re
import threading

from . import autoread, config, seed
from .crawler import discovery, pulse
from .db import connect, dumps, j, now
from .service import get_mode, get_setting, set_setting

AUTO = "discovery-auto"
_lock = threading.Lock()


def START(fn) -> None:
    """How a run is launched. Tests swap this for a direct call."""
    threading.Thread(target=fn, daemon=True, name="pitchdle-autofill").start()


# --- shared with the manual discovery endpoints -----------------------------------------------------

def store_candidates(db, sector: str, country: str, limit: int) -> list:
    """Search the feeds, store new candidates (deduped on name), refresh hints for open ones. Returns rows."""
    query = f"{sector} {country}".strip()
    rows = []
    for c in discovery.search_candidates(query, limit):
        key = discovery.name_key(c["name"])
        row = db.execute("SELECT * FROM candidates WHERE name_key = ?", (key,)).fetchone()
        if row is None:
            cid = db.execute(
                "INSERT INTO candidates (name, name_key, url, source, snippet, sector_query, country_tag, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (c["name"], key, c["url"], c["source"], c["snippet"], sector, country, now())).lastrowid
        else:
            cid = row["id"]
            if not row["url"] and c["url"]:
                db.execute("UPDATE candidates SET url = ? WHERE id = ?", (c["url"], cid))
        row = db.execute("SELECT * FROM candidates WHERE id = ?", (cid,)).fetchone()
        if row["status"] in ("new", "queued"):
            hint = discovery.expand_candidate(dict(row))
            db.execute("UPDATE candidates SET engine_hint = ?, pulse = ? WHERE id = ?",
                       (dumps(hint), dumps(pulse.compute_pulse(row["name"])), cid))
        db.commit()
        rows.append(db.execute("SELECT * FROM candidates WHERE id = ?", (cid,)).fetchone())
    return rows


def one_liner(row, hint: dict) -> str:
    """The site's own description when we fetched it, else the headline it was found under."""
    if hint.get("description"):
        return hint["description"][:200]
    headline = row["snippet"] or ""
    if row["source"] == "hackernews":
        return re.sub(r"^(?:Show|Launch) HN:\s*", "", headline, flags=re.I)[:200]
    return discovery.PUBLISHER.sub("", headline)[:200]  # news: drop the "… - TechCrunch" publisher tail


def approve_candidate(db, row, origin: str = "") -> int:
    """A candidate becomes a real company, out of rotation until the host checks it and activates it."""
    hint = j(row["engine_hint"], {}) or {}
    via = "Auto-found" if origin == AUTO else "Auto-estimate from discovery"
    cid = db.execute(
        "INSERT INTO companies (name, sector, one_liner, website, evidence, evidence_note, is_real, active, origin, "
        "pulse, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)",
        (row["name"], row["sector_query"], one_liner(row, hint), row["url"] or "", dumps(hint.get("evidence", {})),
         f"{via} ({row['source']}): {row['snippet']}", origin, row["pulse"], now())).lastrowid
    seed.score_company(db, cid)
    db.execute("UPDATE candidates SET status = 'approved', company_id = ? WHERE id = ?", (cid, row["id"]))
    db.commit()
    autoread.kick()  # its AI ratings and social media read
    return cid


# --- autofill ---------------------------------------------------------------------------------------

def auto_count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM companies WHERE origin = ?", (AUTO,)).fetchone()[0]


def excluded(row) -> bool:
    text = f"{row['name']} {row['snippet']}".lower()
    return any(word in text for word in config.DISCOVER_EXCLUDE)


def settings_payload() -> dict:
    return {"fields": config.DISCOVER_FIELDS, "region": config.DISCOVER_REGION, "depth": config.DISCOVER_DEPTH,
            "max": config.DISCOVER_MAX, "exclude": config.DISCOVER_EXCLUDE, "auto": config.DISCOVER_AUTO}


def status(db) -> dict:
    st = get_setting(db, "autofill") or {}
    return st | {"running": _lock.locked(), "found": auto_count(db)}


def run(db) -> dict:
    """One pass over every configured field, adding up to DISCOVER_DEPTH startups each, capped at DISCOVER_MAX."""
    st = {"started_at": now(), "finished_at": None, "added": [], "errors": []}
    set_setting(db, "autofill", st)
    try:
        for field in config.DISCOVER_FIELDS:
            if auto_count(db) >= config.DISCOVER_MAX:
                break
            try:
                rows = store_candidates(db, field, config.DISCOVER_REGION, config.DISCOVER_DEPTH)
            except Exception as e:  # noqa: BLE001 - one failing field never stops the rest
                st["errors"].append(f"{field}: {e}")
                continue
            for row in rows:
                if auto_count(db) >= config.DISCOVER_MAX:
                    break
                if row["status"] not in ("new", "queued") or excluded(row):
                    continue
                key = discovery.name_key(row["name"])
                if any(discovery.name_key(r["name"]) == key for r in db.execute("SELECT name FROM companies")):
                    continue
                approve_candidate(db, row, origin=AUTO)
                st["added"].append(row["name"])
    except Exception as e:  # noqa: BLE001
        st["errors"].append(str(e))
    st["finished_at"] = now()
    set_setting(db, "autofill", st)
    return st


def maybe_start(db, force: bool = False) -> str:
    """Start a background run if live mode wants one. Returns why it did or didn't start."""
    if get_mode(db) != "live":
        return "not-live"
    if not force and not config.DISCOVER_AUTO:
        return "auto-off"
    if auto_count(db) >= config.DISCOVER_MAX:
        return "cap-reached"
    if not _lock.acquire(blocking=False):
        return "running"

    def work():
        conn = connect()
        try:
            run(conn)
        finally:
            conn.close()
            _lock.release()

    try:
        START(work)
    except Exception:  # noqa: BLE001
        _lock.release()
        raise
    return "started"
