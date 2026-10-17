"""Discover → queue → approve, with every feed mocked."""
import pytest

from app.crawler import discovery, pulse


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def boom(q, limit):
        raise OSError("down")
    monkeypatch.setattr(discovery, "FEEDS", {
        "hackernews": lambda q, limit: [{"title": "Show HN: Kelpco – seaweed packaging", "link": ""}],
        "news.google": boom,
    })
    monkeypatch.setattr(pulse, "FEEDS", {"news.google": lambda n, l: [{"title": f"{n} raises €2M", "link": "x"}]})


def test_search_queue_approve(client, admin):
    found = client.post("/api/admin/discover/search", json={"sector": "ocean", "country": "Finland"}, auth=admin).json()
    assert [c["name"] for c in found] == ["Kelpco"]
    cand = found[0]
    assert cand["status"] == "new" and cand["country_tag"] == "Finland"
    assert cand["pulse"]["lean"] == "positive" and cand["engine_hint"]["coverage"]["assessed"] == 0

    # Searching again doesn't duplicate.
    client.post("/api/admin/discover/search", json={"sector": "ocean"}, auth=admin)
    assert len(client.get("/api/admin/discover", auth=admin).json()) == 1

    assert client.post(f"/api/admin/discover/{cand['id']}/queue", json={"queued": True}, auth=admin).json()["status"] == "queued"
    assert client.get("/api/admin/discover?status=queued", auth=admin).json()[0]["id"] == cand["id"]

    comp = client.post(f"/api/admin/discover/{cand['id']}/approve", auth=admin).json()
    assert comp["name"] == "Kelpco" and comp["is_real"] == 1 and comp["active"] == 0
    assert comp["sector"] == "ocean" and comp["pulse"]["lean"] == "positive"
    assert client.get("/api/admin/discover?status=approved", auth=admin).json()[0]["company_id"] == comp["id"]
    assert client.post(f"/api/admin/discover/{cand['id']}/approve", auth=admin).status_code == 409


def test_dismiss_is_soft(client, admin):
    cand = client.post("/api/admin/discover/search", json={"sector": "ocean"}, auth=admin).json()[0]
    assert client.delete(f"/api/admin/discover/{cand['id']}", auth=admin).status_code == 200
    assert client.get("/api/admin/discover", auth=admin).json() == []
    assert client.get("/api/admin/discover?status=dismissed", auth=admin).json()[0]["id"] == cand["id"]


def test_discover_needs_admin(client):
    assert client.post("/api/admin/discover/search", json={"sector": "ocean"}).status_code == 401
    assert client.get("/api/admin/discover").status_code == 401


def test_in_scope_needs_no_field_or_country(client, admin):
    assert client.post("/api/admin/discover/search", json={}, auth=admin).status_code == 422
    found = client.post("/api/admin/discover/search", json={"scope": "in"}, auth=admin).json()
    assert [c["name"] for c in found] == ["Kelpco"]  # seaweed: inside the blue-economy gates


def test_in_scope_drops_finds_outside_every_thesis_and_everything_brings_them_back(client, admin, monkeypatch):
    monkeypatch.setitem(discovery.FEEDS, "hackernews",
                        lambda q, limit: [{"title": "Show HN: Payrollio – payroll for dentists", "link": ""}])
    assert client.post("/api/admin/discover/search", json={"sector": "payroll", "scope": "in"}, auth=admin).json() == []
    gone = client.get("/api/admin/discover?status=dismissed", auth=admin).json()[0]
    assert gone["name"] == "Payrollio" and gone["screen"]["reason"].startswith("Out of scope")
    found = client.post("/api/admin/discover/search", json={"sector": "payroll", "scope": "all"}, auth=admin).json()
    assert [c["name"] for c in found] == ["Payrollio"] and found[0]["status"] == "new"


def test_finds_are_labelled_by_scope_and_the_in_scope_ones_track_in_one_go(client, admin, monkeypatch):
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)
    client.post("/api/admin/discover/search", json={"sector": "ocean"}, auth=admin)  # Kelpco, seaweed
    monkeypatch.setitem(discovery.FEEDS, "hackernews",
                        lambda q, limit: [{"title": "Show HN: Payrollio – payroll for dentists", "link": ""}])
    client.post("/api/admin/discover/search", json={"sector": "payroll"}, auth=admin)
    cands = {c["name"]: c for c in client.get("/api/host/radar", auth=admin).json()["candidates"]}
    assert cands["Kelpco"]["scope"] == {"in": True, "why": []}
    assert cands["Payrollio"]["scope"]["in"] is False and "outside the blue-economy focus" in cands["Payrollio"]["scope"]["why"][0]

    r = client.post("/api/admin/discover/track-in-scope", auth=admin).json()
    assert r == {"tracked": ["Kelpco"], "failed": []}
    left = client.get("/api/host/radar", auth=admin).json()
    assert [c["name"] for c in left["candidates"]] == ["Payrollio"]  # out of scope: left for the host
    assert any(c["name"] == "Kelpco" for c in left["companies"])
