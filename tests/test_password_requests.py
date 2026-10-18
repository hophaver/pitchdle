"""Forgot password: a member asks for a new one on /play, and a moderator approves or declines it on /moderate."""
from fastapi.testclient import TestClient

from app import main
from app.db import connect
from tests.conftest import apply, join, new_player, staff, user_id


def ask(c, username="pia", password="newpass1", note="I joined on Friday and play every morning."):
    return c.post("/api/account/password-request", json={"username": username, "password": password, "note": note})


def login(c, username="pia", password="pass1234"):
    return c.post("/api/account/login", json={"username": username, "password": password})


def waiting(client, username="pia", auth=None):
    users = client.get("/api/mod/users", auth=auth or staff()).json()["users"]
    return next(u for u in users if u["username"] == username)["password_request"]


def answer(client, rid, status, auth=None):
    return client.post(f"/api/mod/password-requests/{rid}", json={"status": status}, auth=auth or staff())


def test_a_new_password_works_once_a_moderator_approves_it(client, moderator):
    pia = new_player(client)
    join(pia)
    assert ask(TestClient(client.app)).json() == {"status": "pending"}
    asked = waiting(client, auth=moderator)
    assert set(asked) == {"id", "note", "created_at"}  # never the password, not even hashed
    assert asked["note"] == "I joined on Friday and play every morning."
    # Until then the new one says so, and the old one still works.
    c = TestClient(client.app)
    r = login(c, password="newpass1")
    assert r.status_code == 403 and "once a moderator approves it" in r.json()["detail"]
    assert login(c).status_code == 200
    # Approved: the new one opens the account, the old one doesn't, and every login ends.
    assert answer(client, asked["id"], "approved", auth=moderator).json()["password_request"] is None
    assert pia.get("/api/me").json()["user"] is None and c.get("/api/me").json()["user"] is None
    assert login(c).status_code == 401
    assert login(c, password="newpass1").status_code == 200
    assert answer(client, asked["id"], "declined").status_code == 409  # answered already


def test_a_declined_request_changes_nothing(client, moderator):
    join(new_player(client))
    ask(TestClient(client.app))
    assert answer(client, waiting(client)["id"], "declined", auth=moderator).status_code == 200
    assert waiting(client) is None
    c = TestClient(client.app)
    r = login(c, password="newpass1")
    assert r.status_code == 403 and "declined" in r.json()["detail"]
    assert login(c).status_code == 200
    assert login(c, password="guess123").status_code == 401  # other wrong passwords get the plain answer


def test_asking_again_replaces_the_request(client):
    join(new_player(client))
    c = TestClient(client.app)
    ask(c, password="first11")
    ask(c, password="second2", note="")
    asked = waiting(client)
    assert asked["note"] == ""
    answer(client, asked["id"], "approved")
    assert login(c, password="first11").status_code == 401
    assert login(c, password="second2").status_code == 200


def test_a_request_needs_an_account_and_a_real_password(client, monkeypatch):
    c = TestClient(client.app)
    r = ask(c, "nobody")
    assert r.status_code == 400 and "no account" in r.json()["detail"]
    join(new_player(client))
    assert ask(c, password="ab").status_code == 400
    assert ask(c, note="x" * 301).status_code == 422
    # A sign-up still waiting may ask; a turned-down one may not.
    apply(new_player(client), "maija")
    assert ask(c, "maija").status_code == 200
    apply(new_player(client), "rex")
    client.post(f"/api/mod/users/{user_id(client, 'rex')}/review", json={"status": "rejected"}, auth=staff())
    assert ask(c, "rex").status_code == 403
    # Too many waiting and new ones are turned away until the moderators catch up.
    monkeypatch.setattr(main, "MAX_PASSWORD_REQUESTS", 1)  # maija's is waiting
    assert ask(c).status_code == 503


def test_a_staff_accounts_request_is_for_an_admin(client, moderator):
    ask(TestClient(client.app), "mira")
    rid = waiting(client, "mira")["id"]
    assert answer(client, rid, "approved", auth=moderator).status_code == 403  # not even their own
    assert answer(client, rid, "approved").status_code == 200
    assert login(TestClient(client.app), "mira", "newpass1").status_code == 200


def test_a_reset_by_a_moderator_answers_it(client, moderator):
    join(new_player(client))
    ask(TestClient(client.app))
    client.put(f"/api/mod/users/{user_id(client, 'pia')}/password", json={"password": "fromamod"}, auth=moderator)
    assert waiting(client) is None


def test_deleting_the_account_deletes_its_requests(client):
    join(new_player(client))
    ask(TestClient(client.app))
    client.delete(f"/api/mod/users/{user_id(client, 'pia')}", auth=staff())
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM password_requests").fetchone()[0] == 0
