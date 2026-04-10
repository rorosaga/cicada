"""Table 3 benchmark harness — operational measurements.

Collects three buckets of evidence:

1. **Static counts and disk sizes** of the live memory dir: episode count,
   entity count, clarifications, nudges, memory total, LEANN total, LEANN
   per-index sizes.

2. **Recall latency** over a provided query file. Calls the full
   ``handle_recall`` path (Condition A retrieval) on each query and reports
   median, mean, min, max, and p95 wall-clock latency.

3. **Sleep cycle wall-clock** (optional, ``--sleep-cycle-time``). Creates a
   throwaway memory workspace seeded from ``memory/episodes``, runs one
   full sleep cycle end-to-end with real LLM calls, and records the total
   elapsed time plus the resulting entity/nudge counts. This is the one
   step that costs real API dollars — use ``--episode-limit`` for a smoke
   test first.

Nothing in this runner mutates the live ``memory/`` dir. The sleep cycle
timing pass operates entirely inside ``/tmp/cicada_bench_*``.

Run:

    # Static + recall latency only:
    api/.venv/bin/python -m benchmarks.run_table3 \\
        --memory memory \\
        --queries benchmarks/queries.example.txt \\
        --out benchmark_results/table3

    # Add a full fresh sleep cycle timing (costs API dollars):
    api/.venv/bin/python -m benchmarks.run_table3 \\
        --memory memory \\
        --queries benchmarks/queries.example.txt \\
        --sleep-cycle-time \\
        --out benchmark_results/table3

Outputs:

    metrics_{ts}.json
    metrics_{ts}.csv
"""
from __future__ import annotations

# Must be first — sets sys.path and loads api/.env.
from benchmarks import _bootstrap  # noqa: F401

import argparse
import asyncio
import csv
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from benchmarks._bootstrap import BENCHMARK_RESULTS, LIVE_MEMORY_PATH
from benchmarks.retrieval import retrieve_full
from benchmarks.workspace import create_workspace


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _count_files(path: Path, pattern: str = "*.md") -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.glob(pattern))


def _sum_glob_bytes(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.glob(pattern):
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return total


def _leann_index_status(leann_dir: Path, prefix: str) -> tuple[bool, int, int]:
    """Inspect a single LEANN index by name prefix.

    LEANN writes each index as a fileset sharing a common prefix
    (``<prefix>.index``, ``<prefix>.meta.json``, ``<prefix>.ids.txt``,
    ``<prefix>.passages.idx``, ``<prefix>.passages.jsonl``). The
    ``meta.json`` sidecar is only emitted at the end of a successful
    build, so it's the same "is the index actually searchable" marker
    that ``LeannIndexer._search`` uses. Without that marker any other
    matching files on disk are stale partials from an earlier failed
    build attempt.

    Returns ``(built, built_bytes, partial_bytes)`` where:
      * ``built`` is True iff ``<prefix>.meta.json`` exists.
      * ``built_bytes`` is the byte sum of all ``<prefix>.*`` files
        when built, otherwise 0.
      * ``partial_bytes`` is the byte sum of any ``<prefix>.*`` files
        when not built (so leftover partials are still visible to the
        operator without being misreported as a real index size).
    """
    if not leann_dir.exists():
        return False, 0, 0
    meta_marker = leann_dir / f"{prefix}.meta.json"
    total = _sum_glob_bytes(leann_dir, f"{prefix}.*")
    if meta_marker.exists():
        return True, total, 0
    return False, 0, total


def collect_static(memory_path: Path) -> dict:
    """Return all the counts and sizes that Table 3 cares about.

    Also used by ``run_ablation`` to snapshot each workspace post-run,
    so kept as a plain function rather than inlined.

    LEANN per-index sizes are gated on the ``meta.json`` build marker so
    that a half-finished build (e.g. ``episodes.passages.jsonl`` written
    but ``episodes.index`` / ``episodes.meta.json`` never produced) does
    NOT inflate the reported "index size" into looking like a real
    searchable index. The byte counts of those leftover artifacts are
    still surfaced in the corresponding ``*_partial_bytes`` field so the
    state of the workspace is honest, just not labelled as a built index.
    """
    leann = memory_path / "leann"
    ent_built, ent_bytes, ent_partial = _leann_index_status(leann, "entities")
    epi_built, epi_bytes, epi_partial = _leann_index_status(leann, "episodes")
    pen_built, pen_bytes, pen_partial = _leann_index_status(leann, "pending")
    return {
        "episode_count": _count_files(memory_path / "episodes"),
        "entity_count": _count_files(memory_path / "entities"),
        "clarifications_count": _count_files(memory_path / "clarifications"),
        "nudges_count": _count_files(memory_path / "nudges"),
        "memory_total_bytes": _dir_size_bytes(memory_path),
        "leann_total_bytes": _dir_size_bytes(leann),
        "leann_entity_index_built": ent_built,
        "leann_entity_index_bytes": ent_bytes,
        "leann_entity_index_partial_bytes": ent_partial,
        "leann_episode_index_built": epi_built,
        "leann_episode_index_bytes": epi_bytes,
        "leann_episode_index_partial_bytes": epi_partial,
        "leann_pending_index_built": pen_built,
        "leann_pending_index_bytes": pen_bytes,
        "leann_pending_index_partial_bytes": pen_partial,
        "leann_pending_store_bytes": _sum_glob_bytes(leann, "pending_entities.jsonl"),
    }


def measure_recall_latency(
    memory_path: Path,
    queries: list[str],
    inter_query_sleep: float = 0.3,
) -> dict:
    """Time ``handle_recall`` once per query and summarize the distribution.

    A short sleep between queries keeps LEANN's per-call ``LeannSearcher``
    churn from exhausting the ZMQ distance-computer resource pool. The
    product creates (and cleans up) a new searcher on every call, and
    without the pause that cleanup isn't always done by the time the next
    call starts — which surfaces as ``zmq_msg_recv failed: 35`` crashes
    in the middle of a latency sweep.
    """
    if not queries:
        return {}
    timings: list[float] = []
    for i, q in enumerate(queries):
        if i > 0 and inter_query_sleep > 0:
            time.sleep(inter_query_sleep)
        t0 = time.perf_counter()
        _ = retrieve_full(memory_path, q)
        timings.append(time.perf_counter() - t0)

    sorted_t = sorted(timings)
    # Simple nearest-rank p95. For small samples this is a coarse
    # approximation — we note the sample size alongside so the reader
    # knows how seriously to take the 95th percentile.
    p95_idx = max(0, int(round(0.95 * len(sorted_t))) - 1)
    return {
        "recall_query_count": len(timings),
        "recall_latency_mean_seconds": round(statistics.mean(timings), 3),
        "recall_latency_median_seconds": round(statistics.median(timings), 3),
        "recall_latency_p95_seconds": round(sorted_t[p95_idx], 3),
        "recall_latency_min_seconds": round(min(timings), 3),
        "recall_latency_max_seconds": round(max(timings), 3),
    }


def measure_sleep_cycle_time(
    source_memory: Path,
    episode_limit: int | None = None,
) -> dict:
    """Run one full sleep cycle inside a fresh workspace and time it.

    Returns a dict with wall-clock time, episode/entity counts before and
    after, and any workspace path / error so the caller can inspect
    post-hoc.
    """
    # Local imports so Settings + sleep_cycle don't get pulled in for
    # the no-sleep-cycle path.
    from api.config import Settings
    from api.services.sleep_cycle import get_sleep_state, run as run_sleep

    workspace = create_workspace(
        "table3_sleep",
        episode_limit=episode_limit,
        source_memory=source_memory,
    )
    episodes_before = _count_files(workspace / "episodes")
    entities_before = _count_files(workspace / "entities")

    settings = Settings(memory_path=workspace)
    t0 = time.perf_counter()
    error: str | None = None
    try:
        asyncio.run(run_sleep(settings, "bench_table3"))
    except Exception as e:
        # The sleep cycle catches its own exceptions internally, so this
        # branch only fires for setup-time failures (bad workspace, missing
        # config, etc). Cover both cases.
        error = f"{type(e).__name__}: {e}"
    elapsed = time.perf_counter() - t0
    # The Sleep cycle swallows its own exceptions and only exposes failure
    # via SleepState — read that here so a failed run cannot masquerade as
    # successful just because no Python exception escaped.
    sleep_state = get_sleep_state()
    if error is None and sleep_state.error is not None:
        error = sleep_state.error
    succeeded = error is None
    progress = sleep_state.progress

    result = {
        "sleep_cycle_workspace": str(workspace),
        "sleep_cycle_episodes": episodes_before,
        "sleep_cycle_entities_before": entities_before,
        "sleep_cycle_entities_after": _count_files(workspace / "entities"),
        "sleep_cycle_nudges_after": _count_files(workspace / "nudges"),
        "sleep_cycle_clarifications_after": _count_files(workspace / "clarifications"),
        "sleep_cycle_wall_clock_seconds": round(elapsed, 2),
        "sleep_cycle_seconds_per_episode": (
            round(elapsed / episodes_before, 3) if episodes_before else None
        ),
        "sleep_cycle_succeeded": succeeded,
        "sleep_cycle_error": error,
        "sleep_cycle_progress": progress,
    }
    # Also capture post-run workspace stats so Table 3 and Table 2 are
    # reported in the same units.
    result.update({f"post_sleep_{k}": v for k, v in collect_static(workspace).items()})
    return result


def _load_queries(path: Path | None) -> list[str]:
    if not path:
        return []
    if not path.exists():
        print(f"(queries file {path} not found — skipping recall latency)", file=sys.stderr)
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def _run(
    memory_path: Path,
    queries_path: Path | None,
    out_dir: Path,
    do_sleep: bool,
    episode_limit: int | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    metrics: dict = {
        "timestamp": ts,
        "memory_path": str(memory_path),
    }

    print(f"collecting static metrics for {memory_path}", file=sys.stderr)
    metrics.update(collect_static(memory_path))

    queries = _load_queries(queries_path)
    if queries:
        print(f"measuring recall latency over {len(queries)} queries", file=sys.stderr)
        metrics.update(measure_recall_latency(memory_path, queries))
    else:
        print("(no queries — skipping recall latency)", file=sys.stderr)

    if do_sleep:
        print("running fresh sleep cycle for wall-clock timing (costs API dollars)", file=sys.stderr)
        metrics.update(measure_sleep_cycle_time(memory_path, episode_limit=episode_limit))

    json_path = out_dir / f"metrics_{ts}.json"
    csv_path = out_dir / f"metrics_{ts}.csv"
    json_path.write_text(json.dumps(metrics, indent=2, default=str))
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for k, v in metrics.items():
            w.writerow([k, v])

    print("", file=sys.stderr)
    print(f"wrote {json_path}", file=sys.stderr)
    print(f"wrote {csv_path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cicada Table 3 benchmark — operational measurements."
    )
    parser.add_argument(
        "--memory",
        type=Path,
        default=LIVE_MEMORY_PATH,
        help="Path to memory dir (default: repo_root/memory).",
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=None,
        help="Optional text file, one query per line, # for comments.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=BENCHMARK_RESULTS / "table3",
        help="Output directory (default: benchmark_results/table3).",
    )
    parser.add_argument(
        "--sleep-cycle-time",
        action="store_true",
        help="Also run a full sleep cycle in a fresh workspace. Costs API dollars.",
    )
    parser.add_argument(
        "--episode-limit",
        type=int,
        default=None,
        help="Limit episodes copied into the sleep-cycle workspace (smoke test).",
    )
    args = parser.parse_args()
    _run(
        memory_path=args.memory,
        queries_path=args.queries,
        out_dir=args.out,
        do_sleep=args.sleep_cycle_time,
        episode_limit=args.episode_limit,
    )


if __name__ == "__main__":
    main()
