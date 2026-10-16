from app import config
from tests.conftest import new_player

GUESS = {"novel": 3, "useful": 3, "plausible": 3, "investable": 3}


def today(c):
    return c.get("/api/dive/today").json()


def test_full_solo_dive_without_network(client):
    data = today(client)
    assert len(data["cards"]) == 5
    assert "engine_axes" not in data["cards"][0] and "facts" not in data["cards"][0]
    dive_id = data["dive"]["id"]
    for card in data["cards"]:
        r = client.post("/api/vote", json={"dive_id": dive_id, "company_id": card["id"], "round": 1, "scores": GUESS})
        assert r.status_code == 200, r.text
        rev = client.get(f"/api/dive/{dive_id}/reveal/{card['id']}").json()
        assert len(rev["you"]["tiles"]) == 4 and rev["company"]["facts"]
        r = client.post("/api/vote", json={"dive_id": dive_id, "company_id": card["id"], "round": 2,
                                           "scores": GUESS, "stuck": True})
        assert r.status_code == 200
    s = client.get(f"/api/dive/{dive_id}/summary").json()
    assert len(s["cards"]) == 5 and s["depth"] > 0 and s["rank"] == 1


def test_answer_key_hidden_until_you_vote(client):
    data = today(client)
    dive_id, cid = data["dive"]["id"], data["cards"][0]["id"]
    assert client.get(f"/api/dive/{dive_id}/reveal/{cid}").status_code == 403
    assert client.get(f"/api/company/{cid}").status_code == 404  # no answer-leaking company endpoint


def test_no_double_votes(client):
    data = today(client)
    body = {"dive_id": data["dive"]["id"], "company_id": data["cards"][0]["id"], "round": 1, "scores": GUESS}
    assert client.post("/api/vote", json=body).status_code == 200
    assert client.post("/api/vote", json=body).status_code == 409


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


def test_room_sheet_and_demo_scenario(client, admin):
    dives = client.get("/api/host/dives", auth=admin).json()
    live_dive = next(d for d in dives if d["mode"] == "live")
    client.post("/api/admin/demo-votes", json={"dive_id": live_dive["id"], "players": 30}, auth=admin)
    board = client.get(f"/api/dive/{live_dive['id']}/leaderboard").json()
    assert board["current"][0]["name"] == "ACE"

    overview = client.get("/api/host/overview", auth=admin).json()["companies"]
    by_name = {c["name"]: c for c in overview}
    assert any(f["key"] == "story" for f in by_name["TideLedger"]["flags"])
    assert any(f["key"] == "substance" for f in by_name["Rakko Feed"]["flags"])
    assert by_name["TideLedger"]["actions"][0]["kind"] in ("partner", "customer")

    # A real player in a daily dive full of demo votes sees a room sheet that adds up.
    data = today(client)
    client.post("/api/admin/demo-votes", json={"dive_id": data["dive"]["id"], "players": 10}, auth=admin)
    cid = data["cards"][0]["id"]
    client.post("/api/vote", json={"dive_id": data["dive"]["id"], "company_id": cid, "round": 1, "scores": GUESS})
    rev = client.get(f"/api/dive/{data['dive']['id']}/reveal/{cid}").json()
    assert rev["sheet"] is not None
    for row in rev["sheet"]["axes"]:
        assert sum(row["share"]) == 100
        assert abs(row["mean"] - rev["room"]["means"][row["axis"]]) < 1e-9


def test_live_round_stays_in_sync(client, admin):
    live_dive = next(d for d in client.get("/api/host/dives", auth=admin).json() if d["mode"] == "live")
    phones = [new_player(client) for _ in range(3)]
    post = lambda action: client.post("/api/host/live", json={"action": action, "dive_id": live_dive["id"]}, auth=admin)

    assert post("start").json()["phase"] == "lobby"
    assert post("open").json()["phase"] == "open"
    states = [p.get("/api/live/state").json() for p in phones]
    assert len({s["card"]["id"] for s in states}) == 1
    cid = states[0]["card"]["id"]
    vote = {"dive_id": live_dive["id"], "company_id": cid, "round": 1, "scores": GUESS}
    for p in phones:
        assert p.post("/api/vote", json=vote).status_code == 200
    # Nobody sees the answer before the host reveals.
    assert phones[0].get(f"/api/dive/{live_dive['id']}/reveal/{cid}").status_code == 403
    post("lock")
    assert new_player(client).post("/api/vote", json=vote).status_code == 409  # too late
    post("reveal")
    assert all(p.get(f"/api/dive/{live_dive['id']}/reveal/{cid}").status_code == 200 for p in phones)
    wall = client.get("/api/live/wall").json()
    assert wall["phase"] == "revealed" and wall["reveal"]["room"]["n"] == 3
    for _ in range(5):
        st = post("next").json()
    assert st["phase"] == "final"
    assert client.get("/api/live/wall").json()["divers"]
    assert phones[0].get(f"/api/dive/{live_dive['id']}/summary").status_code == 200


def test_live_timer_locks_voting(client, admin, monkeypatch):
    live_dive = next(d for d in client.get("/api/host/dives", auth=admin).json() if d["mode"] == "live")
    client.post("/api/host/live", json={"action": "start", "dive_id": live_dive["id"]}, auth=admin)
    client.post("/api/host/live", json={"action": "open"}, auth=admin)
    monkeypatch.setattr(config, "LIVE_SECONDS", -1)
    assert client.get("/api/live/state").json()["phase"] == "locked"


def test_qr_is_svg(client):
    r = client.get("/qr?path=/live")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg")
