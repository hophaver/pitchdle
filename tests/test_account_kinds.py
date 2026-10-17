"""Two kinds of account: a player signs up with a username and password and is in at once; an investor gives the
full profile, waits for a moderator, rates the full card and counts for more in crowd scores."""
from app import config, scoring, service
from app.db import connect
from tests.conftest import apply, join, new_player, sign_up, staff, user_id
from tests.test_api import GUESS, answer, today


def test_players_are_in_at_once_and_logged_in(client):
    player = new_player(client)
    r = join(player)
    assert r.status_code == 200
    assert r.json()["user"]["kind"] == "player" and r.json()["status"] == "approved"
    assert player.get("/api/me").json()["user"]["username"] == "pia"
    member = next(u for u in client.get("/api/mod/users", auth=staff()).json()["users"] if u["username"] == "pia")
    assert member["status"] == "approved" and member["kind"] == "player"


def test_a_player_sign_up_needs_only_a_username_and_password(client):
    assert join(new_player(client), "ab").status_code == 400  # too short
    r = new_player(client).post("/api/account/register", json={"username": "pia", "password": "pass1234"})
    assert r.status_code == 200 and r.json()["user"]["kind"] == "player"  # kind left out: a player


def test_investors_wait_for_a_moderator_and_need_the_full_profile(client):
    c = new_player(client)
    r = c.post("/api/account/register", json={"username": "ivy", "password": "pass1234", "kind": "investor"})
    assert r.status_code == 422  # no profile
    assert apply(c, "ivy").json() == {"status": "pending"}
    assert c.post("/api/account/login", json={"username": "ivy", "password": "pass1234"}).status_code == 403
    client.post(f"/api/mod/users/{user_id(client, 'ivy')}/review", json={"status": "approved"}, auth=staff())
    r = c.post("/api/account/login", json={"username": "ivy", "password": "pass1234"})
    assert r.status_code == 200 and r.json()["user"]["kind"] == "investor"


def test_guests_count_least_players_one_and_investors_most(client):
    data = today(client)
    dive_id, cid = data["dive"]["id"], data["cards"][0]["id"]
    guest, player, investor = new_player(client), new_player(client), new_player(client)
    join(player)
    sign_up(investor)
    answer(guest, dive_id, cid, {**GUESS, "novel": 0})
    answer(player, dive_id, cid, {**GUESS, "novel": 2})
    answer(investor, dive_id, cid, {**GUESS, "novel": 5})
    weights = {}
    db = connect()
    try:
        rows = service.card_votes(db, dive_id, cid)
        for row, w in zip(rows, scoring.vote_weights(rows)):
            weights[row["kind"] or "guest"] = w
    finally:
        db.close()
    assert weights["player"] == 1.0
    assert weights["investor"] == config.INVESTOR_WEIGHT == 2.0
    assert weights["guest"] < weights["player"]


def test_a_members_weight_is_their_kind_alone():
    investor = {"user_id": 1, "kind": "investor", "badge": "high"}  # a badge left in an old database is ignored
    player = {"user_id": 2, "kind": "player", "badge": "muted"}
    assert scoring.vote_weights([investor, player]) == [config.INVESTOR_WEIGHT, 1.0]


def test_the_dashboard_shows_the_profile_and_opinions(client, admin):
    c = client.get("/api/host/radar", auth=admin).json()["companies"][0]
    assert {"vision", "stages", "raised_eur", "investors", "opinions", "quiet"} <= set(c)
