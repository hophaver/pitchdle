import csv
import io


from app import config
from tests.conftest import new_player, sign_up

GUESS = {"novel": 3, "useful": 3, "plausible": 3, "investable": 3}


def today(c):
    return c.get("/api/dive/today").json()


def answer(c, dive_id, cid, scores=GUESS):
    return c.post("/api/vote", json={"dive_id": dive_id, "company_id": cid, "scores": scores})


def test_cards_show_everything_but_the_crowd_and_the_engine(client):
    card = today(client)["cards"][0]
    assert set(card) == {"id", "name", "emoji", "sector", "one_liner", "claim_ask", "is_real",
                         "vision", "website", "stages", "raised_eur", "investors", "opinions", "quiet"}
    assert not any(t["key"] in ("you", "crowd") for t in card["opinions"])  # the crowd waits for the results


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
    # "Everyone" leaves out the player's own answer, so a lone player has no one to compare with.
    assert first["crowd"]["n"] == 0 and first["crowd"]["means"] is None and first["lean"] is None
    assert "engine" not in first  # players never see the engine
    assert [o["key"] for o in first["opinions"]] == ["you"]  # nobody else's read yet
    assert 0 < r["next_set_in"] <= 24 * 3600  # countdown to tomorrow's set


def test_everyone_is_the_average_of_other_players(client):
    data = today(client)
    dive_id, cards = data["dive"]["id"], data["cards"]
    for score, c in ((3, new_player(client)), (4, new_player(client))):
        for card in cards:
            answer(c, dive_id, card["id"], {**GUESS, "novel": score})
    for card in cards:
        answer(client, dive_id, card["id"], {**GUESS, "novel": 0})
    first = client.get(f"/api/dive/{dive_id}/results").json()["cards"][0]
    assert first["crowd"]["n"] == 2
    assert first["crowd"]["means"]["novel"] == 3.5  # (3 + 4) / 2, my own 0 left out


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


def test_host_overview_carries_readiness_thesis_and_factors_without_any_votes(client, admin):
    data = client.get("/api/host/overview", auth=admin).json()
    comps = data["companies"]
    assert len(comps) >= 1
    for c in comps:
        # Every readiness level is present and labeled (scores can be None when unevidenced).
        assert set(c["readiness"]) == {"ocean_impact", "business", "tech", "investment"}
        assert all("label" in v for v in c["readiness"].values())
        # Both theses present with a why; a scored example is non-empty.
        assert set(c["theses"]) == {"apelago", "redstone"}
        assert all("description" in v and "why" in v for v in c["theses"].values())
        assert isinstance(c["factors"], list)
    # No one has played yet (fresh test DB) -> the dashboard is still a full evidence-based read.
    assert all(c["crowd"]["n"] == 0 for c in comps)
    # Seed data has evidence, so at least one company has both theses scored.
    assert any(c["theses"]["redstone"]["score"] is not None and c["theses"]["apelago"]["score"] is not None
               for c in comps)
    by_name = {c["name"]: c for c in comps}
    # The thesis read alone puts the boring-but-solid case above the pure-story one.
    assert by_name["Rakko Feed"]["theses"]["redstone"]["score"] > by_name["TideLedger"]["theses"]["redstone"]["score"]
    assert by_name["Rakko Feed"]["evidence_note"]
    # A weak thesis fit lowers an action's score but never claims it "fits".
    assert not any("thesis" in b for a in by_name["TideLedger"]["actions"] for b in a["boosted"])


def test_csv_export_includes_readiness_and_thesis_columns(client, admin):
    rows = list(csv.DictReader(io.StringIO(client.get("/api/admin/export.csv", auth=admin).text)))
    for col in ("ocean_impact", "business_ready", "tech_trl", "investment_ready", "thesis_apelago", "thesis_redstone"):
        assert col in rows[0]
    rakko = next(r for r in rows if r["company"] == "Rakko Feed")
    assert rakko["tech_trl"] == "8" and float(rakko["thesis_redstone"]) >= 3.8


def test_demo_votes_reorder_thesis_aware_actions(client, admin):
    live_dive = next(d for d in client.get("/api/host/dives", auth=admin).json() if d["mode"] == "live")
    client.post("/api/admin/demo-votes", json={"dive_id": live_dive["id"], "players": 30}, auth=admin)
    by_name = {c["name"]: c for c in client.get("/api/host/overview", auth=admin).json()["companies"]}
    # Rakko Feed is strong on fundamentals -> its investor should be the top action, and it should
    # also carry a thesis fit that pushed it there.
    assert by_name["Rakko Feed"]["theses"]["redstone"]["score"] >= 3.8
    assert by_name["Rakko Feed"]["actions"][0]["kind"] == "investor"
    assert any("thesis" in b for b in by_name["Rakko Feed"]["actions"][0]["boosted"])


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


PITCH = {"name": "BrineWorks", "sector": "desalination",
         "one_liner": "A solar raft that turns seawater into drinking water.",
         "claim_ask": "€500k to build ten more rafts", "website": "brineworks.example"}


def test_submit_startup_goes_to_review(client, admin):
    client.get("/api/me")
    assert client.post("/api/submit", json={**PITCH, "name": "  Brine\nWorks  "}).status_code == 200
    subs = client.get("/api/admin/submissions", auth=admin).json()
    assert len(subs) == 1
    assert subs[0]["name"] == "Brine Works"  # one line, single spaces
    assert subs[0]["website"] == "https://brineworks.example"
    comp = client.post(f"/api/admin/submissions/{subs[0]['id']}/approve", auth=admin).json()
    assert comp["is_real"] and not comp["active"]  # host adds evidence before it goes in rotation
    assert client.get("/api/admin/submissions", auth=admin).json() == []


def test_submit_limits(client):
    client.get("/api/me")
    bad = [
        {"one_liner": "x" * 91},
        {"one_liner": "too short"},
        {"name": ""},
        {"claim_ask": "see https://spam.example"},
        {"website": "javascript:alert(1)"},
        {"website": "not a link"},
        {"website": "https://user:pw@example.com"},
    ]
    for patch in bad:
        assert client.post("/api/submit", json={**PITCH, **patch}).status_code == 422, patch
    for _ in range(3):
        assert client.post("/api/submit", json=PITCH).status_code == 200
    assert client.post("/api/submit", json=PITCH).status_code == 429


def test_submissions_need_admin(client):
    assert client.get("/api/admin/submissions").status_code == 401


# --- accounts ---------------------------------------------------------------------------------------

def earlier_daily(c, admin):
    return next(d for d in c.get("/api/host/dives", auth=admin).json() if d["mode"] == "daily" and d["label"] == "#1")


def test_guests_only_get_todays_set(client, admin):
    client.get("/api/me")
    old = earlier_daily(client, admin)
    assert client.get(f"/api/dive/{old['id']}").status_code == 401
    assert answer(client, old["id"], old["company_ids"][0]).status_code == 401
    assert sign_up(client).status_code == 200
    assert client.get("/api/me").json()["user"]["username"] == "maija"
    assert client.get(f"/api/dive/{old['id']}").status_code == 200
    assert answer(client, old["id"], old["company_ids"][0]).status_code == 200


def test_guest_answers_move_to_account_on_login(client):
    sign_up(new_player(client), "kalle")  # account made on another device
    data = today(client)
    dive_id, cards = data["dive"]["id"], data["cards"]
    for card in cards[:2]:
        answer(client, dive_id, card["id"])
    r = client.post("/api/account/login", json={"username": "KALLE", "password": "pass1234"})
    assert r.status_code == 200 and r.json()["claimed"] == 2
    assert len(today(client)["answered"]) == 2
    client.post("/api/account/logout")
    assert client.get("/api/me").json()["user"] is None
    assert today(client)["answered"] == []  # back to an empty guest
    assert client.post("/api/account/login", json={"username": "kalle", "password": "nope"}).status_code == 401


def test_register_rules(client):
    client.get("/api/me")
    assert sign_up(client, "x").status_code == 400
    assert sign_up(client, "has space").status_code == 400
    assert sign_up(client, "ok_name", "abc").status_code == 400
    assert sign_up(client, "ok_name").status_code == 200
    assert sign_up(new_player(client), "OK_NAME").status_code == 400  # taken, any case


def test_history_and_streak(client, admin):
    client.get("/api/me")
    assert client.get("/api/account/history").status_code == 401
    sign_up(client)
    dives = [d for d in client.get("/api/host/dives", auth=admin).json() if d["mode"] == "daily"]
    for d in dives:  # #1, #2 and #3: three days running up to today
        for cid in d["company_ids"]:
            answer(client, d["id"], cid)
    h = client.get("/api/account/history").json()
    assert [s["label"] for s in h["sets"]] == ["#3", "#2", "#1"]
    assert all(s["done"] for s in h["sets"]) and h["sets"][0]["today"]
    assert h["stats"]["sets"] == 3 and h["stats"]["streak"] == 3 and h["stats"]["best_streak"] == 3
    assert h["stats"]["cards"] == 15


def test_delete_account_removes_its_answers(client):
    data = today(client)
    sign_up(client)
    answer(client, data["dive"]["id"], data["cards"][0]["id"])
    assert client.delete("/api/account").status_code == 200
    assert client.get("/api/me").json()["user"] is None
    other = new_player(client)
    for card in data["cards"]:
        answer(other, data["dive"]["id"], card["id"])
    assert other.get(f"/api/dive/{data['dive']['id']}/results").json()["cards"][0]["crowd"]["n"] == 0


def test_moderators_list_and_delete_users(client, moderator):
    assert client.get("/api/mod/users").status_code == 401
    sign_up(new_player(client), "a_user")
    sign_up(new_player(client), "b_user")
    names = lambda: {u["username"]: u["id"] for u in client.get("/api/mod/users", auth=moderator).json()["users"]}
    users = names()
    assert {"a_user", "b_user"} <= set(users)
    assert client.delete(f"/api/mod/users/{users['a_user']}", auth=moderator).status_code == 200
    assert "a_user" not in names() and "b_user" in names()
    assert client.delete(f"/api/mod/users/{users['a_user']}", auth=moderator).status_code == 404


def test_guests_count_for_less_than_signed_in_players(client):
    data = today(client)
    dive_id, cards = data["dive"]["id"], data["cards"]
    user = new_player(client)
    sign_up(user)
    for card in cards:
        answer(user, dive_id, card["id"], {**GUESS, "novel": 5})
    bots = [new_player(client) for _ in range(6)]
    for bot in bots:
        for card in cards:
            answer(bot, dive_id, card["id"], {**GUESS, "novel": 0})
    for card in cards:
        answer(client, dive_id, card["id"])
    crowd = client.get(f"/api/dive/{dive_id}/results").json()["cards"][0]["crowd"]
    assert crowd["n"] == 7
    # Six guest bots at 0 and one signed-in player at 5: guests are capped at GUEST_MAX_SHARE of the score.
    assert crowd["means"]["novel"] == round(5 * (1 - config.GUEST_MAX_SHARE), 2)


def test_only_the_test_account_can_reset_its_data(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "TEST_USERNAME", "tester")
    monkeypatch.setattr(config, "TEST_PASSWORD", "test1234")
    with TestClient(app) as c:
        data = today(c)
        r = c.post("/api/account/login", json={"username": "tester", "password": "test1234"})
        assert r.status_code == 200 and r.json()["user"]["is_test"]
        for card in data["cards"]:
            answer(c, data["dive"]["id"], card["id"])
        assert c.post("/api/account/reset").json()["removed"] == 5
        assert today(c)["answered"] == []
        other = new_player(c)
        sign_up(other)
        assert other.post("/api/account/reset").status_code == 403


def test_pulse_run_all_survives_a_failing_company(client, admin, monkeypatch):
    from app.crawler import pulse
    names = [c["name"] for c in client.get("/api/admin/companies", auth=admin).json() if c["active"]]
    bad = names[0]

    def feed(name, limit):
        if name == bad:
            raise OSError("feed down")
        return [{"title": f"{name} raises €1M", "link": "https://example.com", "published": None}]
    monkeypatch.setattr(pulse, "FEEDS", {"news.google": feed})

    r = client.post("/api/admin/pulse/run-all", json={"active_only": True}, auth=admin)
    assert r.status_code == 200
    out = r.json()
    assert out["ran"] == len(names) and out["skipped"] == 0
    assert [e["name"] for e in out["errors"]] == [bad]

    overview = {c["name"]: c for c in client.get("/api/host/overview", auth=admin).json()["companies"]}
    assert overview[bad]["pulse"]["lean"] == "silent"
    assert overview[names[1]]["pulse"]["lean"] == "positive"
    assert all(c["verdict"] in ("convergent", "divergent", "unknown") and c["verdict_reason"] for c in overview.values())
    assert "verdict" in client.get("/api/admin/export.csv", auth=admin).text.splitlines()[0]


def test_pulse_run_one(client, admin, monkeypatch):
    from app.crawler import pulse
    monkeypatch.setattr(pulse, "FEEDS", {"news.google": lambda n, l: []})
    cid = client.get("/api/admin/companies", auth=admin).json()[0]["id"]
    assert client.post(f"/api/admin/pulse/run/{cid}", auth=admin).json()["coverage"] == "silent"
    assert client.post("/api/admin/pulse/run/999999", auth=admin).status_code == 404
