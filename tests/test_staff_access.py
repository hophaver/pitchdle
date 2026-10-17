"""Staff accounts: moderators reset members' passwords and moderate; admins get the whole host tool from their login."""
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


HOST_TOOL = ("/host", "/game", "/admin", "/api/host/radar", "/api/admin/companies")


def promote(client, username, role, on=True, auth=None):
    return client.put(f"/api/mod/users/{user_id(client, username)}/{role}", json={role: on}, auth=auth or staff())


def test_a_moderator_gets_moderation_only(client, moderator):
    mod = TestClient(client.app)
    assert mod.post("/api/account/login", json={"username": moderator[0], "password": moderator[1]}).status_code == 200
    assert mod.get("/moderate").status_code == 200
    for path in HOST_TOOL:
        assert mod.get(path).status_code == 401, path


def test_an_admin_account_gets_the_whole_tool(client):
    join(new_player(client), "ada", "adapass1")
    assert promote(client, "ada", "admin").json()["is_admin"] is True
    ada = TestClient(client.app)
    r = ada.post("/api/account/login", json={"username": "ada", "password": "adapass1"})
    assert r.json()["user"]["is_admin"] is True and r.json()["user"]["is_moderator"] is False
    for path in HOST_TOOL:
        assert ada.get(path).status_code == 200, path
        assert client.get(path, auth=("ada", "adapass1")).status_code == 200, path  # or at the prompt
    # On /moderate an admin account has the admin's powers, under its own name.
    assert ada.get("/api/mod/users").json()["viewer"] == {"name": "ada", "admin": True}
    join(new_player(client), "bodil")
    assert promote(client, "bodil", "moderator", auth=("ada", "adapass1")).status_code == 200
    # Taking it away ends their access at once.
    promote(client, "ada", "admin", on=False)
    assert ada.get("/host").status_code == 401 and ada.get("/api/mod/users").status_code == 401


def test_roles_are_independent_and_only_admins_grant_them(client, moderator):
    join(new_player(client), "both")
    promote(client, "both", "moderator")
    r = promote(client, "both", "admin")
    assert r.json()["is_admin"] is True and r.json()["is_moderator"] is True
    assert promote(client, "both", "moderator", on=False).json()["is_admin"] is True
    join(new_player(client), "pia")
    assert promote(client, "pia", "admin", auth=moderator).status_code == 403
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


def test_a_staff_account_signs_in_as_itself(client, moderator):
    join(new_player(client), "ada", "adapass1")
    promote(client, "ada", "admin")
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
