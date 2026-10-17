"""Outside reads of a startup: AI models' own ratings, and what people say about it on social media, found and
read by AI search. Run from Admin, never on the game's path.

Two routes: with OPENROUTER_API_KEY, OpenRouter runs all three models on one key; otherwise each model goes to its
own provider with its own key, and a model without one is skipped.

Every read comes back on the players' four calls, 0-5. A social read only counts posts the model cited on that
platform (and, on Anthropic's own API, that its search actually returned), so it can't rest on posts that don't
exist; with none, the platform is recorded as quiet.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from . import config
from .db import j
from .engine import AXES

FALLBACK_BETA = "server-side-fallback-2026-07-01"  # a declined request is retried server-side on another model
XAI_BASE_URL = "https://api.x.ai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT = 180  # seconds per request; a web search loop takes a while
# Output caps on OpenRouter. Without one it reserves the model's whole output window (65k tokens) against the
# key's credit up front, which a key with a spending limit can't cover, so every read fails with a 402.
RATE_MAX_TOKENS = 1200  # a rating is a few lines of JSON, with room for brief, low-effort thinking
SOCIAL_MAX_TOKENS = 3000  # a social read writes a short summary after its searches
SOCIAL_SEARCHES = 2  # searches per platform: enough to find a startup's posts, each one billed

# The model each route asks unless CLAUDE_MODEL, GPT_MODEL or GROK_MODEL says otherwise.
MODELS = {
    "direct": {"claude": "claude-opus-5-5", "gpt": "gpt-6-astra", "grok": "grok-4.7"},
    "openrouter": {"claude": "anthropic/claude-opus-5.5", "gpt": "openai/gpt-6-astra", "grok": "x-ai/grok-4.7"},
}
MODEL_NAMES = {"claude": "Claude", "gpt": "GPT", "grok": "Grok"}


def route() -> str:
    return "openrouter" if config.OPENROUTER_API_KEY else "direct"


def model(key: str) -> str:
    return getattr(config, f"{key.upper()}_MODEL") or MODELS[route()][key]


def models() -> dict[str, str]:
    return {key: model(key) for key in MODEL_NAMES}

# Where each platform's posts live. X is searched by Grok when it has a key, since it searches X directly.
PLATFORMS = {
    "x": ["x.com", "twitter.com"],
    "threads": ["threads.net", "threads.com"],
    "linkedin": ["linkedin.com"],
    "reddit": ["reddit.com"],
    "bluesky": ["bsky.app"],
}
PLATFORM_NAMES = {"x": "X (Twitter)", "threads": "Threads", "linkedin": "LinkedIn", "reddit": "Reddit",
                  "bluesky": "Bluesky"}

# Short on purpose: every review sends it, and the anchors are what keep the scores comparable.
RUBRIC = """Score 0-5 (halves ok):
novel: 0 done many times, 5 genuinely new.
useful: 0 barely matters, 5 solves a big real problem for people or the ocean.
plausible: 0 wishful, 5 already shown to work (given stage, team, proof, money).
investable: 0 would not invest, 5 strong case at this stage."""

RATE_SYSTEM = f"""Rate an early-stage startup for A'Pelago, a Finnish blue-economy accelerator. Use the brief and \
what you already know of the company. Be candid; most startups are not 5s.
{RUBRIC}
reason: one sentence."""

# Grok gets the format in words; Claude and GPT get the schema itself.
RATE_FORMAT = ('Answer with only a JSON object: {"novel": n, "useful": n, "plausible": n, "investable": n, '
               '"reason": "..."}')

SOCIAL_SYSTEM = f"""Find what people say about a startup on one social platform, for A'Pelago, a Finnish \
blue-economy accelerator. Search the platform; count only posts clearly about this company, not a namesake.
Rate what the posters seem to think of it. {RUBRIC}
Write one or two sentences on what people say, citing the posts. End with one line of JSON:
{{"posts": <relevant posts found>, "novel": n, "useful": n, "plausible": n, "investable": n, "summary": "<one sentence>"}}
If you find no posts about this company, end with {{"posts": 0}}."""

SCORE_SCHEMA = {
    "type": "object",
    "properties": {**{a: {"type": "number"} for a in AXES}, "reason": {"type": "string"}},
    "required": [*AXES, "reason"],
    "additionalProperties": False,
}


# --- what the models see ----------------------------------------------------------------------------------

def money(eur) -> str:
    return f"€{eur:,}".replace(",", " ")


def backer(investor: dict) -> str:
    if investor["status"] == "invested" and investor.get("amount_eur"):
        return f"{investor['name']} (invested {money(investor['amount_eur'])})"
    return f"{investor['name']} ({investor['status']})"


def profile_text(comp) -> str:
    """The company as the models see it: the same facts its card shows players."""
    stages, backers = j(comp["stages"], []), [backer(i) for i in j(comp["investors"], [])]
    lines = [
        f"Name: {comp['name']}",
        comp["sector"] and f"Sector: {comp['sector']}",
        comp["one_liner"] and f"Pitch: {comp['one_liner']}",
        comp["claim_ask"] and f"Asking for: {comp['claim_ask']}",
        comp["website"] and f"Website: {comp['website']}",
        comp["vision"] and f"Vision: {comp['vision']}",
        stages and f"Stages passed: {', '.join(stages)}",
        f"Raised so far: {money(comp['raised_eur'])}" if comp["raised_eur"] is not None else "Raised so far: not disclosed",
        backers and f"Investors: {'; '.join(backers)}",
    ]
    return "\n".join(line for line in lines if line)


def social_request(platform: str, comp) -> str:
    about = [f'Company: "{comp["name"]}"', comp["website"] and f"Website: {comp['website']}",
             comp["sector"] and f"Sector: {comp['sector']}", comp["one_liner"] and f"What it does: {comp['one_liner']}"]
    return f"Platform: {PLATFORM_NAMES[platform]}\n" + "\n".join(line for line in about if line)


# --- reading the answers ------------------------------------------------------------------------------------

def last_json(text: str) -> dict:
    """The last flat JSON object in a model's answer."""
    for match in reversed(list(re.finditer(r"\{[^{}]*\}", text or ""))):
        try:
            data = json.loads(match.group())
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("the answer had no JSON in it")


def clamp_scores(data: dict) -> dict:
    """The four calls, kept to 0-5 and rounded to the nearest half."""
    return {a: round(min(5.0, max(0.0, float(data[a]))) * 2) / 2 for a in AXES}


def note_of(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:400]


def on_platform(url: str, domains: list[str]) -> bool:
    host = urlsplit(url).hostname or ""
    return any(host == d or host.endswith("." + d) for d in domains)


def social_result(text: str, posts: list[str], via: str, model: str) -> dict:
    """What a social read found. Without a verified post it's a quiet platform, whatever the answer claims."""
    meta = {"posts": len(posts), "links": posts[:5], "via": via, "model": model}
    if not posts:
        return {"scores": None, "note": "", "meta": meta}
    data = last_json(text)
    return {"scores": clamp_scores(data), "note": note_of(data.get("summary")), "meta": meta}


# --- the providers -------------------------------------------------------------------------------------------

def claude_client():
    import anthropic
    # No key here falls back to the SDK's own lookup (ANTHROPIC_AUTH_TOKEN, an `ant auth login` profile).
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None, timeout=TIMEOUT, max_retries=1)


def openai_client(api_key: str, base_url: str | None = None):
    import openai
    return openai.OpenAI(api_key=api_key, base_url=base_url, timeout=TIMEOUT, max_retries=1)


def claude_rate(profile: str) -> dict:
    response = claude_client().beta.messages.create(
        model=model("claude"),
        max_tokens=RATE_MAX_TOKENS,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCORE_SCHEMA}},
        system=RATE_SYSTEM,
        messages=[{"role": "user", "content": profile}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to rate it")
    data = json.loads(next(b.text for b in response.content if b.type == "text"))
    return {"scores": clamp_scores(data), "note": note_of(data["reason"]), "meta": {"model": response.model}}


def gpt_rate(profile: str) -> dict:
    response = openai_client(config.OPENAI_API_KEY).responses.create(
        model=model("gpt"),
        instructions=RATE_SYSTEM,
        input=profile,
        reasoning={"effort": "low"},
        max_output_tokens=RATE_MAX_TOKENS,
        text={"format": {"type": "json_schema", "name": "startup_read", "strict": True, "schema": SCORE_SCHEMA}},
    )
    data = json.loads(response.output_text)
    return {"scores": clamp_scores(data), "note": note_of(data["reason"]), "meta": {"model": response.model}}


def grok_rate(profile: str) -> dict:
    response = openai_client(config.XAI_API_KEY, XAI_BASE_URL).responses.create(
        model=model("grok"),
        input=[{"role": "system", "content": f"{RATE_SYSTEM}\n{RATE_FORMAT}"}, {"role": "user", "content": profile}],
        max_output_tokens=RATE_MAX_TOKENS,
    )
    data = last_json(response.output_text)
    return {"scores": clamp_scores(data), "note": note_of(data.get("reason")), "meta": {"model": response.model}}


def claude_social(platform: str, comp) -> dict:
    """Claude's web search, kept to one platform's domains."""
    client, domains = claude_client(), PLATFORMS[platform]
    user = {"role": "user", "content": social_request(platform, comp)}
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": SOCIAL_SEARCHES, "allowed_domains": domains}]
    blocks, messages = [], [user]
    # The basic search tool hands back every result it found, so cited posts can be checked against them.
    for _ in range(3):
        response = client.beta.messages.create(
            model=model("claude"), max_tokens=SOCIAL_MAX_TOKENS, betas=[FALLBACK_BETA], fallbacks="default",
            output_config={"effort": "low"}, system=SOCIAL_SYSTEM, messages=messages, tools=tools)
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined to search for it")
        blocks += response.content
        if response.stop_reason != "pause_turn":
            break
        messages = [user, {"role": "assistant", "content": blocks}]  # resume the paused search where it stopped
    found = {r.url for b in blocks if b.type == "web_search_tool_result" and isinstance(b.content, list)
             for r in b.content}
    cited = [c.url for b in blocks if b.type == "text" for c in (b.citations or []) if getattr(c, "url", None)]
    posts = [u for u in dict.fromkeys(cited) if u in found and on_platform(u, domains)]
    text = "".join(b.text for b in blocks if b.type == "text")
    return social_result(text, posts, "Claude web search", response.model)


def grok_social(comp) -> dict:
    """Grok's own X search."""
    response = openai_client(config.XAI_API_KEY, XAI_BASE_URL).responses.create(
        model=model("grok"),
        input=[{"role": "system", "content": SOCIAL_SYSTEM}, {"role": "user", "content": social_request("x", comp)}],
        tools=[{"type": "x_search"}],
    )
    cited = [a.url for item in response.output if getattr(item, "type", "") == "message"
             for part in item.content if getattr(part, "type", "") == "output_text"
             for a in (part.annotations or []) if getattr(a, "type", "") == "url_citation"]
    posts = [u for u in dict.fromkeys(cited) if on_platform(u, PLATFORMS["x"])]
    return social_result(response.output_text, posts, "Grok X search", response.model)


# --- all three through OpenRouter -------------------------------------------------------------------------

def openrouter_client():
    return openai_client(config.OPENROUTER_API_KEY, OPENROUTER_BASE_URL)


def answer_text(response) -> str:
    message = response.choices[0].message
    if not message.content and response.choices[0].finish_reason == "length":
        raise RuntimeError(f"the answer didn't fit in {RATE_MAX_TOKENS} tokens")
    if not message.content:
        raise RuntimeError(getattr(message, "refusal", None) or "the model gave no answer")
    return message.content


def openrouter_rate(key: str, profile: str) -> dict:
    response = openrouter_client().chat.completions.create(
        model=model(key),
        messages=[{"role": "system", "content": RATE_SYSTEM}, {"role": "user", "content": profile}],
        max_tokens=RATE_MAX_TOKENS,
        response_format={"type": "json_schema",
                         "json_schema": {"name": "startup_read", "strict": True, "schema": SCORE_SCHEMA}},
        # Only endpoints that enforce the schema; little thinking (billed as output), none of it sent back.
        extra_body={"provider": {"require_parameters": True}, "reasoning": {"effort": "low", "exclude": True}},
    )
    data = json.loads(answer_text(response))
    return {"scores": clamp_scores(data), "note": note_of(data["reason"]),
            "meta": {"model": response.model, "via": "OpenRouter"}}


def openrouter_social(platform: str, comp) -> dict:
    """OpenRouter's web search with each model's own search engine, kept to the platform's site. X is read by Grok
    with its X search on; every other platform by Claude. Only citations come back, not the full results, so a post
    counts when the model cited it on the platform itself."""
    reader, domains = ("grok" if platform == "x" else "claude"), PLATFORMS[platform]
    search = {"engine": "native", "max_uses": SOCIAL_SEARCHES, "max_results": 5, "allowed_domains": domains}
    if platform == "x":
        search["x_search"] = {}
    response = openrouter_client().chat.completions.create(
        model=model(reader),
        messages=[{"role": "system", "content": SOCIAL_SYSTEM},
                  {"role": "user", "content": social_request(platform, comp)}],
        tools=[{"type": "openrouter:web_search", "parameters": search}],
        max_tokens=SOCIAL_MAX_TOKENS,
    )
    message = response.choices[0].message
    cited = [a.url_citation.url for a in (message.annotations or []) if a.type == "url_citation"]
    posts = [u for u in dict.fromkeys(cited) if on_platform(u, domains)]
    return social_result(message.content or "", posts, f"{MODEL_NAMES[reader]} search via OpenRouter", response.model)


# --- running them ----------------------------------------------------------------------------------------

KEY_NAMES = {"claude": "ANTHROPIC_API_KEY", "gpt": "OPENAI_API_KEY", "grok": "XAI_API_KEY"}


def setup() -> dict[str, bool]:
    """Which models can be asked: all three with an OpenRouter key. Claude also runs on an ANTHROPIC_AUTH_TOKEN."""
    if route() == "openrouter":
        return dict.fromkeys(MODEL_NAMES, True)
    return {"claude": bool(config.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
            "gpt": bool(config.OPENAI_API_KEY), "grok": bool(config.XAI_API_KEY)}


def short_error(e: Exception) -> str:
    code = getattr(e, "status_code", None) or getattr(e, "code", None)  # the SDKs' errors, or pitch.OpenRouterError
    if code == 402 or (code == 403 and "limit" in str(e).lower()):
        return ("Out of credit: the OpenRouter key's spending limit or the account's credit is used up. Raise the "
                "key's limit or add credits on openrouter.ai, then Read missing now.")
    return f"{type(e).__name__}: {e}"[:240]


def run(jobs: dict) -> dict:
    """Run each job in parallel. A failure stays with its own source."""
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        futures = {key: pool.submit(fn) for key, fn in jobs.items()}
    out = {}
    for key, future in futures.items():
        try:
            out[key] = future.result()
        except Exception as e:  # noqa: BLE001 - one provider failing never stops the others
            out[key] = {"error": short_error(e)}
    return out


def can_read(platform: str) -> bool:
    """Whether this setup can read a platform: X needs Grok or Claude, the rest Claude."""
    ready = setup()
    return ready["claude"] or (platform == "x" and ready["grok"])


def rate_all(comp, only: list[str] | None = None, brief: str | None = None) -> dict:
    """Ask every model that has a key, or just those in `only`, to rate the company from its brief (brief.py; the
    full profile without one). Returns {source: result | {"error"} | {"skipped"}}."""
    ready, profile = setup(), brief or profile_text(comp)
    if route() == "openrouter":
        raters = {key: (lambda key=key: openrouter_rate(key, profile)) for key in MODEL_NAMES}
    else:
        direct = {"claude": claude_rate, "gpt": gpt_rate, "grok": grok_rate}
        raters = {key: (lambda fn=fn: fn(profile)) for key, fn in direct.items()}
    raters = {key: fn for key, fn in raters.items() if only is None or key in only}
    out = run({key: fn for key, fn in raters.items() if ready[key]})
    return out | {key: {"skipped": f"no {KEY_NAMES[key]} or OPENROUTER_API_KEY"} for key in raters if not ready[key]}


def social_all(comp, only: list[str] | None = None) -> dict:
    """Read every platform, or just those in `only`: X with Grok's own search when it has a key, the rest with
    Claude's web search."""
    platforms = [p for p in PLATFORMS if only is None or p in only]
    if route() == "openrouter":
        return run({platform: (lambda p=platform: openrouter_social(p, comp)) for platform in platforms})
    ready, jobs, out = setup(), {}, {}
    for platform in platforms:
        if platform == "x" and ready["grok"]:
            jobs[platform] = lambda: grok_social(comp)
        elif ready["claude"]:
            jobs[platform] = lambda p=platform: claude_social(p, comp)
        else:
            out[platform] = {"skipped": "no ANTHROPIC_API_KEY" + (", XAI_API_KEY" if platform == "x" else "")
                                        + " or OPENROUTER_API_KEY"}
    return run(jobs) | out
