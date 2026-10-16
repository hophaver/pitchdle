"""Web pulse: how much public coverage a name gets and which way the headlines lean.

A hint for the host only. It never changes engine scores and never touches a player route.
Every feed failure is caught and recorded, so no network just means a silent pulse with errors.
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import news
from ..db import now

HN_SEARCH = "https://hn.algolia.com/api/v1/search?query={q}&tags=story&hitsPerPage={n}"
RECENT_DAYS = 30
TOP_HITS = 8

GOOD = re.compile(r"\b(rais(e|es|ed|ing)|funding|funded|wins?|won|launch(es|ed)?|partner(s|ship|ships)?|grants?|awards?|awarded"
                  r"|pilots?|expan(d|ds|ded|sion)|growth|grows|contracts?|backed)\b", re.I)
RISK = re.compile(r"\b(lawsuits?|sues?|sued|delay(s|ed)?|layoffs?|lays off|regulators?|investigat(ion|ions|es|ed)|defaults?"
                  r"|cancel(s|led|ed)?|halt(s|ed)?|downgrad(e|es|ed|ing)|probes?|allegations?|bankrupt(cy)?)\b", re.I)


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "PitchdleBot/0.1"})
    with urllib.request.urlopen(req, timeout=news.TIMEOUT) as resp:
        return json.loads(resp.read(2_000_000))


def _google(name: str, limit: int) -> list[dict]:
    return news.fetch(name, limit=limit)


def _hn(name: str, limit: int) -> list[dict]:
    data = get_json(HN_SEARCH.format(q=urllib.parse.quote(f'"{name}"'), n=limit))
    return [{"title": h.get("title"), "link": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
             "published": h.get("created_at")} for h in data.get("hits", [])]


# Name -> fetcher(name, limit). Tests swap these out; nothing here may touch the network in tests.
FEEDS = {"news.google": _google, "hackernews": _hn}


def lean_of(title: str) -> str | None:
    """'good' or 'risk' when a headline clearly reads one way; None when it matches both or neither."""
    good, risk = bool(GOOD.search(title or "")), bool(RISK.search(title or ""))
    if good == risk:
        return None
    return "good" if good else "risk"


def parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def overall_lean(total: int, good: int, risk: int) -> str:
    if not total:
        return "silent"
    if not good and not risk:
        return "neutral"
    if good >= 2 * risk:
        return "positive"
    if risk >= 2 * good:
        return "negative"
    return "mixed"


def coverage_of(total: int, recent: int) -> str:
    if not total:
        return "silent"
    return "high" if total >= 10 or recent >= 3 else "low"


def compute_pulse(name: str, limit: int = 20, now_dt: datetime | None = None) -> dict:
    now_dt = now_dt or datetime.now(timezone.utc)
    items, seen, sources, errors = [], set(), [], []
    for source, fetch in FEEDS.items():
        try:
            got = fetch(name, limit)
        except Exception as e:  # noqa: BLE001 - a dead feed is just no coverage from it
            errors.append(f"{source}: {e}")
            continue
        sources.append(source)
        for it in got:
            title = (it.get("title") or "").strip()
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            items.append({"title": title, "link": it.get("link") or "", "source": source,
                          "date": parse_date(it.get("published")), "lean": lean_of(title)})

    cutoff = now_dt - timedelta(days=RECENT_DAYS)
    recent = sum(1 for it in items if it["date"] and it["date"] >= cutoff)
    good = sum(1 for it in items if it["lean"] == "good")
    risk = sum(1 for it in items if it["lean"] == "risk")
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    newest = sorted(items, key=lambda it: it["date"] or oldest, reverse=True)[:TOP_HITS]
    return {
        "fetched_at": now(),
        "items_total": len(items),
        "items_recent": recent,
        "good_count": good,
        "risk_count": risk,
        "lean": overall_lean(len(items), good, risk),
        "coverage": coverage_of(len(items), recent),
        "top_hits": [{"title": it["title"], "link": it["link"], "source": it["source"],
                      "published": it["date"].date().isoformat() if it["date"] else None, "lean": it["lean"]}
                     for it in newest],
        "sources": sources,
        "errors": errors,
    }
