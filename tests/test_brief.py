"""The reviewers read a short brief the cheap model writes, not the whole profile: written once, rewritten only when
the profile behind it changes, and the full profile whenever no brief can be written."""
import pytest

from app import brief, config, reads, service
from app.db import connect
from app.crawler import pitch


@pytest.fixture
def cheap(client, monkeypatch):
    """A key set and the cheap model faked, recording what it was asked to condense."""
    asked = []
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")

    def post(name, schema, messages, task="card"):
        assert task == "brief" and name == "brief"
        asked.append(messages[1]["content"])
        return {"brief": "Dries Baltic seaweed into cattle feed; trials cut methane 12-18%; three paying co-ops."}
    monkeypatch.setattr(pitch, "_post", post)
    return asked


def rakko(client, admin):
    return next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["name"] == "Rakko Feed")


def test_reviewers_rate_the_brief_not_the_whole_profile(client, admin, cheap, monkeypatch):
    seen = {}

    def rate_all(comp, only=None, brief=None):
        seen["brief"] = brief
        return {}
    monkeypatch.setattr(reads, "rate_all", rate_all)
    cid = rakko(client, admin)["id"]
    client.post(f"/api/admin/companies/{cid}/reads/ai", auth=admin)
    assert seen["brief"].startswith("Name: Rakko Feed\nDries Baltic seaweed")
    assert "Vision:" in cheap[0] and "Evidence scores" in cheap[0]  # condensed from the full profile and evidence
    db = connect()
    assert len(seen["brief"]) < len(reads.profile_text(service.get_company(db, cid)))
    db.close()


def test_the_brief_is_kept_until_the_profile_changes(client, admin, cheap):
    db = connect()
    comp = lambda: db.execute("SELECT * FROM companies WHERE name = 'Rakko Feed'").fetchone()
    first = brief.for_review(db, comp())
    assert brief.for_review(db, comp()) == first and len(cheap) == 1  # asked once
    db.execute("UPDATE companies SET raised_eur = 900000 WHERE name = 'Rakko Feed'")
    db.commit()
    brief.for_review(db, comp())
    assert len(cheap) == 2 and "900 000" in cheap[1]  # the new figure, so a fresh brief
    db.close()


def test_without_a_key_or_on_failure_the_reviewers_read_the_profile(client, admin, monkeypatch):
    db = connect()
    comp = db.execute("SELECT * FROM companies WHERE name = 'Rakko Feed'").fetchone()
    assert brief.for_review(db, comp) == reads.profile_text(comp)  # no key
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")  # conftest's _post fails like a dead network
    assert brief.for_review(db, comp) == reads.profile_text(comp)
    db.close()


def test_review_calls_are_kept_small():
    assert reads.RATE_MAX_TOKENS <= 1200 and reads.SOCIAL_SEARCHES == 2
    assert len(reads.RATE_SYSTEM) < 700  # sent with every review
