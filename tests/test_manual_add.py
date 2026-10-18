"""Startups the host adds by hand on the dashboard. Only the name is needed. With the AI on, it fills whatever was left
empty from the website, the news and everything the host typed, notes included; off, the card is exactly what was
typed, until the host asks for the gaps to be filled. The model, website and feeds are faked here."""
import pytest

from app import autoread, config, engine, reads
from app.crawler import checklist, gate, pitch, profile, pulse, website
from app.db import connect

NOTES = "Met the founders at Slush. Three paying water utilities in Finland, and a pilot in Tallinn."
HOST = {"name": "Hailia", "website": "hailia.example", "country": "Finland",
        "one_liner": "Sensors that find leaks in city water pipes.", "raised_eur": 650_000,
        "stages": ["Seed round: €650k (2025)"], "investors": [{"name": "Blue Fund", "status": "invested", "amount_eur": 300_000}],
        "notes": NOTES}
# What the models answer. Some of it clashes with what the host typed: the host's wins.
CARD = {"is_startup": True, "reject_reason": "", "emoji": "💧", "sector": "water tech",
        "one_liner": "A pitch of the AI's own that mustn't replace the host's.", "claim_ask": "€1.5M to roll out in 10 cities",
        "facts": [{"label": "Customers", "value": "Three paying water utilities"}]}
PROFILE = {"vision": "Hailia puts acoustic sensors in water mains so utilities find leaks early.", "country": "Estonia",
           "raised": {"amount": 9_000_000, "currency": "EUR"}, "stages": ["Something else"],
           "investors": [{"name": "Other VC", "status": "invested", "amount": None, "currency": ""}],
           "evidence": {"trl_stage": "pilot", "patents": None, "basis": "Paying utilities, from the host's notes.",
                        "brl": {"market": 3.5}}}


def checklist_answer(quote: str, source: str = "host") -> dict:
    """The first rung of the first ladder answered yes with this quote; everything else unknown."""
    rubric = engine.load_rubric()
    unknown = {"answer": "unknown", "quote": "", "source": "none"}
    ladders = {key: {str(r["n"]): unknown for r in spec["rungs"]} for key, spec in rubric["ladders"].items()}
    first = next(iter(ladders))
    ladders[first]["1"] = {"answer": "yes", "quote": quote, "source": source}
    return {"ladders": ladders, "investment": {}}


@pytest.fixture
def ai(client, monkeypatch):
    """A key, synchronous runs, the website and news faked, and every model call answered and recorded by kind."""
    sent = {"card": [], "profile": [], "checklist": [], "reviews": []}
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(autoread, "START", lambda fn: fn())
    monkeypatch.setattr(website, "fetch", lambda url: {"text": "Hailia, Helsinki. Acoustic leak detection.", "description": ""})
    monkeypatch.setattr(pulse, "compute_pulse", lambda name, limit=20: {"top_hits": [
        {"title": "Helsinki's Hailia raises seed round for leak sensors", "published": "2025-03-02"}]})

    def answer(kind, reply):
        def complete(messages):
            sent[kind].append(messages[1]["content"])
            return reply() if callable(reply) else reply
        return complete
    monkeypatch.setattr(pitch, "complete", answer("card", CARD))
    monkeypatch.setattr(profile, "complete", answer("profile", PROFILE))
    monkeypatch.setattr(checklist, "complete", answer("checklist", lambda: checklist_answer("Three paying water utilities")))
    monkeypatch.setattr(gate, "complete", lambda messages: {"ok": True, "reason": ""})

    def rate_all(comp, only=None, brief=None):
        sent["reviews"].append(comp["name"])
        return {}
    monkeypatch.setattr(reads, "rate_all", rate_all)
    monkeypatch.setattr(reads, "social_all", lambda comp, only=None: {})
    return sent


def add(client, admin, **body):
    return client.post("/api/admin/startups", json=body, auth=admin)


def stored(client, admin, cid):
    return next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["id"] == cid)


def test_the_ai_fills_only_what_the_host_left_empty(client, admin, ai):
    r = add(client, admin, **HOST)
    assert r.json() == {"id": r.json()["id"], "name": "Hailia", "filling": True}
    c = stored(client, admin, r.json()["id"])
    # The host's own words stay, even where the models said otherwise...
    assert c["one_liner"] == HOST["one_liner"] and c["country"] == "Finland" and c["raised_eur"] == 650_000
    assert c["stages"] == HOST["stages"] and c["investors"] == HOST["investors"]
    # ...and the gaps are filled: the card writer's emoji, field and ask, the profile's vision and evidence.
    assert (c["emoji"], c["sector"], c["claim_ask"]) == ("💧", "water tech", "€1.5M to roll out in 10 cities")
    assert c["vision"].startswith("Hailia puts acoustic sensors") and c["evidence"]["brl"] == {"market": 3.5}
    assert (c["origin"], c["card_status"], c["profile_status"], c["evidence_status"]) == ("manual", "ai", "ai", "ai")
    assert c["website"] == "https://hailia.example" and c["host_notes"] == NOTES and c["is_real"] == 1
    # Its card complete, it passed the game check; and the reviewers were asked as for any card.
    assert c["game_status"] == "in" and c["active"] == 1 and "Hailia" in ai["reviews"]
    # Both models got everything the host gave them.
    for prompt in ai["card"] + ai["profile"]:
        assert NOTES in prompt and "Entered by the host" in prompt and "Raised so far: €650,000" in prompt
        assert "Blue Fund (invested, €300,000)" in prompt and "Hailia raises seed round" in prompt


def test_the_notes_are_a_source_the_checklist_can_quote(client, admin, ai, monkeypatch):
    cid = add(client, admin, **HOST).json()["id"]
    ev = stored(client, admin, cid)["evidence"]
    assert NOTES in ai["checklist"][0]
    yes = next(a for a in ev["checklist"].values() if a["answer"] == "yes")
    assert yes["source"] == "host" and yes["quote"] == "Three paying water utilities"  # found in the notes: it counts
    # A quote that isn't in any source is kept as the AI's inference, which never counts.
    monkeypatch.setattr(checklist, "complete", lambda messages: checklist_answer("Ten thousand sensors sold"))
    cid = add(client, admin, **HOST | {"name": "Hailia Two"}).json()["id"]
    ev = stored(client, admin, cid)["evidence"]
    assert next(a for a in ev["checklist"].values() if a["answer"] == "yes")["source"] == "ai"


def test_only_what_the_host_enters_until_they_ask(client, admin, ai):
    r = add(client, admin, **HOST, fill=False)
    assert r.json()["filling"] is False
    cid = r.json()["id"]
    c = stored(client, admin, cid)
    assert (c["card_status"], c["profile_status"], c["sector"], c["vision"]) == ("", "manual", "", "")
    assert ai["card"] == ai["profile"] == [] and "Hailia" in ai["reviews"]  # no fill, but the reviews as always
    assert c["game_status"] == ""  # no field or ask: not playable yet, so not even checked
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)  # the radar shows the current pool
    radar = next(x for x in client.get("/api/host/radar", auth=admin).json()["companies"] if x["id"] == cid)
    assert radar["origin"] == "manual" and radar["profile"]["status"] == "manual"
    # Later, one click fills the gaps the same way.
    assert client.post(f"/api/admin/companies/{cid}/fill", auth=admin).json() == {"started": True}
    c = stored(client, admin, cid)
    assert (c["sector"], c["profile_status"], c["one_liner"]) == ("water tech", "ai", HOST["one_liner"])
    assert client.post(f"/api/admin/companies/{cid}/fill", auth=admin).status_code == 409  # done already


def test_the_name_is_all_it_takes(client, admin):
    # No key here: it's added all the same, and waits to be filled once there is one.
    r = add(client, admin, name="  Solo  ")
    assert r.json()["name"] == "Solo" and r.json()["filling"] is False
    c = stored(client, admin, r.json()["id"])
    assert (c["card_status"], c["profile_status"], c["active"], c["evidence"]) == ("fill", "", 0, {})
    assert client.post(f"/api/admin/companies/{c['id']}/fill", auth=admin).status_code == 400  # no key to fill with


def test_what_it_refuses(client, admin, moderator):
    assert add(client, admin, name="   ").status_code == 422
    assert add(client, admin, name="Hailia", website="not a site").status_code == 422
    assert add(client, admin, name="Hailia", one_liner="x" * 91).status_code == 422
    assert add(client, admin, name="Hailia", vision="word " * 401).status_code == 422
    assert add(client, admin, name="Redstone Ventures").status_code == 409  # the event's partners are never startups
    assert add(client, admin, name="Hailia").status_code == 200
    r = add(client, admin, name="hailia")
    assert r.status_code == 409 and "already" in r.json()["detail"]
    assert client.post("/api/admin/startups", json={"name": "Mod Co"}, auth=moderator).status_code == 401


def test_the_same_startup_waiting_among_the_finds_is_this_one(client, admin):
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)
    with connect() as db:
        db.execute("INSERT INTO candidates (name, name_key, snippet, source, status, created_at) "
                   "VALUES ('Hailia', 'hailia', 'Hailia raises seed', 'news', 'new', '2026-10-18')")
    assert [c["name"] for c in client.get("/api/host/radar", auth=admin).json()["candidates"]] == ["Hailia"]
    cid = add(client, admin, name="Hailia").json()["id"]
    assert client.get("/api/host/radar", auth=admin).json()["candidates"] == []
    with connect() as db:
        assert db.execute("SELECT company_id FROM candidates WHERE name_key = 'hailia'").fetchone()[0] == cid
