"""Staff accounts: moderators reset members' passwords and moderate; admins get the whole host tool from their login.
Admins are the accounts ADMINS in .env names, and only those."""
from fastapi.testclient import TestClient

from app import accounts, config
from app.db import connect
from tests.conftest import apply, join, new_player, staff, user_id


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


HOST_TOOL = ("/host", "/game", "/admin", "/api/host/radar", "/api/admin/companies")


def promote(client, username, on=True, auth=None):
    return client.put(f"/api/mod/users/{user_id(client, username)}/moderator", json={"moderator": on},
                      auth=auth or staff())


def set_admins(monkeypatch, admins):
    """ADMINS in .env, as the next start reads it. Returns what couldn't be set up."""
    monkeypatch.setattr(config, "ADMINS", admins)
    with connect() as db:
        return accounts.ensure_admins(db)


def test_a_moderator_gets_moderation_only(client, moderator):
    mod = TestClient(client.app)
    assert mod.post("/api/account/login", json={"username": moderator[0], "password": moderator[1]}).status_code == 200
    assert mod.get("/moderate").status_code == 200
    for path in HOST_TOOL:
        assert mod.get(path).status_code == 401, path


def test_an_admin_account_gets_the_whole_tool(client, monkeypatch):
    join(new_player(client), "ada", "adapass1")
    assert set_admins(monkeypatch, {"ada": ""}) == []
    ada = TestClient(client.app)
    r = ada.post("/api/account/login", json={"username": "ada", "password": "adapass1"})
    assert r.json()["user"]["is_admin"] is True and r.json()["user"]["is_moderator"] is False
    for path in HOST_TOOL:
        assert ada.get(path).status_code == 200, path
        assert client.get(path, auth=("ada", "adapass1")).status_code == 200, path  # or at the prompt
    # On /moderate an admin account has the admin's powers, under its own name.
    assert ada.get("/api/mod/users").json()["viewer"] == {"name": "ada", "admin": True}
    join(new_player(client), "bodil")
    assert promote(client, "bodil", auth=("ada", "adapass1")).status_code == 200
    # Out of ADMINS, they lose it from the next start on.
    set_admins(monkeypatch, {})
    assert ada.get("/host").status_code == 401 and ada.get("/api/mod/users").status_code == 401


def test_nothing_on_the_site_makes_an_admin(client, moderator):
    join(new_player(client), "pia")
    uid = user_id(client, "pia")
    for auth in (staff(), moderator):
        assert client.put(f"/api/mod/users/{uid}/admin", json={"admin": True}, auth=auth).status_code == 404
    assert not any(u["is_admin"] for u in client.get("/api/mod/users", auth=staff()).json()["users"])


def test_admins_from_env_get_their_accounts(client, monkeypatch):
    # With a password, the account is made (and its password kept to it); a listed account that was waiting is let in.
    apply(new_player(client), "waiting1")
    problems = set_admins(monkeypatch, {"boss": "bosspass", "waiting1": "", "ghost": ""})
    assert len(problems) == 1 and "'ghost'" in problems[0]
    c = TestClient(client.app)
    assert c.post("/api/account/login", json={"username": "boss", "password": "bosspass"}).json()["user"]["is_admin"]
    assert c.post("/api/account/login", json={"username": "waiting1", "password": "pass1234"}).json()["user"]["is_admin"]
    set_admins(monkeypatch, {"boss": "newboss1", "waiting1": "", "ghost": ""})
    assert c.post("/api/account/login", json={"username": "boss", "password": "newboss1"}).status_code == 200
    # Nobody can sign up with a listed name, whatever the case.
    for name in ("ghost", "GHOST"):
        r = join(new_player(client), name)
        assert r.status_code == 400 and r.json()["detail"] == "That username is taken."


def test_admin_accounts_are_deleted_in_env_only(client, monkeypatch, moderator):
    join(new_player(client), "ada", "adapass1")
    set_admins(monkeypatch, {"ada": ""})
    uid = user_id(client, "ada")
    assert client.delete(f"/api/mod/users/{uid}", auth=staff()).status_code == 403
    assert client.delete(f"/api/admin/users/{uid}", auth=staff()).status_code == 403
    ada = TestClient(client.app)
    ada.post("/api/account/login", json={"username": "ada", "password": "adapass1"})
    assert ada.delete("/api/account").status_code == 403
    set_admins(monkeypatch, {})
    assert client.delete(f"/api/mod/users/{uid}", auth=staff()).status_code == 200


def test_roles_are_independent_and_only_admins_grant_them(client, monkeypatch, moderator):
    join(new_player(client), "both")
    promote(client, "both")
    set_admins(monkeypatch, {"both": ""})
    r = promote(client, "both", on=False)
    assert r.json()["is_admin"] is True and r.json()["is_moderator"] is False
    join(new_player(client), "pia")
    assert promote(client, "pia", auth=moderator).status_code == 403
    # A moderator can't touch an admin's account either.
    uid = user_id(client, "both")
    assert client.put(f"/api/mod/users/{uid}/password", json={"password": "x1234"}, auth=moderator).status_code == 403


def test_players_and_guests_get_the_sign_in_page(client):
    guest = new_player(client)
    r = guest.get("/api/host/radar")
    assert r.status_code == 401 and "www-authenticate" not in r.headers  # no browser password popup
    for path in ("/host", "/game", "/admin", "/moderate", "/review"):
        r = guest.get(path)
        assert r.status_code == 401 and 'id="login"' in r.text, path
    pia = new_player(client)
    join(pia)
    assert pia.get("/host").status_code == 401
    assert pia.get("/api/admin/companies", auth=("x", "wrong")).status_code == 401
    assert pia.get("/api/admin/companies", auth=staff()).status_code == 200


def staff_login(c, username, password, need="admin"):
    return c.post("/api/staff/login", json={"username": username, "password": password, "need": need})


def test_the_admin_password_signs_in_and_out(client):
    c = TestClient(client.app)
    assert staff_login(c, "", "wrong").status_code == 401
    assert staff_login(c, "", "secret").json() == {"user": None, "admin": True}
    for path in HOST_TOOL + ("/moderate",):
        assert c.get(path).status_code == 200, path
    assert c.get("/api/mod/users").json()["viewer"] == {"name": "admin", "admin": True}
    c.post("/api/staff/logout")
    assert c.get("/host").status_code == 401


def test_a_staff_account_signs_in_as_itself(client, monkeypatch, moderator):
    join(new_player(client), "ada", "adapass1")
    set_admins(monkeypatch, {"ada": ""})
    c = TestClient(client.app)
    assert staff_login(c, "ada", "adapass1").json()["user"]["username"] == "ada"
    assert c.get("/host").status_code == 200
    assert c.get("/api/mod/users").json()["viewer"] == {"name": "ada", "admin": True}
    # A moderator signs in for moderation, but not for the dashboard.
    m = TestClient(client.app)
    r = staff_login(m, *moderator)
    assert r.status_code == 403 and "admin" in r.json()["detail"]
    assert staff_login(m, *moderator, need="moderator").status_code == 200
    assert m.get("/moderate").status_code == 200 and m.get("/host").status_code == 401
    # A plain member can't sign in here at all.
    join(new_player(client), "pia", "pass1234")
    assert staff_login(TestClient(client.app), "pia", "pass1234", need="moderator").status_code == 403


def test_signing_in_as_a_moderator_ends_the_admin_password_sign_in(client, moderator):
    c = TestClient(client.app)
    staff_login(c, "", "secret")
    assert staff_login(c, *moderator, need="moderator").status_code == 200
    assert c.get("/api/mod/users").json()["viewer"] == {"name": "mira", "admin": False}
    assert c.get("/host").status_code == 401
