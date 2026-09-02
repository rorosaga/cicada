"""G114 R5 — the nightly Sleep tail polls subscribed feeds and calendars.

Before this, `feed_registry.poll_feeds` / `calendar_registry.poll_calendars`
were only ever reached through the two user-initiated routes
(`POST /sources/poll-feeds` / `POST /sources/poll-calendars`), so an installed
backend's subscriptions never refreshed on their own. Mirrors
test_sleep_connector_poll.py: hermetic, no network, no real model — both
`poll_*` functions are monkeypatched with async fakes, so the
`CICADA_ALLOW_FEED_FETCH` gate (which the suite never opens) is never
consulted here. The one gate under test is the tail's own H1 clean-tree guard,
exercised exactly like test_sleep_engine_state.py's connector twin.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger

from api.services import (
    calendar_registry,
    feed_registry,
    git_service,
    predicates,
    sleep_cycle,
)


def _empty_memory(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _settings(memory):
    return SimpleNamespace(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        archive_threshold=0.2,
        decay_nudge_threshold=0.4,
        link_enrich_enabled=False,
        inbox_stale_after_days=90,
    )


def _subscribe_both(memory):
    feed_registry.subscribe_feed(memory, "https://example.com/feed.xml")
    calendar_registry.subscribe_calendar(memory, "https://example.com/cal.ics")


def _fake_polls(monkeypatch, calls, *, feed_result=None, calendar_result=None):
    """Replace both `poll_*` entry points with recording fakes."""

    async def fake_poll_feeds(memory_path, **kwargs):
        calls.append(("feeds", memory_path))
        return feed_result or {"polled": 1, "new": 2, "per_feed": []}

    async def fake_poll_calendars(memory_path, **kwargs):
        calls.append(("calendars", memory_path))
        return calendar_result or {"polled": 1, "new": 3, "per_calendar": []}

    monkeypatch.setattr(feed_registry, "poll_feeds", fake_poll_feeds)
    monkeypatch.setattr(calendar_registry, "poll_calendars", fake_poll_calendars)


@pytest.fixture
def log_lines():
    """Collect loguru messages (INFO and up) emitted while a test runs.

    Cicada logs through loguru, not stdlib ``logging``, so pytest's ``caplog``
    never sees these lines; a direct sink is the smallest honest capture.
    """
    lines: list[str] = []
    sink_id = logger.add(lambda msg: lines.append(msg.record["message"]), level="INFO")
    try:
        yield lines
    finally:
        logger.remove(sink_id)


def test_feeds_and_calendars_are_polled_on_the_idle_early_return(
    tmp_path, monkeypatch, log_lines,
):
    """(a) A quiet night with one subscription of each kind still refreshes both."""
    memory = _empty_memory(tmp_path)
    _subscribe_both(memory)
    calls: list = []
    _fake_polls(monkeypatch, calls)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-feeds"))

    assert ("feeds", memory) in calls
    assert ("calendars", memory) in calls
    assert sleep_cycle.get_sleep_state().status == "idle"
    assert "Feed poll: 2 new item(s) from 1 feed(s)" in log_lines, log_lines
    assert "Calendar poll: 3 new event(s) from 1 calendar(s)" in log_lines, log_lines


def test_zero_subscriptions_never_calls_either_poll(tmp_path, monkeypatch):
    """(b) No feeds.yaml / calendars.yaml → the slot is silent, not a no-op poll."""
    memory = _empty_memory(tmp_path)
    calls: list = []
    _fake_polls(monkeypatch, calls)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-nosubs"))

    assert calls == []
    assert sleep_cycle.get_sleep_state().status == "idle"


def test_a_raising_poll_never_fails_the_cycle_or_stops_its_peer(
    tmp_path, monkeypatch, log_lines,
):
    """(c) A feed poll that blows up is logged as a warning; calendars still run."""
    memory = _empty_memory(tmp_path)
    _subscribe_both(memory)
    calls: list = []

    async def boom(memory_path, **kwargs):
        raise RuntimeError("feed server melted")

    async def ok(memory_path, **kwargs):
        calls.append(("calendars", memory_path))
        return {"polled": 1, "new": 0, "per_calendar": []}

    monkeypatch.setattr(feed_registry, "poll_feeds", boom)
    monkeypatch.setattr(calendar_registry, "poll_calendars", ok)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-boom"))

    assert sleep_cycle.get_sleep_state().status == "idle"
    assert sleep_cycle.get_sleep_state().error is None
    assert calls == [("calendars", memory)], "feeds raising must not stop the calendar poll"
    assert any(
        "Feed poll failed" in line and "feed server melted" in line for line in log_lines
    ), log_lines


def test_the_poll_is_skipped_once_the_cycle_has_written_and_not_committed(monkeypatch):
    """(d) Same H1 risk window as the connector poll: Stage 5 wrote pages, the
    cycle never reached `_finalize`, and the tree is dirty. Both `poll_*`
    functions commit via `git add -A`, so they must NOT run here."""
    calls: list = []
    _fake_polls(monkeypatch, calls)
    # Pretend subscriptions exist so the only thing standing between the
    # fakes and a call is the clean-tree guard.
    monkeypatch.setattr(feed_registry, "list_feeds", lambda p: [{"url": "https://example.com/f"}])
    monkeypatch.setattr(
        calendar_registry, "list_calendars", lambda p: [{"url": "https://example.com/c"}]
    )

    async def quiet_connectors(memory_path):
        return None

    async def quiet_logos(memory_path):
        return None

    async def quiet_questions(memory_path, settings):
        return None

    monkeypatch.setattr(sleep_cycle, "_poll_connectors_safely", quiet_connectors)
    monkeypatch.setattr(sleep_cycle, "_warm_logos_safely", quiet_logos)
    monkeypatch.setattr(sleep_cycle, "_refresh_questions_safely", quiet_questions)

    async def dirty(_path):
        return " M entities/x.md\n"

    monkeypatch.setattr(git_service, "porcelain_status", dirty)

    sleep_cycle._state.write_started = True
    try:
        asyncio.run(sleep_cycle._run_engine_independent_tail(
            Path("/nonexistent"), _settings(Path("/nonexistent")),
            sleep_cycle._StageOutcome(committed=False),
        ))
    finally:
        sleep_cycle._state.write_started = False

    assert calls == []


def test_a_gate_skipped_poll_logs_the_skip_line(tmp_path, monkeypatch, log_lines):
    """(e) When the registry reports `skipped_no_network` (the opt-in
    `CICADA_ALLOW_FEED_FETCH=1` gate is closed), the tail says so plainly
    instead of pretending the subscriptions were refreshed."""
    memory = _empty_memory(tmp_path)
    _subscribe_both(memory)
    calls: list = []
    _fake_polls(
        monkeypatch, calls,
        feed_result={"polled": 0, "new": 0, "skipped_no_network": 1, "per_feed": []},
        calendar_result={"polled": 0, "new": 0, "skipped_no_network": 1, "per_calendar": []},
    )

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-gated"))

    assert len(calls) == 2
    assert 'Feed poll skipped: CICADA_ALLOW_FEED_FETCH is not "1"' in log_lines, log_lines
    assert 'Calendar poll skipped: CICADA_ALLOW_FEED_FETCH is not "1"' in log_lines, log_lines
    assert not any(line.startswith("Feed poll: ") for line in log_lines)
    assert not any(line.startswith("Calendar poll: ") for line in log_lines)
