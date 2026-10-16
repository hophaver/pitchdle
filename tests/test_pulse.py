"""Web pulse: lean, coverage and recency from mocked feeds. No network."""
from datetime import datetime, timedelta, timezone

import pytest

from app.crawler import pulse

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def item(title, days_ago=None):
    published = (NOW - timedelta(days=days_ago)).isoformat() if days_ago is not None else None
    return {"title": title, "link": "https://example.com/" + title.replace(" ", "-"), "published": published}


@pytest.fixture
def feeds(monkeypatch):
    def use(**by_source):
        monkeypatch.setattr(pulse, "FEEDS", {src: (lambda items: lambda name, limit: items)(items)
                                             for src, items in by_source.items()})
    return use


def test_lean_of_headlines():
    assert pulse.lean_of("Kelpco raises €2M seed round") == "good"
    assert pulse.lean_of("Regulator opens probe into Kelpco") == "risk"
    assert pulse.lean_of("Kelpco raises money despite lawsuit") is None  # both sides
    assert pulse.lean_of("Kelpco hires a new CTO") is None               # neither


def test_positive_and_recent(feeds):
    feeds(**{"news.google": [item("Kelpco raises €2M", 3), item("Kelpco wins ocean award", 10)],
             "hackernews": [item("Kelpco launches pilot", 29), item("Kelpco hires a CTO", 31)]})
    p = pulse.compute_pulse("Kelpco", now_dt=NOW)
    assert p["items_total"] == 4
    assert p["items_recent"] == 3            # day 31 is outside the 30-day window
    assert (p["good_count"], p["risk_count"]) == (3, 0)
    assert p["lean"] == "positive"
    assert p["coverage"] == "high"           # 3 recent is enough
    assert p["sources"] == ["news.google", "hackernews"] and p["errors"] == []
    assert p["top_hits"][0]["title"] == "Kelpco raises €2M"  # newest first


def test_unknown_dates_are_not_recent_and_duplicates_count_once(feeds):
    feeds(**{"news.google": [item("Kelpco faces lawsuit"), item("Kelpco faces lawsuit")],
             "hackernews": [item("kelpco faces lawsuit")]})
    p = pulse.compute_pulse("Kelpco", now_dt=NOW)
    assert p["items_total"] == 1 and p["items_recent"] == 0
    assert p["lean"] == "negative" and p["coverage"] == "low"


def test_mixed_and_neutral(feeds):
    feeds(**{"news.google": [item("Kelpco raises €2M", 1), item("Kelpco delays launch of plant", 1),
                             item("Kelpco faces layoffs", 1)]})
    assert pulse.compute_pulse("Kelpco", now_dt=NOW)["lean"] == "mixed"  # 1 good vs 2 risk
    feeds(**{"news.google": [item("Kelpco hires a CTO", 1)]})
    assert pulse.compute_pulse("Kelpco", now_dt=NOW)["lean"] == "neutral"


def test_failing_feed_never_raises(monkeypatch):
    def boom(name, limit):
        raise OSError("no network")
    monkeypatch.setattr(pulse, "FEEDS", {"news.google": boom, "hackernews": boom})
    p = pulse.compute_pulse("Kelpco", now_dt=NOW)
    assert p["items_total"] == 0 and p["lean"] == "silent" and p["coverage"] == "silent"
    assert len(p["errors"]) == 2 and p["sources"] == []


def test_high_coverage_by_volume(feeds):
    feeds(**{"news.google": [item(f"Kelpco story {i}") for i in range(10)]})
    assert pulse.compute_pulse("Kelpco", now_dt=NOW)["coverage"] == "high"
