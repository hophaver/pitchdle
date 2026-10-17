"""Every card gets its AI ratings (and a real startup its social media read) by itself: when it's added, and on
startup for cards from before. The reads are faked here; tests/test_reads.py covers the real calls."""
import pytest

from app import autoread, config, opinions, reads
from app.crawler import gate, profile
from app.db import connect
from tests.conftest import new_player, sign_up
from tests.test_api import GUESS, today

AI_READ = {"scores": {**GUESS, "novel": 4.0}, "note": "Solid.", "meta": {"model": "test"}}
QUIET = {"scores": None, "note": "", "meta": {"posts": 0, "links": [], "via": "test", "model": "test"}}
REAL = {"name": "Kelp Co", "sector": "seaweed", "one_liner": "Seaweed packaging.", "claim_ask": "€1M", "is_real": True,
        "active": True}


@pytest.fixture
def calls(client, monkeypatch):
    """Keys set, runs made synchronous, and every read faked and recorded as (company, sources)."""
    made = []
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(autoread, "START", lambda fn: fn())

    def rate_all(comp, only=None, brief=None):
        made.append((comp["name"], "ai", tuple(only)))
        return {key: AI_READ for key in only}

    def social_all(comp, only=None):
        made.append((comp["name"], "social", tuple(only)))
        return {p: (AI_READ if p == "x" else QUIET) for p in only}

    def fill_profile(db, comp):  # tests/test_profile.py covers the real one
        db.execute("UPDATE companies SET profile_status = 'ai' WHERE id = ?", (comp["id"],))
        db.commit()

    def check(db, comp):  # and tests/test_gate.py the game check
        db.execute("UPDATE companies SET game_status = 'in', active = 1 WHERE id = ?", (comp["id"],))
        db.commit()

    monkeypatch.setattr(reads, "rate_all", rate_all)
    monkeypatch.setattr(reads, "social_all", social_all)
    monkeypatch.setattr(profile, "fill", fill_profile)
    monkeypatch.setattr(gate, "check", check)
    return made


def test_cards_from_before_get_their_ai_ratings(client, admin, calls):
    assert autoread.kick() is True  # what startup does
    sample = [name for name, kind, _ in calls]
    assert len(sample) == 12 and {kind for _, kind, _ in calls} == {"ai"}  # made-up startups: no social search
    assert all(only == ("claude", "gpt", "grok") for _, _, only in calls)
    investor = new_player(client)
    sign_up(investor)
    card = today(investor)["cards"][0]
    assert [t["key"] for t in card["opinions"]] == ["claude", "gpt", "grok"]
    st = client.get("/api/admin/mode", auth=admin).json()["reads"]["auto"]
    assert len(st["read"]) == 12 and st["finished_at"] and st["running"] is False
    calls.clear()
    autoread.kick()
    assert calls == []  # nothing missing, nothing asked again


def test_a_new_card_is_read_when_its_added(client, admin, calls):
    autoread.kick()
    calls.clear()
    comp = client.post("/api/admin/companies", json=REAL, auth=admin).json()
    assert calls == [("Kelp Co", "ai", ("claude", "gpt", "grok")),
                     ("Kelp Co", "social", ("x", "threads", "linkedin", "reddit", "bluesky"))]
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)  # a real startup plays in live mode
    dive = client.post("/api/admin/dives", json={"label": "one", "company_ids": [comp["id"]]}, auth=admin).json()
    investor = new_player(client)
    sign_up(investor)
    card = investor.get(f"/api/dive/{dive['id']}").json()["cards"][0]
    assert [t["key"] for t in card["opinions"]] == ["claude", "gpt", "grok", "x"]
    assert card["quiet"] == ["Threads", "LinkedIn", "Reddit", "Bluesky"]  # searched, nothing found


def test_failures_wait_for_the_next_run_and_reads_already_there_count(client, admin, calls, monkeypatch):
    autoread.kick()
    comp = client.post("/api/admin/companies", json=REAL, auth=admin).json()
    cid = comp["id"]
    db = connect()
    opinions.remove(db, cid, "gpt")
    opinions.remove(db, cid, "grok")
    opinions.save(db, cid, "grok", {**GUESS, "novel": 1.0}, "Read before.", {"by": "fetched"})
    db.close()
    monkeypatch.setattr(reads, "rate_all", lambda comp, only=None, brief=None: {key: {"error": "APIError: down"} for key in only})
    calls.clear()
    client.post("/api/admin/autoread", auth=admin)
    st = client.get("/api/admin/mode", auth=admin).json()["reads"]["auto"]
    assert st["errors"] == ["Kelp Co, GPT: APIError: down"]  # only GPT was missing: grok was already read
    kelp = next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["id"] == cid)
    assert "gpt" not in kelp["opinions"] and kelp["opinions"]["grok"]["note"] == "Read before."


def test_nothing_runs_without_a_key(client, admin, monkeypatch):
    monkeypatch.setattr(autoread, "START", lambda fn: pytest.fail("no run without a key"))
    assert autoread.kick() is False
    assert client.post("/api/admin/autoread", auth=admin).json()["started"] is False
