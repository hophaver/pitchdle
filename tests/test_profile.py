"""A real startup's profile filled by AI from its website and news: only what the sources say, only empty fields,
with the evidence scored, on OPENROUTER_MODEL. The model, website and feeds are faked here."""
import json

import pytest

from app import autoread, config, reads
from app.crawler import gate, pitch, profile, pulse, website

REAL_POST = pitch._post  # taken before conftest swaps it for one that fails like a dead network
REAL = {"name": "HydroSight", "sector": "water tech", "one_liner": "Sensors that find leaks in city water pipes.",
        "claim_ask": "", "website": "https://hydrosight.example", "is_real": True, "active": True}
ANSWER = {"vision": "HydroSight puts acoustic sensors in water mains so cities find leaks before pipes burst.",
          "country": "Israel", "raised": {"amount": 5_000_000, "currency": "USD"},
          "stages": ["Seed round: $5M (2025)"],
          "investors": [{"name": "Blue Fund", "status": "invested", "amount": 3_000_000, "currency": "USD"},
                        {"name": "Wave Angels", "status": "interested", "amount": None, "currency": ""}],
          "evidence": {"trl_stage": "pilot", "patents": None, "basis": "City pilot in Haifa; $5M seed.",
                       "impact": {"measurability": 3, "problem_pressure": 4, "solution_potential": 3.5},
                       "brl": {"market": 3, "value_prop": 4, "business_model": None, "scalability": 3},
                       "redstone": {"market": 4, "product": 3, "team": None, "business_model": None, "competition": 2.5,
                                    "marketing": None, "financials": 3, "tech": 3.5, "deal_dynamics": 3.5,
                                    "impact": 3.2}}}


@pytest.fixture
def model(client, monkeypatch):
    """Key set, website and feeds faked, and every profile call recorded with what it was sent."""
    sent = []
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(autoread, "START", lambda fn: fn())
    # The ratings that follow a fill have their own tests: here they answer at once, with nothing.
    monkeypatch.setattr(reads, "rate_all", lambda comp, only=None, brief=None: {})
    monkeypatch.setattr(reads, "social_all", lambda comp, only=None, brief=None: {})
    monkeypatch.setattr(website, "fetch", lambda url: {"text": "HydroSight, Haifa. Acoustic leak detection.", "description": "Leak sensors"})
    monkeypatch.setattr(pulse, "compute_pulse", lambda name, limit=20: {"top_hits": [
        {"title": "Haifa startup HydroSight raises $5 million in seed round", "published": "2025-03-02"}]})

    def complete(messages):
        sent.append(messages[1]["content"])
        return ANSWER
    monkeypatch.setattr(profile, "complete", complete)
    monkeypatch.setattr(gate, "complete", lambda messages: {"ok": True, "reason": ""})  # tests/test_gate.py
    return sent


def add(client, admin, **extra):
    client.post("/api/admin/mode", json={"mode": "live"}, auth=admin)
    return client.post("/api/admin/companies", json=REAL | extra, auth=admin).json()


def test_a_new_real_startup_gets_its_profile_filled(client, admin, model):
    comp = add(client, admin)
    got = next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["id"] == comp["id"])
    assert got["vision"].startswith("HydroSight puts acoustic sensors") and got["country"] == "Israel"
    assert got["raised_eur"] == 4_500_000  # $5M at the rough rate; the stage line keeps the dollars
    assert got["stages"] == ["Seed round: $5M (2025)"]
    assert got["investors"] == [{"name": "Blue Fund", "status": "invested", "amount_eur": 2_700_000},
                                {"name": "Wave Angels", "status": "interested", "amount_eur": None}]
    assert got["profile_status"] == "ai" and "Check it" in got["profile_note"]
    assert "raises $5 million" in model[0] and "Acoustic leak detection" in model[0]  # headlines and website
    radar = next(c for c in client.get("/api/host/radar", auth=admin).json()["companies"] if c["id"] == comp["id"])
    assert radar["profile"]["status"] == "ai"


def test_the_evidence_is_scored_so_readiness_thesis_and_the_call_follow(client, admin, model):
    comp = add(client, admin)
    got = next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["id"] == comp["id"])
    assert got["evidence"]["trl_stage"] == "pilot" and got["evidence"]["impact"]["problem_pressure"] == 4.0
    assert "team" not in got["evidence"]["redstone"]  # the sources didn't say: unknown, not a guess
    assert got["evidence"]["redstone"]["impact"] == 3.0  # kept to halves
    assert got["evidence_status"] == "ai" and "City pilot in Haifa" in got["evidence_note"]
    radar = next(c for c in client.get("/api/host/radar", auth=admin).json()["companies"] if c["id"] == comp["id"])
    assert radar["readiness"]["tech"]["trl"] == 6 and radar["readiness"]["ocean_impact"]["score"] is not None
    assert radar["theses"]["redstone"]["score"] is not None
    assert radar["call"]["key"] in ("watch", "avoid")  # never Back on evidence the host hasn't confirmed
    assert radar["review"]["label"].startswith("Estimated by AI")


def test_confirmed_evidence_is_never_touched(client, admin, model):
    mine = {"impact": {"measurability": 1}, "trl_stage": "idea"}
    comp = add(client, admin, evidence=mine)  # the host's own: saved as confirmed
    got = next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["id"] == comp["id"])
    assert got["evidence"] == mine and got["evidence_status"] == "confirmed"
    assert got["country"] == "Israel"  # the empty profile fields are still filled


def test_only_empty_fields_are_filled_and_only_once(client, admin, model):
    comp = add(client, admin, vision="Our own words.", raised_eur=100_000)
    got = next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["id"] == comp["id"])
    assert got["vision"] == "Our own words." and got["raised_eur"] == 100_000  # the host's, kept
    assert got["country"] == "Israel" and got["stages"]  # the empty ones, filled
    model.clear()
    autoread.kick()
    assert model == []  # done once


def test_sample_startups_are_never_filled(client, admin, model):
    autoread.kick()
    assert model == []  # made up: there's nothing about them to read


def test_a_failed_fill_waits_for_the_next_run(client, admin, model, monkeypatch):
    monkeypatch.setattr(profile, "complete", lambda messages: (_ for _ in ()).throw(OSError("down")))
    comp = add(client, admin)
    assert next(c for c in client.get("/api/admin/companies", auth=admin).json() if c["id"] == comp["id"])["profile_status"] == ""
    assert any("profile: OSError: down" in e for e in client.get("/api/admin/mode", auth=admin).json()["reads"]["auto"]["errors"])


def test_calls_are_capped_and_use_the_cheap_model(monkeypatch):
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode()

    def urlopen(req, timeout):
        sent.update(json.loads(req.data))
        return Resp()
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(config, "OPENROUTER_MODEL", "cheap/model")
    monkeypatch.setattr(pitch.urllib.request, "urlopen", urlopen)
    assert REAL_POST("profile", profile.SCHEMA, [], task="profile") == {"ok": True}
    # Capped, or OpenRouter reserves the model's whole output window against the key's credit and refuses (402).
    assert sent["model"] == "cheap/model" and sent["max_tokens"] == pitch.MAX_TOKENS["profile"]


def test_a_used_up_key_says_so(monkeypatch):
    import io
    import urllib.error

    def urlopen(req, timeout):
        body = b'{"error": {"message": "Key limit exceeded (total limit). $1.33 of $1.00 used; does not reset."}}'
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(body))
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(pitch.urllib.request, "urlopen", urlopen)
    with pytest.raises(pitch.OpenRouterError) as err:
        REAL_POST("profile", profile.SCHEMA, [], task="profile")
    assert "Key limit exceeded" in str(err.value)
    assert reads.short_error(err.value).startswith("Out of credit")
