import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from api.config import Settings
from api.services import git_service, markdown_parser


@dataclass
class SleepState:
    status: str = "idle"
    cycle_id: str | None = None
    started_at: str | None = None
    progress: str | None = None
    # Set to a string when the most recent run hit an exception. The benchmark
    # harness reads this to distinguish a real success from a swallowed
    # exception, since ``run`` deliberately catches everything internally so
    # the FastAPI background task doesn't crash the API process.
    error: str | None = None
    # Non-fatal warning surfaced to the Sleep page when the main entity writes
    # + commit succeeded but a post-cycle step (e.g. LEANN index rebuild) did
    # not. Makes "completed but indexes stale" visible instead of reporting it
    # as a clean success.
    index_warning: str | None = None
    # Structured progress metrics for the Sleep dashboard. ``stage`` is the
    # index of the *completed* stage (0 = not started, 5 = all done). Counters
    # are populated at each stage boundary and ticked live into ``/sleep/status``
    # so the UI can animate a real progress bar instead of a text tooltip.
    stage: int = 0
    total_stages: int = 5
    episodes_total: int = 0
    entities_created: int = 0
    entities_updated: int = 0
    relationships_created: int = 0
    skills_detected: int = 0


_state = SleepState()
_lock = asyncio.Lock()


def get_sleep_state() -> SleepState:
    return _state


async def run(settings: Settings, cycle_id: str) -> None:
    """Execute the 5-stage Sleep cycle pipeline."""
    global _state

    _state.status = "running"
    _state.cycle_id = cycle_id
    _state.started_at = datetime.now().isoformat()
    _state.progress = "Starting..."
    _state.error = None
    _state.index_warning = None
    # Reset structured metrics at the top of every run so the Sleep dashboard
    # doesn't show stale counts from a previous cycle.
    _state.stage = 0
    _state.episodes_total = 0
    _state.entities_created = 0
    _state.entities_updated = 0
    _state.relationships_created = 0
    _state.skills_detected = 0

    memory_path = settings.memory_path
    logger.info(f"Sleep cycle {cycle_id} started — model: {settings.litellm_model}")

    try:
        # Collect unprocessed episodes
        episodes = _get_unprocessed_episodes(memory_path)
        if not episodes:
            logger.info("No unprocessed episodes found — skipping")
            _state.progress = "No unprocessed episodes"
            _state.status = "idle"
            return

        logger.info(f"Found {len(episodes)} unprocessed episodes")
        _state.episodes_total = len(episodes)

        # Stage 1: Entity & Relationship Extraction
        _state.progress = f"Stage 1/5: Extracting entities from {len(episodes)} episodes..."
        logger.info(f"Stage 1: Extracting entities from {len(episodes)} episodes")
        from api.services.entity_extractor import extract
        extracted = await extract(episodes, settings)
        total_entities = sum(len(e.get("entities", [])) for e in extracted)
        total_rels = sum(len(e.get("relationships", [])) for e in extracted)
        logger.info(f"Stage 1 complete: {total_entities} entities, {total_rels} relationships extracted")
        _state.stage = 1

        # Stage 2: Entity Resolution & Deduplication
        _state.progress = "Stage 2/5: Resolving entities..."
        logger.info("Stage 2: Resolving entities against existing graph")
        existing = _load_existing_entities(memory_path)
        from api.services.entity_resolver import resolve
        resolved_result = await resolve(extracted, existing, settings)
        resolved_changes = resolved_result["changes"]
        resolved_edges = resolved_result["relationships"]
        episode_cooccurrences = resolved_result.get("episode_cooccurrences", {})
        creates = sum(1 for r in resolved_changes if r.get("action") == "create")
        updates = sum(1 for r in resolved_changes if r.get("action") == "update")
        logger.info(f"Stage 2 complete: {creates} new entities, {updates} updates, {len(resolved_edges)} relationships")
        _state.entities_created = creates
        _state.entities_updated = updates
        _state.relationships_created = len(resolved_edges)
        _state.stage = 2

        # Stage 3: Conflict Resolution & Pruning
        _state.progress = "Stage 3/5: Resolving conflicts..."
        logger.info("Stage 3: Conflict resolution & temporal decay")
        from api.services.conflict_resolver import resolve_and_prune
        changes = await resolve_and_prune(resolved_changes, existing, settings)
        logger.info(f"Stage 3 complete: {len(changes)} total changes")
        _state.stage = 3

        # Stage 4: Pattern Detection & Skill Extraction
        _state.progress = "Stage 4/5: Extracting skills..."
        logger.info("Stage 4: Pattern detection & skill extraction")
        from api.services.skill_extractor import detect_patterns
        skills = await detect_patterns(
            changes,
            existing,
            settings,
            episode_cooccurrences=episode_cooccurrences,
        )
        logger.info(f"Stage 4 complete: {len(skills)} skills detected")
        _state.skills_detected = len(skills)
        _state.stage = 4

        # Stage 5: Nudge Generation & Versioning
        _state.progress = "Stage 5/5: Writing changes..."
        logger.info("Stage 5: Writing entities, nudges, clarifications, and relationships")
        from api.services.nudge_generator import generate
        await generate(changes, skills, memory_path, relationships=resolved_edges)

        # Mark episodes as processed
        _mark_episodes_processed(episodes)
        logger.info(f"Marked {len(episodes)} episodes as processed")

        # Rebuild LEANN indexes so Bookworm reflects the post-sleep state.
        # Entity and episode rebuilds are independent and we want to surface
        # partial failures: if only the episode index fails, the cycle still
        # wrote the markdown graph, committed, and should report success
        # *with a warning* — not a silent pass, not a hard failure.
        index_warnings: list[str] = []
        try:
            from api.services.leann_indexer import LeannIndexer
            indexer = LeannIndexer(memory_path)
        except Exception as e:
            indexer = None
            warning = f"LEANN indexer init failed: {type(e).__name__}: {e}"
            logger.warning(warning)
            index_warnings.append(warning)

        if indexer is not None:
            try:
                indexer.index_entities()
            except Exception as e:
                warning = f"entity index rebuild failed: {type(e).__name__}: {e}"
                logger.warning(f"LEANN {warning}")
                index_warnings.append(warning)
            try:
                indexer.index_episodes()
            except Exception as e:
                warning = f"episode index rebuild failed: {type(e).__name__}: {e}"
                logger.warning(f"LEANN {warning}")
                index_warnings.append(warning)

        if index_warnings:
            _state.index_warning = "; ".join(index_warnings)

        # Commit
        await _finalize(memory_path, cycle_id, changes)
        if _state.index_warning:
            _state.progress = f"Completed with warnings: {_state.index_warning}"
            logger.warning(
                f"Sleep cycle {cycle_id} completed with warnings — "
                f"{len(changes)} changes committed; {_state.index_warning}"
            )
        else:
            _state.progress = "Completed"
            logger.success(
                f"Sleep cycle {cycle_id} completed — {len(changes)} changes committed"
            )
        _state.stage = 5

    except Exception as e:
        _state.progress = f"Failed: {e}"
        _state.error = f"{type(e).__name__}: {e}"
        logger.error(f"Sleep cycle failed: {e}")
        logger.exception("Full traceback:")
    finally:
        _state.status = "idle"


def _get_unprocessed_episodes(memory_path: Path) -> list[dict]:
    """Load all episodes with processed: false, sorted by frontmatter timestamp.

    Sorting by timestamp (not filename) keeps the queue the Sleep dashboard
    shows aligned with the chronology-aware entity writes in
    ``conflict_resolver.apply_changes``, which use earliest/latest source
    episode timestamps to set ``created`` and ``last_referenced``.
    """
    episodes_dir = memory_path / "episodes"
    results: list[dict] = []
    for filepath in episodes_dir.glob("*.md"):
        parsed = markdown_parser.parse(filepath)
        if not parsed.frontmatter.get("processed", False):
            results.append({
                "id": parsed.frontmatter.get("id", filepath.stem),
                "content": parsed.body,
                "source": parsed.frontmatter.get("source", "unknown"),
                "timestamp": str(parsed.frontmatter.get("timestamp", "") or ""),
                "filepath": filepath,
            })
    # Fall back on the id (which begins with the date) for episodes missing a
    # timestamp so the sort is stable regardless of filesystem order.
    results.sort(key=lambda r: (r.get("timestamp") or "", r["id"]))
    return results


def list_all_episodes(memory_path: Path) -> list[dict]:
    """Return every episode (processed + unprocessed), sorted by timestamp.

    Used by ``GET /sleep/episodes`` so the Sleep dashboard can show both the
    queue and recently processed episodes in the same chronology that the
    sleep cycle consumes them in.
    """
    episodes_dir = memory_path / "episodes"
    results: list[dict] = []
    for filepath in episodes_dir.glob("*.md"):
        parsed = markdown_parser.parse(filepath)
        fm = parsed.frontmatter
        results.append({
            "id": fm.get("id", filepath.stem),
            "timestamp": str(fm.get("timestamp", "") or ""),
            "source": fm.get("source", "unknown"),
            "title": fm.get("title"),
            "body": parsed.body or "",
            "processed": bool(fm.get("processed", False)),
            "filepath": filepath,
        })
    results.sort(key=lambda r: (r.get("timestamp") or "", r["id"]))
    return results


def _load_existing_entities(memory_path: Path) -> list[dict]:
    """Load all existing entity data."""
    entities_dir = memory_path / "entities"
    results: list[dict] = []
    for filepath in sorted(entities_dir.glob("*.md")):
        parsed = markdown_parser.parse(filepath)
        results.append({
            "id": filepath.stem,
            "frontmatter": parsed.frontmatter,
            "body": parsed.body,
            "filepath": filepath,
        })
    return results


def _mark_episodes_processed(episodes: list[dict]) -> None:
    """Mark episodes as processed in their frontmatter."""
    for ep in episodes:
        filepath = ep["filepath"]
        parsed = markdown_parser.parse(filepath)
        parsed.frontmatter["processed"] = True
        markdown_parser.write(filepath, parsed.frontmatter, parsed.body)


async def _finalize(memory_path: Path, cycle_id: str, changes: list) -> None:
    """Commit all changes from the sleep cycle with a structured message.

    Entity-level lines from ``changes`` have source + trigger; file-level
    additions (nudges, clarifications, graph_edges, etc.) are inferred from
    ``git status`` so the commit message remains a complete manifest.
    """
    date_str = datetime.now().strftime("%Y-%m-%d")

    # --- Entity lines from structured change data ---
    entity_lines: list[str] = []
    entity_files_covered: set[str] = set()
    for change in changes:
        if not isinstance(change, dict):
            continue
        entity_id = change.get("id", "unknown")
        action = change.get("action", "updated")
        source = change.get("source_episode", "") or "n/a"
        trigger = change.get("trigger", "sleep/extraction")
        path = f"entities/{entity_id}.md"
        entity_files_covered.add(path)
        entity_lines.append(
            f"{path}: {action} (source: {source}, trigger: {trigger})"
        )

    # --- File lines for anything else touched in the working tree ---
    extra_lines: list[str] = []
    # Stage so porcelain reports paths beneath the memory repo's index filter.
    status = await git_service.porcelain_status(memory_path)

    for raw in status.splitlines():
        if not raw.strip():
            continue
        # porcelain format: XY <path>, possibly "XY orig -> new"
        parts = raw[3:].split(" -> ")
        path = parts[-1].strip()
        if path in entity_files_covered:
            continue
        status_code = raw[:2].strip()
        action = _porcelain_action(status_code)
        trigger = _infer_trigger_for_path(path)
        extra_lines.append(f"{path}: {action} (trigger: {trigger})")

    body_lines = entity_lines + extra_lines
    message = f"Sleep cycle {date_str}\n\n" + "\n".join(body_lines)
    async with _lock:
        await git_service.commit_changes(memory_path, message)


def _porcelain_action(status_code: str) -> str:
    """Map a git porcelain status code to a human-readable action."""
    if "A" in status_code or status_code == "??":
        return "created"
    if "D" in status_code:
        return "deleted"
    if "R" in status_code:
        return "renamed"
    return "updated"


def _infer_trigger_for_path(path: str) -> str:
    """Infer a trigger type for a non-entity file based on its directory."""
    if path.startswith("nudges/"):
        return "sleep/nudge_generation"
    if path.startswith("clarifications/"):
        return "sleep/extraction"
    if path.startswith("episodes/"):
        return "sleep/extraction"
    if path.startswith("leann/"):
        return "sleep/index_rebuild"
    if path == "graph_edges.yaml":
        return "sleep/extraction"
    return "sleep/extraction"
