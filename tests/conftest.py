import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture(autouse=True)
def no_local_settings(monkeypatch):
    """Tests don't depend on a local .env: no test accounts, no API keys and default models, unless a test sets its own."""
    for name in ("TEST_USERNAME", "TEST_PASSWORD", "TEST_MODERATOR_USERNAME", "TEST_MODERATOR_PASSWORD",
                 "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY",
                 "CLAUDE_MODEL", "GPT_MODEL", "GROK_MODEL"):
        monkeypatch.setattr(config, name, "")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    # The vote weights at their defaults; a test that saves new ones gets them put back afterwards.
    for name, value in (("PLAYER_WEIGHT", 1.0), ("INVESTOR_WEIGHT", 2.0), ("GUEST_WEIGHT", 0.5), ("GUEST_MAX_SHARE", 0.4)):
        monkeypatch.setattr(config, name, value)


@pytest.fixture(autouse=True)
def no_leftover_runs(monkeypatch):
    """No test starts a real background run (tests that want one make runs synchronous), and each starts with none
    on: one left going would swallow the test's own kick."""
    from app import autoread
    monkeypatch.setattr(autoread, "START", lambda fn: None)
    monkeypatch.setattr(autoread, "_running", False)
    monkeypatch.setattr(autoread, "_again", False)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret")
    # Same for the demo/live settings: start in demo, and never crawl in the background during tests.
    monkeypatch.setattr(config, "APP_MODE", "demo")
    monkeypatch.setattr(config, "DISCOVER_AUTO", False)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")  # no AI calls unless a test stubs them
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def no_openrouter(monkeypatch):
    """No test reaches OpenRouter: a call a test didn't stub fails like a dead network would."""
    from app.crawler import pitch

    def offline(*_args, **_kwargs):
        raise OSError("no network in tests")
    monkeypatch.setattr(pitch, "_post", offline)


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
    """Send an investor's sign-up. It waits for a moderator and doesn't log in."""
    return c.post("/api/account/register",
                  json={"username": username, "password": password, "kind": "investor", **PROFILE, **profile})


def user_id(c, username):
    users = c.get("/api/mod/users", auth=staff()).json()["users"]
    return next(u["id"] for u in users if u["username"].lower() == username.lower())


def join(c, username="pia", password="pass1234"):
    """Sign up as a player: no review, logged in at once."""
    return c.post("/api/account/register", json={"username": username, "password": password, "kind": "player"})


def sign_up(c, username="maija", password="pass1234"):
    """Sign up as an investor, have a moderator approve it, then log in. Returns the first response that failed, or
    the login."""
    r = apply(c, username, password)
    if r.status_code != 200:
        return r
    c.post(f"/api/mod/users/{user_id(c, username)}/review", json={"status": "approved"}, auth=staff())
    return c.post("/api/account/login", json={"username": username, "password": password})
