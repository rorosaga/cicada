"""`GET /sleep/status` during a run (2026-10-08): it took ~11 s and sometimes timed out on a ~3,600-page
bank because Stage 5's bank-wide steps (page writes, wikilink and media edges, the claim layer, hubs, claim
edges, the processed flags) and Stage 2's page load ran synchronously ON the event loop — every request
waited for them. They run in worker threads now; these tests keep them there."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from drain_harness import episode_ids, install, seed_bank, settings

from api.services import entity_resolver, sleep_cycle


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def _record_threads(monkeypatch, seen: dict[str, list[int]]):
    """Wrap each bank-wide step so it records the thread it ran in (each keeps its real behaviour)."""
    from api.services import (claim_pipeline, graph_builder, hub_builder, inbox_generator, inbox_questions,
                              media_ingestor, wikilink_resolver)

    targets = [
        (sleep_cycle, "_load_existing_entities"), (sleep_cycle, "_mark_episodes_processed"),
        (inbox_generator, "_generate_sync"), (inbox_generator, "write_claim_nudges"),
        (wikilink_resolver, "materialize_wikilink_edges"), (media_ingestor, "inject_media_edges"),
        (claim_pipeline, "run_claim_pipeline"), (inbox_questions, "refresh_open_questions"),
        (hub_builder, "regenerate_hubs_and_index"), (graph_builder, "regenerate_edges_from_claims"),
    ]
    for module, name in targets:
        real = getattr(module, name)

        def wrapper(*a, _real=real, _name=name, **kw):
            seen.setdefault(_name, []).append(threading.get_ident())
            return _real(*a, **kw)

        monkeypatch.setattr(module, name, wrapper)
    return [name for _m, name in targets]


def test_stage_5s_bank_wide_steps_run_off_the_event_loop(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    install(monkeypatch)
    seen: dict[str, list[int]] = {}
    names = _record_threads(monkeypatch, seen)
    loop_thread: list[int] = []

    async def go():
        loop_thread.append(threading.get_ident())
        await sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=3), "sleep_offloop",
                              user_triggered=True, drain=True)

    asyncio.run(go())
    assert set(seen) == set(names), f"every step ran: missing {set(names) - set(seen)}"
    on_loop = sorted(n for n, idents in seen.items() if loop_thread[0] in idents)
    assert on_loop == [], f"ran on the event loop: {on_loop}"


def test_the_loop_answers_while_stage_5_writes(tmp_path, monkeypatch):
    """The symptom itself: a slow Stage 5 step no longer stalls everything else the loop serves."""
    memory = seed_bank(tmp_path, episode_ids(2))
    install(monkeypatch)
    from api.services import hub_builder

    real = hub_builder.regenerate_hubs_and_index

    def slow_hubs(*a, **kw):
        time.sleep(0.6)   # stands in for a whole-bank read on a large bank
        return real(*a, **kw)

    monkeypatch.setattr(hub_builder, "regenerate_hubs_and_index", slow_hubs)
    worst = [0.0]
    done = asyncio.Event()

    async def heartbeat():
        while not done.is_set():
            t0 = time.monotonic()
            await asyncio.sleep(0.02)
            worst[0] = max(worst[0], time.monotonic() - t0 - 0.02)

    async def go():
        beat = asyncio.create_task(heartbeat())
        try:
            await sleep_cycle.run(settings(memory), "sleep_beat", user_triggered=True, drain=True)
        finally:
            done.set()
            await beat

    asyncio.run(go())
    assert worst[0] < 0.4, f"the event loop stalled {worst[0]:.2f}s"


def test_name_tokens_is_memoised_and_immutable():
    """Stage 2 tokenises every page's name for every extracted name — memoised, and a frozenset so a
    caller can never change a cached answer."""
    entity_resolver._name_tokens.cache_clear()
    first = entity_resolver._name_tokens("The Alpha Project")
    again = entity_resolver._name_tokens("The Alpha Project")
    assert first == frozenset({"alpha", "project"}) and again is first
    assert entity_resolver._name_tokens.cache_info().hits >= 1
    assert entity_resolver._share_content_token("alpha thing", "Project Alpha")
    assert not entity_resolver._share_content_token("the", "the")
