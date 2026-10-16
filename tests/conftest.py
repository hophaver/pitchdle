import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret")
    # Tests don't depend on a local .env; the test-account test sets its own.
    monkeypatch.setattr(config, "TEST_USERNAME", "")
    monkeypatch.setattr(config, "TEST_PASSWORD", "")
    # Same for the demo/live settings: start in demo, and never crawl in the background during tests.
    monkeypatch.setattr(config, "APP_MODE", "demo")
    monkeypatch.setattr(config, "DISCOVER_AUTO", False)
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin():
    return ("host", "secret")


def new_player(client):
    """A separate device: fresh client sharing the app but with its own cookie jar."""
    c = TestClient(client.app)
    c.get("/api/me")
    return c
