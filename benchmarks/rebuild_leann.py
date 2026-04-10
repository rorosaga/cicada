"""One-shot helper to rebuild the LEANN indexes on the live memory dir.

The live ``memory/leann/episodes.*`` fileset is currently incomplete —
only ``episodes.passages.idx`` and ``episodes.passages.jsonl`` exist,
the actual ``episodes.index`` + ``episodes.meta.json`` + ``episodes.ids.txt``
were never written (a prior rebuild attempt failed partway through).
With the episode index unbuilt, the Condition B (episodes-only) baseline
in ``run_table1`` has nothing to query and returns empty for every
question. This script rebuilds all three indexes in place so Condition
B has something real to hit.

**This script WILL spend OpenAI embedding dollars**. Rough cost for the
current corpus (116 episodes + 1473 entities + whatever's in pending):
well under 1 USD with ``text-embedding-3-small``. The operation is
idempotent — if an index is already complete it gets overwritten with
an equivalent one.

Run:

    cd /path/to/cicada
    api/.venv/bin/python -m benchmarks.rebuild_leann

You can also rebuild a single index:

    api/.venv/bin/python -m benchmarks.rebuild_leann --only episodes
    api/.venv/bin/python -m benchmarks.rebuild_leann --only entities
    api/.venv/bin/python -m benchmarks.rebuild_leann --only pending
"""
from __future__ import annotations

# Must be first — sets sys.path and loads api/.env.
from benchmarks import _bootstrap  # noqa: F401

import argparse
import sys
from pathlib import Path

from benchmarks._bootstrap import LIVE_MEMORY_PATH

from api.services.leann_indexer import LeannIndexer


def _run(memory: Path, which: set[str]) -> None:
    indexer = LeannIndexer(memory)
    print(f"memory path: {memory}", file=sys.stderr)
    print(f"indexes:     {sorted(which)}", file=sys.stderr)
    print("", file=sys.stderr)

    if "entities" in which:
        print("rebuilding entity index...", file=sys.stderr)
        n = indexer.index_entities()
        print(f"  -> {n} entities indexed", file=sys.stderr)

    if "episodes" in which:
        print("rebuilding episode index (this one costs the most tokens)...",
              file=sys.stderr)
        n = indexer.index_episodes()
        print(f"  -> {n} episodes indexed", file=sys.stderr)

    if "pending" in which:
        print("rebuilding pending index...", file=sys.stderr)
        n = indexer.rebuild_pending_index()
        print(f"  -> {n} pending entries indexed", file=sys.stderr)

    print("\ndone.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild Cicada's LEANN indexes in place.",
    )
    parser.add_argument(
        "--memory",
        type=Path,
        default=LIVE_MEMORY_PATH,
        help="Memory directory (default: repo_root/memory).",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        choices=["entities", "episodes", "pending"],
        default=["entities", "episodes", "pending"],
        help="Subset of indexes to rebuild.",
    )
    args = parser.parse_args()
    _run(args.memory, set(args.only))


if __name__ == "__main__":
    main()
