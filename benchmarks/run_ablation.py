"""Table 2 ablation harness — threshold sweeps over fresh workspaces.

Creates one fresh memory workspace per ablation row (seeded from the
live ``memory/episodes`` dir, with entities/nudges/clarifications
empty), runs one full sleep cycle per workspace with the overridden
config, and records structural metrics for each run.

**Important scoping note.** The ``experiments.tex`` ablation plan lists
five rows, some of which are config-level (promotion threshold, decay
threshold) and some of which are feature-level (Stage 4 on/off, LEANN
pending index on/off). Only the config-level knobs are supported by
``Settings`` today; toggling Stage 4 or the pending index would require
invasive product changes. To stay honest within the 24-hour budget this
harness only sweeps the threshold knobs. If the full feature ablations
matter, add a toggle flag to the corresponding stage module and extend
the ``ABLATIONS`` list below.

What this harness reports is the **structural ablation**: how the
sleep cycle's output changes as each threshold varies — entity counts,
nudge counts, clarification counts, promoted vs pending ratio, wall
clock, LEANN footprint. It does NOT rerun the four-dimensional rubric
on each ablation (that would require scoring hundreds more cells by
hand). If you want per-ablation rubric scores, re-run
``benchmarks.run_table1`` pointing at each workspace after the sweep
finishes — this harness leaves every workspace on disk for exactly
that reason.

Run:

    api/.venv/bin/python -m benchmarks.run_ablation \\
        --memory memory \\
        --out benchmark_results/table2

    # Smoke test with a 10-episode slice per ablation:
    api/.venv/bin/python -m benchmarks.run_ablation \\
        --memory memory \\
        --out benchmark_results/table2 \\
        --episode-limit 10

    # Run only a subset of ablations:
    api/.venv/bin/python -m benchmarks.run_ablation --only default promotion_1

Outputs:

    ablation_{ts}.json
    ablation_{ts}.csv
    (workspaces persist under /tmp/cicada_bench_table2_* for inspection)
"""
from __future__ import annotations

# Must be first — sets sys.path and loads api/.env.
from benchmarks import _bootstrap  # noqa: F401

import argparse
import asyncio
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from benchmarks._bootstrap import BENCHMARK_RESULTS, LIVE_MEMORY_PATH
from benchmarks.run_table3 import collect_static
from benchmarks.workspace import create_workspace

from api.config import Settings
from api.services.sleep_cycle import get_sleep_state, run as run_sleep


# Only threshold knobs — these map 1:1 to fields already on Settings.
# Each entry becomes one row in Table 2.
ABLATIONS: list[dict] = [
    {"name": "default",          "promotion": 2, "decay": 0.4, "archive": 0.2},
    {"name": "promotion_1",      "promotion": 1, "decay": 0.4, "archive": 0.2},
    {"name": "promotion_3",      "promotion": 3, "decay": 0.4, "archive": 0.2},
    {"name": "decay_aggressive", "promotion": 2, "decay": 0.5, "archive": 0.2},
    {"name": "decay_loose",      "promotion": 2, "decay": 0.3, "archive": 0.2},
]


def _run_one(
    ablation: dict,
    source_memory: Path,
    episode_limit: int | None,
) -> dict:
    name = ablation["name"]
    print(f"\n--- ablation: {name} ---", file=sys.stderr)

    workspace = create_workspace(
        f"table2_{name}",
        episode_limit=episode_limit,
        source_memory=source_memory,
    )

    settings = Settings(
        memory_path=workspace,
        sleep_promotion_threshold=ablation["promotion"],
        decay_nudge_threshold=ablation["decay"],
        archive_threshold=ablation["archive"],
    )

    t0 = time.perf_counter()
    error: str | None = None
    try:
        asyncio.run(run_sleep(settings, f"bench_{name}"))
    except Exception as e:
        # Setup-time failures only — sleep_cycle.run catches its own
        # internal exceptions and exposes them via SleepState below.
        error = f"{type(e).__name__}: {e}"
    elapsed = time.perf_counter() - t0
    sleep_state = get_sleep_state()
    if error is None and sleep_state.error is not None:
        error = sleep_state.error
    succeeded = error is None
    if not succeeded:
        print(f"  !! sleep cycle failed: {error}", file=sys.stderr)

    stats = collect_static(workspace)
    row = {
        "ablation": name,
        "promotion_threshold": ablation["promotion"],
        "decay_nudge_threshold": ablation["decay"],
        "archive_threshold": ablation["archive"],
        "workspace": str(workspace),
        "sleep_wall_clock_seconds": round(elapsed, 2),
        "sleep_succeeded": succeeded,
        "sleep_error": error,
    }
    row.update(stats)

    print(
        f"  {name:18s} entities={row.get('entity_count', 0):4d} "
        f"nudges={row.get('nudges_count', 0):3d} "
        f"clars={row.get('clarifications_count', 0):3d} "
        f"wall={row.get('sleep_wall_clock_seconds', 0):.1f}s",
        file=sys.stderr,
    )
    return row


def _run(
    source_memory: Path,
    out_dir: Path,
    episode_limit: int | None,
    only: list[str] | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    ablations = ABLATIONS
    if only:
        ablations = [a for a in ABLATIONS if a["name"] in only]
        if not ablations:
            print(f"No ablations matched filter {only}. Available: "
                  f"{[a['name'] for a in ABLATIONS]}", file=sys.stderr)
            sys.exit(1)

    print(f"running {len(ablations)} ablation(s):", file=sys.stderr)
    for a in ablations:
        print(
            f"  {a['name']:18s} promotion={a['promotion']} "
            f"decay={a['decay']} archive={a['archive']}",
            file=sys.stderr,
        )

    rows = [_run_one(a, source_memory, episode_limit) for a in ablations]

    json_path = out_dir / f"ablation_{ts}.json"
    csv_path = out_dir / f"ablation_{ts}.csv"
    json_path.write_text(json.dumps(rows, indent=2, default=str))
    if rows:
        fieldnames = list({k for row in rows for k in row.keys()})
        # Preserve a sensible column order: knobs and top-level stats
        # first, everything else in insertion order of the first row.
        preferred = [
            "ablation", "promotion_threshold", "decay_nudge_threshold",
            "archive_threshold", "sleep_succeeded", "sleep_wall_clock_seconds",
            "episode_count", "entity_count", "nudges_count",
            "clarifications_count", "memory_total_bytes", "leann_total_bytes",
            "leann_entity_index_built", "leann_entity_index_bytes",
            "leann_entity_index_partial_bytes",
            "leann_episode_index_built", "leann_episode_index_bytes",
            "leann_episode_index_partial_bytes",
            "leann_pending_index_built", "leann_pending_index_bytes",
            "leann_pending_index_partial_bytes",
            "leann_pending_store_bytes",
            "sleep_error", "workspace",
        ]
        ordered = [f for f in preferred if f in fieldnames]
        ordered += [f for f in fieldnames if f not in ordered]
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ordered)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    print("", file=sys.stderr)
    print(f"wrote {json_path}", file=sys.stderr)
    print(f"wrote {csv_path}", file=sys.stderr)
    print(
        "\nWorkspaces left on disk under /tmp/cicada_bench_table2_* for "
        "inspection. Delete with: rm -rf /tmp/cicada_bench_table2_*",
        file=sys.stderr,
    )
    print(
        "To score Table 2 with the four-dimensional rubric on top of the "
        "structural metrics, re-run benchmarks.run_table1 per workspace:\n"
        "  api/.venv/bin/python -m benchmarks.run_table1 \\\n"
        "    --questions benchmarks/questions.example.yaml \\\n"
        "    --memory /tmp/cicada_bench_table2_default_xxxx \\\n"
        "    --out benchmark_results/table2/scored/default",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cicada Table 2 ablation — threshold sweeps on fresh workspaces."
    )
    parser.add_argument(
        "--memory",
        type=Path,
        default=LIVE_MEMORY_PATH,
        help="Source memory dir to seed workspaces from (default: repo_root/memory).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=BENCHMARK_RESULTS / "table2",
        help="Output directory (default: benchmark_results/table2).",
    )
    parser.add_argument(
        "--episode-limit",
        type=int,
        default=None,
        help="Limit episodes per workspace. Use for smoke tests to save API cost.",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Run only a subset of ablations by name (default: all).",
    )
    args = parser.parse_args()
    _run(
        source_memory=args.memory,
        out_dir=args.out,
        episode_limit=args.episode_limit,
        only=args.only,
    )


if __name__ == "__main__":
    main()
