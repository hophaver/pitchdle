"""Sign-ups wait for a moderator; moderators see how members play; only admins manage moderators."""
from statistics import fmean

from fastapi.testclient import TestClient

from app import accounts, config
from tests.conftest import apply, new_player, sign_up, user_id
from tests.test_api import GUESS, answer, today


def login(c, username="maija", password="pass1234"):
    return c.post("/api/account/login", json={"username": username, "password": password})


def mod_user(client, moderator, username):
    return next(u for u in client.get("/api/mod/users", auth=moderator).json()["users"] if u["username"] == username)


def review(client, moderator, username, status):
    return client.post(f"/api/mod/users/{user_id(client, username)}/review", json={"status": status}, auth=moderator)


def test_sign_ups_wait_for_a_moderator(client, moderator):
    data = today(client)
    for card in data["cards"][:2]:  # played as a guest first
        answer(client, data["dive"]["id"], card["id"])
    r = apply(client)
    assert r.status_code == 200 and r.json() == {"status": "pending"}
    assert client.get("/api/me").json()["user"] is None  # signing up doesn't log in
    r = login(client)
    assert r.status_code == 403 and "moderator" in r.json()["detail"]
    assert login(client, password="wrong").status_code == 401  # the wrong password doesn't learn the status

    pending = mod_user(client, moderator, "maija")
    assert pending["status"] == "pending" and pending["profile"]["email"] == "maija@example.com"
    assert pending["profile"]["links"] == {"linkedin": "https://www.linkedin.com/in/maija"}
    r = review(client, moderator, "maija", "approved")
    assert r.status_code == 200
    member = r.json()
    assert member["status"] == "approved" and "badge" not in member
    assert member["reviewed_by"] == "mira"  # the moderator's own account

    r = login(client)
    assert r.status_code == 200 and r.json()["claimed"] == 2  # guest answers move onto the account
    assert client.get("/api/me").json()["user"]["username"] == "maija"


def test_turned_down_sign_ups_cannot_log_in_until_reconsidered(client, moderator):
    apply(client)
    r = review(client, moderator, "maija", "rejected")
    assert r.json()["status"] == "rejected" and r.json()["reviewed_by"] == "mira"
    r = login(client)
    assert r.status_code == 403 and "didn't approve" in r.json()["detail"]
    assert review(client, moderator, "maija", "approved").status_code == 200
    assert login(client).status_code == 200


def test_review_rules(client, moderator):
    apply(client)
    review(client, moderator, "maija", "approved")
    assert review(client, moderator, "maija", "rejected").status_code == 409  # members get deleted instead
    assert client.put(f"/api/mod/users/{user_id(client, 'maija')}/badge", json={"badge": "high"},
                      auth=moderator).status_code in (404, 405)  # badges are gone
    for call in (lambda: client.post("/api/mod/users/9999/review", json={"status": "approved"}, auth=moderator),
                 lambda: client.delete("/api/mod/users/9999", auth=moderator)):
        assert call().status_code == 404


def test_sign_up_form_rules(client, moderator):
    client.get("/api/me")
    bad = [
        {"full_name": ""},
        {"email": "not-an-email"},
        {"role": "pirate"},
        {"motivation": "too short"},
        {"linkedin": ""},  # no links at all
        {"linkedin": "https://github.com/maija"},  # a LinkedIn link has to be on LinkedIn
        {"github": "https://evil.example/maija"},
        {"cv": "javascript:alert(1)"},
        {"portfolio": "https://user:pw@example.com"},
        {"organisation": "x" * 81},
    ]
    for i, patch in enumerate(bad):
        assert apply(client, f"user{i}", **patch).status_code == 422, patch
    assert apply(client, "x").status_code == 400  # username rules as before

    r = apply(client, full_name="  Maija \n Virtanen ", github="github.com/maija", organisation=" Ocean  Fund ",
              motivation="Line one of why.\r\n\r\n\r\n  Line two.  ")
    assert r.status_code == 200
    profile = mod_user(client, moderator, "maija")["profile"]
    assert profile["full_name"] == "Maija Virtanen" and profile["organisation"] == "Ocean Fund"
    assert profile["motivation"] == "Line one of why.\n\nLine two."  # line breaks kept, blank runs squeezed
    assert profile["links"] == {"linkedin": "https://www.linkedin.com/in/maija", "github": "https://github.com/maija"}
    assert not {"username", "password", "linkedin"} & set(profile)


def test_sign_ups_pause_when_the_queue_is_full(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "MAX_PENDING_SIGNUPS", 1)
    client.get("/api/me")
    assert apply(client, "first").status_code == 200
    assert apply(client, "second").status_code == 503


def test_moderation_needs_a_moderator_account_or_the_admin(client, admin, moderator):
    assert client.get("/moderate").status_code == 401
    assert client.get("/api/mod/users").status_code == 401
    assert client.get("/api/mod/users", auth=("mira", "wrong")).status_code == 401
    r = client.get("/api/mod/users", auth=moderator)
    assert r.status_code == 200 and r.json()["viewer"] == {"name": "mira", "admin": False}
    assert client.get("/moderate", auth=moderator).status_code == 200
    r = client.get("/api/mod/users", auth=admin)  # admins get in with the admin password, any username
    assert r.status_code == 200 and r.json()["viewer"] == {"name": "admin", "admin": True}
    assert client.get("/admin", auth=moderator).status_code == 401  # moderators don't get the host tools
    assert client.get("/api/host/overview", auth=moderator).status_code == 401
    member = new_player(client)
    sign_up(member, "plain")
    assert client.get("/api/mod/users", auth=("plain", "pass1234")).status_code == 401  # members aren't moderators
    assert member.get("/api/mod/users").status_code == 401  # nor is a member's login session


def test_moderators_can_use_their_login_from_the_game(client, moderator):
    device = new_player(client)
    r = login(device, *moderator)
    assert r.status_code == 200 and r.json()["user"]["is_moderator"] is True
    assert device.get("/api/mod/users").json()["viewer"] == {"name": "mira", "admin": False}
    assert device.get("/moderate").status_code == 200
    device.post("/api/account/logout")
    assert device.get("/api/mod/users").status_code == 401


def test_only_admins_manage_moderators(client, admin, moderator):
    sign_up(new_player(client), "maija")
    maija, mira = user_id(client, "maija"), user_id(client, "mira")
    promote = lambda uid, on, auth: client.put(f"/api/mod/users/{uid}/moderator", json={"moderator": on}, auth=auth)
    assert promote(maija, True, moderator).status_code == 403
    r = promote(maija, True, admin)
    assert r.status_code == 200 and r.json()["is_moderator"] is True
    assert client.get("/api/mod/users", auth=("maija", "pass1234")).status_code == 200
    # Moderator accounts, a moderator's own included, are for admins to change.
    for target in (maija, mira):
        assert client.delete(f"/api/mod/users/{target}", auth=moderator).status_code == 403
    # Taking the role away ends their access at once.
    assert promote(maija, False, admin).json()["is_moderator"] is False
    assert client.get("/api/mod/users", auth=("maija", "pass1234")).status_code == 401
    apply(new_player(client), "waiting")
    assert promote(user_id(client, "waiting"), True, admin).status_code == 409  # members only
    assert promote(9999, True, admin).status_code == 404


def test_the_test_moderator_comes_from_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(config, "DISCOVER_AUTO", False)
    monkeypatch.setattr(config, "TEST_MODERATOR_USERNAME", "mod1234")
    monkeypatch.setattr(config, "TEST_MODERATOR_PASSWORD", "moderator")
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/mod/users", auth=("mod1234", "moderator")).json()["viewer"]["name"] == "mod1234"
        assert login(c, "mod1234", "moderator").json()["user"]["is_moderator"] is True
        # Resetting everything brings it straight back, without a restart.
        c.post("/api/admin/reset", json={"scope": "everything"}, auth=("host", "secret"))
        assert c.get("/api/mod/users", auth=("mod1234", "moderator")).status_code == 200


def test_every_member_counts_by_their_kind_alone(client, moderator):
    """Players count 1 each: two opposite players average out, whatever was set on their accounts before."""
    data = today(client)
    dive_id, cards = data["dive"]["id"], data["cards"]
    loud, quiet = new_player(client), new_player(client)
    sign_up(loud, "loud")
    sign_up(quiet, "quiet")
    for card in cards:
        answer(loud, dive_id, card["id"], {**GUESS, "novel": 5})
        answer(quiet, dive_id, card["id"], {**GUESS, "novel": 1})
        answer(client, dive_id, card["id"])  # a guest, so their results show everyone else
    import sqlite3
    with sqlite3.connect(config.DB_PATH) as db:  # a badge left in an old database changes nothing now
        db.execute("UPDATE users SET badge = 'muted' WHERE username = 'loud'")
    crowd = client.get(f"/api/dive/{dive_id}/results").json()["cards"][0]["crowd"]
    assert crowd["n"] == 2 and crowd["means"]["novel"] == 3.0


def test_moderators_see_how_members_play(client, admin, moderator):
    data = today(client)
    member = new_player(client)
    sign_up(member, "flat")
    for card in data["cards"]:
        answer(member, data["dive"]["id"], card["id"])  # 3-3-3-3 every time
    engine = {c["id"]: c["engine_composite"] for c in client.get("/api/admin/companies", auth=admin).json()}
    u = mod_user(client, moderator, "flat")
    assert (u["answers"], u["sets"], u["flat_share"]) == (5, 1, 1.0)
    assert u["engine_gap"] == round(fmean(abs(3.0 - engine[c["id"]]) for c in data["cards"]), 2)
    apply(new_player(client), "newbie")
    newbie = mod_user(client, moderator, "newbie")
    assert newbie["answers"] == 0 and newbie["engine_gap"] is None and newbie["flat_share"] is None


def test_accounts_from_before_review_stay_members(tmp_path, monkeypatch):
    """A database from before sign-up review: its accounts must still log in, as plain members."""
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, "
                "password_hash TEXT NOT NULL, created_at TEXT)")
    old.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                ("veteran", accounts.hash_password("pass1234"), "2026-01-01T00:00:00+00:00"))
    old.commit()
    old.close()
    monkeypatch.setattr(config, "DB_PATH", str(path))
    monkeypatch.setattr(config, "DISCOVER_AUTO", False)
    from app.main import app
    with TestClient(app) as c:
        r = login(c, "veteran")
        assert r.status_code == 200
        u = mod_user(c, ("staff", config.ADMIN_PASSWORD), "veteran")
        assert (u["status"], u["profile"]) == ("approved", {})
