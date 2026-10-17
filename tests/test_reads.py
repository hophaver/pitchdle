"""The outside reads against canned API responses: the real SDKs build each request and parse each answer, over a
mock transport, so no network or API key is needed."""
import json

import anthropic
import httpx2
import openai
import pytest

from app import config, reads

PROFILE = {"id": 1, "name": "Rakko Feed", "sector": "aquaculture & feed", "one_liner": "Seaweed in cow feed.",
           "claim_ask": "€800k", "website": "https://rakko.example", "vision": "Less methane.",
           "stages": '["Seed"]', "raised_eur": 650000,
           "investors": '[{"name": "Lumi Seed Fund", "status": "invested", "amount_eur": 400000}]'}


def claude_answer(content, stop_reason="end_turn", model="claude-opus-5-5"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


def openai_answer(text, annotations=(), model="gpt-6-astra"):
    return {"id": "resp_1", "object": "response", "created_at": 0, "model": model, "status": "completed",
            "output": [{"type": "message", "id": "m1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": list(annotations)}]}],
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": []}


class Recorder:
    """A mock transport that hands out canned answers in order and keeps every request it got."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, request):
        self.requests.append({"url": str(request.url), "headers": dict(request.headers),
                              "body": json.loads(request.content)})
        return httpx2.Response(200, json=self.answers.pop(0))


@pytest.fixture
def claude(monkeypatch):
    def use(*answers):
        rec = Recorder(*answers)
        monkeypatch.setattr(reads, "claude_client", lambda: anthropic.Anthropic(
            api_key="test", http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(rec))))
        return rec
    return use


@pytest.fixture
def oai(monkeypatch):
    def use(*answers):
        rec = Recorder(*answers)
        monkeypatch.setattr(reads, "openai_client", lambda key, base_url=None: openai.OpenAI(
            api_key="test", base_url=base_url,
            http_client=openai.DefaultHttpxClient(transport=httpx2.MockTransport(rec))))
        return rec
    return use


def test_profile_text_is_what_the_card_shows():
    text = reads.profile_text(PROFILE)
    assert "Name: Rakko Feed" in text and "Raised so far: €650 000" in text
    assert "Lumi Seed Fund (invested €400 000)" in text and "Stages passed: Seed" in text


def test_claude_rates_with_structured_output_and_fallback(claude):
    rec = claude(claude_answer([{"type": "text", "text": json.dumps(
        {"novel": 3, "useful": 4.3, "plausible": -1, "investable": 9, "reason": " Real   revenue. "})}]))
    out = reads.claude_rate(reads.profile_text(PROFILE))
    assert out == {"scores": {"novel": 3.0, "useful": 4.5, "plausible": 0.0, "investable": 5.0},
                   "note": "Real revenue.", "meta": {"model": "claude-opus-5-5"}}  # clamped, to the nearest half
    req = rec.requests[0]
    assert req["headers"]["anthropic-beta"] == reads.FALLBACK_BETA and req["body"]["fallbacks"] == "default"
    assert req["body"]["model"] == "claude-opus-5-5"
    assert req["body"]["output_config"]["format"]["schema"] == reads.SCORE_SCHEMA


def test_claude_refusal_is_an_error(claude):
    claude(claude_answer([], stop_reason="refusal"))
    with pytest.raises(RuntimeError, match="declined"):
        reads.claude_rate("x")


def test_gpt_rates_with_a_strict_schema(oai):
    rec = oai(openai_answer(json.dumps({"novel": 2, "useful": 3, "plausible": 4, "investable": 1, "reason": "ok"})))
    out = reads.gpt_rate("profile")
    assert out["scores"] == {"novel": 2.0, "useful": 3.0, "plausible": 4.0, "investable": 1.0}
    body = rec.requests[0]["body"]
    assert rec.requests[0]["url"] == "https://api.openai.com/v1/responses"
    assert body["model"] == "gpt-6-astra" and body["text"]["format"]["strict"] is True


def test_grok_rates_through_xai(oai):
    rec = oai(openai_answer('Sure. {"novel": 1, "useful": 2, "plausible": 3, "investable": 2.5, "reason": "meh"}',
                            model="grok-4.7"))
    out = reads.grok_rate("profile")
    assert out["scores"]["investable"] == 2.5 and out["meta"]["model"] == "grok-4.7"
    assert rec.requests[0]["url"] == "https://api.x.ai/v1/responses"


def search_turn(*urls):
    return [{"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "Rakko Feed"}},
            {"type": "web_search_tool_result", "tool_use_id": "srv_1", "content": [
                {"type": "web_search_result", "url": u, "title": "post", "encrypted_content": "e", "page_age": None}
                for u in urls]}]


def cited(text, *urls):
    return {"type": "text", "text": text, "citations": [
        {"type": "web_search_result_location", "url": u, "title": "post", "encrypted_index": "e", "cited_text": "c"}
        for u in urls]}


def test_claude_reads_one_platform_and_keeps_only_real_posts(claude):
    real = "https://www.reddit.com/r/Baltic/comments/abc/rakko_feed/"
    rec = claude(claude_answer([
        *search_turn(real, "https://www.reddit.com/r/Baltic/comments/def/other/"),
        # A cited link the search never returned is dropped, however sure the answer sounds.
        cited("Farmers like it.", real, "https://www.reddit.com/r/invented/comments/zzz/"),
        {"type": "text", "text": '\n{"posts": 9, "novel": 3, "useful": 4, "plausible": 3.5, "investable": 3, '
                                 '"summary": "Farmers like it."}'},
    ]))
    out = reads.claude_social("reddit", PROFILE)
    assert out["scores"] == {"novel": 3.0, "useful": 4.0, "plausible": 3.5, "investable": 3.0}
    assert out["meta"]["posts"] == 1 and out["meta"]["links"] == [real]  # verified posts, not the claimed 9
    tool = rec.requests[0]["body"]["tools"][0]
    assert tool["type"] == "web_search_20250305" and tool["allowed_domains"] == ["reddit.com"]


def test_a_paused_search_is_resumed(claude):
    post = "https://www.threads.com/@someone/post/1"
    rec = claude(claude_answer(search_turn(post), stop_reason="pause_turn"),
                 claude_answer([cited("Mixed.", post),
                                {"type": "text", "text": '{"posts": 1, "novel": 2, "useful": 2, "plausible": 2, '
                                                         '"investable": 2, "summary": "Mixed."}'}]))
    out = reads.claude_social("threads", PROFILE)
    assert out["meta"]["links"] == [post] and out["scores"]["novel"] == 2.0
    resumed = rec.requests[1]["body"]["messages"]
    assert [m["role"] for m in resumed] == ["user", "assistant"]
    assert resumed[1]["content"][0]["type"] == "server_tool_use"


def test_a_quiet_platform_has_no_scores(claude):
    claude(claude_answer([*search_turn(), {"type": "text", "text": '{"posts": 3, "novel": 5, "useful": 5, '
                                                                    '"plausible": 5, "investable": 5}'}]))
    out = reads.claude_social("bluesky", PROFILE)  # it claims posts, but cited none
    assert out["scores"] is None and out["meta"]["posts"] == 0


def test_grok_searches_x_itself(oai):
    post = "https://x.com/someone/status/123"
    rec = oai(openai_answer(
        'People on X are excited [[1]](https://x.com/someone/status/123). {"posts": 1, "novel": 4, "useful": 3, '
        '"plausible": 2, "investable": 3, "summary": "Excited."}',
        annotations=[{"type": "url_citation", "url": post, "start_index": 0, "end_index": 5, "title": "1"},
                     {"type": "url_citation", "url": "https://news.example/story", "start_index": 0, "end_index": 5,
                      "title": "2"}],
        model="grok-4.7"))
    out = reads.grok_social(PROFILE)
    assert out["meta"]["links"] == [post] and out["meta"]["via"] == "Grok X search"
    assert rec.requests[0]["body"]["tools"] == [{"type": "x_search"}]


def test_only_models_with_a_key_are_asked(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(config, "XAI_API_KEY", "")
    monkeypatch.setattr(reads, "gpt_rate", lambda profile: (_ for _ in ()).throw(RuntimeError("boom")))
    out = reads.rate_all(PROFILE)
    assert out["claude"] == {"skipped": "no ANTHROPIC_API_KEY or OPENROUTER_API_KEY"}
    assert out["grok"] == {"skipped": "no XAI_API_KEY or OPENROUTER_API_KEY"}
    assert out["gpt"] == {"error": "RuntimeError: boom"}  # a failure stays with its own model
    social = reads.social_all(PROFILE)
    assert set(social) == set(reads.PLATFORMS) and all("skipped" in r for r in social.values())


# --- one OpenRouter key for all three ------------------------------------------------------------------------

def chat_answer(content, annotations=(), model="anthropic/claude-opus-5.5"):
    return {"id": "gen_1", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": content, "annotations": list(annotations)}}]}


def url_citation(url):
    return {"type": "url_citation", "url_citation": {"url": url, "title": "post", "start_index": 0, "end_index": 4}}


def test_one_openrouter_key_runs_all_three(oai, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    assert reads.setup() == {"claude": True, "gpt": True, "grok": True}
    assert reads.models() == {"claude": "anthropic/claude-opus-5.5", "gpt": "openai/gpt-6-astra", "grok": "x-ai/grok-4.7"}
    answer = json.dumps({"novel": 3, "useful": 4, "plausible": 2, "investable": 3, "reason": "Solid."})
    rec = oai(*(chat_answer(answer, model=m) for m in reads.models().values()))
    out = reads.rate_all(PROFILE)
    assert set(out) == {"claude", "gpt", "grok"} and all(r["scores"]["useful"] == 4.0 for r in out.values())
    assert {r["body"]["model"] for r in rec.requests} == set(reads.models().values())
    req = rec.requests[0]
    assert req["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert req["body"]["response_format"]["json_schema"]["strict"] is True
    assert req["body"]["provider"] == {"require_parameters": True}
    # Capped, or OpenRouter reserves the whole 65k output window against the key's credit and refuses (402).
    assert all(r["body"]["max_tokens"] == reads.RATE_MAX_TOKENS for r in rec.requests)


def test_running_out_of_openrouter_credit_says_so():
    class PaymentRequired(Exception):
        status_code = 402
    assert reads.short_error(PaymentRequired("Error code: 402 - requested up to 65536 tokens")).startswith("Out of credit")


def test_models_can_be_overridden(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(config, "GPT_MODEL", "openai/gpt-6-sol")
    assert reads.model("gpt") == "openai/gpt-6-sol" and reads.model("claude") == "anthropic/claude-opus-5.5"


def test_an_empty_openrouter_answer_is_an_error(oai, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    oai(chat_answer(None))
    with pytest.raises(RuntimeError, match="no answer"):
        reads.openrouter_rate("claude", "profile")


def test_openrouter_reads_a_platform_with_native_search(oai, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    post = "https://www.linkedin.com/posts/someone_rakko-feed-123"
    rec = oai(chat_answer('People in the trade like it. {"posts": 4, "novel": 3, "useful": 4.5, "plausible": 4, '
                          '"investable": 3.5, "summary": "Practical."}',
                          [url_citation(post), url_citation("https://news.example/story")]))
    out = reads.openrouter_social("linkedin", PROFILE)
    assert out["meta"]["links"] == [post] and out["meta"]["posts"] == 1  # cited on the platform itself
    assert out["meta"]["via"] == "Claude search via OpenRouter" and out["scores"]["useful"] == 4.5
    body = rec.requests[0]["body"]
    assert body["model"] == "anthropic/claude-opus-5.5" and body["max_tokens"] == reads.SOCIAL_MAX_TOKENS
    assert body["tools"] == [{"type": "openrouter:web_search", "parameters": {
        "engine": "native", "max_uses": 2, "max_results": 5, "allowed_domains": ["linkedin.com"]}}]


def test_openrouter_reads_x_with_grok_search(oai, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-or-test")
    rec = oai(chat_answer('{"posts": 0}', model="x-ai/grok-4.7"))
    out = reads.openrouter_social("x", PROFILE)
    assert out["scores"] is None and out["meta"]["posts"] == 0  # nothing cited: a quiet platform
    body = rec.requests[0]["body"]
    assert body["model"] == "x-ai/grok-4.7" and body["tools"][0]["parameters"]["x_search"] == {}
