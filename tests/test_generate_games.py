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
