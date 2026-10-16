"""Optional evidence crawler. Never on the game's critical path.

Results are hints for a human to confirm in /admin; they never change engine scores by themselves.
Every failure is caught and reported, so a dead network just means an empty result.
"""
import re

from . import news, website

SIGNALS = {
    "pilot": r"\bpilot(s|ed|ing)?\b",
    "customers": r"\b(customers?|clients?|contracts?)\b",
    "revenue": r"\b(revenue|ARR|sales)\b",
    "patents": r"\bpatent(s|ed)?\b",
    "funding": r"\b(raised|funding|investors?|seed round|series [a-c])\b",
    "certification": r"\b(certifi(ed|cation)|ISO \d+|approved)\b",
    "team": r"\b(team|founders?|engineers?)\b",
}


def signals(text: str) -> dict:
    """Count evidence keywords and keep a short snippet around the first hit for each."""
    out = {}
    for name, pattern in SIGNALS.items():
        hits = list(re.finditer(pattern, text, re.IGNORECASE))
        if hits:
            m = hits[0]
            snippet = text[max(0, m.start() - 80): m.end() + 80].replace("\n", " ").strip()
            out[name] = {"count": len(hits), "snippet": snippet}
    return out


def run_crawl(name: str, url: str | None) -> dict:
    result = {"website": None, "news": None, "signals": {}, "errors": []}
    if url:
        try:
            result["website"] = website.fetch(url)
            result["signals"] = signals(result["website"]["text"])
            result["website"]["text"] = result["website"]["text"][:2000]
        except Exception as e:  # noqa: BLE001 - any failure degrades to "no evidence"
            result["errors"].append(f"website: {e}")
    else:
        result["errors"].append("website: no URL set for this company")
    try:
        result["news"] = news.fetch(name)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"news: {e}")
    return result
