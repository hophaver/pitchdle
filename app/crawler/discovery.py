"""Candidate discovery: find startup names on open feeds for a sector query, and an honest auto-estimate.

Hints for the host only. Nothing found here enters rotation until the host approves it in /admin,
and the auto-estimate scores only what the crawl can actually show (a tech stage), reporting coverage.
"""
import re
import urllib.parse

from . import news, signals, website
from .. import engine
from ..db import now
from .pulse import get_json

HN_SEARCH = "https://hn.algolia.com/api/v1/search?query={q}&tags=story&hitsPerPage={n}"

SHOW_HN = re.compile(r"^(?:Show|Launch) HN:\s*(?P<name>[^–—:\-|(,]{2,40}?)\s*(?:[–—:\-|(,]|$)", re.I)
FUNDING_VERB = re.compile(r"\s(?:raises|raised|secures|secured|lands|closes|bags|nabs|nets|snags|attracts|gets|wins)\b", re.I)
NAME_PREFIX = re.compile(r"^(?P<name>[A-Z0-9][\w&.'’-]*(?: [A-Z0-9][\w&.'’-]*){0,2}):\s")
PUBLISHER = re.compile(r"\s[-–—|]\s[^-–—|]{2,60}$")
# Capitalised words in a headline that describe a company rather than name it.
GENERIC = {"startup", "start-up", "company", "firm", "biotech", "scaleup", "scale-up", "spinout", "spin-off", "the", "a", "an",
           "provider", "maker", "developer", "producer", "platform", "specialist", "pioneer", "innovator", "leader",
           # title-case headlines capitalise these too: "… Has Already Raised"
           "has", "have", "had", "is", "was", "already", "just", "now", "also", "finally", "officially", "reportedly", "and"}


# Strongest first: the first stage word the site uses sets the primed tech stage.
STAGE_WORDS = [
    ("commercial", r"\b(commercial(ly)? (available|launch)|on the market|paying customers)\b"),
    ("deployed", r"\b(deployed|in operation|installed at)\b"),
    ("pilot", r"\bpilot(s|ed|ing)?\b"),
    ("prototype", r"\bprototypes?\b"),
]


def name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def name_from(title: str, source: str) -> str | None:
    """A company name from a "Show HN: Name – …" title, or from the words just before a funding verb
    ("Seaweed startup Uluu raises …" → Uluu). Headlines with no clear name give None."""
    title = (title or "").strip()
    if source == "hackernews" and (m := SHOW_HN.search(title)):
        return clean_name(m.group("name"))
    title = PUBLISHER.sub("", title)
    verb = FUNDING_VERB.search(title)
    if not verb:
        return None
    words = []
    for word in reversed(title[:verb.start()].split()):
        bare = word.strip(",;\"“”()")
        if bare != word and words:     # punctuation ends the run: "…problem, Solubag raises"
            break
        if not bare[:1].isupper() and not bare[:1].isdigit():
            break
        if re.search(r"['’]s$|-based$", bare) or bare.lower() in GENERIC:
            break
        words.insert(0, bare)
    name = " ".join(words[-4:]) if words else None
    if not name and (m := NAME_PREFIX.match(title)):
        name = m.group("name")         # "Traceless: Biomaterials Startup Raises …"
    return clean_name(name) if name else None


def clean_name(name: str) -> str | None:
    name = name.strip(" .:'’")
    if len(name) < 2 or name.lower() in GENERIC or len(name.split()) > 4:
        return None
    return name


def _hn(q: str, limit: int) -> list[dict]:
    data = get_json(HN_SEARCH.format(q=urllib.parse.quote(f"{q} startup"), n=limit * 3))
    return [{"title": h.get("title"), "link": h.get("url") or "", "published": h.get("created_at")}
            for h in data.get("hits", [])]


def _google(q: str, limit: int) -> list[dict]:
    items = news.fetch(f"{q} startup raises", limit=limit * 3, exact=False)
    # News links are Google redirects, not the company's site: keep the headline, drop the link.
    return [it | {"link": ""} for it in items]


FEEDS = {"hackernews": _hn, "news.google": _google}


def search_candidates(q: str, limit: int = 10) -> list[dict]:
    """Deduped candidates from every reachable feed. A failing feed is skipped, never raised."""
    out, seen = [], set()
    for source, fetch in FEEDS.items():
        try:
            items = fetch(q, limit)
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            name = name_from(it.get("title"), source)
            if not name or name_key(name) in seen:
                continue
            seen.add(name_key(name))
            # Only a Show HN post links to the product itself; other stories link to an article about it.
            own_site = source == "hackernews" and SHOW_HN.search(it.get("title") or "")
            out.append({"name": name, "url": (it.get("link") or "") if own_site else "", "source": source,
                        "snippet": (it.get("title") or "")[:200], "fetched_at": now()})
            if len(out) >= limit:
                return out
    return out


def primed_evidence(text: str) -> dict:
    for stage, pattern in STAGE_WORDS:
        if re.search(pattern, text, re.I):
            return {"trl_stage": stage}
    return {}


def expand_candidate(c: dict) -> dict:
    """Site signals plus an engine run on the little they prove. Any failure gives an empty hint."""
    text, description, errors = "", "", []
    if c.get("url"):
        try:
            page = website.fetch(c["url"])
            text, description = page["text"], page.get("description", "")
        except Exception as e:  # noqa: BLE001
            errors.append(f"website: {e}")
    found = signals(text) if text else {}
    primed = primed_evidence(text) if text else {}
    result = engine.score(primed)
    return {
        "signals": {k: v["count"] for k, v in found.items()},
        "flags": ["funding"] if "funding" in found else [],
        "evidence": primed,
        "description": description,
        "composite": result["composite"],
        "axes": result["axes"],
        "coverage": {"assessed": result["coverage"]["assessed"], "total": result["coverage"]["total"]},
        "errors": errors,
    }
