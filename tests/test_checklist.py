"""The readiness checklists: answered by AI with quotes checked against the sources, or by hand without a key;
the host's answers always win; the thesis criteria are editable. The model, website and feeds are faked."""
import shutil
import sqlite3

import pytest

from app import config, engine
from app.crawler import checklist, profile


def company(client, admin, name="Kelp Co", **extra):
    body = {"name": name, "sector": "aquaculture", "one_liner": "Kelp farms off the Finnish coast.",
            "website": "https://kelp.example", "is_real": True, "active": True} | extra
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)  # the radar shows the current pool
    return client.post("/api/admin/companies", json=body, auth=admin).json()


def radar_entry(client, admin, cid):
    return next(c for c in client.get("/api/host/radar", auth=admin).json()["companies"] if c["id"] == cid)


SOURCES = "Company name: Kelp Co\nWebsite text: Kelp Co sells dried kelp to three feed mills under paid trial contracts."


def answer(rung6: str) -> dict:
    """BRL rungs 1-5 'yes' with a real quote, rung 6 'yes' with the quote given; everything else unknown."""
    real = {"answer": "yes", "quote": "sells dried kelp to three feed mills", "source": "site"}
    unknown = {"answer": "unknown", "quote": "", "source": "none"}
    rubric = engine.load_rubric()
    ladders = {key: {str(r["n"]): unknown for r in spec["rungs"]} for key, spec in rubric["ladders"].items()}
    ladders["business"].update({str(n): real for n in range(1, 6)})
    ladders["business"]["6"] = {"answer": "yes", "quote": rung6, "source": "site"}
    factors = {n: {"value": None, "quote": "", "source": "none"} for n in rubric["investment"]["factors"]}
    factors["market"] = {"value": 4, "quote": "three feed mills", "source": "site"}
    return {"ladders": ladders, "investment": factors}


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(profile, "gather", lambda comp: (SOURCES, ["website"]))
    out = {"answer": answer("paid trial contracts")}
    monkeypatch.setattr(checklist, "complete", lambda messages: out["answer"])
    return out


def test_ai_answers_with_quotes_set_the_level(client, admin, model):
    cid = company(client, admin)["id"]
    r = client.post(f"/api/admin/companies/{cid}/checklist/ai", auth=admin)
    assert r.status_code == 200 and r.json()["tally"]["verified"] == 7  # six rungs and the market factor's quote
    lv = radar_entry(client, admin, cid)["readiness"]["business"]
    assert lv["level"] == 6 and lv["source"] == "site" and lv["blocker"]["n"] == 7


def test_a_quote_missing_from_the_sources_is_downgraded(client, admin, model):
    model["answer"] = answer("a signed €2M offtake with Cargill")  # not in the sources: made up
    cid = company(client, admin)["id"]
    tally = client.post(f"/api/admin/companies/{cid}/checklist/ai", auth=admin).json()["tally"]
    assert tally["unverified"] == 1
    lv = radar_entry(client, admin, cid)["readiness"]["business"]
    assert lv["level"] == 5 and lv["blocker"] == {"n": 6, "text": "no test sales", "kind": "unverified"}
    step = lv["steps"][5]
    assert step["source"] == "ai" and not step["counted"]


def test_host_answers_survive_an_ai_run(client, admin, model):
    cid = company(client, admin)["id"]
    r = client.put(f"/api/admin/companies/{cid}/checklist", auth=admin, json={"checklist": {
        "business.6": {"answer": "no", "quote": "Trials are unpaid", "source": "host"}}})
    assert r.status_code == 200
    client.post(f"/api/admin/companies/{cid}/checklist/ai", auth=admin)
    ev = next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["id"] == cid)["evidence"]
    assert ev["checklist"]["business.6"]["by"] == "host" and ev["checklist"]["business.6"]["answer"] == "no"
    assert ev["checklist"]["business.5"]["by"] == "ai"
    lv = radar_entry(client, admin, cid)["readiness"]["business"]
    assert lv["level"] == 5 and lv["blocker"]["kind"] == "no"


def test_without_a_key_the_host_answers_by_hand(client, admin):
    cid = company(client, admin)["id"]
    r = client.post(f"/api/admin/companies/{cid}/checklist/ai", auth=admin)
    assert r.status_code == 400 and "by hand" in r.json()["detail"]
    r = client.put(f"/api/admin/companies/{cid}/checklist", auth=admin, json={
        "checklist": {"tech.1": {"answer": "yes"}, "tech.2": {"answer": "yes", "quote": "Design done",
                                                              "url": "https://kelp.example/tech", "source": "site"}},
        "support": {"redstone.team": {"value": 3.5, "quote": "Two marine biologists", "source": "site"}},
        "confirm": True})
    assert r.status_code == 200
    c = radar_entry(client, admin, cid)
    assert c["readiness"]["tech"]["trl"] == 2 and c["review"]["status"] == "confirmed"
    team = next(f for f in c["factors"] if f["key"] == "redstone.team")
    assert team["value"] == 3.5 and team["source"] == "site" and team["quote"] == "Two marine biologists"
    # "unknown" clears an answer; a bad rung, source or link is refused.
    client.put(f"/api/admin/companies/{cid}/checklist", auth=admin, json={"checklist": {"tech.2": {"answer": "unknown"}}})
    assert radar_entry(client, admin, cid)["readiness"]["tech"]["trl"] == 1
    for bad in ({"checklist": {"tech.10": {"answer": "yes"}}}, {"checklist": {"tech.1": {"answer": "yes", "source": "vibes"}}},
                {"checklist": {"tech.1": {"answer": "yes", "url": "javascript:alert(1)"}}}):
        assert client.put(f"/api/admin/companies/{cid}/checklist", auth=admin, json=bad).status_code == 400


@pytest.fixture
def rubric_copy(tmp_path, monkeypatch):
    """Edits go to a copy, never the repo's rubric.json."""
    path = tmp_path / "rubric.json"
    shutil.copy(config.RUBRIC_PATH, path)
    monkeypatch.setattr(config, "RUBRIC_PATH", path)
    engine.reload()
    yield path
    engine.reload()


def test_thesis_criteria_are_editable_and_gate_the_fit(client, admin, rubric_copy):
    cid = company(client, admin, evidence={"redstone": {"market": 4, "team": 4, "product": 4}})["id"]
    with sqlite3.connect(config.DB_PATH) as db:  # the country comes from the profile fill; set it as that would
        db.execute("UPDATE companies SET country = 'Brazil' WHERE id = ?", (cid,))
    assert radar_entry(client, admin, cid)["theses"]["redstone"]["fit"] == "in"
    criteria = engine.load_rubric()["theses"]
    body = {k: {"sectors": t["gates"]["sectors"], "countries": ["Finland", "Nordic"], "ticket_eur": None,
                "window": t["window"], "criteria_note": "From the partner, 2026-10-17."} for k, t in criteria.items()
            if not k.startswith("_")}
    r = client.put("/api/admin/rubric/theses", auth=admin, json=body)
    assert r.status_code == 200 and r.json()["redstone"]["gates"]["countries"] == ["Finland", "Nordic"]
    c = radar_entry(client, admin, cid)
    assert c["theses"]["redstone"]["fit"] == "out" and "Brazil" in c["theses"]["redstone"]["why"]
    assert c["call"]["label"] == "Out of scope"
    bad = {"redstone": body["redstone"] | {"window": {"scale": "trl", "peak": [7, 3], "falloff": 3}}}
    assert client.put("/api/admin/rubric/theses", auth=admin, json=bad).status_code == 422
