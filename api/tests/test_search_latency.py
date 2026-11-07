"""G136 — the search latency budget, measured at the live bank's scale.

A synthetic bank of 2,000 entities (3 claims each, prose from a paragraph
to ~8,000 characters) and 1,500 episodes (~11 MB of conversation text) — the live bank is 1,866 / 1,396 (TODO.md,
Live environment) — generated in the test's tmp dir from a fixed seed and a
made-up syllable vocabulary (no real names, no dictionary file, the same
numbers on every machine).

Budgets are the design's (round-3 §3.2): Pass A, ``mode=prefix``, p95
≤ 50 ms; Pass B, ``mode=hybrid``, 200 ms (G58's target), of CPU time (see ``_measure``). Measured on the
server twin — ``search_service.search``, the function ``GET /search`` runs
in its threadpool — so HTTP overhead is not in the number and a regression
in the search path is. Run with ``-s`` to see the numbers.
"""
from __future__ import annotations

import random
import statistics
import time
import zlib

import numpy as np
import pytest

from api.services import bank_index, markdown_parser, search_index, search_service

#: A wall-clock budget: the `bench` tier (`make test-bench`, and `make test` before a release), never the default run.
pytestmark = pytest.mark.bench

N_ENTITIES = 2000
N_EPISODES = 1500
N_QUERIES = 120
PALETTE_KINDS = ("entity", "claim", "episode", "media")
_SYLLABLES = ["ka", "lo", "mi", "ra", "tu", "sen", "vel", "dor", "qui", "zan",
              "pe", "ri", "mo", "na", "tho", "gar", "lin", "bex", "sol", "fen"]


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 4)))


def _sentence(rng: random.Random, n: int) -> str:
    return " ".join(_word(rng) for _ in range(n)).capitalize() + "."


def _fake_embed(texts, *, is_query=False):
    """Hashed bag of words, 16 dims — deterministic and fast, so the hybrid
    number measures fusion and hydration, not a model."""
    rows = np.zeros((len(texts), 16), dtype=np.float32)
    for i, text in enumerate(texts):
        for word in text.lower().split()[:200]:
            rows[i, zlib.crc32(word.encode()) % 16] += 1.0
        rows[i, 0] += 0.01
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def write_bank(memory, rng: random.Random, *, entities: int = N_ENTITIES, episodes: int = N_EPISODES) -> list[str]:
    """The synthetic bank's pages and conversations, from ``rng``; its vocabulary back. Shared with the default-suite
    behaviour checks, which build a smaller one from the same generator."""
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    vocab: list[str] = []
    types = ["project", "person", "concept", "tool", "media"]
    for i in range(entities):
        a, b = _word(rng), _word(rng)
        vocab += [a, b]
        claims = "".join(
            f"- id: clm_{i}_{k}\n  text: \"{_sentence(rng, 8)}\"\n  subject: e-{i}\n"
            f"  predicate: uses\n  object: {_word(rng)}\n"
            for k in range(3)
        )
        # Page prose from a paragraph to a long page (~8,000 characters, the
        # indexed cap), so snippet and highlight work is measured at its worst.
        prose = " ".join(_sentence(rng, 12) for _ in range(rng.choice([6, 6, 12, 40, 80])))
        body = f"## Summary\n{prose}\n\n```claims\n{claims}```\n"
        markdown_parser.write(memory / "entities" / f"e-{i}.md",
                              {"name": f"{a} {b} {i}", "type": types[i % 5], "status": "active",
                               "confidence": 0.5, "aliases": [_word(rng), _word(rng)], "tags": [_word(rng)]},
                              body)
    for i in range(episodes):
        turns = rng.choice([4, 8, 8, 12, 20, 60])
        body = "\n".join(f"{rng.choice(['user', 'assistant'])}: {_sentence(rng, rng.randint(10, 60))}"
                         for _ in range(turns))
        markdown_parser.write(memory / "episodes" / f"ep_2026-09-{i % 28 + 1:02d}_{i:03d}.md",
                              {"id": f"ep_{i}", "title": _sentence(rng, 4), "harness": "claude-code",
                               "session_id": f"ses_2026-09-01_{i:08d}", "timestamp": "2026-09-01T00:00:00+00:00"},
                              body)
    return vocab


@pytest.fixture(scope="module")
def big_bank(tmp_path_factory):
    rng = random.Random(7)
    memory = tmp_path_factory.mktemp("latency") / "memory"
    vocab = write_bank(memory, rng)
    bank_index.invalidate()
    search_index.reset()
    started = time.perf_counter()
    search_index.rebuild(memory)
    build_s = time.perf_counter() - started
    queries = []
    for _ in range(N_QUERIES):
        word = rng.choice(vocab)
        queries.append(word[: rng.randint(2, min(7, len(word)))])
    queries += [f"{rng.choice(vocab)} {rng.choice(vocab)[:3]}" for _ in range(N_QUERIES // 4)]
    print(f"\nG136 synthetic bank: {N_ENTITIES} entities, {N_EPISODES} episodes; full index build {build_s:.2f} s")
    yield memory, queries
    search_index.reset()
    bank_index.invalidate()


def _measure(memory, queries, **kw) -> tuple[float, float]:
    """p50/p95 of the CPU each search spends (``time.process_time``: every thread of this process, never the time it
    waited for a core). A wall clock failed these budgets whenever the Mac ran 30–55 other processes (dev 2026-10-28:
    prefix p95 above 50 ms at load 30–55, 13–19 ms re-run at load 16–20 on the same commit); the budget is the code's
    cost, which a busy machine does not change. The wall p95 is printed beside it."""
    for q in queries[:10]:  # warm the bank_index cache and SQLite's page cache
        search_service.search(memory, q, **kw)
    samples, wall = [], []
    for q in queries:
        started, cpu = time.perf_counter(), time.process_time()
        search_service.search(memory, q, **kw)
        samples.append(time.process_time() - cpu)
        wall.append(time.perf_counter() - started)
    wall_p95 = statistics.quantiles(wall, n=20)[18]
    print(f"G136 wall p95 {wall_p95 * 1000:.1f} ms")
    _WALL[0] = wall_p95
    return statistics.median(samples), statistics.quantiles(samples, n=20)[18]


#: The last `_measure`'s wall p95 (review of #518): CPU time alone would pass a search that WAITS — on a subprocess, a
#: lock, a disk read — so each budget also holds the wall p95 under :data:`WALL_FACTOR` times itself, loose enough
#: for a loaded machine (load 30–55 measured at most ~5× the CPU p95's budget share, never 4× a budget).
_WALL = [0.0]
WALL_FACTOR = 4


def _assert_within(p95: float, budget: float) -> None:
    assert p95 <= budget, f"CPU p95 {p95 * 1000:.1f} ms over {budget * 1000:.0f} ms"
    assert _WALL[0] <= WALL_FACTOR * budget, (
        f"wall p95 {_WALL[0] * 1000:.1f} ms over {WALL_FACTOR}× the {budget * 1000:.0f} ms budget: a wait, not work")


def test_prefix_mode_p95_is_within_the_50ms_budget(big_bank):
    memory, queries = big_bank
    p50, p95 = _measure(memory, queries, kinds=PALETTE_KINDS, mode="prefix", per_kind=5)
    print(f"G136 prefix (palette Pass A, default freshness TTL): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    _assert_within(p95, 0.050)


def test_prefix_mode_stays_within_budget_with_a_staleness_scan_on_every_request(big_bank):
    memory, queries = big_bank
    p50, p95 = _measure(memory, queries, kinds=PALETTE_KINDS, mode="prefix", per_kind=5, freshness_ttl_s=0)
    print(f"G136 prefix (scan on every request): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    _assert_within(p95, 0.050)


def test_hybrid_mode_p95_is_within_the_200ms_budget(big_bank):
    from api.services.vector_index import SqliteVecIndexer

    memory, queries = big_bank
    indexer = SqliteVecIndexer(memory, embed_fn=_fake_embed)
    indexer.index_entities()
    indexer.index_claims()
    indexer.index_episodes()
    p50, p95 = _measure(memory, queries, kinds=PALETTE_KINDS, mode="hybrid", per_kind=5, embed_fn=_fake_embed)
    print(f"G136 hybrid (palette Pass B, fake embedder): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    _assert_within(p95, 0.200)
