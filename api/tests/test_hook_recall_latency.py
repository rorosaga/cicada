"""G149 — the recall hook's latency and note size at the live bank's scale:
the 2,000-entity / 1,500-episode synthetic bank ``test_search_latency`` builds
(fixed seed, made-up syllables), FTS warm. Run with ``-s`` for the numbers the
PR body reports. Budgets: the service p95 ≤ 100 ms and the route p95 ≤ 150 ms,
both inside R-H6's hard 300 ms; every note ≤ 400 tokens; zero notes for the
English prompts."""
from __future__ import annotations

import statistics
import time

from fastapi.testclient import TestClient

from api import config, main
from api.services import hook_recall, markdown_parser
from test_search_latency import big_bank  # noqa: F401 — module-scoped, built once here

ENGLISH = [
    "Fix the failing test in the parser", "Summarize this error log for me", "Write a function that parses dates",
    "What does this stack trace mean", "Rename the variables to be clearer", "Make the button bigger on mobile",
    "Explain how async iterators work", "Why is the build slow today", "Draft a polite reply to this email",
    "Convert this list into a table", "Add type hints to this module", "Review the diff before I merge",
]


def _named(memory, n=60):
    out = []
    for i in range(0, 2000, 2000 // n):
        if i % 5 == 4:          # media pages are not in the entity table
            continue
        page = markdown_parser.parse(memory / "entities" / f"e-{i}.md")
        out.append((f"e-{i}", f"Where does {page.frontmatter['name']} stand after last week?"))
    return out


def _p(samples):
    return statistics.median(samples), statistics.quantiles(samples, n=20)[18]


def test_the_service_is_fast_small_and_silent_on_english(big_bank):  # noqa: F811
    memory, _ = big_bank
    hook_recall.reset()
    named = _named(memory)
    for _, prompt in named[:5]:
        hook_recall.prompt_context(memory, prompt)            # warm SQLite's page cache
    samples, tokens = [], []
    for page_id, prompt in named:
        started = time.perf_counter()
        result = hook_recall.prompt_context(memory, prompt)
        samples.append(time.perf_counter() - started)
        assert page_id in result.injected, prompt
        tokens.append(result.tokens)
    for prompt in ENGLISH * 5:
        started = time.perf_counter()
        result = hook_recall.prompt_context(memory, prompt)
        samples.append(time.perf_counter() - started)
        assert result.injected == (), prompt
    p50, p95 = _p(samples)
    t = sorted(tokens)
    print(f"\nG149 service (FTS warm, {len(samples)} prompts): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    print(f"G149 note tokens over {len(t)} hits: min {t[0]}, p50 {t[len(t) // 2]}, "
          f"p95 {t[int(len(t) * 0.95) - 1]}, max {t[-1]}")
    assert p95 <= 0.100 and t[-1] <= hook_recall.MAX_TOKENS


def test_the_route_and_the_primer_are_inside_the_budget(big_bank, monkeypatch):  # noqa: F811
    memory, _ = big_bank
    hook_recall.reset()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    samples = []
    for n, (_, prompt) in enumerate(_named(memory, 40) * 2):
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
