"""G74(a) Task 4 — engine failures are visible, retried correctly, and never
mistaken for a model's opinion.

Two pre-existing bugs are fixed here and both predate the rung:
  * `_EXTRACT_RETRYABLE` is litellm-exception-typed, so a CLI failure matched
    nothing and got ZERO retries.
  * `_llm_judge_same_entity`'s blanket `except -> "unsure"` turned an engine
    failure into a clarification and a split entity page, while the cycle
    reported success.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from api.config import Settings
from api.services import agent_engine, engine_errors, entity_extractor, entity_resolver, providers


def _agent_settings():
    # Fix round 1, M1: `agent_max_concurrency=1` makes the throttle-breaker
    # test below deterministic without changing production behavior. Stage
    # 1's own fan-out (MAX_CONCURRENCY=10) combined with the seam's default
    # `agent_max_concurrency` (3) let up to 3 concurrently-dispatched
    # `claude -p` calls each independently discover a throttle before any of
    # them could trip the circuit breaker (the breaker is only set AFTER a
    # call fails — calls already in flight can't be recalled). A
    # first-episode "probe" was tried in the extractor to force this to
    # exactly 1 and reverted: it only guaranteed the count when the engine
    # was ALREADY throttled before the cycle started (the realistic case —
    # quota hit mid-cycle — still produced 2-3 spawns), while charging every
    # agent-mode cycle one fully-serialized episode ahead of the fan-out.
    # `agent_max_concurrency=1` gets the same 1-spawn determinism here, in
    # the test only, with zero production cost.
    return Settings(
        llm_mode="agent", agent_model="sonnet", agent_disambiguation_model="haiku",
        agent_max_concurrency=1,
    )


@pytest.fixture(autouse=True)
def _propagate_loguru_to_caplog():
    """`logger.error(...)` in the stage classifiers is loguru, not stdlib
    ``logging`` — pytest's ``caplog`` only sees the latter. Bridge loguru's
    sink into stdlib logging for the duration of each test (standard loguru
    pytest-capture pattern), so `caplog.text` actually sees the per-episode
    reason lines Step 4 adds."""

    class _PropagateHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logging.getLogger(record.name).handle(record)

    from loguru import logger as _loguru_logger

    handler_id = _loguru_logger.add(_PropagateHandler(), format="{message}")
    yield
    _loguru_logger.remove(handler_id)


def _extract_with(monkeypatch, runner):
    """Point every call site's seam at an injected agent runner.

    entity_extractor and entity_resolver import ``resolve_llm_fn`` INSIDE
    their functions (``from api.services.providers import resolve_llm_fn`` at
    call time), so patching ``providers.resolve_llm_fn`` reaches them.
    conflict_resolver and skill_extractor import it once at MODULE level, so
    their own already-bound name has to be patched directly too — patching
    only ``providers.resolve_llm_fn`` leaves their calls pointed at the
    ORIGINAL function, which reaches the real (test-guarded) runner instead
    of this one (fix round 1, M2 test coverage)."""
    real = providers.resolve_llm_fn

    def patched(settings, **kw):
        kw.setdefault("runner", runner)
        kw.setdefault("sink", lambda e: None)
        return real(settings, **kw)

    from api.services import conflict_resolver, skill_extractor

    monkeypatch.setattr(conflict_resolver, "resolve_llm_fn", patched)
    monkeypatch.setattr(skill_extractor, "resolve_llm_fn", patched)

    monkeypatch.setattr(providers, "resolve_llm_fn", patched)


# --------------------------------------------------------------------------- #
# Retry widening
# --------------------------------------------------------------------------- #

def test_engine_errors_are_in_the_retry_tuple():
    for exc in (engine_errors.EngineTimeout, engine_errors.EngineProtocolError,
                engine_errors.EngineFailed):
        assert issubclass(exc, entity_extractor._EXTRACT_RETRYABLE)


def test_non_transient_engine_errors_are_not_retried():
    for exc in (engine_errors.EngineThrottled, engine_errors.EngineUnavailable,
                engine_errors.EngineExhausted, engine_errors.EngineModelNotFound):
        assert not issubclass(exc, entity_extractor._EXTRACT_RETRYABLE)


def test_a_timed_out_chunk_is_retried_once_then_succeeds(monkeypatch, agent_runner, agent_envelopes):
    from api.services.connections.base import CliResult

    runner = agent_runner(CliResult(124, "", "timed out"), agent_envelopes["success"])
    _extract_with(monkeypatch, runner)
    # Skip the real 10s backoff without recursing into the patched `sleep`
    # itself — capture the ORIGINAL before replacing it.
    _real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda *_: _real_sleep(0))
    parsed = asyncio.run(entity_extractor._extract_chunk("ep1", "body", 0, 1, _agent_settings()))
    assert parsed == {"entities": [], "relationships": []}
    assert len(runner.calls) == 2


def test_a_signed_out_engine_is_not_retried(monkeypatch, agent_runner, agent_envelopes):
    runner = agent_runner(agent_envelopes["not_logged_in"])
    _extract_with(monkeypatch, runner)
    with pytest.raises(engine_errors.EngineUnavailable):
        asyncio.run(entity_extractor._extract_chunk("ep1", "body", 0, 1, _agent_settings()))
    assert len(runner.calls) == 1


# --------------------------------------------------------------------------- #
# The per-episode classifier
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("envelope_key,needle", [
    ("not_logged_in", "signed out"),
    ("budget_exhausted", "budget"),
    ("model_not_found", "model"),
    ("rate_limited", "throttled"),
])
def test_extract_logs_a_specific_reason_per_engine_failure(
        monkeypatch, agent_runner, agent_envelopes, caplog, envelope_key, needle):
    runner = agent_runner(agent_envelopes[envelope_key])
    _extract_with(monkeypatch, runner)
    episodes = [{"id": "ep_2026-09-01_001", "content": "hello", "timestamp": "2026-09-01T10:00:00"}]
    with caplog.at_level("ERROR"):
        out = asyncio.run(entity_extractor.extract(episodes, _agent_settings()))
    assert out == []                                   # the episode requeues
    assert needle in caplog.text.lower()


def test_a_throttle_stops_the_batch_instead_of_re_hitting_it_per_episode(
        monkeypatch, agent_runner, agent_envelopes):
    """Stage 1 fans out per-episode with no batch abort; without the breaker
    one throttle is re-hit once per remaining episode."""
    runner = agent_runner(agent_envelopes["rate_limited"])
    _extract_with(monkeypatch, runner)
    episodes = [{"id": f"ep_2026-09-01_{i:03d}", "content": "hello",
                 "timestamp": "2026-09-01T10:00:00"} for i in range(12)]
    out = asyncio.run(entity_extractor.extract(episodes, _agent_settings()))
    assert out == []                                   # every episode stays queued
    assert len(runner.calls) == 1                      # exactly one spawn, then fail-fast
    assert agent_engine.breaker_reason() is not None


def test_a_throttled_cycle_mints_no_clarifications(monkeypatch, agent_runner, agent_envelopes):
    """The whole point: a throttle must not become graph damage."""
    runner = agent_runner(agent_envelopes["rate_limited"])
    _extract_with(monkeypatch, runner)
    episodes = [{"id": "ep_2026-09-01_001", "content": "hello", "timestamp": "2026-09-01T10:00:00"}]
    assert asyncio.run(entity_extractor.extract(episodes, _agent_settings())) == []


# --------------------------------------------------------------------------- #
# entity_resolver: engine failure is NOT model uncertainty
# --------------------------------------------------------------------------- #

def test_judge_raises_on_engine_failure_instead_of_answering_unsure(
        monkeypatch, agent_runner, agent_envelopes):
    """An `except -> "unsure"` here creates a clarification and splits the
    entity page: the inbox floods and the graph fragments while the cycle
    reports success."""
    runner = agent_runner(agent_envelopes["budget_exhausted"])
    _extract_with(monkeypatch, runner)
    with pytest.raises(engine_errors.EngineExhausted):
        asyncio.run(entity_resolver._llm_judge_same_entity(
            "Francesco", "person", "d", "Francesco B.", "person", "b", _agent_settings()))


def test_judge_still_answers_unsure_on_a_genuinely_ambiguous_reply(monkeypatch):
    """Model uncertainty is unchanged — only ENGINE failure is escalated."""
    from api.services.agent_engine import _wrap

    async def fake(**kw):
        return _wrap({"choices": [{"message": {"content": '{"decision": "maybe?"}'}}]})

    monkeypatch.setattr(entity_resolver.litellm, "acompletion", fake)
    out = asyncio.run(entity_resolver._llm_judge_same_entity(
        "A", "person", "d", "A.", "person", "b", Settings()))
    assert out == "unsure"


def test_judge_still_swallows_a_malformed_reply_as_unsure(monkeypatch):
    from api.services.agent_engine import _wrap

    async def fake(**kw):
        return _wrap({"choices": [{"message": {"content": "not json at all"}}]})

    monkeypatch.setattr(entity_resolver.litellm, "acompletion", fake)
    out = asyncio.run(entity_resolver._llm_judge_same_entity(
        "A", "person", "d", "A.", "person", "b", Settings()))
    assert out == "unsure"


# --------------------------------------------------------------------------- #
# Fix round 1, M2 — Stages 3 and 4 committed the exact bug just fixed in the
# resolver: swallowing an ENGINE failure into "nothing to do" instead of
# propagating it. Reachable path: a partial throttle (some episodes extract,
# the breaker trips) with no Stage-2 judge candidate needed — Stage 3 would
# silently skip synthesis AND contradiction detection for every entity,
# Stage 4 would return zero skills, Stage 5 would still commit, episodes
# would get marked processed, and the cycle would report "Completed".
# --------------------------------------------------------------------------- #

_EXISTING_ENTITY = [{
    "id": "test-entity",
    "frontmatter": {"name": "Test Entity", "type": "concept"},
    "body": "Old body about Test Entity.",
}]
_UPDATE_CHANGE = [{
    "id": "test-entity",
    "action": "update",
    "entity": {
        "name": "Test Entity", "type": "concept",
        "description": "A brand new description from this episode.",
        "history_entries": [],
    },
    "source_episode": "ep_2026-09-01_000",
}]


def test_stage3_synthesis_raises_on_engine_failure_instead_of_skipping_it(
        monkeypatch, agent_runner, agent_envelopes):
    from api.services import conflict_resolver

    runner = agent_runner(agent_envelopes["rate_limited"])
    _extract_with(monkeypatch, runner)
    with pytest.raises(engine_errors.EngineThrottled):
        asyncio.run(conflict_resolver.resolve_and_prune(
            _UPDATE_CHANGE, _EXISTING_ENTITY, _agent_settings()))


def test_stage4_skill_detection_raises_on_engine_failure_instead_of_returning_empty(
        monkeypatch, agent_runner, agent_envelopes):
    from api.services import skill_extractor

    runner = agent_runner(agent_envelopes["rate_limited"])
    _extract_with(monkeypatch, runner)
    with pytest.raises(engine_errors.EngineThrottled):
        asyncio.run(skill_extractor.detect_patterns(_UPDATE_CHANGE, [], _agent_settings()))


def _seed_partial_throttle_bank(tmp_path):
    """One existing entity ('Test Entity') and one queued, unprocessed episode
    — enough for Stage 2 to resolve a direct (non-LLM) name match, so the
    throttle is discovered for the first time in Stage 3."""
    from api.services import markdown_parser, predicates

    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    (memory / "inbox").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    markdown_parser.write(
        memory / "entities" / "test-entity.md",
        {"id": "test-entity", "type": "concept", "name": "Test Entity",
         "status": "active", "confidence": 0.7, "created": "2026-01-01",
         "last_referenced": "2026-01-01", "decay_class": "active", "version": 1},
        "Old body about Test Entity.",
    )
    markdown_parser.write(
        memory / "episodes" / "ep_2026-09-01_000.md",
        {"id": "ep_2026-09-01_000", "processed": False, "source": "mcp",
         "timestamp": "2026-09-01T10:00:00"},
        "Episode body mentioning Test Entity.",
    )
    return memory


def test_a_partial_throttle_mid_cycle_stops_cleanly_with_the_queue_intact(
        tmp_path, monkeypatch, agent_runner, agent_envelopes):
    """The whole point of M2: Stage 1 succeeds (some episodes extract), Stage 2
    needs no judge call (direct name match), and the throttle is only
    discovered in Stage 3 — the cycle must still stop cleanly rather than
    silently completing with zero synthesis and zero skills."""
    from api.services import sleep_cycle

    memory = _seed_partial_throttle_bank(tmp_path)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))

    async def _canned_extract(episodes, settings):
        return [{
            "episode_id": "ep_2026-09-01_000",
            "episode_timestamp": "2026-09-01T10:00:00",
            "origin": "mcp",
            "entities": [{
                "name": "Test Entity", "type": "concept",
                "description": "A brand new description from this episode.",
                "confidence": 0.8, "source_episode": "ep_2026-09-01_000",
                "source_episode_timestamp": "2026-09-01T10:00:00", "origin": "mcp",
            }],
            "relationships": [],
        }]

    monkeypatch.setattr("api.services.entity_extractor.extract", _canned_extract)

    runner = agent_runner(agent_envelopes["rate_limited"])
    _extract_with(monkeypatch, runner)

    asyncio.run(sleep_cycle.run(_agent_settings(), "sleep_test"))

    state = sleep_cycle.get_sleep_state()
    assert state.error                                        # not "Completed"
    assert "throttl" in state.error.lower()
    assert len(sleep_cycle._get_unprocessed_episodes(memory)) == 1   # still queued
    assert list((memory / "inbox").glob("*.md")) == []         # no clarification minted
