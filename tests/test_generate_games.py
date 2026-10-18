"""The Game page queues the next games by itself: on the next free days, rotating the in-game companies fairly."""
from collections import Counter
from datetime import date, timedelta


def dives(client, admin):
    return client.get("/api/host/dives", auth=admin).json()


def test_generates_on_the_next_free_days_and_rotates_companies(client, admin):
    before = dives(client, admin)
    shown = Counter(i for d in before for i in d["company_ids"])
    active = [c["id"] for c in client.get("/api/admin/companies?pool=current", auth=admin).json() if c["active"]]
    taken = {d["date"] for d in before}

    r = client.post("/api/admin/dives/generate", json={"count": 3, "cards": 5}, auth=admin)
    assert r.status_code == 200
    made = r.json()
    assert len(made) == 3
    free, day = [], date.today()
    while len(free) < 3:
        if day.isoformat() not in taken:
            free.append(day.isoformat())
        day += timedelta(days=1)
    assert [d["date"] for d in made] == free  # the first days without a game, in order
    for d in made:
        assert len(set(d["company_ids"])) == 5 and set(d["company_ids"]) <= set(active)
    # The least-shown companies go first.
    least = min(shown.get(i, 0) for i in active)
    first_pick = [i for i in active if shown.get(i, 0) == least]
    assert set(made[0]["company_ids"]) >= set(first_pick[:5]) or set(made[0]["company_ids"]) <= set(first_pick)
    labels = [d["label"] for d in made]
    assert len(set(labels)) == 3 and all(lbl.startswith("#") for lbl in labels)

    again = client.post("/api/admin/dives/generate", json={"count": 2}, auth=admin).json()
    assert min(d["date"] for d in again) > max(d["date"] for d in made)  # never on a day that has a game


def test_needs_companies_in_the_game(client, admin):
    for c in client.get("/api/admin/companies?pool=current", auth=admin).json():
        client.put(f"/api/admin/companies/{c['id']}", json={"name": c["name"], "active": False}, auth=admin)
    r = client.post("/api/admin/dives/generate", json={"count": 2}, auth=admin)
    assert r.status_code == 409 and "activate" in r.json()["detail"]
    assert client.post("/api/admin/dives/generate", json={"count": 0}, auth=admin).status_code == 422


def live_with(client, admin, n):
    """Live mode with n real startups in the game."""
    from app.db import connect, now
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)
    db = connect()
    ids = [db.execute("INSERT INTO companies (name, name_key, one_liner, is_real, active, created_at) VALUES (?, ?, 'x', 1, 1, ?)",
                      (f"Real{i}", f"real{i}", now())).lastrowid for i in range(n)]
    db.commit()
    db.close()
    return ids


def test_live_startups_play_one_day_only(client, admin):
    ids = live_with(client, admin, 12)
    made = client.post("/api/admin/dives/generate", json={"count": 5, "cards": 5}, auth=admin).json()
    assert len(made) == 3  # 12 startups: two full games and one of two, then they've all had their day
    used = [i for d in made for i in d["company_ids"]]
    assert sorted(used) == sorted(ids)
    assert client.get("/api/host/game-pool", auth=admin).json()["eligible"] == []
    r = client.post("/api/admin/dives/generate", json={"count": 1}, auth=admin)
    assert r.status_code == 409 and "had its day" in r.json()["detail"]


def test_a_major_update_brings_a_startup_back_once(client, admin):
    from app.db import connect, now
    ids = live_with(client, admin, 5)
    client.post("/api/admin/dives/generate", json={"count": 1}, auth=admin)
    db = connect()
    db.execute("UPDATE companies SET major_update_at = ? WHERE id = ?", (now(), ids[0]))
    db.commit()
    db.close()
    pool = client.get("/api/host/game-pool", auth=admin).json()
    assert pool["eligible"] == [ids[0]] and pool["updated"] == [ids[0]]
    made = client.post("/api/admin/dives/generate", json={"count": 3}, auth=admin).json()
    assert [d["company_ids"] for d in made] == [[ids[0]]]


def test_a_game_queued_by_hand_can_hold_more_than_five(client, admin):
    companies = client.get("/api/admin/companies?pool=current", auth=admin).json()[:8]
    r = client.post("/api/admin/dives", json={"label": "Ocean week", "company_ids": [c["id"] for c in companies]},
                    auth=admin)
    assert r.status_code == 200
    cards = client.get(f"/api/host/dives/{r.json()['id']}", auth=admin).json()["cards"]
    assert [c["name"] for c in cards] == [c["name"] for c in companies]  # all eight, in the order picked
    # Each startup once, and at most 20 of them.
    twice = [companies[0]["id"], companies[1]["id"], companies[0]["id"]]
    assert client.post("/api/admin/dives", json={"label": "Twice", "company_ids": twice}, auth=admin).status_code == 422
    many = list(range(1, 22))
    assert client.post("/api/admin/dives", json={"label": "Too many", "company_ids": many}, auth=admin).status_code == 422
