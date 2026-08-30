"""Sleep cycle logo warm-up (G59): `warm_logos` must run even when a cycle
has zero unprocessed episodes and takes the early return, not only after a
full 5-stage run — otherwise a quiet night (no new episodes) never warms
missing logos.

Hermetic: no network, no real git, no real model — mirrors
``test_sleep_resumable.py``.
"""

from __future__ import annotations

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
    )


def test_warm_logos_runs_on_the_zero_unprocessed_episodes_early_return(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    calls = []

    async def fake_warm_logos(memory_path, *, limit=50, fetcher=None):
        calls.append((memory_path, limit))
        return 0

    monkeypatch.setattr("api.services.logo_service.warm_logos", fake_warm_logos)

    import asyncio
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-empty"))

    assert calls == [(memory, 50)]
    assert sleep_cycle.get_sleep_state().status == "idle"
