"""The nightly connector poll rides the Sleep cycle's tail (G71 §2).

Mirrors test_sleep_cycle_logo_warmup.py: hermetic, no network, no real model,
no real git. Covers both peer connectors, Pinterest and Reddit.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.services import predicates, sleep_cycle


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


def test_connectors_are_polled_on_the_idle_early_return(tmp_path, monkeypatch):
    """A quiet night still has to pull new pins and saves."""
    memory = _empty_memory(tmp_path)
    calls = []

    async def fake_sync(memory_path, **kwargs):
        calls.append(memory_path)
        return {"status": "ok", "new": 0, "seen": 0, "error": None}

    monkeypatch.setattr("api.services.connectors.pinterest.sync", fake_sync)
    monkeypatch.setattr("api.services.connectors.reddit.sync", fake_sync)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-empty"))

    assert calls == [memory, memory]
    assert sleep_cycle.get_sleep_state().status == "idle"


def test_a_failing_connector_never_fails_the_cycle_or_stops_its_peer(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    calls = []

    async def boom(memory_path, **kwargs):
        raise RuntimeError("token expired")

    async def ok(memory_path, **kwargs):
        calls.append(memory_path)
        return {"status": "ok", "new": 0, "seen": 0, "error": None}

    monkeypatch.setattr("api.services.connectors.pinterest.sync", boom)
    monkeypatch.setattr("api.services.connectors.reddit.sync", ok)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-boom"))
    assert sleep_cycle.get_sleep_state().status == "idle"
    assert sleep_cycle.get_sleep_state().error is None
    assert calls == [memory], "Pinterest raising must not stop Reddit's poll"
