"""Discover by country and/or field: the AI screen keeps only real startups that fit the search, the card writer
runs when the host queues or approves one, and neither failing loses a candidate. Feeds, sites and AI are mocked."""
import pytest

from app import autofill, config
from app.crawler import discovery, pitch, pulse, website

HEADLINES = [
    "Finnish startup Kelpo raises €2M for seaweed packaging - Arctic News",
    "Swedish startup Fjordly raises €1M to map fjord currents - Nordic Tech",
    "Seabin raises $5M to clean marinas worldwide - Ocean Daily",
    "Redstone raises €25m blue economy fund - Enlit World",
]
SHOW_HN = "Show HN: Lumo – note taking for ship crews"
SITES = {"https://lumo.example": {"text": "Lumo Oy builds software for ship crews. Our office is in Helsinki.",
                                  "description": "Notes for ship crews"}}
# What the mocked model knows about each name, as if it read the headline and the site.
BASED = {"Kelpo": "Finland", "Fjordly": "Sweden", "Seabin": "Australia", "Lumo": "Finland"}


@pytest.fixture(autouse=True)
def offline(client, monkeypatch):
    calls = {"queries": []}

    def google(q, limit):
        calls["queries"].append(q)
        return [{"title": t, "link": ""} for t in HEADLINES]

    def hn(q, limit):
        return [{"title": SHOW_HN, "link": "https://lumo.example"}]

    def fetch(url):
        if url not in SITES:
            raise OSError("unreachable")
        return SITES[url] | {"cached": False}

    monkeypatch.setattr(discovery, "FEEDS", {"news.google": google, "hackernews": hn})
    monkeypatch.setattr(pulse, "FEEDS", {"news.google": lambda n, l: []})
    monkeypatch.setattr(website, "fetch", fetch)
    monkeypatch.setattr(config, "DISCOVER_EXCLUDE", [])
    return calls


class FakeAI:
    """Stands in for OpenRouter: screens like a careful model, and writes cards."""

    def __init__(self):
        self.screened, self.cards, self.fail_cards = [], [], set()

    def screen(self, messages):
        text = messages[-1]["content"]
        country = text.split("Searched country: ", 1)[1].split("\n", 1)[0]
        self.screened.append(text)
        results = []
        for block in text.split("\n[")[1:]:
            cid, rest = block.split("] ", 1)
            name = rest.split("\n", 1)[0]
            based = BASED.get(name, "")
            results.append({"id": int(cid), "is_startup": True, "based_in": based, "on_topic": True,
                            "in_country": country == "(any)" or based == country, "reason": ""})
        return {"results": results}

    def card(self, messages):
        name = messages[-1]["content"].split("Company name: ", 1)[1].split("\n", 1)[0]
        self.cards.append(name)
        if name in self.fail_cards:
            raise OSError("rate limited")
        return {"is_startup": True, "reject_reason": "", "emoji": "🌿", "sector": "packaging",
                "one_liner": f"{name}: packaging that dissolves in water.", "claim_ask": "€2M to build a line",
                "facts": [{"label": "Funding", "value": "€2M seed"}]}


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(pitch, "screen_complete", fake.screen)
    monkeypatch.setattr(pitch, "complete", fake.card)
    return fake


def search(client, admin, **body):
    r = client.post("/api/admin/discover/search", json=body, auth=admin)
    assert r.status_code == 200, r.text
    return r.json()


def listed(client, admin, status=""):
    return {c["name"]: c for c in client.get(f"/api/admin/discover?status={status}", auth=admin).json()}


# --- country-only search ---------------------------------------------------------------------------

def test_a_country_alone_is_a_search(client, admin, ai, offline):
    found = search(client, admin, country="Finland")
    assert sorted(c["name"] for c in found) == ["Kelpo", "Lumo"]
    assert all(c["country_tag"] == "Finland" and c["screen"]["verdict"] == "kept" for c in found)
    # Headlines say "Finnish startup", not "Finland": the demonym is searched too.
    assert offline["queries"] == ["Finland", "Finnish"]


def test_the_country_is_inferred_from_the_site_not_the_headline(client, admin, ai):
    lumo = next(c for c in search(client, admin, country="Finland") if c["name"] == "Lumo")
    assert "Finland" not in SHOW_HN and lumo["screen"]["based_in"] == "Finland" and lumo["screen"]["by"] == "ai"
    # The model was given the site text it inferred that from.
    assert "Helsinki" in ai.screened[0]


def test_loose_hits_from_elsewhere_are_left_out_with_a_reason(client, admin, ai):
    search(client, admin, country="Finland")
    assert set(listed(client, admin)) == {"Kelpo", "Lumo"}
    dismissed = listed(client, admin, "dismissed")
    assert dismissed["Fjordly"]["screen"]["reason"] == "based in Sweden, not Finland"
    assert dismissed["Seabin"]["screen"]["kind"] == "country"


def test_a_hit_left_out_for_one_country_is_found_for_its_own(client, admin, ai):
    search(client, admin, country="Finland")
    found = search(client, admin, country="Sweden")
    assert [c["name"] for c in found] == ["Fjordly"] and found[0]["status"] == "new"
    assert "Fjordly" in listed(client, admin)
    assert "Kelpo" in listed(client, admin)  # kept by the first search; not a match now, but not dismissed


def test_excluded_names_never_reach_the_ai_or_the_host(client, admin, ai):
    search(client, admin, country="Finland")
    assert "Redstone" not in "".join(ai.screened)
    assert "Redstone" in listed(client, admin, "dismissed") and "Redstone" not in listed(client, admin)


def test_a_search_needs_a_field_or_a_country(client, admin):
    assert client.post("/api/admin/discover/search", json={}, auth=admin).status_code == 422
    assert client.post("/api/admin/discover/search", json={"sector": "ocean"}, auth=admin).status_code == 200


def test_a_failed_screen_drops_nothing(client, admin, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")  # the screen call hits the blocked network
    found = search(client, admin, country="Finland")
    assert sorted(c["name"] for c in found) == ["Fjordly", "Kelpo", "Lumo", "Seabin"]
    assert all(c["screen"]["verdict"] == "unchecked" and "failed" in c["screen"]["reason"] for c in found)


def test_without_ai_a_country_search_marks_what_it_cannot_place(client, admin):
    found = {c["name"]: c["screen"] for c in search(client, admin, country="Finland")}
    assert set(found) == {"Fjordly", "Kelpo", "Lumo", "Seabin"}  # nothing dropped
    assert found["Kelpo"] == found["Kelpo"] | {"verdict": "kept", "by": "text", "based_in": "Finland"}
    assert found["Seabin"]["verdict"] == "unchecked" and "AI screening is off" in found["Seabin"]["reason"]


# --- queue / approve write the card ---------------------------------------------------------------

def candidate(client, admin, name):
    return listed(client, admin)[name]


def test_queueing_writes_the_card_and_approving_reuses_it(client, admin, ai):
    search(client, admin, country="Finland")
    kelpo = candidate(client, admin, "Kelpo")
    out = client.post(f"/api/admin/discover/{kelpo['id']}/queue", json={"queued": True}, auth=admin).json()
    assert out["status"] == "queued" and out["card"]["one_liner"].startswith("Kelpo: packaging") and out["card_error"] == ""

    comp = client.post(f"/api/admin/discover/{kelpo['id']}/approve", auth=admin).json()
    assert comp["one_liner"] == "Kelpo: packaging that dissolves in water." and comp["claim_ask"] == "€2M to build a line"
    assert comp["facts"] == [{"label": "Funding", "value": "€2M seed"}] and comp["card_status"] == "ai"
    assert ai.cards == ["Kelpo"]  # written once, at queue time


def test_approving_straight_away_writes_the_card(client, admin, ai):
    search(client, admin, country="Finland")
    comp = client.post(f"/api/admin/discover/{candidate(client, admin, 'Lumo')['id']}/approve", auth=admin).json()
    assert comp["emoji"] == "🌿" and comp["one_liner"].startswith("Lumo:") and comp["card_status"] == "ai"


def test_a_failed_card_keeps_the_candidate_for_a_manual_pass(client, admin, ai):
    ai.fail_cards.add("Kelpo")
    search(client, admin, country="Finland")
    kelpo = candidate(client, admin, "Kelpo")
    out = client.post(f"/api/admin/discover/{kelpo['id']}/queue", json={"queued": True}, auth=admin).json()
    assert out["status"] == "queued" and out["card"] is None and "by hand" in out["card_error"]

    comp = client.post(f"/api/admin/discover/{kelpo['id']}/approve", auth=admin).json()
    assert comp["card_status"] == "manual" and comp["one_liner"].startswith("Finnish startup Kelpo raises")
    # The host's full save from the editor clears the flag; a quick toggle doesn't.
    body = {k: comp[k] for k in ("name", "sector", "one_liner", "claim_ask", "website", "evidence", "evidence_note")}
    client.put(f"/api/admin/companies/{comp['id']}", json=body | {"active": True}, auth=admin)
    assert client.get("/api/admin/companies?pool=live", auth=admin).json()[0]["card_status"] == "manual"
    client.put(f"/api/admin/companies/{comp['id']}", json=body | {"card_reviewed": True}, auth=admin)
    assert client.get("/api/admin/companies?pool=live", auth=admin).json()[0]["card_status"] == ""


def test_without_ai_queueing_says_the_card_needs_writing(client, admin):
    search(client, admin, country="Finland")
    out = client.post(f"/api/admin/discover/{candidate(client, admin, 'Kelpo')['id']}/queue", json={"queued": True},
                      auth=admin).json()
    assert out["status"] == "queued" and out["card_error"] == autofill.AI_OFF


# --- exclusions ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, url, hit", [
    ("RS Partners Fund", "", "fund"), ("Ocean VC", "", "vc"), ("Blue Angels", "", "angels"),
    ("Marine Institute", "", "institute"), ("Ocean Summit", "", "summit"),
    ("Wavely", "https://www.redstone.vc/portfolio", "redstone"), ("Bluefront", "techcrunch.com", "techcrunch"),
])
def test_more_funds_publishers_and_partners_are_excluded(name, url, hit):
    assert autofill.exclusion(name, url=url) == hit


@pytest.mark.parametrize("name", ["Angelfish", "Vcare", "Summitly", "Instituto"])
def test_new_exclusions_are_still_whole_words(name):
    assert autofill.exclusion(name) is None


def test_a_player_cannot_submit_a_partner_as_a_startup(client, admin):
    client.get("/api/me")
    pitch_body = {"name": "Redstone", "sector": "venture", "one_liner": "We back blue economy startups early.",
                  "claim_ask": "€25m for a new fund", "website": "redstone.example"}
    assert client.post("/api/submit", json=pitch_body).status_code == 200
    sub = client.get("/api/admin/submissions", auth=admin).json()[0]
    out = client.post(f"/api/admin/submissions/{sub['id']}/approve", auth=admin)
    assert out.status_code == 409 and "excluded" in out.json()["detail"]
