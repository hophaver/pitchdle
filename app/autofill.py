"""Live-mode autofill: find real startups on open feeds and put them on the host dashboard.

Driven by the DISCOVER_* settings in .env (fields, region, depth, cap, exclusions). Found startups become
real companies that are *inactive*: the host sees them on the dashboard and activates the ones that
belong in the game. Runs in a background thread, never on a player's request path, and every failure is
recorded in the status rather than raised.
"""
import re
import sqlite3
import threading
from urllib.parse import urlsplit

from . import config, seed
from .crawler import discovery, pitch, pulse, website
from .db import connect, dumps, j, name_key, now
from .service import get_mode, get_setting, set_setting

AUTO = "discovery-auto"
PICKED = "discovery"  # a candidate the host approved by hand
_lock = threading.Lock()


def START(fn) -> None:
    """How a run is launched. Tests swap this for a direct call."""
    threading.Thread(target=fn, daemon=True, name="pitchdle-autofill").start()


# --- shared with the manual discovery endpoints -----------------------------------------------------

RAW_PER_RESULT = 2  # raw feed hits fetched per wanted result: screening drops the loose ones
OPEN = ("new", "queued")


def store_candidates(db, sector: str, country: str, limit: int, skipped: list | None = None) -> list:
    """Search the feeds for a sector and/or a country and store the hits that pass screening. Returns the rows
    this search matched (open or already approved), at most `limit`.

    Raw hits are deduped on name, then screened: exclusions first (never offered), then the AI relevance
    screen (or a text check without AI). A hit that fails is filed as dismissed with its reason, so the host
    can see it under Dismissed. A screen that can't run (an AI error, or no AI) never drops a hit: it's kept,
    marked unchecked. Names that fail go in `skipped` as {"name", "reason"}.
    """
    skipped = [] if skipped is None else skipped
    raw, seen = [], set()
    for q in discovery.queries(sector, country):
        for c in discovery.search_candidates(q, limit * RAW_PER_RESULT):
            if (key := name_key(c["name"])) not in seen:
                seen.add(key)
                raw.append(c)
    to_screen = []
    for c in raw[:limit * RAW_PER_RESULT]:
        row = upsert_candidate(db, c, sector, country)
        if hit := excluded(row):
            if row["status"] in OPEN:
                db.execute("UPDATE candidates SET status = 'dismissed' WHERE id = ?", (row["id"],))  # never offered
            note_skip(skipped, row["name"], f"excluded (matches “{hit}”)")
        elif row["status"] in OPEN or row["status"] == "approved" or rejected_by_screen(row):
            to_screen.append(row)
    db.commit()

    verdicts = screen(to_screen, sector, country)
    rows = []
    for row in to_screen:
        v = verdicts[row["id"]]
        if v["verdict"] == "rejected":
            # Only a hit this search filed is dismissed; one kept or picked before just isn't a match this time.
            if row["status"] == "new" and is_new(row):
                db.execute("UPDATE candidates SET status = 'dismissed', screen = ? WHERE id = ?", (dumps(v), row["id"]))
            elif rejected_by_screen(row):
                db.execute("UPDATE candidates SET screen = ? WHERE id = ?", (dumps(v), row["id"]))
            note_skip(skipped, row["name"], v["reason"])
            continue
        if len(rows) >= limit:
            if row["status"] == "new" and is_new(row):  # past the limit: left for the next search to find
                db.execute("DELETE FROM candidates WHERE id = ?", (row["id"],))
            continue
        status = "new" if rejected_by_screen(row) else row["status"]  # a fresh search can revive a screen reject
        db.execute("UPDATE candidates SET status = ?, screen = ?, country_tag = ? WHERE id = ?",
                   (status, dumps(v), country or row["country_tag"] or "", row["id"]))
        row = get_row(db, row["id"])
        if row["status"] in OPEN:
            hint = discovery.expand_candidate(dict(row))
            db.execute("UPDATE candidates SET engine_hint = ?, pulse = ? WHERE id = ?",
                       (dumps(hint), dumps(pulse.compute_pulse(row["name"])), row["id"]))
        rows.append(get_row(db, row["id"]))
    db.commit()
    return rows


def get_row(db, cand_id: int):
    return db.execute("SELECT * FROM candidates WHERE id = ?", (cand_id,)).fetchone()


def upsert_candidate(db, c: dict, sector: str, country: str):
    """The stored candidate for a feed hit, filed if new. A new one carries the search it was found under."""
    key = name_key(c["name"])
    row = db.execute("SELECT * FROM candidates WHERE name_key = ?", (key,)).fetchone()
    if row is None:
        cid = db.execute(
            "INSERT INTO candidates (name, name_key, url, source, snippet, sector_query, country_tag, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (c["name"], key, c["url"], c["source"], c["snippet"], sector, country, now())).lastrowid
        return get_row(db, cid)
    if not row["url"] and c["url"]:
        db.execute("UPDATE candidates SET url = ? WHERE id = ?", (c["url"], row["id"]))
    if not row["sector_query"] and sector:
        db.execute("UPDATE candidates SET sector_query = ? WHERE id = ?", (sector, row["id"]))
    return get_row(db, row["id"])


def is_new(row) -> bool:
    """Filed by this search and never looked at: no screen verdict yet."""
    return not row["screen"]


def rejected_by_screen(row) -> bool:
    """Dismissed by screening rather than by the host: a later search for another field or country may fit it."""
    return row["status"] == "dismissed" and (j(row["screen"], {}) or {}).get("verdict") == "rejected"


def note_skip(skipped: list, name: str, reason: str) -> None:
    if name not in [x["name"] for x in skipped]:
        skipped.append({"name": name, "reason": reason})


def site_text(url: str) -> tuple[str, str]:
    """(description, text) of a candidate's own site, or blanks. Cached, so discovery's later fetch is free."""
    if not url:
        return "", ""
    try:
        page = website.fetch(url)
        return page.get("description", ""), page["text"]
    except Exception:  # noqa: BLE001 - the headline alone can still be screened
        return "", ""


def screen(rows: list, sector: str, country: str) -> dict[int, dict]:
    """A verdict per candidate id: {"verdict": "kept"|"rejected"|"unchecked", "by", "kind", "reason",
    "based_in", "sector", "country"}.

    With AI: one batched OpenRouter call decides startup / on topic / based in the country, inferred from the
    headline and the site's text. If that call fails, every hit is kept as unchecked. Without AI nothing is
    rejected: a country search marks a hit kept when its headline or site names the country (or its
    demonym), unchecked when nothing does, so the host sees which ones to verify.
    """
    context = {"sector": sector, "country": country}
    if not rows:
        return {}
    sites = {r["id"]: site_text(r["url"]) for r in rows}
    if pitch.available():
        items = [{"id": r["id"], "name": r["name"], "headline": r["snippet"], "description": sites[r["id"]][0],
                  "text": sites[r["id"]][1]} for r in rows]
        try:
            found = pitch.screen(sector, country, items)
        except Exception as e:  # noqa: BLE001 - a screen that fails never drops a candidate
            found, error = {}, f"AI screening failed ({e}); not checked"
        else:
            error = "AI screening gave no verdict; not checked"
        out = {}
        for r in rows:
            v = found.get(r["id"])
            if v is None:
                out[r["id"]] = context | {"verdict": "unchecked", "by": "ai", "kind": "", "reason": error, "based_in": ""}
                continue
            kind = ("not_startup" if not v["is_startup"] else "country" if country and not v["in_country"]
                    else "off_topic" if sector and not v["on_topic"] else "")
            reason = v["reason"] or {"not_startup": "not a startup", "off_topic": f"not in {sector}",
                                     "country": f"not based in {country}"}.get(kind, "")
            if kind == "country" and v["based_in"]:
                reason = f"based in {v['based_in']}, not {country}"
            out[r["id"]] = context | {"verdict": "rejected" if kind else "kept", "by": "ai", "kind": kind,
                                      "reason": reason if kind else "", "based_in": v["based_in"]}
        return out
    out = {}
    for r in rows:
        if not country:
            out[r["id"]] = context | {"verdict": "kept", "by": "none", "kind": "", "reason": "", "based_in": ""}
            continue
        word = discovery.mentions_country(country, [r["snippet"], *sites[r["id"]]])
        out[r["id"]] = context | (
            {"verdict": "kept", "by": "text", "kind": "", "reason": "", "based_in": country} if word else
            {"verdict": "unchecked", "by": "text", "kind": "", "based_in": "",
             "reason": f"nothing in its headline or site names {country}; AI screening is off"})
    return out


def one_liner(row, hint: dict) -> str:
    """The site's own description when we fetched it, else the headline it was found under."""
    if hint.get("description"):
        return hint["description"][:200]
    headline = row["snippet"] or ""
    if row["source"] == "hackernews":
        return re.sub(r"^(?:Show|Launch) HN:\s*", "", headline, flags=re.I)[:200]
    return discovery.PUBLISHER.sub("", headline)[:200]  # news: drop the "… - TechCrunch" publisher tail


def write_card(name: str, field: str, headline: str, pulse_data: dict | None, url: str) -> dict:
    """An AI-written game card from the discovery headline, the coverage headlines and the site (if any)."""
    description = text = ""
    if url:
        try:
            page = website.fetch(url)  # usually cached from discovery
            description, text = page.get("description", ""), page["text"]
        except Exception:  # noqa: BLE001 - headlines alone still make a card
            pass
    hits = (pulse_data or {}).get("top_hits") or []
    return pitch.write_card(pitch.sources_text(name, field, headline, hits, description, text))


def card_for_candidate(row) -> dict:
    return write_card(row["name"], row["sector_query"], row["snippet"], j(row["pulse"]), row["url"] or "")


AI_OFF = "AI card writer is off (set OPENROUTER_API_KEY); write the pitch and ask by hand."


def write_candidate_card(db, row) -> dict | None:
    """Write and keep the game card for a candidate the host picked (queued or approved), so it arrives playable.

    A card written earlier is reused. On any failure, or if the AI doubts it's a startup (the host chose it,
    so it stays), the candidate keeps no card and a card_error saying it needs a manual pass. Returns the card.
    """
    if card := j(row["card"]):
        return card
    card, error = None, ""
    if not pitch.available():
        error = AI_OFF
    else:
        try:
            card = card_for_candidate(row)
        except Exception as e:  # noqa: BLE001 - the candidate stays; the host writes the card
            error = f"Card writer failed ({e}); write the pitch and ask by hand."
        if card and not card["is_startup"]:
            error, card = f"AI doubts it's a startup ({card['reject_reason']}); check it and write the card by hand.", None
    db.execute("UPDATE candidates SET card = ?, card_error = ? WHERE id = ?",
               (dumps(card) if card else None, error, row["id"]))
    db.commit()
    return card


AI_NOTE = "Card text written by AI ({model}) from headlines and website; check it before adding to the game."


AUTO_EVIDENCE_NOTE = "Auto-estimated, host confirms: tech stage \"{stage}\" ({basis})."


class Excluded(ValueError):
    """The name is on the exclusion list (a fund, publisher, or one of the event's partners)."""


def existing_company(db, name: str):
    """The real company already filed under this name, if any."""
    return db.execute("SELECT * FROM companies WHERE is_real = 1 AND name_key = ?", (name_key(name),)).fetchone()


def estimate_evidence(row, hint: dict) -> tuple[dict, str]:
    """Best-effort evidence from what discovery saw: the tech stage, if the site or a headline names one.

    Nothing else is estimated: a keyword can show "they run a pilot", not a market or team score.
    """
    if hint.get("evidence"):
        return hint["evidence"], "from its website text"
    hits = (j(row["pulse"]) or {}).get("top_hits") or []
    evidence, basis = discovery.stage_evidence(
        [("the discovery headline", row["snippet"])] + [("a coverage headline", h.get("title")) for h in hits])
    return evidence, basis


def based_in(row) -> str:
    """Where the screen placed a candidate, if it did: kept by the AI or by the text check."""
    screen = j(row["screen"], {}) or {}
    return screen.get("based_in", "") if screen.get("verdict") == "kept" else ""


def link(db, cand_id: int, cid: int) -> int:
    db.execute("UPDATE candidates SET status = 'approved', company_id = ? WHERE id = ?", (cid, cand_id))
    db.commit()
    return cid


def approve_candidate(db, row, origin: str = PICKED, card: dict | None = None) -> int:
    """A candidate becomes a real company, out of rotation until the host checks it and activates it.

    With a written card (passed in, or kept on the candidate from queueing) it reads like a demo company and its
    card_status is 'ai'; without one the headline stands in as the pitch and card_status is 'manual', so the
    host knows it needs a pass by hand.
    Idempotent: if a real company with this name exists (an earlier pass, a double click, another process),
    the candidate is linked to it and nothing new is added. Raises Excluded for names on the exclusion list.
    """
    if hit := exclusion(row["name"]):
        raise Excluded(f"{row['name']} is excluded (matches “{hit}”): funds, publishers and the event's partners "
                       "are never rated as startups.")
    if same := existing_company(db, row["name"]):
        return link(db, row["id"], same["id"])
    hint = j(row["engine_hint"], {}) or {}
    via = "Auto-found" if origin == AUTO else "Found by discovery"
    note = f"{via} ({row['source']}): {row['snippet']}"
    fields = {"emoji": "", "sector": row["sector_query"], "one_liner": one_liner(row, hint), "claim_ask": "", "facts": []}
    card = card or j(row["card"])
    written = bool(card and card.get("is_startup") and card.get("one_liner"))
    if written:
        fields = {k: card[k] or fields[k] for k in fields}
        note += " " + AI_NOTE.format(model=config.OPENROUTER_MODEL)
    evidence, basis = estimate_evidence(row, hint)
    if evidence:
        note += " " + AUTO_EVIDENCE_NOTE.format(stage=evidence["trl_stage"], basis=basis)
    try:
        cid = db.execute(
            "INSERT INTO companies (name, name_key, emoji, sector, one_liner, claim_ask, facts, website, evidence, "
            "evidence_note, evidence_status, card_status, country, is_real, active, origin, pulse, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)",
            (row["name"], name_key(row["name"]), fields["emoji"], fields["sector"], fields["one_liner"],
             fields["claim_ask"], dumps(fields["facts"]), row["url"] or "", dumps(evidence), note,
             "auto" if evidence else "pending", "ai" if written else "manual", based_in(row), origin, row["pulse"],
             now())).lastrowid
    except sqlite3.IntegrityError:  # filed by a concurrent request since the check above
        db.rollback()
        return link(db, row["id"], existing_company(db, row["name"])["id"])
    seed.score_company(db, cid)
    return link(db, row["id"], cid)


# --- autofill ---------------------------------------------------------------------------------------

def auto_count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM companies WHERE origin = ?", (AUTO,)).fetchone()[0]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _has_term(tokens: list[str], term: str) -> bool:
    """Whether the term is a whole word, or a run of whole words, of the text: "redstone" matches "Redstone",
    "Red Stone" and "Redstone Capital" but not "Redstoneware"; "a'pelago" matches "A'Pelago" and "Apelago"."""
    key = name_key(term)
    for i in range(len(tokens)):
        run = ""
        for token in tokens[i:]:
            run += token
            if run == key:
                return True
            if len(run) >= len(key):
                break
    return False


def exclusion(name: str, headline: str = "", url: str = "") -> str | None:
    """The exclusion a candidate hits, or None.

    The partners, publishers and name words are a hard stop on the name alone, so a fund or one of the
    event's partners can never become a startup whatever its headline says. The partners and publishers also
    count in the website's domain ("rs-ventures.example" no, "redstone.vc" yes). Your DISCOVER_EXCLUDE words
    also count when they're in the headline.
    """
    name_tokens = _tokens(name)
    for term in config.EXCLUDE_ALWAYS + config.DISCOVER_EXCLUDE_NAMES + config.DISCOVER_EXCLUDE:
        if _has_term(name_tokens, term):
            return term
    host_tokens = _tokens(urlsplit(url if "://" in url else f"//{url}").hostname or "") if url else []
    if hit := next((term for term in config.EXCLUDE_ALWAYS if _has_term(host_tokens, term)), None):
        return hit
    headline_tokens = _tokens(headline)
    return next((term for term in config.DISCOVER_EXCLUDE if _has_term(headline_tokens, term)), None)


def excluded(row) -> str | None:
    return exclusion(row["name"], row["snippet"], row["url"] or "")


def settings_payload() -> dict:
    return {"fields": config.DISCOVER_FIELDS, "region": config.DISCOVER_REGION, "depth": config.DISCOVER_DEPTH,
            "max": config.DISCOVER_MAX, "exclude": config.DISCOVER_EXCLUDE, "auto": config.DISCOVER_AUTO,
            "exclude_names": config.EXCLUDE_ALWAYS + config.DISCOVER_EXCLUDE_NAMES,
            "ai": {"enabled": pitch.available(), "model": config.OPENROUTER_MODEL}}


def status(db) -> dict:
    st = get_setting(db, "autofill") or {}
    return st | {"running": _lock.locked(), "found": auto_count(db)}


def run(db) -> dict:
    """One pass over every configured field, adding up to DISCOVER_DEPTH startups each, capped at DISCOVER_MAX."""
    st = {"started_at": now(), "finished_at": None, "added": [], "skipped": [], "errors": []}
    set_setting(db, "autofill", st)
    try:
        tidy(db)
        for field in config.DISCOVER_FIELDS:
            if auto_count(db) >= config.DISCOVER_MAX:
                break
            try:
                rows = store_candidates(db, field, config.DISCOVER_REGION, config.DISCOVER_DEPTH, st["skipped"])
            except Exception as e:  # noqa: BLE001 - one failing field never stops the rest
                st["errors"].append(f"{field}: {e}")
                continue
            for row in rows:
                if auto_count(db) >= config.DISCOVER_MAX:
                    break
                if row["status"] not in OPEN:
                    continue
                if same := existing_company(db, row["name"]):  # already filed, maybe under another candidate
                    link(db, row["id"], same["id"])
                    continue
                card = None
                if pitch.available():
                    try:
                        card = card_for_candidate(row)
                    except Exception as e:  # noqa: BLE001 - keep the startup, with the headline as its pitch
                        st["errors"].append(f"{row['name']}: card writer: {e}")
                if card and not card["is_startup"]:
                    # Funds, publishers and misparsed headlines: set aside, visible under dismissed candidates.
                    db.execute("UPDATE candidates SET status = 'dismissed' WHERE id = ?", (row["id"],))
                    db.commit()
                    note_skip(st["skipped"], row["name"], card["reject_reason"])
                    continue
                approve_candidate(db, row, origin=AUTO, card=card)
                st["added"].append(row["name"])
    except Exception as e:  # noqa: BLE001
        st["errors"].append(str(e))
    st["finished_at"] = now()
    set_setting(db, "autofill", st)
    return st


def tidy(db) -> dict:
    """Repair what discovery filed before these checks existed. Safe to run any time; changes nothing twice.

    - Startups discovery filed under an excluded name (a fund, a publisher, the event's partners) are removed,
      with their answers, and their candidate is dismissed. Hand-made companies are never touched.
    - Discovery-filed companies get their origin and an evidence review status, and a tech stage estimated
      from their stored headlines when nothing was estimated before.
    Duplicate names are merged by db.init_db.
    """
    out = {"removed": [], "flagged": []}
    for cand in db.execute("SELECT * FROM candidates WHERE status IN ('new', 'queued')").fetchall():
        if excluded(cand):
            db.execute("UPDATE candidates SET status = 'dismissed' WHERE id = ?", (cand["id"],))
    found = db.execute(
        "SELECT c.*, k.id AS cand_id, k.snippet, k.source, k.engine_hint, k.pulse AS cand_pulse "
        "FROM companies c JOIN candidates k ON k.company_id = c.id WHERE c.is_real = 1").fetchall()
    for comp in found:
        if exclusion(comp["name"]):
            db.execute("DELETE FROM companies WHERE id = ?", (comp["id"],))
            db.execute("UPDATE candidates SET status = 'dismissed', company_id = NULL WHERE id = ?", (comp["cand_id"],))
            out["removed"].append(comp["name"])
            continue
        if not comp["origin"]:
            db.execute("UPDATE companies SET origin = ? WHERE id = ?", (PICKED, comp["id"]))
        if comp["evidence_status"]:
            continue
        hint = j(comp["engine_hint"], {}) or {}
        evidence = j(comp["evidence"], {}) or {}
        if evidence and evidence != hint.get("evidence"):
            db.execute("UPDATE companies SET evidence_status = 'confirmed' WHERE id = ?", (comp["id"],))  # host-edited
            continue
        note = comp["evidence_note"] or ""
        if not evidence:
            evidence, basis = estimate_evidence({"snippet": comp["snippet"], "pulse": comp["pulse"] or comp["cand_pulse"]}, {})
            if evidence:
                note = f"{note} {AUTO_EVIDENCE_NOTE.format(stage=evidence['trl_stage'], basis=basis)}".strip()
        db.execute("UPDATE companies SET evidence = ?, evidence_note = ?, evidence_status = ? WHERE id = ?",
                   (dumps(evidence), note, "auto" if evidence else "pending", comp["id"]))
        seed.score_company(db, comp["id"])
        out["flagged"].append(comp["name"])
    db.commit()
    return out


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
