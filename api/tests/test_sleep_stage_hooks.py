"""The seams the strip and a Pause hang on (Sleep page v5, critic M6): Stage 2 and Stage 3 count what
finished, and a cancel lands BETWEEN pages in Stage 3 — each page is a paid engine call, and "Pausing…"
must not mean "wait for the whole stage"."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.services import conflict_resolver, entity_resolver


def _updates(n):
    return [{"id": f"page-{i}", "action": "update", "source_episode": "ep_1",
             "entity": {"name": f"Page {i}", "type": "concept", "description": f"new fact {i}"}} for i in range(n)]


def _existing(n):
    return [{"id": f"page-{i}", "frontmatter": {"type": "concept", "status": "active", "confidence": 0.9,
                                                 "last_referenced": "2026-09-01"}, "body": "old prose"}
            for i in range(n)]


def _cfg():
    return SimpleNamespace(archive_threshold=0.2, decay_nudge_threshold=0.4)


def _stub(monkeypatch, calls):
    async def synth(**kw):
        calls.append(("synth", kw["entity_name"]))
        return None

    async def contradiction(**kw):
        calls.append(("contradiction", kw["entity_name"]))
        return None

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", synth)
    monkeypatch.setattr(conflict_resolver, "_detect_contradiction", contradiction)


def test_stage_three_counts_pages_and_fixes_its_total_when_the_loop_starts(monkeypatch):
    calls, ticks = [], []
    _stub(monkeypatch, calls)
    asyncio.run(conflict_resolver.resolve_and_prune(
        _updates(3), _existing(3), _cfg(), tuning={}, progress_callback=lambda d, t: ticks.append((d, t))))
    assert ticks[0] == (0, 3) and ticks[-1] == (3, 3)
    assert {t for _, t in ticks} == {3}, "the total never moves once the stage has started"
    assert [d for d, _ in ticks] == sorted(d for d, _ in ticks), "and the count only goes up"
    assert len(calls) == 6


def test_a_pause_during_stage_three_stops_between_pages(monkeypatch):
    calls, stop = [], {"now": False}
    _stub(monkeypatch, calls)

    real_synth = conflict_resolver._synthesize_entity_update

    async def synth_then_stop(**kw):
        out = await real_synth(**kw)
        stop["now"] = True   # the person pressed Pause while the first page's call was in flight
        return out

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", synth_then_stop)
    asyncio.run(conflict_resolver.resolve_and_prune(
        _updates(4), _existing(4), _cfg(), tuning={}, cancel_check=lambda: stop["now"]))
    pages = {name for _, name in calls}
    assert pages == {"Page 0"}, "the page in flight finished; no further page was asked about"


def test_stage_two_reports_names_sorted_out_of_a_fixed_total(tmp_path, monkeypatch):
    class _NoIndex:
        def __init__(self, *_a, **_k):
            pass

        def __getattr__(self, name):
            return lambda *a, **k: None

    (tmp_path / "entities").mkdir()
    monkeypatch.setattr(entity_resolver, "SqliteVecIndexer", _NoIndex)
    ticks = []
    settings = SimpleNamespace(memory_path=tmp_path, litellm_model="m", litellm_disambiguation_model="m",
                               sleep_promotion_threshold=2)
    extracted = [{"episode_id": "ep_1", "entities": [
        {"name": n, "type": "concept", "confidence": 0.9, "source_episode": "ep_1"} for n in ("Alpha", "Beta", "Gamma")],
        "relationships": []}]
    asyncio.run(entity_resolver.resolve(extracted, [], settings, progress_callback=lambda d, t: ticks.append((d, t))))
    assert ticks[0] == (0, 3) and ticks[-1] == (3, 3) and {t for _, t in ticks} == {3}
    assert [d for d, _ in ticks] == sorted(d for d, _ in ticks)


def test_a_drains_stage_three_gets_the_pause_and_the_counter_but_a_plain_cycle_calls_it_as_it_always_did(
        tmp_path, monkeypatch):
    from drain_harness import episode_ids, install, seed_bank, settings

    from api.services import sleep_cycle

    memory = seed_bank(tmp_path, episode_ids(4))
    install(monkeypatch)
    seen = []
    real = conflict_resolver.resolve_and_prune

    async def spy(resolved, existing, settings_, **kw):
        seen.append(sorted(kw))
        return await real(resolved, existing, settings_, **kw)

    monkeypatch.setattr("api.services.conflict_resolver.resolve_and_prune", spy)
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=2), "sleep_hooks",
                                user_triggered=True, drain=True))
    assert seen and all({"cancel_check", "progress_callback"} <= set(k) for k in seen)
    seen.clear()
    memory2 = seed_bank(tmp_path / "plain", episode_ids(2))
    asyncio.run(sleep_cycle.run(settings(memory2, sleep_max_episodes_per_cycle=25), "sleep_plain"))
    assert seen == [[]], "a plain cycle's call is exactly what it always was"
