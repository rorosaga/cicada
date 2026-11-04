"""G237: a Claude key through the official SDK, at the HTTP layer. No network: `anthropic_stub` is the server."""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

pytest.importorskip("anthropic")

import litellm

from api.config import Settings
from api.services import agent_engine, anthropic_engine, anthropic_models, engine_errors, price_supplement, providers, telemetry
from api.services.sleep_drain import classify, classify_episode
from api.tests.anthropic_stub import StubAnthropic, error_body

MODEL = "anthropic/claude-haiku-5-5"
SYSTEM = "You extract facts. " * 200     # long enough to cache
SCOPE = "test:anthropic"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    agent_engine.reset_breaker(scope=SCOPE)
    yield
    agent_engine.reset_breaker(scope=SCOPE)
    anthropic_engine.reset_clients()


def _fn(events=None, *, model=MODEL, completion=None, **kw):
    settings = Settings(llm_mode="byok", litellm_model=model)
    return providers.resolve_llm_fn(settings, model=model, completion=completion or litellm.completion,
                                    stage="extraction", sink=(events if events is not None else []).append,
                                    bank="b", scope=SCOPE, **kw)


def _msgs(user="alpha-project shipped."):
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


# ---- what goes on the wire ----------------------------------------------------------------------------------------


def test_cicadas_call_shape_is_a_request_the_api_takes(monkeypatch):
    """Every kwarg a stage sends through litellm's shape is translated or dropped: nothing the API rejects survives."""
    stub = StubAnthropic(answer=lambda b: '{"ok": true}')
    stub.install(monkeypatch)
    resp = _fn()(messages=_msgs(), response_format={"type": "json_object"},
                 extra_body={"reasoning": {"enabled": False}}, timeout=120, temperature=0)
    body = stub.requests[0]
    assert set(body) <= {"model", "max_tokens", "system", "messages", "output_config", "stream"}
    assert "extra_body" not in body and "temperature" not in body and "response_format" not in body
    assert body["model"] == "claude-haiku-5-5" and body["stream"] is True
    assert body["output_config"] == {"effort": "low"}
    assert body["messages"] == [{"role": "user", "content": "alpha-project shipped."}]
    assert resp.choices[0].message.content == '{"ok": true}'
    assert resp["choices"][0]["message"]["content"] == '{"ok": true}'


def test_json_is_asked_for_in_the_same_words_as_the_plan_and_the_marker_ends_the_system_prompt(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    _fn()(messages=_msgs(), response_format={"type": "json_object"})
    (block,) = stub.requests[0]["system"]
    assert block["text"].endswith(agent_engine.JSON_ONLY_SUFFIX) and block["text"].startswith(SYSTEM.strip())
    assert agent_engine.CONTEXT_GUARD not in block["text"]   # the API attaches no context of its own
    assert block["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_the_prefix_is_byte_identical_between_calls(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    fn = _fn()
    fn(messages=_msgs("first conversation"), response_format={"type": "json_object"})
    fn(messages=_msgs("second conversation"), response_format={"type": "json_object"})
    first, second = stub.requests
    assert json.dumps(first["system"], sort_keys=True) == json.dumps(second["system"], sort_keys=True)
    assert first["messages"] != second["messages"]


def test_a_callers_short_cap_leaves_room_for_thinking_and_the_ceiling_is_the_models(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "A site about things.")
    stub.install(monkeypatch)
    _fn()(messages=[{"role": "user", "content": "describe"}], max_tokens=100, temperature=0)
    assert stub.requests[0]["max_tokens"] == anthropic_engine.THINKING_ROOM
    anthropic_models.refresh(client=stub.client("k"))
    _fn(model="anthropic/claude-haiku-4-5-20251001")(messages=_msgs())
    assert stub.requests[-1]["max_tokens"] == 64000   # the list's own limit
    _fn()(messages=_msgs())
    assert stub.requests[-1]["max_tokens"] == anthropic_engine.DEFAULT_MAX_TOKENS


def test_effort_goes_only_to_a_model_that_takes_it(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    reasoning_off = {"reasoning": {"enabled": False}}
    _fn(model="anthropic/claude-haiku-4-5")(messages=_msgs(), extra_body=reasoning_off)
    assert "output_config" not in stub.requests[-1]
    _fn(model="anthropic/claude-sonnet-5-5")(messages=_msgs(), extra_body=reasoning_off)
    assert stub.requests[-1]["output_config"] == {"effort": "low"}


def test_a_key_is_never_read_from_the_sdks_own_chain_and_the_host_is_fixed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    anthropic_engine.reset_clients()
    with pytest.raises(engine_errors.EngineUnavailable, match="refused the API key"):
        anthropic_engine.make_client()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stub-key-not-real")
    assert str(anthropic_engine.make_client().base_url).startswith("https://api.anthropic.com")


# ---- caching ------------------------------------------------------------------------------------------------------


def _hit_rate(events):
    read = sum(e.cache_read_tokens for e in events)
    gross = sum(e.input_tokens for e in events)
    return read / gross if gross else 0.0


def test_sequential_calls_read_what_the_first_wrote(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    events: list = []
    fn = _fn(events)
    for i in range(5):
        fn(messages=_msgs(f"conversation {i}"), response_format={"type": "json_object"})
    assert events[0].cache_write_tokens > 0 and events[0].cache_read_tokens == 0
    assert all(e.cache_read_tokens > 0 and e.cache_write_tokens == 0 for e in events[1:])
    assert _hit_rate(events) > 0.7


def test_a_fan_out_writes_once_and_reads_the_rest(monkeypatch):
    """Measured on the plan (three parallel `claude -p`, zero reads, three full writes): what the first-call gate is for."""
    stub = StubAnthropic(answer=lambda b: "{}", latency=0.05)
    stub.install(monkeypatch)
    events: list = []
    fn = _fn(events)
    threads = [threading.Thread(target=fn, kwargs={"messages": _msgs(f"c{i}")}) for i in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(e.cache_write_tokens > 0 for e in events) == [False, False, True]
    assert sum(e.cache_read_tokens > 0 for e in events) == 2


def test_a_first_call_that_fails_hands_the_prefix_on_and_nobody_waits_the_full_bound(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}", fail=[(500, error_body("api_error", "boom"), {})])
    stub.install(monkeypatch)
    monkeypatch.setattr(anthropic_engine, "GATE_WAIT_S", 2.0)
    fn = _fn()
    with pytest.raises(engine_errors.EngineConnectionLost):
        fn(messages=_msgs())
    fn(messages=_msgs())   # the next call goes first
    assert len(stub.requests) >= 2


def test_cost_reads_each_cache_rate_and_the_long_prompt_rate():
    per_million = price_supplement.claude_cost
    # Haiku 5.5, a 1-hour write: 1M input-equivalent units at each listed rate.
    assert per_million(MODEL, input_tokens=1_000, output_tokens=1_000, cache_read=10_000, cache_write=5_000,
                       cache_write_1h=5_000) == pytest.approx((100 + 500 + 100 + 1000) / 1e6, abs=1e-6)
    # Over 100,000 tokens of prompt (cache reads count) every rate is the long one.
    assert per_million(MODEL, input_tokens=1_000, output_tokens=0, cache_read=100_000) == pytest.approx(
        (500 + 5000) / 1e6, abs=1e-6)
    assert per_million("anthropic/claude-haiku-4-5-20251001", input_tokens=1_000_000, output_tokens=0) == 1.0
    assert per_million("anthropic/claude-new-9", input_tokens=1, output_tokens=1) is None


def test_the_ledger_records_a_charged_call_with_its_source_and_a_gross_prompt(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    events: list[telemetry.UsageEvent] = []
    _fn(events)(messages=_msgs())
    (ev,) = events
    assert (ev.engine, ev.connection, ev.billing, ev.model) == ("anthropic-api", "byok-anthropic", "usage",
                                                                "claude-haiku-5-5")
    assert ev.input_tokens >= ev.cache_write_tokens > 0
    assert ev.cost_usd is not None and ev.cost_usd > 0 and ev.refs["cost_source"] == "table"


def test_a_model_with_no_price_is_unknown_and_its_tokens_still_show(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    events: list[telemetry.UsageEvent] = []
    _fn(events, model="anthropic/claude-haiku-9")(messages=_msgs())
    (ev,) = events
    assert ev.cost_usd is None and ev.input_tokens > 0


# ---- failures, in words -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status, body, headers, expected, words", [
    (429, error_body("rate_limit_error", "Number of requests exceeded"), {"retry-after": "30"},
     engine_errors.EngineThrottled, "rate-limiting the API key"),
    (429, error_body("rate_limit_error", "You have reached your API usage limits", "enforced_spend_limit_reached"), {},
     engine_errors.EngineExhausted, "spending limit"),
    (400, error_body("invalid_request_error", "You have reached your specified API usage limits."), {},
     engine_errors.EngineExhausted, "spending limit"),
    (400, error_body("invalid_request_error", "Your credit balance is too low"), {},
     engine_errors.EngineExhausted, "spending limit"),
    (401, error_body("authentication_error", "invalid x-api-key"), {},
     engine_errors.EngineUnavailable, "refused the API key"),
    (529, error_body("overloaded_error", "Overloaded"), {}, engine_errors.EngineThrottled, "overloaded"),
    (500, error_body("api_error", "Internal"), {}, engine_errors.EngineConnectionLost, "service failed"),
    (400, error_body("invalid_request_error", "prompt is too long"), {}, engine_errors.EngineFailed, "refused this"),
])
def test_every_refusal_is_a_class_above_understands_and_says_nothing_of_the_provider(
        monkeypatch, status, body, headers, expected, words):
    stub = StubAnthropic(fail=[(status, body, headers)])
    stub.install(monkeypatch)
    with pytest.raises(expected) as caught:
        _fn()(messages=_msgs())
    assert words in str(caught.value)
    assert body["error"]["message"] not in str(caught.value)   # the provider's raw text never reaches the wire


def test_a_429_trips_the_breaker_once_and_every_later_call_fails_before_anything_is_sent(monkeypatch):
    stub = StubAnthropic(fail=[(429, error_body("rate_limit_error", "slow down"), {"retry-after": "600"})])
    stub.install(monkeypatch)
    events: list[telemetry.UsageEvent] = []
    fn = _fn(events)
    with pytest.raises(engine_errors.EngineThrottled):
        fn(messages=_msgs())
    sent = len(stub.requests)
    with pytest.raises(engine_errors.EngineThrottled):
        fn(messages=_msgs())
    assert len(stub.requests) == sent, "the breaker stops the next call before it is sent"
    assert agent_engine.breaker_kind(scope=SCOPE) == "key_limit"
    assert isinstance(agent_engine.breaker_resets_at(scope=SCOPE), int)
    assert [e.kind for e in events] == ["llm_call", "throttle"]   # one failed call, one throttle, no phantom row
    assert events[0].ok is False


def test_a_429_is_a_pause_that_never_says_the_persons_plan(monkeypatch):
    stub = StubAnthropic(fail=[(429, error_body("rate_limit_error", "slow down"), {})])
    stub.install(monkeypatch)
    with pytest.raises(engine_errors.EngineThrottled) as caught:
        _fn()(messages=_msgs())
    stop = classify(caught.value)
    assert stop.reason == "plan_limit" and stop.limit == "key_limit"
    assert "plan" not in stop.sentence.lower()
    from api.services import sleep_paused

    assert sleep_paused.reason_for(stop) == "key_limit"


def test_the_sdks_own_retry_rides_out_a_short_429(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}", fail=[(429, error_body("rate_limit_error", "slow"), {"retry-after": "0"})])
    stub.install(monkeypatch, max_retries=2)
    resp = _fn()(messages=_msgs())
    assert resp.choices[0].message.content == "{}" and len(stub.requests) == 2


def test_a_refusal_is_the_conversations_never_the_engines_and_is_not_retried(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "", stop_reason="refusal",
                         stop_details={"type": "refusal", "category": "cyber", "explanation": None})
    stub.install(monkeypatch)
    with pytest.raises(engine_errors.EngineRefused) as caught:
        _fn()(messages=_msgs())
    assert classify_episode(caught.value) == ("content", "refused")
    assert len(stub.requests) == 1


def test_an_answer_cut_off_is_a_protocol_error_worth_one_retry(monkeypatch):
    stub = StubAnthropic(answer=lambda b: '{"partial":', stop_reason="max_tokens")
    stub.install(monkeypatch)
    with pytest.raises(engine_errors.EngineProtocolError, match="cut off"):
        _fn()(messages=_msgs())


def test_an_empty_answer_is_an_empty_answer(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "")
    stub.install(monkeypatch)
    with pytest.raises(engine_errors.EngineProtocolError):
        _fn()(messages=_msgs())


def test_the_semaphore_and_the_async_seam_are_the_plans(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    async def gather():
        fn = _fn(completion=litellm.acompletion)
        return await asyncio.gather(*(fn(messages=_msgs(f"c{i}")) for i in range(4)))
    assert [r.choices[0].message.content for r in asyncio.run(gather())] == ["{}"] * 4


def test_a_fake_completion_a_test_injected_stays_the_answer(monkeypatch):
    calls = []

    async def fake(**kw):
        calls.append(kw)
        return "from the fake"

    fn = providers.resolve_llm_fn(Settings(llm_mode="byok", litellm_model=MODEL), model=MODEL, completion=fake,
                                  sink=lambda e: None, bank="b")
    assert asyncio.run(fn(messages=_msgs())) == "from the fake" and calls[0]["model"] == MODEL


def test_a_router_or_another_key_stays_on_litellm():
    from api.services import direct_engines

    assert direct_engines.for_model("anthropic/claude-haiku-5-5").label == "anthropic-api"
    assert direct_engines.for_model("claude-sonnet-5-5").label == "anthropic-api"
    for model in ("openrouter/anthropic/claude-haiku-4-5", "gpt-5.4-mini", "bedrock/anthropic.claude-haiku-5-5",
                  "groq/openai/gpt-oss-120b", "ollama/llama3", ""):
        assert direct_engines.for_model(model) is None, model


def test_a_search_comes_back_in_the_shape_the_pinned_query_check_reads(monkeypatch):
    from api.services import web_lookup

    stub = StubAnthropic(answer=lambda b: "{}", search_blocks=[
        {"type": "server_tool_use", "id": "srvtoolu_x", "name": "web_search", "input": {}}])
    stub.install(monkeypatch)
    events: list[telemetry.UsageEvent] = []
    resp = _fn(events)(messages=_msgs(), web_search=True)
    assert stub.requests[0]["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
    assert web_lookup.searched_queries(resp) == [""]
    assert events[0].cost_usd >= price_supplement.CLAUDE_SEARCH_USD
    _fn(model="anthropic/claude-sonnet-5-5")(messages=_msgs(), web_search=True)
    assert stub.requests[-1]["tools"][0]["type"] == "web_search_20260209"


# ---- the model list -----------------------------------------------------------------------------------------------


def test_a_key_lists_its_models_and_the_tiers_follow_the_lines(monkeypatch):
    stub = StubAnthropic()
    stub.install(monkeypatch)
    assert anthropic_models.tier("small") == "anthropic/claude-haiku-5-5"   # the documented floor, before any list
    assert anthropic_models.refresh() is True
    assert anthropic_models.tier("standard") == "anthropic/claude-sonnet-5-5"
    # A new model in a line takes its tier without a code change.
    stub.models = [*stub.models, {"id": "claude-haiku-6", "line": "haiku", "lifecycle": "active",
                                  "created_at": "2026-12-01T00:00:00Z", "display_name": "Claude Haiku 6",
                                  "max_tokens": 128000}]
    anthropic_models.refresh()
    assert anthropic_models.tier("small") == "anthropic/claude-haiku-6"
    assert anthropic_models.resolve("anthropic/haiku").model == "claude-haiku-6"


def test_a_retired_id_moves_forward_with_words(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}")
    stub.install(monkeypatch)
    anthropic_models.refresh()
    served = anthropic_models.resolve("anthropic/claude-opus-4-1-20250805")
    assert served.model == "claude-opus-5-5" and "no longer offered" in served.note
    events: list[telemetry.UsageEvent] = []
    _fn(events, model="anthropic/claude-opus-4-1-20250805")(messages=_msgs())
    assert stub.requests[-1]["model"] == "claude-opus-5-5" and events[0].model == "claude-opus-5-5"
    assert "no longer offered" in anthropic_models.forwarded_sentence("anthropic/claude-opus-4-1-20250805")


def test_a_404_moves_forward_once_and_a_second_stops_the_run_in_words(monkeypatch):
    stub = StubAnthropic(answer=lambda b: "{}", refused_models={"claude-haiku-3-old"})
    stub.install(monkeypatch)
    resp = _fn(model="anthropic/claude-haiku-3-old")(messages=_msgs())
    assert resp.model == "claude-haiku-5-5"
    assert "no longer offered" in anthropic_models.forwarded_sentence("anthropic/claude-haiku-3-old")
    stub.refused_models = {"claude-weird-9"}
    with pytest.raises(engine_errors.EngineModelNotFound, match="does not know the model"):
        _fn(model="anthropic/claude-weird-9")(messages=_msgs())


def test_a_list_that_fails_keeps_the_last_answer_and_an_empty_one_is_drift(monkeypatch):
    stub = StubAnthropic()
    stub.install(monkeypatch)
    anthropic_models.refresh()
    stub.models = []
    assert anthropic_models.refresh() is False
    assert anthropic_models.tier("top") == "anthropic/claude-opus-5-5"
    ids, cat = anthropic_models.card(None)
    assert ids and cat["drift"]


def test_the_list_read_is_daily_and_bills_nothing(monkeypatch):
    stub = StubAnthropic()
    stub.install(monkeypatch)
    assert anthropic_models.refresh_if_stale() is True
    before = len(stub.headers_seen)
    assert anthropic_models.refresh_if_stale() is False
    assert len(stub.headers_seen) == before
    assert not stub.requests


def test_the_card_keeps_a_saved_choice_first_and_hides_old_models_unless_saved(monkeypatch):
    stub = StubAnthropic()
    stub.install(monkeypatch)
    anthropic_models.refresh()
    ids, cat = anthropic_models.card(None)
    assert ids[:3] == ["anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5", "anthropic/claude-opus-5-5"]
    assert "anthropic/claude-opus-4-1-20250805" not in ids and "anthropic/claude-sonnet-4-5-20250929" not in ids
    ids, cat = anthropic_models.card("anthropic/claude-opus-4-1-20250805")
    assert ids[0] == "anthropic/claude-opus-4-1-20250805"
    assert {m["source"] for m in cat["models"] if m["id"] == ids[0]} == {"saved"}
    assert cat["source"] == "your key"
