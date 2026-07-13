"""CLI entrypoint: deterministically seed in-page claims from graph_edges.yaml.

Usage:

    python -m api.scripts.seed_claims --memory <path>

This converts every ``<memory>/graph_edges.yaml`` edge into a seed claim written
into ``entities/<subject>.md`` (preserving prose), then rebuilds the derived
claims index. It is idempotent — safe to re-run.

SAFETY: pass an explicit ``--memory`` path. The script does NOT default to the
live ``memory/`` directory; you must opt in by naming the path. ``--dry-run``
parses + groups the edges and reports what WOULD be written without touching any
file or building the index.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m api.scripts.seed_claims",
        description="Seed in-page claims from graph_edges.yaml (idempotent, $0 LLM).",
    )
    parser.add_argument(
        "--memory",
        required=True,
        type=Path,
        help="Path to the memory workspace to seed (e.g. ./memory or a tmp dir).",
    )
    parser.add_argument(
        "--today",
        default=None,
        help="valid_from fallback (YYYY-MM-DD) for subjects without a created date.",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Skip rebuilding the claims vector index (seed pages only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned claims without writing pages or building the index.",
    )
    args = parser.parse_args(argv)

    memory_path = args.memory.expanduser().resolve()
    if not memory_path.exists():
        print(f"error: memory path does not exist: {memory_path}", file=sys.stderr)
        return 2

    if args.dry_run:
        return _dry_run(memory_path)

    from api.services.claim_seeder import seed_claims_from_edges

    summary = seed_claims_from_edges(
        memory_path,
        today=args.today,
        rebuild_index=not args.no_index,
    )
    print(
        "seeded {claims_written} new claims across {subjects} subjects "
        "({edges_total} edges, {indexed} indexed)".format(**summary)
    )
    return 0


def _dry_run(memory_path: Path) -> int:
    """Report subject/edge counts without mutating anything."""
    from api.services import predicates
    from api.services.claim_seeder import _load_edges

    edges = _load_edges(memory_path)
    # Dry-run must not write anything (not even the predicate map), so build the
    # normalizer from whatever map is already on disk (falls back to slugify).
    normalize = predicates.load_normalizer(memory_path)

    subjects: set[str] = set()
    valid = 0
    for edge in edges:
        source = str(edge.get("source", "") or "").strip()
        target = str(edge.get("target", "") or "").strip()
        if not source or not target or source == target:
            continue
        subjects.add(source)
        valid += 1
        _ = normalize(str(edge.get("label", "") or ""))
    print(
        f"[dry-run] {len(edges)} edges -> {valid} seedable claims "
        f"across {len(subjects)} subjects (no files written)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
