"""Moderators: a password reset for any member, and the whole host tool from their normal login."""
from fastapi.testclient import TestClient

from tests.conftest import join, new_player, staff, user_id


def test_a_moderator_resets_a_members_password(client, moderator):
    join(new_player(client), "pia", "oldpass")
    uid = user_id(client, "pia")
    r = client.put(f"/api/mod/users/{uid}/password", json={"password": "newpass1"}, auth=moderator)
    assert r.status_code == 200
    c = TestClient(client.app)
    assert c.post("/api/account/login", json={"username": "pia", "password": "oldpass"}).status_code == 401
    assert c.post("/api/account/login", json={"username": "pia", "password": "newpass1"}).status_code == 200


def test_a_reset_ends_old_logins_and_needs_a_real_password(client, moderator):
    pia = new_player(client)
    join(pia, "pia", "oldpass")
    assert pia.get("/api/me").json()["user"]["username"] == "pia"
    uid = user_id(client, "pia")
    assert client.put(f"/api/mod/users/{uid}/password", json={"password": "ab"}, auth=moderator).status_code == 400
    client.put(f"/api/mod/users/{uid}/password", json={"password": "newpass1"}, auth=moderator)
    assert pia.get("/api/me").json()["user"] is None


def test_only_an_admin_resets_a_moderators_password(client, moderator):
    uid = user_id(client, "mira")
    assert client.put(f"/api/mod/users/{uid}/password", json={"password": "x1234"}, auth=moderator).status_code == 403
    assert client.put(f"/api/mod/users/{uid}/password", json={"password": "x1234"}, auth=staff()).status_code == 200
    assert client.put(f"/api/mod/users/{uid}/password", json={"password": "x1234"}).status_code == 401


def test_a_logged_in_moderator_gets_the_whole_tool(client, admin, moderator):
    mod = TestClient(client.app)
    assert mod.post("/api/account/login", json={"username": moderator[0], "password": moderator[1]}).status_code == 200
    for path in ("/host", "/game", "/admin", "/api/host/radar", "/api/admin/companies"):
        assert mod.get(path).status_code == 200, path


def test_players_and_guests_still_get_the_password_prompt(client):
    guest = new_player(client)
    r = guest.get("/api/host/radar")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    pia = new_player(client)
    join(pia)
    assert pia.get("/host").status_code == 401
    assert pia.get("/api/admin/companies", auth=("x", "wrong")).status_code == 401
    assert pia.get("/api/admin/companies", auth=staff()).status_code == 200
