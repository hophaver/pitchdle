"""Data quality of what discovery files: no duplicate companies, no funds or partners as startups, and an honest,
legible evidence state for every auto-found startup. Every feed is mocked and runs are synchronous."""
import sqlite3

import pytest

from app import autofill, config
from app.crawler import discovery, pulse
from app.db import connect, dumps, init_db, now

HEADLINES = {
    "ocean": ["Finnish startup Granarium raises EUR 1m from a seed fund for renewable supercapacitors - Arctic News"],
    "aquaculture": ["Finnish startup Granarium raises EUR 1m from a seed fund for renewable supercapacitors - Arctic News",
                    "Redstone raises €25m blue economy fund for ocean tech - Enlit World",
                    "Blue Ocean Capital raises $40M for its second fund - Fin News"],
}


@pytest.fixture(autouse=True)
def offline(client, monkeypatch):
    def google(q, limit):
        return [{"title": t, "link": ""} for t in HEADLINES.get(q.split()[0], [])]
    monkeypatch.setattr(discovery, "FEEDS", {"news.google": google})
    monkeypatch.setattr(pulse, "FEEDS", {"news.google": lambda n, l: []})
    monkeypatch.setattr(autofill, "START", lambda fn: fn())
    monkeypatch.setattr(config, "DISCOVER_FIELDS", ["ocean", "aquaculture"])
    monkeypatch.setattr(config, "DISCOVER_REGION", "")
    monkeypatch.setattr(config, "DISCOVER_DEPTH", 5)
    monkeypatch.setattr(config, "DISCOVER_MAX", 10)
    monkeypatch.setattr(config, "DISCOVER_EXCLUDE", [])
    monkeypatch.setattr(config, "DISCOVER_AUTO", True)


@pytest.fixture
def credulous_ai(monkeypatch):
    """An AI screener that calls everything a startup: the exclusions must hold without it."""
    from app.crawler import pitch
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(pitch, "complete", lambda messages: {
        "is_startup": True, "reject_reason": "", "emoji": "⚡", "sector": "energy", "one_liner": "Batteries made of sand.",
        "claim_ask": "€1m to build a pilot line", "facts": []})


def live(client, admin):
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)


def companies(client, admin) -> list[dict]:
    return client.get("/api/admin/companies", auth=admin).json()


def names(client, admin) -> list[str]:
    return sorted(c["name"] for c in companies(client, admin) if c["is_real"])


# --- duplicates ------------------------------------------------------------------------------------

def test_autofill_twice_on_the_same_headline_adds_one_company(client, admin):
    live(client, admin)  # first pass; Granarium is found under both fields
    client.post("/api/admin/autofill", auth=admin)
    client.post("/api/admin/autofill", auth=admin)
    assert names(client, admin) == ["Granarium"]


def test_approving_the_same_candidate_again_files_nothing_new(client, admin):
    """Two requests holding the same not-yet-approved row (a double click during the slow AI call)."""
    cand = client.post("/api/admin/discover/search", json={"sector": "ocean"}, auth=admin).json()[0]
    db = connect()
    row = db.execute("SELECT * FROM candidates WHERE id = ?", (cand["id"],)).fetchone()  # stale: status 'new'
    first, second = autofill.approve_candidate(db, row), autofill.approve_candidate(db, row)
    db.close()
    assert first == second and names(client, admin) == ["Granarium"]


def test_a_second_real_company_with_the_same_name_is_refused(client, admin):
    body = {"name": "Granarium", "is_real": True, "active": False}
    assert client.post("/api/admin/companies", json=body, auth=admin).status_code == 200
    out = client.post("/api/admin/companies", json=body | {"name": "granarium."}, auth=admin)
    assert out.status_code == 409 and "already" in out.json()["detail"]
    # A sample company may share a real one's name: they're separate pools.
    assert client.post("/api/admin/companies", json=body | {"is_real": False}, auth=admin).status_code == 200


def test_existing_duplicates_are_merged_on_startup(client, admin):
    db = connect()
    db.execute("DROP INDEX companies_real_name")  # the state an older build left behind
    ids = [db.execute("INSERT INTO companies (name, name_key, is_real, active, created_at) VALUES "
                      "('Granarium', 'granarium', 1, ?, ?)", (active, now())).lastrowid for active in (0, 1, 0)]
    db.execute("INSERT INTO candidates (name, name_key, status, company_id) VALUES ('Granarium', 'granarium', "
               "'approved', ?)", (ids[2],))
    dive = db.execute("INSERT INTO dives (label, company_ids, mode, pool) VALUES ('Live', ?, 'live', 'live')",
                      (dumps([ids[0], ids[2], 1]),)).lastrowid
    db.commit()

    init_db(db)
    kept = [r["id"] for r in db.execute("SELECT id FROM companies WHERE name_key = 'granarium'")]
    assert kept == [ids[1]]  # the active one survives
    assert db.execute("SELECT company_id FROM candidates").fetchone()[0] == ids[1]
    assert db.execute("SELECT company_ids FROM dives WHERE id = ?", (dive,)).fetchone()[0] == dumps([ids[1], 1])
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO companies (name, name_key, is_real) VALUES ('Granarium', 'granarium', 1)")
    init_db(db)  # idempotent
    db.close()


# --- exclusions ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, hit", [
    ("Redstone", "redstone"), ("Red Stone", "redstone"), ("Redstone Ventures", "redstone"),
    ("A'Pelago", "a'pelago"), ("Apelago Accelerator", "a'pelago"),
    ("Blue Ocean Capital", "capital"), ("Ocean News", "news"), ("Marine Laboratory", "laboratory"),
    ("TechCrunch", "techcrunch"),
])
def test_funds_publishers_and_partners_are_excluded_by_name(name, hit):
    assert autofill.exclusion(name) == hit


@pytest.mark.parametrize("name", ["Granarium", "Fundbox", "Newsly", "Capitalwave", "Redstoneware", "Quartermaster"])
def test_exclusions_match_whole_words_not_substrings(name):
    assert autofill.exclusion(name) is None


def test_name_words_never_match_the_headline(monkeypatch):
    # "fund" and "news" are in Granarium's headline; only DISCOVER_EXCLUDE words count there.
    assert autofill.exclusion("Granarium", HEADLINES["ocean"][0]) is None
    monkeypatch.setattr(config, "DISCOVER_EXCLUDE", ["supercapacitors"])
    assert autofill.exclusion("Granarium", HEADLINES["ocean"][0]) == "supercapacitors"


def test_redstone_never_becomes_a_startup_even_when_the_ai_says_it_is(client, admin, credulous_ai):
    live(client, admin)
    assert names(client, admin) == ["Granarium"]
    st = client.get("/api/admin/mode", auth=admin).json()
    skipped = {s["name"]: s["reason"] for s in st["autofill"]["skipped"]}
    assert "redstone" in skipped["Redstone"] and "capital" in skipped["Blue Ocean Capital"]
    assert {"redstone", "a'pelago"} <= set(st["discover"]["exclude_names"])

    # Never offered to the host either, and approving it by hand is refused.
    assert "Redstone" not in [c["name"] for c in client.get("/api/admin/discover", auth=admin).json()]
    red = next(c for c in client.get("/api/admin/discover?status=dismissed", auth=admin).json() if c["name"] == "Redstone")
    out = client.post(f"/api/admin/discover/{red['id']}/approve", auth=admin)
    assert out.status_code == 409 and "excluded" in out.json()["detail"]
    assert names(client, admin) == ["Granarium"]


def test_startup_removes_excluded_names_discovery_filed_earlier(client, admin):
    db = connect()
    cid = db.execute("INSERT INTO companies (name, name_key, is_real, active, origin, created_at) VALUES "
                     "('Redstone', 'redstone', 1, 1, 'discovery-auto', ?)", (now(),)).lastrowid
    db.execute("INSERT INTO candidates (name, name_key, status, company_id, snippet) VALUES "
               "('Redstone', 'redstone', 'approved', ?, 'Redstone raises €25m fund')", (cid,))
    # A company the host made by hand is theirs to keep, whatever its name.
    db.execute("INSERT INTO companies (name, name_key, is_real, active, created_at) VALUES "
               "('Harbour Capital', 'harbourcapital', 1, 0, ?)", (now(),))
    db.commit()
    assert autofill.tidy(db)["removed"] == ["Redstone"]
    assert db.execute("SELECT status, company_id FROM candidates").fetchone()[:] == ("dismissed", None)
    assert autofill.tidy(db)["removed"] == []
    db.close()
    assert names(client, admin) == ["Harbour Capital"]


# --- evidence and its review state -----------------------------------------------------------------

def insight(client, admin, name: str) -> dict:
    data = client.get("/api/host/overview", auth=admin).json()
    return next(c for c in data["companies"] if c["name"] == name)


def test_auto_found_startup_with_nothing_to_score_is_labelled_not_blank(client, admin):
    live(client, admin)
    c = insight(client, admin, "Granarium")
    assert c["origin"] == "discovery-auto"
    assert c["review"] == {"status": "pending", "pending": True, "label": "Awaiting host evidence review",
                           "detail": c["review"]["detail"]} and "not yet evidence-backed" in c["review"]["detail"]
    # Unknown stays unknown: no invented numbers.
    assert all(level["score"] is None for level in c["readiness"].values())
    assert all(t["score"] is None for t in c["theses"].values())


def test_a_stage_the_sources_state_is_estimated_and_labelled(client, admin, monkeypatch):
    monkeypatch.setitem(HEADLINES, "ocean", ["Seaweed startup Kelpco raises €2M after a pilot with Baltic fish farms"])
    live(client, admin)
    kelp = next(c for c in companies(client, admin) if c["name"] == "Kelpco")
    assert kelp["evidence"] == {"trl_stage": "pilot"} and kelp["evidence_status"] == "auto"
    assert 'Auto-estimated, host confirms: tech stage "pilot"' in kelp["evidence_note"]
    c = insight(client, admin, "Kelpco")
    assert c["review"]["status"] == "auto" and c["review"]["pending"]
    assert c["readiness"]["tech"]["trl"] == 6 and c["theses"]["apelago"]["score"] is not None
    assert c["readiness"]["business"]["score"] is None  # only the stage is estimated


def test_only_the_editor_save_confirms_evidence(client, admin):
    live(client, admin)
    comp = next(c for c in companies(client, admin) if c["name"] == "Granarium")
    body = {k: comp[k] for k in ("name", "sector", "one_liner", "claim_ask", "website", "evidence", "evidence_note")}
    # Ticking Active (a quick toggle) doesn't count as reviewing the evidence...
    client.put(f"/api/admin/companies/{comp['id']}", json=body | {"is_real": True, "active": True}, auth=admin)
    assert insight(client, admin, "Granarium")["review"]["pending"]
    # ...the editor's "Save and score" does.
    client.put(f"/api/admin/companies/{comp['id']}", auth=admin, json=body | {
        "is_real": True, "active": True, "evidence": {"trl_stage": "prototype"}, "evidence_reviewed": True})
    c = insight(client, admin, "Granarium")
    assert c["review"]["status"] == "confirmed" and not c["review"]["pending"] and c["readiness"]["tech"]["trl"] == 5


def test_older_discovery_rows_get_a_review_state_on_startup(client, admin):
    db = connect()
    cid = db.execute("INSERT INTO companies (name, name_key, is_real, active, evidence, created_at) VALUES "
                     "('Oceanloop', 'oceanloop', 1, 0, '{}', ?)", (now(),)).lastrowid
    db.execute("INSERT INTO candidates (name, name_key, status, company_id, snippet) VALUES ('Oceanloop', 'oceanloop', "
               "'approved', ?, 'Oceanloop nets €38.5M to scale its land-based shrimp farms, now deployed in Germany')", (cid,))
    db.commit()
    assert autofill.tidy(db)["flagged"] == ["Oceanloop"]
    assert autofill.tidy(db)["flagged"] == []
    db.close()
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)
    c = insight(client, admin, "Oceanloop")
    assert c["origin"] == "discovery" and c["review"]["status"] == "auto" and c["readiness"]["tech"]["trl"] == 8


def test_sample_and_hand_made_companies_count_as_reviewed(client, admin):
    data = client.get("/api/host/overview", auth=admin).json()
    assert data["companies"] and not any(c["review"]["pending"] for c in data["companies"])
    row = next(r for r in client.get("/api/admin/export.csv", auth=admin).text.splitlines()[:1])
    assert "evidence_review" in row and "origin" in row
