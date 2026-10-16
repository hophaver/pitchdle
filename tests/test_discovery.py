"""Candidate names from feed titles, dedupe, and feed failures. No network."""
from app.crawler import discovery


def test_names_from_titles():
    assert discovery.name_from("Show HN: Kelpco – seaweed plastics for packaging", "hackernews") == "Kelpco"
    assert discovery.name_from("Show HN: Tide Labs (YC W25), tidal sensors", "hackernews") == "Tide Labs"
    assert discovery.name_from("Ask HN: who's hiring?", "hackernews") is None
    assert discovery.name_from("BlueNet raises €4M to map fishing nets", "news.google") == "BlueNet"
    assert discovery.name_from("The startup raises €4M for ocean data", "news.google") is None
    assert discovery.name_from("Why ocean tech is booming", "news.google") is None


def test_names_from_real_world_headlines():
    cases = {
        "Seaweed biomaterials startup Uluu raises AU$16m to scale fossil-free plastic - Global": "Uluu",
        "Traceless: Biomaterials Startup Raises $39 Million in Debt and Equity - Business Insider": "Traceless",
        "Taking aim at the plastic problem, Solubag raises $4.5M": "Solubag",
        "Circularity Tech Startup Resynergi Raises $6.4 Million - ESG Today": "Resynergi",
        "Munich-based Oceanloop nets up to €38.5 million": "Oceanloop",
        "Belgium's Novadip Biosciences raises €10.4 million": "Novadip Biosciences",
        "Biomass space heats up as Enifer raises $39m - AgFunder": "Enifer",
        "Recycling Tech Provider Resynergi Raises $6.4M": "Resynergi",
        "Seaweed Startup Snags $16M Series A - WWD": None,
        "How This Ocean Startup Has Already Raised $20M": None,
        "Finnish biotech startup raises €11M": None,
        "Novoloop says it worked out how to upcycle plastic, raises $11M": None,
    }
    for title, name in cases.items():
        assert discovery.name_from(title, "news.google") == name, title


def test_search_dedupes_across_feeds_and_skips_failures(monkeypatch):
    def boom(q, limit):
        raise OSError("down")
    monkeypatch.setattr(discovery, "FEEDS", {
        "hackernews": lambda q, limit: [{"title": "Show HN: Kelpco – seaweed packaging", "link": "https://kelpco.example"},
                                        {"title": "Ask HN: anything?", "link": ""},
                                        {"title": "Tidely raises $3M", "link": "https://techpress.example/tidely"}],
        "broken": boom,
        "news.google": lambda q, limit: [{"title": "KelpCo raises €2M", "link": ""},
                                         {"title": "BlueNet secures grant", "link": ""}],
    })
    found = discovery.search_candidates("ocean", limit=10)
    assert [c["name"] for c in found] == ["Kelpco", "Tidely", "BlueNet"]
    assert found[0]["url"] == "https://kelpco.example"
    assert found[1]["url"] == ""  # an article about it, not its own site


def test_search_with_every_feed_down_is_empty(monkeypatch):
    def boom(q, limit):
        raise OSError("down")
    monkeypatch.setattr(discovery, "FEEDS", {"hackernews": boom, "news.google": boom})
    assert discovery.search_candidates("ocean") == []


def test_expand_primes_only_the_tech_stage(monkeypatch):
    text = "We ran a pilot with two ports. Patent pending. Raised a seed round from investors."
    monkeypatch.setattr(discovery.website, "fetch", lambda url: {"text": text})
    hint = discovery.expand_candidate({"url": "https://kelpco.example"})
    assert hint["evidence"] == {"trl_stage": "pilot"}   # a patent mention is not a granted patent
    assert hint["flags"] == ["funding"]
    assert hint["coverage"]["assessed"] == 1


def test_expand_without_site_is_an_empty_estimate():
    hint = discovery.expand_candidate({"url": ""})
    assert hint["evidence"] == {} and hint["coverage"]["assessed"] == 0
