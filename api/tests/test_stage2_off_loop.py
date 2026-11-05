"""The Stage 2 stall (2026-11-05): during a scheduled Sleep on a bank of 8,500 pages, `/healthz` and `/sleep/status` went
past 30 s for seven minutes. Each project name with no page was weighed against every project page, and each weighing
parsed the whole pending store, on the event loop. The store is now read once per change, and Stage 2 runs on a worker
thread with only its judge calls on the backend's loop. The behaviour and the read count are pinned here; the budget at
the owner's scale is the `bench` tier (`make test-bench`), like every wall-clock assertion in this suite."""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from _stage2_bench_bank import batch as bench_batch
from _stage2_bench_bank import build as build_bench_bank
from drain_harness import git, install, settings

from api.services import engine_errors, entity_resolver, markdown_parser, pending_store, sleep_cycle, vector_index


def _line(name: str, **kw) -> pending_store.PendingEntity:
    return pending_store.PendingEntity(name=name, type="concept", description="d", source_episode="ep_2026-09-01_001",
                                       confidence=0.5, tags=[], history_entries=[], **kw)


def _bank(tmp_path, *, projects: int = 0):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    (memory / "inbox").mkdir()
    for n in range(projects):
        markdown_parser.write(memory / "entities" / f"build-{n}.md",
                              {"name": f"Build {n}", "type": "project", "status": "active"}, "Body.")
    return memory


def _existing(memory):
    return sleep_cycle._load_existing_entities(memory)


def _settings(memory, **kw):
    return SimpleNamespace(memory_path=memory, litellm_model="m", litellm_disambiguation_model="m",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=3, **kw)


def _extraction(*names: str, kind: str = "project") -> list[dict]:
    return [{"episode_id": "ep_2026-11-04_001", "relationships": [],
             "entities": [{"name": n, "type": kind, "confidence": 0.8, "source_episode": "ep_2026-11-04_001",
                           "summary": f"{n}."} for n in names]}]


def _stub_judges(monkeypatch, *, seen: list | None = None):
    async def one(*_a, **_kw):
        if seen is not None:
            seen.append(threading.get_ident())
        return "different"

    async def many(*a, **kw):
        if seen is not None:
            seen.append(threading.get_ident())
        return ["different"] * len(kw.get("candidates") or a[3])

    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", one)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", many)


# The store's lookups


def test_a_lookup_answers_as_a_scan_of_the_lines_would(tmp_path):
    memory = _bank(tmp_path)
    pending_store.save(memory, [
        _line("Alpha Example", apart={"pages": ["page-a"], "episodes": ["ep_2026-09-01_001"]}),
        _line("alpha example", apart={"pages": ["page-b"]}),   # a second line of the name: the first wins a lookup
        _line("Beta Example"),
    ])
    assert pending_store.held_line(memory, "ALPHA example").name == "Alpha Example"
    assert pending_store.held_line(memory, "beta example").name == "Beta Example"
    assert pending_store.held_line(memory, "gone example") is None
    assert pending_store.apart_of(memory, " Alpha Example ") == {"page-a", "page-b"}
    assert pending_store.apart_of(memory, "Beta Example") == frozenset()
    assert vector_index.SqliteVecIndexer.pending_by_name(SimpleNamespace(memory_path=memory), "beta example").name == (
        "Beta Example")


def test_a_write_is_seen_by_the_next_lookup_and_a_caller_owns_its_copy(tmp_path):
    memory = _bank(tmp_path)
    pending_store.save(memory, [_line("Alpha Example")])
    pending_store.held_line(memory, "Alpha Example").description = "changed by a caller"
    assert pending_store.held_line(memory, "Alpha Example").description == "d"
    assert pending_store.mark_apart(memory, "Alpha Example", ["page-a"])
    assert pending_store.apart_of(memory, "Alpha Example") == {"page-a"}
    pending_store.save(memory, [])     # same directory, a shorter file
    assert pending_store.held_line(memory, "Alpha Example") is None
    assert pending_store.apart_of(memory, "Alpha Example") == frozenset()


def test_a_bad_line_is_skipped_and_no_store_is_no_answer(tmp_path):
    memory = _bank(tmp_path)
    assert pending_store.held_line(memory, "Alpha Example") is None
    pending_store.store_path(memory).write_text('not json\n\n[1]\n{"name": "Only A Name"}\n', encoding="utf-8")
    assert [e.name for e in pending_store.load(memory)] == ["Only A Name"]
    assert pending_store.held_line(memory, "only a name").name == "Only A Name"


def test_two_banks_do_not_answer_for_each_other(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first, second = _bank(tmp_path / "a"), _bank(tmp_path / "b")
    pending_store.save(first, [_line("Alpha Example")])
    pending_store.save(second, [_line("Beta Example")])
    assert pending_store.held_line(first, "Alpha Example") is not None
    assert pending_store.held_line(second, "Alpha Example") is None
    assert pending_store.held_line(first, "Beta Example") is None


def test_weighing_project_names_reads_the_store_a_bounded_number_of_times(tmp_path, monkeypatch):
    """The cause: a read per page per name. At 200 pages and 3 names that was at least 600 reads; it must not grow."""
    memory = _bank(tmp_path, projects=200)
    pending_store.save(memory, [_line(f"Held {n}") for n in range(50)])
    _stub_judges(monkeypatch)
    parses = [0]
    real = pending_store.PendingEntity.from_dict

    def counted(data):
        parses[0] += 1
        return real(data)

    monkeypatch.setattr(pending_store.PendingEntity, "from_dict", staticmethod(counted))
    names = ("Unborn One", "Unborn Two", "Unborn Three")
    asyncio.run(entity_resolver.resolve(_extraction(*names), _existing(memory), _settings(memory)))
    assert parses[0] < 50 * 12, f"{parses[0]} lines parsed for a store of 50: a read per lookup is back"


# Off the loop


def test_stage_2_works_off_the_loop_and_judges_on_it(tmp_path, monkeypatch):
    memory = _bank(tmp_path, projects=5)
    judged_on: list[int] = []
    _stub_judges(monkeypatch, seen=None)
    worked_on: list[int] = []
    real = entity_resolver._waiting_cards

    def spy(*a, **kw):
        worked_on.append(threading.get_ident())
        return real(*a, **kw)

    monkeypatch.setattr(entity_resolver, "_waiting_cards", spy)

    class Reply:
        choices = [SimpleNamespace(message=SimpleNamespace(content='{"decision": "different", "decisions": []}'))]

    def fake_llm_fn(*_a, **_kw):
        async def call(**_call):
            judged_on.append(threading.get_ident())
            return Reply()
        return call

    monkeypatch.setattr("api.services.providers.resolve_llm_fn", fake_llm_fn)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", ORIGINAL_ONE)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", ORIGINAL_MANY)
    loop_thread: list[int] = []

    async def go():
        loop_thread.append(threading.get_ident())
        return await entity_resolver.resolve_off_loop(_extraction("Build Zero Two"), _existing(memory),
                                                      _settings(memory))

    assert asyncio.run(go())["changes"] is not None
    assert worked_on and loop_thread[0] not in worked_on, "the work ran on the event loop"
    assert judged_on and set(judged_on) == {loop_thread[0]}, "a judge call left the backend's loop"


ORIGINAL_ONE = entity_resolver._llm_judge_same_entity
ORIGINAL_MANY = entity_resolver._llm_judge_batch


def test_an_engine_error_on_the_loop_reaches_the_batch(tmp_path, monkeypatch):
    """A plan limit met by a judge call is still the batch's pause, across the thread."""
    memory = _bank(tmp_path, projects=5)

    def fake_llm_fn(*_a, **_kw):
        async def call(**_call):
            raise engine_errors.EngineUnavailable("limit")
        return call

    monkeypatch.setattr("api.services.providers.resolve_llm_fn", fake_llm_fn)

    async def go():
        return await entity_resolver.resolve_off_loop(_extraction("Build Zero Two"), _existing(memory),
                                                      _settings(memory))

    with pytest.raises(engine_errors.EngineError):
        asyncio.run(go())


def test_a_cancel_between_names_still_writes_nothing(tmp_path, monkeypatch):
    memory = _bank(tmp_path, projects=2)
    pending_store.save(memory, [])
    before = pending_store.store_path(memory).read_bytes()
    _stub_judges(monkeypatch)

    async def go():
        return await entity_resolver.resolve_off_loop(
            _extraction("Held One", "Held Two", kind="concept"), _existing(memory), _settings(memory),
            cancel_check=lambda: True)

    asyncio.run(go())
    assert pending_store.store_path(memory).read_bytes() == before
    assert list((memory / "inbox").iterdir()) == []


def test_a_cancelled_batch_stops_the_thread_before_it_writes(tmp_path, monkeypatch):
    """Sleep's task cancelled mid-judge: the thread sees it at its next checkpoint, and `resolve` writes nothing."""
    memory = _bank(tmp_path, projects=2)
    pending_store.save(memory, [])
    before = pending_store.store_path(memory).read_bytes()
    entered, finished = threading.Event(), threading.Event()
    real = entity_resolver.resolve

    async def spy(*a, **kw):
        entered.set()
        await asyncio.sleep(0.2)
        try:
            return await real(*a, **kw)
        finally:
            finished.set()

    monkeypatch.setattr(entity_resolver, "resolve", spy)
    _stub_judges(monkeypatch)

    async def go():
        task = asyncio.create_task(entity_resolver.resolve_off_loop(
            _extraction("Held One", "Held Two", kind="concept"), _existing(memory), _settings(memory)))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert finished.wait(10), "the worker thread did not end"
    assert pending_store.store_path(memory).read_bytes() == before


def test_the_same_batch_decides_the_same_on_and_off_the_loop(tmp_path, monkeypatch):
    """The move changes where it runs, never what it decides."""
    results = []
    for label, runner in (("on", entity_resolver.resolve), ("off", entity_resolver.resolve_off_loop)):
        root = tmp_path / label
        root.mkdir()
        memory = _bank(root, projects=20)
        pending_store.save(memory, [_line("Held Again", heard_in=[
            {"episode": "ep_2026-09-01_001", "timestamp": "2026-09-01T10:00:00+00:00", "day": "2026-09-01"}])])
        _stub_judges(monkeypatch)
        extracted = _extraction("Build 3", "Held Again", "Unborn Thing", kind="project")
        result = asyncio.run(runner(extracted, _existing(memory), _settings(memory)))
        results.append((sorted((c.get("action"), c.get("id")) for c in result["changes"]),
                        pending_store.store_path(memory).read_text(encoding="utf-8"),
                        sorted(p.name for p in (memory / "inbox").iterdir())))
    assert results[0] == results[1]


# The budget, at the owner's scale


@pytest.fixture(scope="module")
def bench_bank(tmp_path_factory):
    memory = build_bench_bank(tmp_path_factory.mktemp("stage2") / "memory")
    git(memory, "init", "-q")
    git(memory, "config", "user.email", "test@cicada.local")
    git(memory, "config", "user.name", "Cicada Test")
    git(memory, "add", "-A")
    git(memory, "commit", "-q", "-m", "seed")
    return memory


@pytest.mark.bench
def test_stage_2_at_the_owners_scale_answers_within_a_second(bench_bank, monkeypatch):
    _stub_judges(monkeypatch)
    worst = [0.0]

    async def go():
        done = asyncio.Event()

        async def heartbeat():
            while not done.is_set():
                t0 = time.monotonic()
                await asyncio.sleep(0.02)
                worst[0] = max(worst[0], time.monotonic() - t0 - 0.02)

        beat = asyncio.create_task(heartbeat())
        try:
            existing = await asyncio.to_thread(_existing, bench_bank)
            return await entity_resolver.resolve_off_loop(
                bench_batch(), existing, _settings(bench_bank, ) )
        finally:
            done.set()
            await beat

    t0 = time.monotonic()
    asyncio.run(go())
    wall = time.monotonic() - t0
    assert wall < 60, f"Stage 2 took {wall:.1f}s"
    assert worst[0] < 1.0, f"the event loop stalled {worst[0]:.2f}s"


@pytest.mark.bench
def test_a_whole_batch_at_the_owners_scale_never_stalls_the_loop_a_second(bench_bank, monkeypatch):
    """Every stage of a batch, by stage: the one that blocks past the bound is the one named."""
    rig = install(monkeypatch)
    from api.services import entity_extractor

    async def extract(episodes, settings_, **kw):
        rig.extract_batches.append([e["id"] for e in episodes])
        wanted = {e["id"] for e in episodes}
        return [{**x, "episode_timestamp": f"{x['episode_id'][3:13]}T10:00:00+00:00", "origin": "claude_code"}
                for x in bench_batch() if x["episode_id"] in wanted]

    monkeypatch.setattr(entity_extractor, "extract", extract)
    monkeypatch.setattr(entity_resolver, "resolve", REAL_RESOLVE)
    _stub_judges(monkeypatch)
    worst: dict[str, float] = {}
    state = sleep_cycle.get_sleep_state()

    async def go():
        done = asyncio.Event()

        async def heartbeat():
            while not done.is_set():
                before = str(state.stage)
                t0 = time.monotonic()
                await asyncio.sleep(0.02)
                lag = time.monotonic() - t0 - 0.02
                worst[before] = max(worst.get(before, 0.0), lag)

        beat = asyncio.create_task(heartbeat())
        try:
            await sleep_cycle.run(settings(bench_bank, sleep_promotion_threshold=2, sleep_resolve_concurrency=10,
                                           sleep_max_episodes_per_cycle=25),
                                  "sleep_bench", user_triggered=True, drain=True)
        finally:
            done.set()
            await beat

    asyncio.run(go())
    assert len(rig.extract_batches) >= 1
    over = {stage: round(lag, 2) for stage, lag in worst.items() if lag >= 1.0}
    assert not over, f"the loop stalled past a second, by stage reached: {over}"


REAL_RESOLVE = entity_resolver.resolve
