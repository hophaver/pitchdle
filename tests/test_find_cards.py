"""New finds on the dashboard get their game card written in the background, so they show the same brief pitch a
tracked startup does; a find the writer says isn't a startup is set aside, and Track reuses the written card."""
import pytest

from app import autofill, autoread, config, reads
from app.crawler import profile
from app.db import connect, name_key, now

CARD = {"is_startup": True, "reject_reason": "", "emoji": "🌊", "sector": "water tech",
        "one_liner": "Acoustic sensors that find leaks in city water mains.", "claim_ask": "$5M seed to reach 20 cities",
        "facts": []}


@pytest.fixture
def writer(client, admin, monkeypatch):
    """Key set, runs synchronous, and the card writer faked: it answers with whatever `answers` holds per name."""
    answers, asked = {}, []
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(autoread, "START", lambda fn: fn())

    def card_for(row):
        asked.append(row["name"])
        answer = answers.get(row["name"], CARD)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(autofill, "card_for_candidate", card_for)
    # What follows a Track (the fill and the reviews) has its own tests; here it's instant and offline.
    monkeypatch.setattr(profile, "fill", lambda db, comp: None)
    monkeypatch.setattr(reads, "rate_all", lambda comp, only=None, brief=None: {})
    monkeypatch.setattr(reads, "social_all", lambda comp, only=None: {})
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)
    return {"answers": answers, "asked": asked}


def find(name: str, headline: str) -> None:
    db = connect()
    db.execute("INSERT INTO candidates (name, name_key, snippet, source, sector_query, status, created_at) "
               "VALUES (?, ?, ?, 'news.google', 'water', 'new', ?)", (name, name_key(name), headline, now()))
    db.commit()
    db.close()


def finds(client, admin):
    return {c["name"]: c for c in client.get("/api/host/radar", auth=admin).json()["candidates"]}


def test_a_new_find_gets_the_same_brief_pitch_as_a_tracked_card(client, admin, writer):
    find("HydroSight", "Haifa startup HydroSight raises $5 million in seed round - The Jerusalem Post")
    autoread.kick()
    card = finds(client, admin)["HydroSight"]["card"]
    assert card["one_liner"] == CARD["one_liner"] and card["claim_ask"] == CARD["claim_ask"]
    autoread.kick()
    assert writer["asked"] == ["HydroSight"]  # written once


def test_tracking_reuses_the_written_card(client, admin, writer):
    find("HydroSight", "Haifa startup HydroSight raises $5 million")
    autoread.kick()
    cid = finds(client, admin)["HydroSight"]["id"]
    client.post(f"/api/admin/discover/{cid}/approve", auth=admin)
    tracked = next(c for c in client.get("/api/host/radar", auth=admin).json()["companies"] if c["name"] == "HydroSight")
    assert tracked["one_liner"] == CARD["one_liner"] and writer["asked"] == ["HydroSight"]


def test_a_find_that_isnt_a_startup_is_set_aside(client, admin, writer):
    writer["answers"]["Blue Fund"] = CARD | {"is_startup": False, "reject_reason": "a venture fund", "one_liner": ""}
    find("Blue Fund", "Blue Fund closes €50M ocean fund")
    autoread.kick()
    assert "Blue Fund" not in finds(client, admin)
    db = connect()
    row = db.execute("SELECT status, screen FROM candidates WHERE name = 'Blue Fund'").fetchone()
    db.close()
    assert row["status"] == "dismissed" and "a venture fund" in row["screen"]


def test_a_failed_card_keeps_the_headline_and_isnt_asked_again(client, admin, writer):
    writer["answers"]["HydroSight"] = OSError("down")
    find("HydroSight", "Haifa startup HydroSight raises $5 million")
    autoread.kick()
    autoread.kick()
    got = finds(client, admin)["HydroSight"]
    assert got["card"] is None and "down" in got["card_error"] and writer["asked"] == ["HydroSight"]
