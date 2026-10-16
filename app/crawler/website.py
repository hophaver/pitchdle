"""Fetch one page of a company site as plain text: robots.txt respected, size capped, cached on disk."""
import hashlib
import json
import re
import time
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urlparse

from .. import config

UA = "PitchdleBot/0.1 (+hackathon demo; evidence collection)"
MAX_BYTES = 500_000
TIMEOUT = 8
CACHE_SECONDS = 24 * 3600


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__()
        self.parts, self.depth, self.description = [], 0, ""

    def handle_starttag(self, tag, attrs):
        if tag == "meta" and not self.description:
            a = {k.lower(): (v or "") for k, v in attrs}
            if a.get("name", "").lower() == "description" or a.get("property", "").lower() == "og:description":
                self.description = re.sub(r"\s+", " ", a.get("content", "")).strip()
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth and data.strip():
            self.parts.append(data.strip())


def _cache_path(url: str):
    config.CRAWL_CACHE.mkdir(parents=True, exist_ok=True)
    return config.CRAWL_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")


def fetch(url: str) -> dict:
    if not urlparse(url).scheme:
        url = "https://" + url
    cache = _cache_path(url)
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_SECONDS:
        return json.loads(cache.read_text()) | {"cached": True}

    parts = urlparse(url)
    robots = urllib.robotparser.RobotFileParser(f"{parts.scheme}://{parts.netloc}/robots.txt")
    try:
        robots.read()
        allowed = robots.can_fetch(UA, url)
    except Exception:  # noqa: BLE001 - unreadable robots.txt: proceed politely with a single page
        allowed = True
    if not allowed:
        raise PermissionError("robots.txt disallows fetching this page")

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read(MAX_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
    parser = _Text()
    parser.feed(raw.decode(charset, errors="replace"))
    text = re.sub(r"\s+", " ", " ".join(parser.parts))
    result = {"url": url, "fetched_at": int(time.time()), "text": text, "description": parser.description[:300],
              "cached": False}
    cache.write_text(json.dumps(result))
    return result
