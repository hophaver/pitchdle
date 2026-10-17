"""Demo/live toggle and live-mode autofill, with every feed mocked and runs made synchronous."""
import pytest

from app import autofill, config
from app.crawler import discovery, pulse
from tests.conftest import new_player

HEADLINES = {
    "ocean": ["Show HN: Kelpco – seaweed packaging", "Show HN: Tidewise – buoy sensors", "Show HN: Spamco – crypto fish"],
    "aquaculture": ["Show HN: Kelpco – seaweed packaging", "Show HN: Finfarm – salmon pens"],
}


@pytest.fixture(autouse=True)
def offline(client, monkeypatch):  # after `client`, which turns auto discovery off
    def hn(q, limit):
        field = q.split()[0]
        return [{"title": t, "link": ""} for t in HEADLINES.get(field, [])]
    monkeypatch.setattr(discovery, "FEEDS", {"hackernews": hn})
    monkeypatch.setattr(pulse, "FEEDS", {"news.google": lambda n, l: []})
    monkeypatch.setattr(autofill, "START", lambda fn: fn())
    monkeypatch.setattr(config, "DISCOVER_FIELDS", ["ocean", "aquaculture"])
    monkeypatch.setattr(config, "DISCOVER_REGION", "")
    monkeypatch.setattr(config, "DISCOVER_DEPTH", 3)
    monkeypatch.setattr(config, "DISCOVER_MAX", 10)
    monkeypatch.setattr(config, "DISCOVER_EXCLUDE", ["crypto"])
    monkeypatch.setattr(config, "DISCOVER_AUTO", True)


def set_mode(client, admin, mode):
    return client.post("/api/admin/mode", json={"mode": mode}, auth=admin).json()


def overview(client, admin):
    return client.get("/api/host/overview", auth=admin).json()


def test_demo_is_the_default_and_shows_only_sample_companies(client, admin):
    assert client.get("/api/admin/mode", auth=admin).json()["mode"] == "demo"
    data = overview(client, admin)
    assert data["mode"] == "demo" and data["companies"] and not any(c["is_real"] for c in data["companies"])
    today = client.get("/api/dive/today").json()
    assert today["cards"] and not any(c["is_real"] for c in today["cards"]) and today["notice"] is None


def test_live_mode_with_nothing_found_shows_a_notice(client, admin, monkeypatch):
    monkeypatch.setattr(config, "DISCOVER_AUTO", False)
    out = set_mode(client, admin, "live")
    assert out["mode"] == "live" and out["autofill_start"] == "auto-off"
    assert overview(client, admin)["companies"] == []
    today = client.get("/api/dive/today").json()
    assert today["cards"] == [] and "real startups" in today["notice"]


def test_autofill_finds_real_startups_for_the_dashboard_not_the_game(client, admin):
    out = set_mode(client, admin, "live")
    assert out["autofill_start"] == "started"
    st = client.get("/api/admin/mode", auth=admin).json()
    # Kelpco is found under both fields but added once; the crypto one is excluded by DISCOVER_EXCLUDE.
    assert sorted(st["autofill"]["added"]) == ["Finfarm", "Kelpco", "Tidewise"]
    assert st["counts"]["live_pending"] == 3 and st["counts"]["live_active"] == 0

    comps = overview(client, admin)["companies"]
    assert {c["name"] for c in comps} == {"Finfarm", "Kelpco", "Tidewise"}
    assert all(c["is_real"] and not c["active"] for c in comps)
    companies = client.get("/api/admin/companies", auth=admin).json()
    kelp = next(c for c in companies if c["name"] == "Kelpco")
    assert kelp["origin"] == "discovery-auto" and kelp["one_liner"] == "Kelpco – seaweed packaging"

    # Not in the game until the host adds it; then today's (empty) live set fills in.
    assert client.get("/api/dive/today").json()["cards"] == []
    body = {k: kelp[k] for k in ("name", "sector", "one_liner", "claim_ask", "website", "evidence", "evidence_note")}
    client.put(f"/api/admin/companies/{kelp['id']}", json=body | {"is_real": True, "active": True}, auth=admin)
    today = client.get("/api/dive/today").json()
    assert [c["name"] for c in today["cards"]] == ["Kelpco"] and today["notice"] is None

    # A second run adds nothing new.
    client.post("/api/admin/autofill", auth=admin)
    assert client.get("/api/admin/mode", auth=admin).json()["autofill"]["added"] == []


def test_autofill_respects_the_cap(client, admin, monkeypatch):
    monkeypatch.setattr(config, "DISCOVER_MAX", 2)
    set_mode(client, admin, "live")
    assert client.get("/api/admin/mode", auth=admin).json()["autofill"]["found"] == 2
    assert client.post("/api/admin/autofill", auth=admin).json()["autofill_start"] == "cap-reached"


def test_switching_back_to_demo_restores_the_sample_set(client, admin):
    player = new_player(client)
    demo_ids = [c["id"] for c in player.get("/api/dive/today").json()["cards"]]
    set_mode(client, admin, "live")
    assert player.get("/api/dive/today").json()["cards"] == []
    set_mode(client, admin, "demo")
    assert [c["id"] for c in player.get("/api/dive/today").json()["cards"]] == demo_ids


def test_sets_follow_the_mode(client, admin):
    demo_dives = client.get("/api/host/dives", auth=admin).json()
    assert demo_dives
    set_mode(client, admin, "live")
    assert client.get("/api/host/dives", auth=admin).json() == []
    real = client.get("/api/admin/companies?pool=live", auth=admin).json()[0]
    client.post("/api/admin/dives", json={"label": "Real room", "company_ids": [real["id"]]}, auth=admin)
    assert [d["label"] for d in client.get("/api/host/dives", auth=admin).json()] == ["Real room"]
    set_mode(client, admin, "demo")
    assert "Real room" not in [d["label"] for d in client.get("/api/host/dives", auth=admin).json()]


def test_mode_needs_admin(client):
    assert client.post("/api/admin/mode", json={"mode": "live"}).status_code == 401
    assert client.post("/api/admin/autofill").status_code == 401


# --- AI-written cards (OpenRouter call stubbed) ------------------------------------------------------

def fake_complete(messages):
    sources = messages[-1]["content"]
    if "Company name: Tidewise" in sources:
        return {"is_startup": False, "reject_reason": "a news aggregator", "emoji": "", "sector": "", "one_liner": "",
                "claim_ask": "", "facts": []}
    if "Company name: Finfarm" in sources:
        raise OSError("rate limited")
    return {"is_startup": True, "reject_reason": "", "emoji": "🌿", "sector": "Seaweed Packaging",
            "one_liner": "Food packaging made from seaweed that dissolves in water.",
            "claim_ask": "Funding to build its first production line",
            "facts": [{"label": "Origin", "value": "Launched on Hacker News"}, {"label": "", "value": "dropped"}]}


@pytest.fixture
def ai(monkeypatch):
    from app.crawler import pitch
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(pitch, "complete", fake_complete)
    return pitch


def test_autofill_writes_demo_style_cards_and_skips_non_startups(client, admin, ai):
    set_mode(client, admin, "live")
    st = client.get("/api/admin/mode", auth=admin).json()
    assert st["discover"]["ai"]["enabled"]
    assert sorted(st["autofill"]["added"]) == ["Finfarm", "Kelpco"]
    assert {"name": "Tidewise", "reason": "a news aggregator"} in st["autofill"]["skipped"]
    assert {"name": "Spamco", "reason": "excluded (matches “crypto”)"} in st["autofill"]["skipped"]
    assert any("Finfarm: card writer" in e for e in st["autofill"]["errors"])
    dismissed = {c["name"] for c in client.get("/api/admin/discover?status=dismissed", auth=admin).json()}
    assert dismissed == {"Tidewise", "Spamco"}

    by_name = {c["name"]: c for c in client.get("/api/admin/companies", auth=admin).json()}
    kelp = by_name["Kelpco"]
    assert kelp["emoji"] == "🌿" and kelp["sector"] == "seaweed packaging"
    assert kelp["one_liner"].startswith("Food packaging") and kelp["claim_ask"].startswith("Funding")
    assert kelp["facts"] == [{"label": "Origin", "value": "Launched on Hacker News"}]
    assert "written by AI" in kelp["evidence_note"]
    # Card text only: evidence and scores are what discovery proved, nothing more.
    assert kelp["evidence"] == {} and kelp["engine_coverage"]["assessed"] == 0
    # A failed call keeps the startup with its headline as the pitch.
    assert by_name["Finfarm"]["one_liner"] == "Finfarm – salmon pens" and by_name["Finfarm"]["claim_ask"] == ""


def test_rewrite_card(client, admin, monkeypatch):
    set_mode(client, admin, "live")
    kelp = next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["name"] == "Kelpco")
    assert client.post(f"/api/admin/companies/{kelp['id']}/rewrite", auth=admin).status_code == 400  # no key

    from app.crawler import pitch
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(pitch, "complete", fake_complete)
    out = client.post(f"/api/admin/companies/{kelp['id']}/rewrite", auth=admin).json()
    assert out["is_startup"] and out["company"]["claim_ask"] == "Funding to build its first production line"

    tide = next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["name"] == "Tidewise")
    out = client.post(f"/api/admin/companies/{tide['id']}/rewrite", auth=admin).json()
    assert not out["is_startup"] and out["reject_reason"] == "a news aggregator"
    assert out["company"]["one_liner"] == tide["one_liner"]  # unchanged


def test_written_cards_fit_the_game_limits(ai, monkeypatch):
    monkeypatch.setattr(ai, "complete", lambda m: {
        "is_startup": True, "reject_reason": "", "emoji": "🐟", "sector": "x" * 50, "one_liner": "word " * 40,
        "claim_ask": "€1M " * 30, "facts": [{"label": "A", "value": "b"}] * 5})
    card = ai.write_card("sources")
    assert len(card["one_liner"]) <= 90 and len(card["claim_ask"]) <= 60 and len(card["sector"]) <= 30
    assert len(card["facts"]) == 3
