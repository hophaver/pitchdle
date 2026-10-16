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
    assert "real startups" in client.get("/api/live/state").json()["notice"]


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
    real = client.get("/api/admin/companies", auth=admin).json()[0]
    client.post("/api/admin/dives", json={"label": "Real room", "company_ids": [real["id"]], "mode": "live"}, auth=admin)
    assert [d["label"] for d in client.get("/api/host/dives", auth=admin).json()] == ["Real room"]
    set_mode(client, admin, "demo")
    assert "Real room" not in [d["label"] for d in client.get("/api/host/dives", auth=admin).json()]


def test_mode_needs_admin(client):
    assert client.post("/api/admin/mode", json={"mode": "live"}).status_code == 401
    assert client.post("/api/admin/autofill").status_code == 401
