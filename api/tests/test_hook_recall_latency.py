"""G149 — the recall hook's latency and note size at the live bank's scale:
the 2,000-entity / 1,500-episode synthetic bank ``test_search_latency`` builds
(fixed seed, made-up syllables), FTS warm. Run with ``-s`` for the numbers the
PR body reports. Budgets: the service p95 ≤ 100 ms and the route p95 ≤ 150 ms,
both inside R-H6's hard 300 ms. What the notes say — the named page injected, every note ≤ 400 tokens, zero notes
for the English prompts — is checked in the default suite (``test_hook_recall.py``) on a smaller bank from the
same generator; here it is only timed."""
from __future__ import annotations

import statistics
import time

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import hook_recall
from test_hook_recall import ENGLISH, named_prompts
from test_search_latency import big_bank  # noqa: F401 — module-scoped, built once here

#: A wall-clock budget: the `bench` tier (`make test-bench`, and `make test` before a release), never the default run.
pytestmark = pytest.mark.bench

def _p(samples):
    return statistics.median(samples), statistics.quantiles(samples, n=20)[18]


def test_the_service_is_fast(big_bank):  # noqa: F811
    memory, _ = big_bank
    hook_recall.reset()
    named = named_prompts(memory)
    for _, prompt in named[:5]:
        hook_recall.prompt_context(memory, prompt)            # warm SQLite's page cache
    samples, tokens = [], []
    for _page_id, prompt in named:
        started = time.perf_counter()
        result = hook_recall.prompt_context(memory, prompt)
        samples.append(time.perf_counter() - started)
        tokens.append(result.tokens)
    for prompt in ENGLISH * 5:
        started = time.perf_counter()
        hook_recall.prompt_context(memory, prompt)
        samples.append(time.perf_counter() - started)
    p50, p95 = _p(samples)
    t = sorted(tokens)
    print(f"\nG149 service (FTS warm, {len(samples)} prompts): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    print(f"G149 note tokens over {len(t)} hits: min {t[0]}, p50 {t[len(t) // 2]}, "
          f"p95 {t[int(len(t) * 0.95) - 1]}, max {t[-1]}")
    assert p95 <= 0.100


def test_the_route_and_the_primer_are_inside_the_budget(big_bank, monkeypatch):  # noqa: F811
    memory, _ = big_bank
    hook_recall.reset()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    samples = []
    for n, (_, prompt) in enumerate(named_prompts(memory, 40) * 2):
        body = {"event": "user_prompt_submit", "harness": "claude-code", "session_id": f"s{n}", "prompt": prompt}
        started = time.perf_counter()
        assert client.post("/capture/hook-context", json=body).status_code == 200
        samples.append(time.perf_counter() - started)
    primer = []
    for n in range(20):
        body = {"event": "session_start", "harness": "claude-code", "session_id": f"p{n}"}
        started = time.perf_counter()
        assert client.post("/capture/hook-context", json=body).json()["reason"] == "primer"
        primer.append(time.perf_counter() - started)
    config.get_settings.cache_clear()
    p50, p95 = _p(samples)
    q50, q95 = _p(primer)
    print(f"G149 route (TestClient, {len(samples)} prompts): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    print(f"G149 primer (cached): p50 {q50 * 1000:.1f} ms, p95 {q95 * 1000:.1f} ms")
    assert p95 <= 0.150 and q95 <= 0.150
