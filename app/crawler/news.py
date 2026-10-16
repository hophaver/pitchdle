"""Optional news headlines for a company name from a public RSS search feed."""
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

FEED = "https://news.google.com/rss/search?q={q}&hl=en"
TIMEOUT = 8


def fetch(name: str, limit: int = 5, exact: bool = True) -> list[dict]:
    """Headlines for a name (an exact phrase by default) or, with exact=False, a free keyword query."""
    url = FEED.format(q=urllib.parse.quote(f'"{name}"' if exact else name))
    req = urllib.request.Request(url, headers={"User-Agent": "PitchdleBot/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        root = ET.fromstring(resp.read(1_000_000))
    items = []
    for item in root.iter("item"):
        items.append({"title": item.findtext("title"), "link": item.findtext("link"),
                      "published": item.findtext("pubDate")})
        if len(items) >= limit:
            break
    return items
