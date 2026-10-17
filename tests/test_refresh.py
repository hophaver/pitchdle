"""Update all cards: unchanged sources cost no model call, a change is checked on the default model, and only a major
one re-runs the checklist and the AI reviews, and brings a played startup back into the game."""
import pytest

from app import config, refresh, service
from app.db import connect, j, now


@pytest.fixture
def real(client, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(refresh.pulse, "compute_pulse", lambda name, **_: {"top_hits": []})
    db = connect()
    cid = db.execute("INSERT INTO companies (name, name_key, one_liner, is_real, active, raised_eur, created_at) "
                     "VALUES ('Realwave', 'realwave', 'Wave power.', 1, 1, 100000, ?)", (now(),)).lastrowid
    db.commit()
    yield db, cid
    db.close()


def stub(monkeypatch, sources, answer):
    calls = {"model": 0, "checklist": 0, "reads": 0}
    monkeypatch.setattr(refresh.profile, "gather", lambda comp: (sources["text"], ["website"]))

    def model(_messages):
        calls["model"] += 1
        return answer
    monkeypatch.setattr(refresh, "complete", model)
    monkeypatch.setattr(refresh, "reread", lambda db, comp, src: calls.__setitem__("reads", calls["reads"] + 1))
    return calls


NOTHING = {"changed": False, "major": False, "kinds": [], "summary": "", "raised": None, "stages": [], "investors": [], "vision": ""}


def test_unchanged_sources_cost_no_model_call(real, monkeypatch):
    db, cid = real
    sources = {"text": "Website text\n- Realwave pilots in Turku (2026-10-01)"}
    calls = stub(monkeypatch, sources, NOTHING)
    refresh.run(db)
    assert calls["model"] == 1
    sources["text"] = "- Realwave pilots in Turku (2026-10-02)\nWebsite text"  # reordered, new date: same content
    st = refresh.run(db)
    assert calls["model"] == 1 and st["unchanged"] == 1


def test_a_minor_change_patches_the_card_only(real, monkeypatch):
    db, cid = real
    calls = stub(monkeypatch, {"text": "new text"}, NOTHING | {
        "changed": True, "summary": "Lists a second investor.",
        "investors": [{"name": "Sea Angels", "status": "invested", "amount": None, "currency": "EUR"}],
        "raised": {"amount": 50000, "currency": "EUR"}})  # lower than the card: ignored
    st = refresh.run(db)
    row = db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
    assert st["minor"] == 1 and calls["reads"] == 0
    assert [i["name"] for i in j(row["investors"], [])] == ["Sea Angels"]
    assert row["raised_eur"] == 100000 and row["major_update_at"] is None and "second investor" in row["update_note"]


def test_a_major_update_rereads_and_returns_to_the_game(real, client, admin, monkeypatch):
    db, cid = real
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)
    client.post("/api/admin/dives", json={"label": "Day one", "company_ids": [cid]}, auth=admin)
    assert cid not in service.eligible_ids(db, "live")
    calls = stub(monkeypatch, {"text": "Realwave raises €2M"}, NOTHING | {
        "changed": True, "major": True, "kinds": ["funding"], "summary": "Raised €2M seed.",
        "raised": {"amount": 2000000, "currency": "EUR"}})
    st = refresh.run(db)
    row = db.execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
    assert st["major"] == 1 and calls["reads"] == 1
    assert row["raised_eur"] == 2000000 and row["major_update_at"]
    assert cid in service.eligible_ids(db, "live")


def test_major_needs_a_named_kind(real, monkeypatch):
    db, _ = real
    calls = stub(monkeypatch, {"text": "x"}, NOTHING | {"changed": True, "major": True, "kinds": []})
    assert refresh.run(db)["major"] == 0 and calls["reads"] == 0


def test_the_endpoint_needs_a_key(client, admin, monkeypatch):
    assert client.post("/api/admin/refresh", auth=admin).status_code == 409
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(refresh, "START", lambda fn: None)
    monkeypatch.setattr(refresh, "_running", False)
    assert client.post("/api/admin/refresh", auth=admin).json()["running"] is True
