import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret")
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
