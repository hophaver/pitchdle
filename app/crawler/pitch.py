"""OpenRouter jobs for discovery: screen raw feed hits, and write a real startup's game card.

Discovery only gives us headlines and sometimes a website. Two structured calls turn that into something the
host can use, using only those sources: no invented numbers.

- screen(): which raw hits are real startups, on topic, and based in the searched country. Run before
  anything is stored, so a loose search doesn't flood the host with noise.
- write_card(): a card shaped like the demo companies (emoji, sector, pitch, ask, facts), which also says
  whether the name is a startup at all.

Card text only. Neither call writes evidence factors, so engine scores stay human-confirmed.
"""
import json
import re
import urllib.request

from .. import config

URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 45
# The same limits the player submission form uses, so a written card fits the card layout.
LIMITS = {"one_liner": 90, "claim_ask": 60, "sector": 30}
MAX_FACTS = 3

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_startup", "reject_reason", "emoji", "sector", "one_liner", "claim_ask", "facts"],
    "properties": {
        "is_startup": {"type": "boolean"},
        "reject_reason": {"type": "string"},
        "emoji": {"type": "string"},
        "sector": {"type": "string"},
        "one_liner": {"type": "string"},
        "claim_ask": {"type": "string"},
        "facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["label", "value"],
            "properties": {"label": {"type": "string"}, "value": {"type": "string"}}}},
    },
}

SYSTEM = """You write cards for a game where players rate startups from a short pitch.
You get a company name, the field it was found under, and the only sources available: news headlines and
maybe text from its website. Use those sources only. Never invent numbers, customers, dates or claims.

First decide is_startup: true only if the name is an operating company (startup or young scaleup) with its own
product or service. False for investors and funds, accelerators, publishers, news aggregators, events,
government bodies, large established corporations, or if the name looks like a misparsed headline fragment.
Always false for Redstone (a venture fund) and A'Pelago (an accelerator): they run this event.
When false, give a short reject_reason and leave the other text fields empty.

When true, write the card in the style of these examples:
  {"emoji": "🐄", "sector": "aquaculture & feed",
   "one_liner": "Dried Baltic seaweed in cow feed. The cows burp less methane.",
   "claim_ask": "€800k to double its drying plant",
   "facts": [{"label": "Revenue", "value": "€420k last year; 3 dairy co-ops buying repeatedly"},
             {"label": "Evidence", "value": "Two university feeding trials: 12–18% less methane per cow"}]}
  {"emoji": "🧴", "sector": "ocean plastics",
   "one_liner": "Pick up a bottle on the beach, scan it, earn a token.",
   "claim_ask": "€3M to launch in 40 countries next year", "facts": [...]}

Rules:
- emoji: one emoji for what the product is.
- sector: 1-3 lowercase words.
- one_liner: what the product does, concretely, in plain words a player understands. 20-90 characters.
  No hype, no company name, no "revolutionary".
- claim_ask: what money they want and what for, 10-60 characters, like "€1.7M to scale oxygen units for fish farms".
  Use a current or latest round from the sources, in its original currency. If the sources give no amount,
  name the goal without a number ("Funding to build its first pilot plant"). Never make up an amount.
- facts: 1-3 short label/value pairs a judge would want (traction, funding, team, partners, location), each
  backed by the sources. Value under 90 characters. Fewer facts beats unsupported facts.
Use British English."""


def available() -> bool:
    return bool(config.OPENROUTER_API_KEY)


def _post(schema_name: str, schema: dict, messages: list[dict]) -> dict:
    """One structured chat completion: the only network call here. Tests block it outright."""
    body = {"model": config.OPENROUTER_MODEL, "messages": messages, "temperature": 0.2,
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}", "Content-Type": "application/json",
        "X-Title": "Pitchdle"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        return content
    # Some models wrap JSON in a code fence even when asked for structured output.
    return json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip()))


def complete(messages: list[dict]) -> dict:
    """The card call. Tests replace this."""
    return _post("card", SCHEMA, messages)


def screen_complete(messages: list[dict]) -> dict:
    """The screening call. Tests replace this."""
    return _post("screen", SCREEN_SCHEMA, messages)


def sources_text(name: str, field: str, headline: str = "", hits: list | None = None,
                 description: str = "", page_text: str = "") -> str:
    lines = [f"Company name: {name}", f"Found while searching the field: {field or 'unknown'}", "", "Headlines:"]
    seen = set()
    for title, published in [(headline, "")] + [(h.get("title"), h.get("published")) for h in hits or []]:
        if title and title not in seen:
            seen.add(title)
            lines.append(f"- {title}" + (f" ({str(published)[:16]})" if published else ""))
    if description:
        lines += ["", f"Website description: {description}"]
    if page_text:
        lines += ["", "Website text (truncated):", page_text[:3000]]
    return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip(" ,;:-") + "…"


def write_card(sources: str) -> dict:
    """The card, cleaned to fit the game's limits. Raises on any API or format error; callers fall back."""
    raw = complete([{"role": "system", "content": SYSTEM}, {"role": "user", "content": sources}])
    card = {
        "is_startup": bool(raw.get("is_startup")),
        "reject_reason": _clip(raw.get("reject_reason", ""), 200),
        "emoji": (raw.get("emoji") or "").strip()[:8],
        "sector": _clip(raw.get("sector", ""), LIMITS["sector"]).lower(),
        "one_liner": _clip(raw.get("one_liner", ""), LIMITS["one_liner"]),
        "claim_ask": _clip(raw.get("claim_ask", ""), LIMITS["claim_ask"]),
        "facts": [{"label": _clip(f.get("label", ""), 30), "value": _clip(f.get("value", ""), 90)}
                  for f in (raw.get("facts") or [])[:MAX_FACTS] if f.get("label") and f.get("value")],
    }
    if card["is_startup"] and not card["one_liner"]:
        raise ValueError("model returned an empty pitch")
    return card


# --- screening raw feed hits -------------------------------------------------------------------------

SCREEN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["results"],
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "is_startup", "based_in", "in_country", "on_topic", "reason"],
        "properties": {
            "id": {"type": "integer"},
            "is_startup": {"type": "boolean"},
            "based_in": {"type": "string"},
            "in_country": {"type": "boolean"},
            "on_topic": {"type": "boolean"},
            "reason": {"type": "string"},
        }}}},
}

SCREEN_SYSTEM = """You screen search hits for a host looking for real startups to put in a pitch game.
Each hit has an id, a company name parsed from a headline, the headline, and maybe text from its website.
Use only those sources. For every hit return:
- is_startup: true only for an operating young company (startup or scaleup) with its own product or service.
  False for investors and funds, accelerators, publishers, news sites, events, universities, government bodies,
  large established corporations, or a name that is really a misparsed headline fragment.
  Always false for Redstone (a venture fund) and A'Pelago (an accelerator).
- based_in: the country the company is headquartered or founded in, inferred from the website text, the
  headline's wording ("Finnish startup", "Oslo-based", a .fi address, a city) or other clues. Empty if unclear.
- in_country: true only if the sources clearly place the company in the searched country. A company that merely
  sells to, partners with or raised from that country is not based there. Unclear means false.
  When no country was searched, true.
- on_topic: true if the company's own product fits the searched field. When no field was searched, true.
- reason: under 12 words, why it fails, or empty if it passes."""

SCREEN_TEXT = 1200  # website characters per hit: enough to place a company, short enough to batch ten


def screen_sources(sector: str, country: str, items: list[dict]) -> str:
    lines = [f"Searched field: {sector or '(any)'}", f"Searched country: {country or '(any)'}", ""]
    for it in items:
        lines.append(f"[{it['id']}] {it['name']}")
        lines.append(f"  Headline: {it.get('headline') or '-'}")
        if it.get("description"):
            lines.append(f"  Website description: {it['description'][:300]}")
        if it.get("text"):
            lines.append(f"  Website text: {' '.join(it['text'].split())[:SCREEN_TEXT]}")
    return "\n".join(lines)


def screen(sector: str, country: str, items: list[dict]) -> dict[int, dict]:
    """A verdict per hit id: {is_startup, based_in, in_country, on_topic, reason}. Raises on any API or format
    error; ids the model left out are simply missing. Callers keep whatever has no verdict."""
    if not items:
        return {}
    raw = screen_complete([{"role": "system", "content": SCREEN_SYSTEM},
                           {"role": "user", "content": screen_sources(sector, country, items)}])
    wanted = {it["id"] for it in items}
    out = {}
    for r in raw.get("results") or []:
        if not isinstance(r, dict) or r.get("id") not in wanted:
            continue
        out[r["id"]] = {"is_startup": bool(r.get("is_startup")), "based_in": _clip(r.get("based_in", ""), 40),
                        "in_country": bool(r.get("in_country")), "on_topic": bool(r.get("on_topic")),
                        "reason": _clip(r.get("reason", ""), 120)}
    return out
