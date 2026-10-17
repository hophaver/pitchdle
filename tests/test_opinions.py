"""The card's profile, and every opinion besides the players': A'Pelago's, AI models' and social media's."""
from app import reads
from tests.conftest import new_player, sign_up, staff
from tests.test_api import GUESS, answer, today

PROFILE = {"name": "Kelp Co", "sector": "seaweed", "one_liner": "Seaweed packaging.", "claim_ask": "€1M",
           "website": "https://kelp.example", "vision": "Line one.\r\n\r\n\r\nLine two.",
           "stages": [" Pre-seed ", "", "Accelerator  programme"], "raised_eur": 250000,
           "investors": [{"name": "Lumi Seed Fund", "status": "invested", "amount_eur": 200000},
                         {"name": "Kantele Angels", "status": "interested"}]}


def add_company(client, admin, **fields):
    return client.post("/api/admin/companies", json=PROFILE | fields, auth=admin)


def card_of(client, admin, cid):
    dive = client.post("/api/admin/dives", json={"label": "one", "company_ids": [cid]}, auth=admin).json()
    return dive["id"], client.get(f"/api/dive/{dive['id']}").json()["cards"][0]


def test_admin_edits_the_card_profile(client, admin):
    r = add_company(client, admin)
    assert r.status_code == 200
    comp = r.json()
    assert comp["vision"] == "Line one.\n\nLine two." and comp["stages"] == ["Pre-seed", "Accelerator programme"]
    assert comp["investors"][1] == {"name": "Kantele Angels", "status": "interested", "amount_eur": None}
    _, card = card_of(client, admin, comp["id"])
    assert card["vision"] == comp["vision"] and card["raised_eur"] == 250000 and card["website"] == "https://kelp.example"
    # Saving without the profile (e.g. an older caller) clears it, as the whole company is replaced.
    body = {k: comp[k] for k in ("name", "sector", "one_liner", "claim_ask")}
    assert client.put(f"/api/admin/companies/{comp['id']}", json=body, auth=admin).json()["vision"] == ""


def test_profile_rules(client, admin):
    assert add_company(client, admin, vision="word " * 401).status_code == 422
    assert add_company(client, admin, vision="word " * 400).status_code == 200
    assert add_company(client, admin, raised_eur=-5).status_code == 422
    assert add_company(client, admin, investors=[{"name": "X", "status": "maybe"}]).status_code == 422
    assert add_company(client, admin, investors=[{"name": "  ", "status": "invested"}]).status_code == 422


def test_sample_companies_get_profiles(client, admin):
    from app import seed
    from app.db import connect
    comps = {c["name"]: c for c in client.get("/api/admin/companies", auth=admin).json()}
    assert comps["Rakko Feed"]["raised_eur"] == 650000 and comps["Rakko Feed"]["investors"]
    db = connect()
    # A database from before profiles: never-saved sample companies get theirs, nothing an admin wrote is touched.
    db.execute("UPDATE companies SET vision = NULL, investors = '[]' WHERE name = 'TideLedger'")
    db.execute("UPDATE companies SET vision = '' WHERE name = 'Rakko Feed'")
    db.commit()
    assert seed.fill_profiles(db) == 1
    comps = {c["name"]: c for c in client.get("/api/admin/companies", auth=admin).json()}
    assert comps["TideLedger"]["vision"].startswith("Every bottle") and comps["TideLedger"]["investors"]
    assert comps["Rakko Feed"]["vision"] == ""


def evaluate(c, auth, cid, scores, note=""):
    return c.put(f"/api/mod/evaluations/{cid}", json={"scores": scores, "note": note}, auth=auth)


def test_apelago_evaluations(client, admin, moderator):
    data = today(client)
    dive_id, first = data["dive"]["id"], data["cards"][0]["id"]
    assert client.get("/api/mod/evaluations").status_code == 401  # players can't
    listed = client.get("/api/mod/evaluations", auth=moderator).json()
    entry = next(c for c in listed["companies"] if c["id"] == first)
    assert entry["mine"] is None and entry["apelago"] is None and "vision" in entry

    r = evaluate(client, moderator, first, {**GUESS, "novel": 5}, "Good team.")
    assert r.json()["mine"]["scores"]["novel"] == 5
    assert r.json()["apelago"] == {"n": 1, "means": {**GUESS, "novel": 5.0}, "reps": ["mira"]}
    r = evaluate(client, admin, first, {**GUESS, "novel": 2})
    assert r.json()["apelago"]["reps"] == ["mira", "admin"] and r.json()["apelago"]["means"]["novel"] == 3.5
    assert evaluate(client, moderator, first, {**GUESS, "novel": 6}).status_code == 422

    for card in data["cards"]:
        answer(client, dive_id, card["id"])
    tiles = client.get(f"/api/dive/{dive_id}/results").json()["cards"][0]["opinions"]
    apelago = next(t for t in tiles if t["key"] == "apelago")
    assert apelago["label"] == "A'Pelago" and apelago["count"] == 2 and apelago["scores"]["novel"] == 3.5
    assert apelago["note"] == ""  # representatives' comments stay with the staff

    # A moderator changing their mind, then their account going: their evaluation goes with it.
    evaluate(client, moderator, first, {**GUESS, "novel": 3})
    client.delete(f"/api/mod/users/{next(u['id'] for u in client.get('/api/mod/users', auth=admin).json()['users'] if u['username'] == 'mira')}",
                  auth=admin)
    left = client.get("/api/mod/evaluations", auth=admin).json()["companies"]
    assert next(c for c in left if c["id"] == first)["apelago"]["reps"] == ["admin"]


def fake_reads(monkeypatch):
    def rate_all(comp, brief=None):
        return {"claude": {"scores": {**GUESS, "novel": 4.0}, "note": "Strong trials.", "meta": {"model": "claude-opus-5-5"}},
                "gpt": {"error": "APIError: overloaded"}, "grok": {"skipped": "no XAI_API_KEY"}}

    def social_all(comp):
        return {"x": {"scores": {**GUESS, "useful": 5.0}, "note": "People love it.",
                      "meta": {"posts": 3, "links": ["https://x.com/a/status/1"], "via": "Grok X search", "model": "grok-4.7"}},
                "reddit": {"scores": None, "note": "", "meta": {"posts": 0, "links": [], "via": "Claude web search",
                                                                 "model": "claude-opus-5-5"}}}
    monkeypatch.setattr(reads, "rate_all", rate_all)
    monkeypatch.setattr(reads, "social_all", social_all)


def test_outside_reads_are_kept(client, admin, monkeypatch):
    fake_reads(monkeypatch)
    cid = client.get("/api/admin/companies", auth=admin).json()[0]["id"]
    assert client.post(f"/api/admin/companies/{cid}/reads/ai").status_code == 401
    r = client.post(f"/api/admin/companies/{cid}/reads/ai", auth=admin).json()
    assert r["report"] == {"claude": {"done": True, "posts": None}, "gpt": {"error": "APIError: overloaded"},
                           "grok": {"skipped": "no XAI_API_KEY"}}
    assert r["company"]["opinions"]["claude"]["meta"]["by"] == "fetched"
    r = client.post(f"/api/admin/companies/{cid}/reads/social", auth=admin).json()
    assert r["report"]["reddit"] == {"done": True, "posts": 0}  # looked, found nothing: kept as a quiet platform
    assert r["company"]["opinions"]["reddit"]["scores"] is None
    assert client.post(f"/api/admin/companies/{cid}/reads/tarot", auth=admin).status_code == 404
    assert "ready" in client.get("/api/admin/mode", auth=admin).json()["reads"]


def test_result_cards_show_every_opinion_in_order(client, admin, moderator, monkeypatch):
    fake_reads(monkeypatch)
    data = today(client)
    dive_id, cid = data["dive"]["id"], data["cards"][0]["id"]
    client.post(f"/api/admin/companies/{cid}/reads/ai", auth=admin)
    client.post(f"/api/admin/companies/{cid}/reads/social", auth=admin)
    evaluate(client, moderator, cid, GUESS)
    other = new_player(client)
    for card in data["cards"]:
        answer(other, dive_id, card["id"], {**GUESS, "novel": 1})
        answer(client, dive_id, card["id"])
    tiles = client.get(f"/api/dive/{dive_id}/results").json()["cards"][0]["opinions"]
    assert [(t["key"], t["group"]) for t in tiles] == [
        ("you", "people"), ("crowd", "people"), ("apelago", "people"), ("claude", "ai"), ("x", "social")]
    assert tiles[1]["count"] == 1 and tiles[3]["note"] == "Strong trials." and tiles[4]["count"] == 3
    assert "reddit" not in [t["key"] for t in tiles]  # a quiet platform has nothing to chart
