import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture(autouse=True)
def no_test_accounts(monkeypatch):
    """Tests don't depend on a local .env: no test account or test moderator unless a test sets its own."""
    for name in ("TEST_USERNAME", "TEST_PASSWORD", "TEST_MODERATOR_USERNAME", "TEST_MODERATOR_PASSWORD"):
        monkeypatch.setattr(config, name, "")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret")
    # Same for the demo/live settings: start in demo, and never crawl in the background during tests.
    monkeypatch.setattr(config, "APP_MODE", "demo")
    monkeypatch.setattr(config, "DISCOVER_AUTO", False)
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin():
    return ("host", "secret")


@pytest.fixture
def moderator(client):
    """A moderator account, made the way an admin would: sign up, approve, promote. Its login works as Basic auth."""
    sign_up(new_player(client), "mira")
    client.put(f"/api/mod/users/{user_id(client, 'mira')}/moderator", json={"moderator": True}, auth=staff())
    return ("mira", "pass1234")


def new_player(client):
    """A separate device: fresh client sharing the app but with its own cookie jar."""
    c = TestClient(client.app)
    c.get("/api/me")
    return c


# A sign-up that passes the form. Tests override single fields with keyword arguments.
PROFILE = {"full_name": "Maija Virtanen", "email": "maija@example.com", "role": "investor",
           "motivation": "I back early ocean startups and want to see how my reads compare with the crowd.",
           "linkedin": "https://www.linkedin.com/in/maija"}


def staff():
    """The admin password, which also opens moderation. Read at call time: some tests set up their own app."""
    return ("staff", config.ADMIN_PASSWORD)


def apply(c, username="maija", password="pass1234", **profile):
    """Send a sign-up. It waits for a moderator and doesn't log in."""
    return c.post("/api/account/register", json={"username": username, "password": password, **PROFILE, **profile})


def user_id(c, username):
    users = c.get("/api/mod/users", auth=staff()).json()["users"]
    return next(u["id"] for u in users if u["username"].lower() == username.lower())


def sign_up(c, username="maija", password="pass1234"):
    """Sign up, have a moderator approve it, then log in. Returns the first response that failed, or the login."""
    r = apply(c, username, password)
    if r.status_code != 200:
        return r
    c.post(f"/api/mod/users/{user_id(c, username)}/review", json={"status": "approved"}, auth=staff())
    return c.post("/api/account/login", json={"username": username, "password": password})
