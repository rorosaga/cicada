"""CLI entrypoint: backfill ``origin:`` onto bookmark-synced episodes/entities.

Usage:

    python -m api.scripts.backfill_bookmark_origins --memory <path> [--no-dry-run]

Before ``api/services/media_ingestor.py`` and ``api/services/bookmark_sync.py``
threaded ``RawItem.origin`` into the episode/media-entity writers (G9
origin-provenance), every URL synced through the bookmark connector wrote
``source: bookmark`` on its episode but never stamped ``origin:`` at all —
that left the Capture page's origins strip bucketing every bookmark-synced
episode and media entity under "Unknown". This script repairs the *existing*
files the old code path already wrote; it does not touch the ingest pipeline
itself (already fixed).

SAFETY: pass an explicit ``--memory`` path. The script does NOT default to the
live ``memory/`` directory; you must opt in by naming the path.
``--dry-run`` defaults to **on** — it reports counts + up to 5 examples of
what WOULD be stamped without writing any file. Pass ``--no-dry-run`` to
actually write. This script never runs ``git commit`` — commit the result
yourself if you want it versioned.

Origin is resolved per candidate, in priority order:

1. an existing ``chrome-bookmark`` / ``safari-bookmark`` tag already present in
   the file's frontmatter ``tags`` — ``media_ingestor.write_media_entity``
   already copied ``RawItem.tags`` (which ``bookmark_sync._tag_origin`` always
   tagged) onto the media entity even before this fix landed, so most media
   entities already carry this clue even though ``origin:`` itself was never
   written. A paired bookmark episode without its own tags borrows the origin
   resolved for its media entity (via the episode's ``media_entity_id``
   field) rather than guessing blind;
2. a folder-name hint anywhere in ``tags``/``title``/``name`` starting with
   ``"Bookmarks Bar"`` (Chrome's default bookmarks-bar folder name) ->
   ``chrome-bookmark``, or starting with ``"BookmarksBar"`` (Safari's
   un-spaced folder-title convention) -> ``safari-bookmark`` — this heuristic
   matched the live data exactly;
3. otherwise the generic ``"bookmark"`` origin — still strictly better than
   falling into "unknown" in ``api/services/origin_stats.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _infer_origin(fm: dict) -> str:
    """Resolve a bookmark origin from whatever provenance clues survive in
    ``fm`` (an episode's or a media entity's frontmatter). Never raises;
    always returns a non-empty origin string (worst case: ``"bookmark"``).
    """
    tags = fm.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tag_strs = [str(t) for t in tags if isinstance(t, (str, int, float))]

    tag_set = set(tag_strs)
    if "chrome-bookmark" in tag_set:
        return "chrome-bookmark"
    if "safari-bookmark" in tag_set:
        return "safari-bookmark"

    candidates = list(tag_strs)
    for field_name in ("title", "name"):
        value = fm.get(field_name)
        if isinstance(value, str) and value:
            candidates.append(value)

    for candidate in candidates:
        if candidate.startswith("Bookmarks Bar"):
            return "chrome-bookmark"
        if candidate.startswith("BookmarksBar"):
            return "safari-bookmark"

    return "bookmark"


def plan_backfill(memory_path: Path) -> dict:
    """Scan ``memory_path`` and compute what *would* be stamped, writing nothing.

    Returns ``{"episodes": [...], "entities": [...]}`` where each entry is
    ``{"path", "id", "origin"}``. Shared by the dry-run report and the real
    write pass so the two never drift.
    """
    from api.services import markdown_parser

    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    entities_dir = memory_path / "entities"

    # Pass 1: media entities missing `origin` -- these carry the richest
    # provenance clue (tags), so resolve them first.
    entity_plans: list[dict] = []
    entity_origin_by_id: dict[str, str] = {}
    if entities_dir.exists():
        for filepath in sorted(entities_dir.glob("media-*.md")):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            fm = parsed.frontmatter or {}
            if fm.get("type") != "media" or fm.get("origin"):
                continue
            origin = _infer_origin(fm)
            entity_origin_by_id[filepath.stem] = origin
            entity_plans.append({
                "path": filepath,
                "id": str(fm.get("id") or filepath.stem),
                "origin": origin,
                "frontmatter": fm,
                "body": parsed.body,
            })

    # Pass 2: bookmark episodes missing `origin`. Episodes never carried
    # `tags` (media_ingestor.write_media_episode has no tags field), so prefer
    # whatever origin pass 1 already resolved for the paired media entity
    # (via `media_entity_id`) before falling back to inferring from the
    # episode's own sparser frontmatter.
    episode_plans: list[dict] = []
    if episodes_dir.exists():
        for filepath in sorted(episodes_dir.glob("*.md")):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            fm = parsed.frontmatter or {}
            if fm.get("source") != "bookmark" or fm.get("origin"):
                continue
            media_id = str(fm.get("media_entity_id") or "")
            origin = entity_origin_by_id.get(media_id) or _infer_origin(fm)
            episode_plans.append({
                "path": filepath,
                "id": str(fm.get("id") or filepath.stem),
                "origin": origin,
                "frontmatter": fm,
                "body": parsed.body,
            })

    return {"episodes": episode_plans, "entities": entity_plans}


def apply_backfill(plan: dict) -> None:
    """Write the resolved ``origin`` into every planned file's frontmatter."""
    from api.services import markdown_parser

    for kind in ("episodes", "entities"):
        for item in plan[kind]:
            fm = dict(item["frontmatter"])
            fm["origin"] = item["origin"]
            markdown_parser.write(item["path"], fm, item["body"])


def _origin_counts(plan: dict) -> dict:
    counts: dict[str, int] = {}
    for kind in ("episodes", "entities"):
        for item in plan[kind]:
            counts[item["origin"]] = counts.get(item["origin"], 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m api.scripts.backfill_bookmark_origins",
        description=(
            "Backfill origin: onto bookmark-synced episodes/entities that "
            "predate G9 origin-provenance threading (idempotent, no LLM, no git)."
        ),
    )
    parser.add_argument(
        "--memory",
        required=True,
        type=Path,
        help="Path to the memory workspace to backfill (e.g. ./memory or a tmp dir).",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Report planned changes without writing (default: on). "
            "Pass --no-dry-run to actually write."
        ),
    )
    args = parser.parse_args(argv)

    memory_path = args.memory.expanduser().resolve()
    if not memory_path.exists():
        print(f"error: memory path does not exist: {memory_path}", file=sys.stderr)
        return 2

    plan = plan_backfill(memory_path)
    n_episodes = len(plan["episodes"])
    n_entities = len(plan["entities"])
    counts = _origin_counts(plan)

    if args.dry_run:
        print(
            f"[dry-run] {n_episodes} episode(s) + {n_entities} entity(ies) "
            f"missing origin -> {counts} (no files written)"
        )
        examples = (plan["episodes"] + plan["entities"])[:5]
        for item in examples:
            print(f"  {item['path']} -> origin: {item['origin']}")
        return 0

    apply_backfill(plan)
    print(
        f"backfilled origin on {n_episodes} episode(s) + {n_entities} entity(ies) "
        f"-> {counts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
