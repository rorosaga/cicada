"""G74(a) Task 3 — the `llm_mode="agent"` branch of resolve_llm_fn.

The seam contract (spec §2) is non-negotiable: dual access, sync/async
duality, accept-and-drop unknown kwargs except `timeout`, optional `usage`.
Zero spawns: every test injects a runner.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from api.config import Settings
from api.services import agent_engine, engine_errors, providers
from api.services.connections.base import CliResult
from api.services.telemetry import UsageEvent


def _agent_settings(**kw):
    return Settings(llm_mode="agent", agent_model="sonnet",
                    agent_disambiguation_model="haiku", **kw)


# --------------------------------------------------------------------------- #
# The seam contract
# --------------------------------------------------------------------------- #

def test_sync_call_site_gets_a_dual_access_response(agent_runner, agent_envelopes):
    fn = providers.resolve_llm_fn(_agent_settings(), stage="dedup", sink=lambda e: None,
                                  runner=agent_runner(agent_envelopes["success"]))
    resp = fn(messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == '{"entities": [], "relationships": []}'
    assert resp["choices"][0]["message"]["content"] == '{"entities": [], "relationships": []}'


def test_async_call_site_gets_an_awaitable(agent_runner, agent_envelopes):
    import litellm

    fn = providers.resolve_llm_fn(_agent_settings(), completion=litellm.acompletion,
                                  stage="extraction", sink=lambda e: None,
                                  runner=agent_runner(agent_envelopes["success"]))
    result = fn(messages=[{"role": "user", "content": "hi"}])
    assert asyncio.iscoroutine(result) or hasattr(result, "__await__")
    resp = asyncio.run(result)
    assert resp.choices[0].message.content


def test_is_async_override_wins_over_inference(agent_runner, agent_envelopes):
    """V6: iscoroutinefunction(litellm.acompletion) is True and (completion) is
    False, so inference is sound — but the override exists for callers that
    pass neither."""
    fn = providers.resolve_llm_fn(_agent_settings(), is_async=True, sink=lambda e: None,
                                  runner=agent_runner(agent_envelopes["success"]))
    resp = asyncio.run(fn(messages=[{"role": "user", "content": "hi"}]))
    assert resp["model"] == "claude-sonnet-5"


def test_unknown_kwargs_are_dropped_but_timeout_is_honoured(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["success"])
    fn = providers.resolve_llm_fn(_agent_settings(), sink=lambda e: None, runner=runner)
    fn(messages=[{"role": "user", "content": "hi"}],
       response_format={"type": "json_object"},
       extra_body={"reasoning": {"enabled": False}}, temperature=0, max_tokens=100,
       timeout=42)
    call = runner.calls[0]
    assert call["timeout"] == 42.0
    argv = " ".join(call["argv"])
    for leaked in ("reasoning", "temperature", "max_tokens", "extra_body"):
        assert leaked not in argv


def test_stage_selects_the_cheaper_judge_model(agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["structured"])
    fn = providers.resolve_llm_fn(_agent_settings(), stage="disambiguation",
                                  sink=lambda e: None, runner=runner)
    fn(messages=[{"role": "user", "content": "a vs b"}], response_format={"type": "json_object"})
    argv = runner.calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == "haiku"


def test_is_async_false_override_forces_the_sync_path(agent_runner, agent_envelopes):
    """Fix round 1, L4: only the True direction was tested; False (forcing
    the blocking path even though completion=litellm.acompletion infers
    async) had no coverage."""
    import litellm

    fn = providers.resolve_llm_fn(_agent_settings(), completion=litellm.acompletion,
                                  is_async=False, sink=lambda e: None,
                                  runner=agent_runner(agent_envelopes["success"]))
    resp = fn(messages=[{"role": "user", "content": "hi"}])
    assert not asyncio.iscoroutine(resp) and not hasattr(resp, "__await__")
    assert resp["model"] == "claude-sonnet-5"


def test_a_non_numeric_or_non_positive_timeout_falls_back_without_raising(agent_runner, agent_envelopes):
    """Fix round 1, L3: `float(raw_timeout)` used to raise out of the seam
    before any telemetry for a non-numeric value, and `timeout=0` silently
    (accidentally) degraded to the default rather than by deliberate rule."""
    runner = agent_runner(agent_envelopes["success"])
    fn = providers.resolve_llm_fn(_agent_settings(), sink=lambda e: None, runner=runner)
    fn(messages=[{"role": "user", "content": "hi"}], timeout="not-a-number")
    fn(messages=[{"role": "user", "content": "hi"}], timeout=0)
    fn(messages=[{"role": "user", "content": "hi"}], timeout=-5)
    for call in runner.calls:
        assert call["timeout"] == providers.AGENT_DEFAULT_TIMEOUT_S


# --------------------------------------------------------------------------- #
# Telemetry: honest numbers for a subscription call (spec §6)
# --------------------------------------------------------------------------- #

def test_agent_event_is_subscription_shaped(agent_runner, agent_envelopes):
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(_agent_settings(), stage="extraction",
                                  sink=events.append, bank="lab",
                                  runner=agent_runner(agent_envelopes["success"]))
    fn(messages=[{"role": "user", "content": "hi"}])

    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "llm_call" and ev.stage == "extraction" and ev.bank == "lab"
    assert ev.engine == "claude-cli"
    # Must EQUAL the adapter id: consumption_stats.per_connection joins strictly on it.
    assert ev.connection == "claude-plan"
    assert ev.billing == "subscription"
    assert ev.model == "claude-sonnet-5"          # what the CLI actually used
    assert ev.cost_usd is None                    # a plan call is never money
    assert ev.equiv_cost_usd == 0.092             # list-price metering only
    assert (ev.input_tokens, ev.output_tokens) == (19633, 57)
    assert ev.cache_write_tokens == 19631
    assert ev.ok and ev.duration_ms is not None


def test_byok_events_are_byte_identical_to_before():
    """The non-agent path must not move. Same assertions as
    test_seam_telemetry.test_sync_call_records_event."""
    class _Resp:
        def __init__(self):
            self.choices = [type("C", (), {"message": type("M", (), {"content": "{}"})()})()]
            self.usage = {"prompt_tokens": 120, "completion_tokens": 30}
            self._hidden_params = {"response_cost": 0.002}

    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(Settings(litellm_model="gpt-5.4-mini"),
                                  completion=lambda **kw: _Resp(),
                                  stage="ask", sink=events.append)
    fn(messages=[])
    ev = events[0]
    assert ev.engine == "litellm" and ev.connection == "byok-openai" and ev.billing == "usage"
    assert ev.cost_usd == 0.002


def test_a_failed_agent_call_records_not_ok_and_reraises(agent_runner, agent_envelopes):
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(_agent_settings(), sink=events.append,
                                  runner=agent_runner(agent_envelopes["budget_exhausted"]))
    with pytest.raises(engine_errors.EngineExhausted):
        fn(messages=[{"role": "user", "content": "hi"}])
    assert len(events) == 1 and events[0].ok is False and events[0].engine == "claude-cli"


def test_a_non_engine_error_from_the_runner_still_emits_an_event():
    """Fix round 1, M1: the agent branch used to catch only
    `engine_errors.EngineError`, where byok catches `except Exception`. A
    runner that raises anything else — or a `response_shim`/
    `equiv_cost_from_envelope` failure, which used to sit OUTSIDE the try —
    produced NO UsageEvent at all, on the one path whose entire justification
    is making failures visible."""
    events: list[UsageEvent] = []

    def _boom(argv, *, stdin=None, timeout=None, cwd=None):
        raise RuntimeError("the subprocess machinery itself blew up")

    fn = providers.resolve_llm_fn(_agent_settings(), sink=events.append, runner=_boom)
    with pytest.raises(RuntimeError):
        fn(messages=[{"role": "user", "content": "hi"}])
    assert len(events) == 1
    assert events[0].ok is False and events[0].engine == "claude-cli"


def test_the_first_throttle_writes_the_first_ever_throttle_event(agent_runner, agent_envelopes):
    """telemetry.KINDS has listed "throttle" and consumption_stats:249 has
    counted throttle_events since G51 — nothing has ever written one."""
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(_agent_settings(), stage="extraction", sink=events.append,
                                  runner=agent_runner(agent_envelopes["rate_limited"]))
    with pytest.raises(engine_errors.EngineThrottled):
        fn(messages=[{"role": "user", "content": "hi"}])
    kinds = [e.kind for e in events]
    assert kinds.count("throttle") == 1
    throttle = next(e for e in events if e.kind == "throttle")
    assert throttle.throttled is True and throttle.connection == "claude-plan"
    assert throttle.invocations == 0 and throttle.ok is False


def test_only_one_throttle_event_per_cycle_even_across_many_calls(agent_runner, agent_envelopes):
    events: list[UsageEvent] = []
    runner = agent_runner(agent_envelopes["rate_limited"])
    fn = providers.resolve_llm_fn(_agent_settings(), sink=events.append, runner=runner)
    for _ in range(5):
        with pytest.raises(engine_errors.EngineThrottled):
            fn(messages=[{"role": "user", "content": "hi"}])
    assert sum(1 for e in events if e.kind == "throttle") == 1
    # Only the tripping call spawned; the other four failed fast.
    assert len(runner.calls) == 1
    # Fix round 1, L1: the four fail-fast calls never touched the runner, so
    # they must not become phantom `llm_call` rows either — only the one
    # genuine (spawned) attempt and the one throttle event are recorded.
    assert sum(1 for e in events if e.kind == "llm_call") == 1
    assert len(events) == 2


def test_a_throttle_event_is_exactly_one_under_concurrent_callers(agent_runner, agent_envelopes):
    """Fix round 1, L2: the existing throttle-count assertion above is
    sequential. Under real concurrency (agent_max_concurrency > 1), several
    callers can spawn before any of them trips the breaker — `trip_breaker`
    is `_STATE_LOCK`-guarded and only the winner emits `_emit_throttle`, so
    the throttle-event count must stay exactly one even when more than one
    call genuinely spawns and independently discovers the throttle."""
    import litellm

    events: list[UsageEvent] = []
    runner = agent_runner(agent_envelopes["rate_limited"])
    fn = providers.resolve_llm_fn(_agent_settings(agent_max_concurrency=5),
                                  completion=litellm.acompletion,
                                  sink=events.append, runner=runner)

    async def _fan_out():
        results = await asyncio.gather(
            *(fn(messages=[{"role": "user", "content": "x"}]) for _ in range(8)),
            return_exceptions=True,
        )
        assert all(isinstance(r, engine_errors.EngineThrottled) for r in results)

    asyncio.run(_fan_out())

    assert sum(1 for e in events if e.kind == "throttle") == 1
    # More than one call may have genuinely spawned and raced to discover the
    # throttle (bounded by agent_max_concurrency), but never all 8.
    assert 1 <= len(runner.calls) < 8


def test_the_dashboard_aggregations_survive_a_null_cost_event():
    """The Usage page must total a subscription event without crashing on the
    None cost, and attribute it to the claude-plan card."""
    from api.services import consumption_stats

    ev = UsageEvent(kind="llm_call", connection="claude-plan", engine="claude-cli",
                    billing="subscription", model="claude-sonnet-5",
                    input_tokens=19633, output_tokens=57,
                    cost_usd=None, equiv_cost_usd=0.092)
    rows = consumption_stats.per_connection(
        [ev], [{"id": "claude-plan", "label": "Claude plan",
                "billing": "subscription", "connected": True, "priceUsdMonth": 100.0}])
    assert rows[0]["cost_usd"] is None            # never presented as spend
    assert rows[0]["equiv_cost_usd"] == 0.092
    assert rows[0]["tokens"] == 19690


def test_the_rung_semaphore_caps_concurrent_spawns():
    """Stage 1 fans out at MAX_CONCURRENCY=10; the rung must not turn that into
    10 concurrent `claude` processes."""
    import threading

    live = 0
    peak = 0
    lock = threading.Lock()

    def runner(argv, *, stdin=None, timeout=None, cwd=None):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        try:
            import time as _t
            _t.sleep(0.02)
            return CliResult(0, json.dumps({
                "is_error": False, "result": "{}", "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1}}), "")
        finally:
            with lock:
                live -= 1

    import litellm

    fn = providers.resolve_llm_fn(_agent_settings(agent_max_concurrency=2),
                                  completion=litellm.acompletion,
                                  sink=lambda e: None, runner=runner)

    async def _fan_out():
        await asyncio.gather(*(fn(messages=[{"role": "user", "content": "x"}]) for _ in range(8)))

    asyncio.run(_fan_out())
    assert peak <= 2


def test_the_rung_semaphore_is_shared_across_sync_and_async_callers():
    """Devin PR #25 round 1, finding 2: the sync branch (a synchronous Ask,
    say) and the async branch (a Sleep cycle) used to draw from two
    INDEPENDENT semaphore pools, so together they could spawn up to DOUBLE
    the configured `agent_max_concurrency` — exactly the machine-wide cap
    this limiter exists to enforce. One shared `threading.BoundedSemaphore`
    now backs both call styles, so mixed concurrent use still caps at the
    configured limit."""
    import threading
    import time as _t

    live = 0
    peak = 0
    lock = threading.Lock()

    def runner(argv, *, stdin=None, timeout=None, cwd=None):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        try:
            _t.sleep(0.05)
            return CliResult(0, json.dumps({
                "is_error": False, "result": "{}", "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1}}), "")
        finally:
            with lock:
                live -= 1

    import litellm

    settings = _agent_settings(agent_max_concurrency=2)
    sync_fn = providers.resolve_llm_fn(settings, sink=lambda e: None, runner=runner)
    async_fn = providers.resolve_llm_fn(settings, completion=litellm.acompletion,
                                        sink=lambda e: None, runner=runner)

    async def _drive():
        loop = asyncio.get_event_loop()
        # Four "synchronous Ask" callers, each dispatched to its own worker
        # thread (mirroring how a sync call site is actually invoked outside
        # an event loop) ...
        sync_futures = [
            loop.run_in_executor(
                None, lambda: sync_fn(messages=[{"role": "user", "content": "x"}])
            )
            for _ in range(4)
        ]
        # ... running AT THE SAME TIME as four native async ("Sleep cycle")
        # callers.
        async_coros = [
            async_fn(messages=[{"role": "user", "content": "x"}]) for _ in range(4)
        ]
        await asyncio.gather(*sync_futures, *async_coros)

    asyncio.run(_drive())
    assert peak <= 2
