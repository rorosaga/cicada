"""Owner G171/G163: transport failures retry, pause and keep Continue available."""
from __future__ import annotations

import asyncio
import json

import pytest

from drain_harness import episode_ids, git, install, seed_bank, settings, waiting
from api.config import Settings
from api.services import agent_engine, codex_engine, engine_errors, providers, sleep_cycle, sleep_paused, sleep_parked
from api.services.connections.base import CliResult


@pytest.fixture(autouse=True)
def idle():
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    yield
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False


def failed(mode, message, shape="events"):
    if shape == "empty":
        return CliResult(1, "", message)
    if shape == "plain":
        return CliResult(1, message, "")
    event = ({"type": "turn.failed", "error": {"message": message}} if mode == "codex" else
             {"type": "result", "is_error": True, "subtype": "error_during_execution", "result": message})
    return CliResult(1, json.dumps(event), "")


def check(mode, result):
    if mode == "codex":
        return codex_engine.check(result, codex_engine.parse_events(result.stdout))
    return agent_engine.parse_envelope(result)


@pytest.mark.parametrize("mode", ["agent", "codex"])
@pytest.mark.parametrize("shape", ["events", "empty", "plain"])
@pytest.mark.parametrize("message", [
    "workspace routing discovery failed", "Reconnecting… 5/5 (connection closed)",
    "Reconnecting... 2/5", "getaddrinfo ENOTFOUND example.com", "connect ECONNREFUSED 127.0.0.1",
    "Temporary failure in name resolution", "Network is unreachable", "Connection error.",
    "The Internet connection appears to be offline", "error sending request: connection reset by peer",
])
def test_failed_transport_diagnoses_are_retryable_connection_errors(mode, shape, message):
    with pytest.raises(engine_errors.EngineError) as caught:
        check(mode, failed(mode, message, shape))
    assert type(caught.value).__name__ == "EngineConnectionLost"
    assert isinstance(caught.value, engine_errors.RETRYABLE)
    assert message in str(caught.value)


@pytest.mark.parametrize("mode", ["agent", "codex"])
def test_reconnect_notice_without_a_result_is_connection_loss_even_at_timeout(mode):
    event = ({"type": "error", "message": "Reconnecting... 5/5"} if mode == "codex" else
             {"type": "system", "subtype": "api_retry", "error": "connection_error"})
    for rc in (1, 124):
        with pytest.raises(engine_errors.EngineError) as caught:
            check(mode, CliResult(rc, json.dumps(event), ""))
        assert type(caught.value).__name__ == "EngineConnectionLost"


@pytest.mark.parametrize("mode", ["agent", "codex"])
@pytest.mark.parametrize("shape", ["events", "empty", "plain"])
@pytest.mark.parametrize("message,expected", [
    ("not logged in", engine_errors.EngineUnavailable),
    ("model not found", engine_errors.EngineModelNotFound),
    ("rate limit reached", engine_errors.EngineThrottled),
])
def test_non_transient_diagnoses_outrank_earlier_reconnect_warnings(mode, shape, message, expected):
    result = failed(mode, message, shape)
    result = CliResult(result.rc, result.stdout, f"{result.stderr}\nReconnecting... 2/5")
    with pytest.raises(expected):
        check(mode, result)


@pytest.mark.parametrize("mode", ["agent", "codex"])
def test_completed_reply_after_reconnection_is_success(mode):
    events = ([{"type": "error", "message": "Reconnecting... 2/5"},
               {"type": "item.completed", "item": {"type": "agent_message", "text": "offline notes"}},
               {"type": "turn.completed", "usage": {}}] if mode == "codex" else
              [{"type": "system", "subtype": "api_retry", "error": "connection_error"},
               {"type": "result", "is_error": False, "result": "offline notes"}])
    check(mode, CliResult(0, "\n".join(json.dumps(e) for e in events), "connection reset"))


@pytest.mark.parametrize("mode", ["agent", "codex"])
def test_repeated_extraction_connection_loss_never_parks_and_recovers_on_continue(tmp_path, monkeypatch, mode):
    from types import SimpleNamespace
    from api.services import entity_extractor

    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    real_extract = entity_extractor.extract
    install(monkeypatch)
    monkeypatch.setattr(entity_extractor, "extract", real_extract)
    outage = True
    calls, backoffs = [], []
    real_sleep = asyncio.sleep

    async def sleep(delay):
        backoffs.append(delay)
        await real_sleep(0)

    async def complete(*, messages, **kw):
        ep_id = next(i for i in ids if i in messages[-1]["content"])
        calls.append(ep_id)
        if outage and ep_id == ids[0]:
            check(mode, failed(mode, "connection refused", "empty"))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"entities": [], "relationships": []}'))])

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(providers, "resolve_llm_fn", lambda *a, **kw: complete)
    rec = None
    for leg in range(2):
        asyncio.run(sleep_cycle.run(settings(memory), "sleep_connection", user_triggered=True,
                                   drain=True, continue_from=rec))
        rec = sleep_paused.get_paused(memory)
        assert rec and rec["reason"] == "engine" and rec["engine_kind"] == "transient"
        assert rec["attempts"] == {} and rec["timeout_attempts"] == {}
        assert sleep_parked.ids(memory) == set() and waiting(memory) == ids
        assert git(memory, "status", "--porcelain") == ""
    assert calls.count(ids[0]) == 4 and backoffs == [2, 2]
    outage = False
    asyncio.run(sleep_cycle.run(settings(memory), "sleep_connection", user_triggered=True,
                               drain=True, continue_from=rec))
    assert waiting(memory) == [] and sleep_paused.get_paused(memory) is None


@pytest.mark.parametrize("mode", ["agent", "codex"])
@pytest.mark.parametrize("persistent", [False, True])
def test_real_cli_seam_retries_connection_once_then_pauses_and_continue_recovers(
        tmp_path, monkeypatch, agent_runner, agent_envelopes, codex_events, mode, persistent):
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    install(monkeypatch)
    outage = failed(mode, "workspace routing discovery failed", "empty")
    success = agent_envelopes["success"] if mode == "agent" else CliResult(0, codex_events["ok"], "")
    runner = agent_runner(*([outage] * (4 if persistent else 1)), success)
    backoffs = []
    real_sleep = asyncio.sleep

    async def sleep(delay):
        backoffs.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    async def patterns(*a, **kw):
        fn = providers.resolve_llm_fn(Settings(_env_file=None, llm_mode=mode), stage="skills", runner=runner,
                                      sink=lambda e: None, is_async=True)
        await fn(messages=[{"role": "user", "content": "alpha-project"}])
        return []

    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", patterns)

    def run(**kw):
        asyncio.run(sleep_cycle.run(settings(memory), "sleep_connection", user_triggered=True, drain=True, **kw))

    try:
        run()
        if persistent:
            for calls in (2, 4):
                rec = sleep_paused.get_paused(memory)
                assert rec and rec["reason"] == "engine" and rec["engine_kind"] == "transient"
                assert rec["can_continue"] and rec["calls"] == calls and rec["frozen_ids"] == ids
                assert state.error is None and waiting(memory) == ids and sleep_parked.ids(memory) == set()
                assert rec["attempts"] == {} and rec["timeout_attempts"] == {}
                assert "workspace routing discovery failed" in rec["sentence"]
                assert git(memory, "status", "--porcelain") == ""
                run(continue_from=rec)
        assert state.drain.finished and state.error is None and waiting(memory) == []
        assert sleep_paused.get_paused(memory) is None
        assert len(runner.calls) == (5 if persistent else 2)
        assert backoffs == ([2, 2] if persistent else [2])
    finally:
        state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
