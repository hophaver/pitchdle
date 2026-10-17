"""A tracked real startup joins the daily game by itself once its card is filled and passes the automatic check;
one that fails stays out, with the reason. Players' suggestions show on the dashboard to track like any find."""
import pytest

from app import autoread, config, reads
from app.crawler import gate, profile

REAL = {"name": "HydroSight", "sector": "water tech", "one_liner": "Acoustic sensors that find leaks in city water mains.",
        "claim_ask": "$5M seed", "website": "", "is_real": True, "active": False}


@pytest.fixture
def ai(client, admin, monkeypatch):
    """Key set, runs synchronous, the fill a no-op that marks the card filled, reviews instant, and the check's
    verdict set per test. Records what the check was shown."""
    shown, verdict = [], {"ok": True, "reason": ""}
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(autoread, "START", lambda fn: fn())
    monkeypatch.setattr(reads, "rate_all", lambda comp, only=None, brief=None: {})
    monkeypatch.setattr(reads, "social_all", lambda comp, only=None: {})

    def fill(db, comp):
        db.execute("UPDATE companies SET profile_status = 'ai' WHERE id = ?", (comp["id"],))
        db.commit()
    monkeypatch.setattr(profile, "fill", fill)

    def complete(messages):
        shown.append(messages[1]["content"])
        return dict(verdict)
    monkeypatch.setattr(gate, "complete", complete)
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)
    return {"shown": shown, "verdict": verdict}


def company(client, admin, cid):
    return next(c for c in client.get("/api/host/radar", auth=admin).json()["companies"] if c["id"] == cid)


def test_a_filled_startup_that_passes_joins_the_game(client, admin, ai):
    cid = client.post("/api/admin/companies", json=REAL, auth=admin).json()["id"]
    c = company(client, admin, cid)
    assert c["active"] is True and c["game"] == {"status": "in", "note": ""}
    assert "Pitch: Acoustic sensors" in ai["shown"][0]  # judged on the card players would see
    assert client.get("/api/dive/today").json()["cards"]  # players get real startups now


def test_one_that_fails_stays_out_with_the_reason(client, admin, ai):
    ai["verdict"].update(ok=False, reason="a news site, not a startup")
    cid = client.post("/api/admin/companies", json=REAL | {"active": True}, auth=admin).json()["id"]
    c = company(client, admin, cid)
    assert c["active"] is False and c["game"] == {"status": "out", "note": "a news site, not a startup"}


def test_a_card_without_a_pitch_never_reaches_the_check(client, admin, ai):
    cid = client.post("/api/admin/companies", json=REAL | {"one_liner": ""}, auth=admin).json()["id"]
    assert company(client, admin, cid)["game"] == {"status": "out", "note": "no pitch yet"} and ai["shown"] == []


def test_checked_once(client, admin, ai):
    client.post("/api/admin/companies", json=REAL, auth=admin)
    autoread.kick()
    assert len(ai["shown"]) == 1


def test_players_suggestions_show_on_the_dashboard_and_track_like_finds(client, admin, ai):
    client.post("/api/submit", json={"name": "Kelp Co", "sector": "seaweed", "one_liner": "Seaweed packaging that dissolves.",
                                     "claim_ask": "€1M for a line", "website": "https://kelp.example"})
    subs = client.get("/api/host/radar", auth=admin).json()["submissions"]
    assert [s["name"] for s in subs] == ["Kelp Co"]
    client.post(f"/api/admin/submissions/{subs[0]['id']}/approve", auth=admin)
    radar = client.get("/api/host/radar", auth=admin).json()
    assert radar["submissions"] == []
    kelp = next(c for c in radar["companies"] if c["name"] == "Kelp Co")
    assert kelp["game"]["status"] == "in" and kelp["active"] is True  # filled and checked by itself
