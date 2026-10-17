"""The content rule: live mode never shows a sample company, demo mode never shows a real one. Checked at every
place the game, the wall and the dashboard read companies, and at every write that could mix the pools."""
import pytest

from app.db import connect, dumps, now


def set_mode(client, admin, mode):
    assert client.post("/api/admin/mode", json={"mode": mode}, auth=admin).status_code == 200


@pytest.fixture
def pools(client, admin):
    """Both pools populated: the seeded sample companies, plus two real startups in today's live set."""
    db = connect()
    real = [db.execute("INSERT INTO companies (name, name_key, one_liner, is_real, active, created_at) "
                       "VALUES (?, ?, 'A real pitch.', 1, 1, ?)", (n, n.lower(), now())).lastrowid
            for n in ("Realwave", "Truekelp")]
    sample = [r["id"] for r in db.execute("SELECT id FROM companies WHERE is_real = 0")]
    db.commit()
    db.close()
    return {"real": real, "sample": sample}


def everything_shown(client, admin):
    """Every company a mode puts in front of players or the host, by is_real."""
    shown = []
    shown += [c["is_real"] for c in client.get("/api/host/overview", auth=admin).json()["companies"]]
    shown += [c["is_real"] for c in client.get("/api/dive/today").json()["cards"]]
    shown += [c["is_real"] for c in client.get("/api/admin/companies?pool=current", auth=admin).json()]
    for d in client.get("/api/host/dives", auth=admin).json():
        r = client.get(f"/api/dive/{d['id']}")
        if r.status_code == 200:
            shown += [c["is_real"] for c in r.json()["cards"]]
    return shown


def test_each_mode_shows_only_its_own_pool(client, admin, pools):
    assert everything_shown(client, admin) and not any(everything_shown(client, admin))
    set_mode(client, admin, "live")
    client.post("/api/admin/dives", json={"label": "Real room", "company_ids": pools["real"]}, auth=admin)
    shown = everything_shown(client, admin)
    assert shown and all(shown)


def test_a_set_cannot_mix_pools(client, admin, pools):
    out = client.post("/api/admin/dives", json={"label": "Mixed", "company_ids": [pools["sample"][0], pools["real"][0]]},
                      auth=admin)
    assert out.status_code == 409 and "sample" in out.json()["detail"]
    set_mode(client, admin, "live")
    out = client.post("/api/admin/dives", json={"label": "Mixed", "company_ids": [pools["real"][0], pools["sample"][0]]},
                      auth=admin)
    assert out.status_code == 409 and "real" in out.json()["detail"]


def test_a_set_that_somehow_holds_both_yields_only_its_own(client, admin, pools):
    db = connect()
    mixed = db.execute("INSERT INTO dives (label, company_ids, mode, pool) VALUES ('Old', ?, 'daily', 'demo')",
                       (dumps([pools["real"][0], pools["sample"][0]]),)).lastrowid
    db.commit()
    db.close()
    cards = client.get(f"/api/dive/{mixed}").json()["cards"]
    assert [c["id"] for c in cards] == [pools["sample"][0]]


def test_players_only_reach_the_current_modes_sets(client, admin, pools):
    demo_set = client.get("/api/dive/today").json()
    set_mode(client, admin, "live")
    assert client.get(f"/api/dive/{demo_set['dive']['id']}").status_code == 404
    card = demo_set["cards"][0]
    vote = {"dive_id": demo_set["dive"]["id"], "company_id": card["id"],
            "scores": {"novel": 3, "useful": 3, "plausible": 3, "investable": 3}}
    assert client.post("/api/vote", json=vote).status_code == 404


def test_an_edit_never_moves_a_company_between_pools(client, admin, pools):
    sample = next(c for c in client.get("/api/admin/companies?pool=demo", auth=admin).json())
    body = {k: sample[k] for k in ("name", "sector", "one_liner", "claim_ask", "website", "evidence", "evidence_note")}
    assert client.put(f"/api/admin/companies/{sample['id']}", json=body | {"is_real": True}, auth=admin).json()["is_real"] == 0
    set_mode(client, admin, "live")
    assert sample["id"] not in [c["id"] for c in client.get("/api/host/overview", auth=admin).json()["companies"]]


def test_a_new_company_joins_the_current_modes_pool(client, admin):
    assert client.post("/api/admin/companies", json={"name": "Handmade"}, auth=admin).json()["is_real"] == 0
    set_mode(client, admin, "live")
    assert client.post("/api/admin/companies", json={"name": "Realmade"}, auth=admin).json()["is_real"] == 1
    assert client.get("/api/admin/companies?pool=bogus", auth=admin).status_code == 400
