from app import config
from tests.conftest import new_player

GUESS = {"novel": 3, "useful": 3, "plausible": 3, "investable": 3}


def today(c):
    return c.get("/api/dive/today").json()


def answer(c, dive_id, cid, scores=GUESS):
    return c.post("/api/vote", json={"dive_id": dive_id, "company_id": cid, "scores": scores})


def test_cards_show_only_the_pitch(client):
    card = today(client)["cards"][0]
    assert set(card) == {"id", "name", "emoji", "sector", "one_liner", "claim_ask", "is_real"}


def test_results_only_after_every_card(client):
    data = today(client)
    dive_id = data["dive"]["id"]
    assert len(data["cards"]) == 5
    for i, card in enumerate(data["cards"]):
        assert client.get(f"/api/dive/{dive_id}/results").status_code == 403, f"results leaked after {i} cards"
        assert answer(client, dive_id, card["id"]).status_code == 200
    r = client.get(f"/api/dive/{dive_id}/results").json()
    assert len(r["cards"]) == 5
    first = r["cards"][0]
    assert first["crowd"]["n"] == 1 and first["lean"] == "with"
    assert all(sum(a["share"]) == 100 for a in first["axes"])
    assert "engine" not in first  # players compare with the crowd only
    assert r["summary"]["axes_total"] == 20


def test_answers_are_final(client):
    data = today(client)
    dive_id, cid = data["dive"]["id"], data["cards"][0]["id"]
    assert answer(client, dive_id, cid).status_code == 200
    assert answer(client, dive_id, cid, {**GUESS, "novel": 5}).status_code == 409
    assert today(client)["answered"] == [cid]


def test_host_and_admin_need_password(client, admin):
    assert client.get("/api/host/overview").status_code == 401
    assert client.get("/admin").status_code == 401
    assert client.get("/api/host/overview", auth=admin).status_code == 200


def test_admin_adds_company_it_scores_immediately(client, admin):
    body = {"name": "Test Kelp Co", "sector": "kelp", "one_liner": "Grows kelp.", "claim_ask": "Raising €1M.",
            "facts": [{"label": "Pilot", "value": "1 line"}],
            "evidence": {"trl_stage": "pilot", "redstone": {"team": 4, "market": 3}}}
    r = client.post("/api/admin/companies", json=body, auth=admin)
    assert r.status_code == 200
    comp = r.json()
    assert comp["engine_composite"] is not None and comp["engine_coverage"]["assessed"] == 3
    d = client.post("/api/admin/dives", json={"label": "custom", "company_ids": [comp["id"]]}, auth=admin).json()
    assert client.get(f"/api/dive/{d['id']}").json()["cards"][0]["name"] == "Test Kelp Co"


def test_demo_votes_light_up_the_designed_cases(client, admin):
    live_dive = next(d for d in client.get("/api/host/dives", auth=admin).json() if d["mode"] == "live")
    client.post("/api/admin/demo-votes", json={"dive_id": live_dive["id"], "players": 30}, auth=admin)
    by_name = {c["name"]: c for c in client.get("/api/host/overview", auth=admin).json()["companies"]}
    assert any(f["key"] == "story" for f in by_name["TideLedger"]["flags"])
    assert any(f["key"] == "substance" for f in by_name["Rakko Feed"]["flags"])
    assert by_name["TideLedger"]["actions"][0]["kind"] in ("partner", "customer")
    real_only = client.get("/api/host/overview?real_only=true", auth=admin).json()["companies"]
    assert all(c["crowd"]["n"] == 0 for c in real_only)


def test_live_round(client, admin):
    live_dive = next(d for d in client.get("/api/host/dives", auth=admin).json() if d["mode"] == "live")
    dive_id = live_dive["id"]
    phones = [new_player(client) for _ in range(3)]
    post = lambda action: client.post("/api/host/live", json={"action": action, "dive_id": dive_id}, auth=admin)

    assert post("start").json()["phase"] == "lobby"
    assert post("open").json()["phase"] == "open"
    states = [p.get("/api/live/state").json() for p in phones]
    assert len({s["card"]["id"] for s in states}) == 1
    cid = states[0]["card"]["id"]
    for p in phones:
        assert answer(p, dive_id, cid).status_code == 200
    assert phones[0].get("/api/live/state").json()["voted"] is True
    post("lock")
    assert answer(new_player(client), dive_id, cid).status_code == 409  # too late
    post("reveal")
    wall = client.get("/api/live/wall").json()
    assert wall["phase"] == "revealed" and wall["reveal"]["room"]["n"] == 3
    # Phones only get results when the whole set is over.
    assert phones[0].get(f"/api/dive/{dive_id}/results").status_code == 403
    for _ in range(5):
        st = post("next").json()
    assert st["phase"] == "final"
    assert len(client.get("/api/live/wall").json()["cards"]) == 5
    r = phones[0].get(f"/api/dive/{dive_id}/results").json()
    assert len(r["cards"]) == 1 and r["total"] == 5


def test_live_timer_locks_voting(client, admin, monkeypatch):
    live_dive = next(d for d in client.get("/api/host/dives", auth=admin).json() if d["mode"] == "live")
    client.post("/api/host/live", json={"action": "start", "dive_id": live_dive["id"]}, auth=admin)
    client.post("/api/host/live", json={"action": "open"}, auth=admin)
    monkeypatch.setattr(config, "LIVE_SECONDS", -1)
    assert client.get("/api/live/state").json()["phase"] == "locked"


def test_qr_is_svg(client):
    r = client.get("/qr?path=/live")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg")
