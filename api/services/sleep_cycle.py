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

        # Stage 1: Entity & Relationship Extraction
        _state.progress = f"Stage 1/5: Extracting entities from {len(episodes)} episodes..."
        logger.info(f"Stage 1: Extracting entities from {len(episodes)} episodes")
        from api.services.entity_extractor import extract
        extracted = await extract(episodes, settings)
        total_entities = sum(len(e.get("entities", [])) for e in extracted)
        total_rels = sum(len(e.get("relationships", [])) for e in extracted)
        logger.info(f"Stage 1 complete: {total_entities} entities, {total_rels} relationships extracted")

        # Stage 2: Entity Resolution & Deduplication
        _state.progress = "Stage 2/5: Resolving entities..."
        logger.info("Stage 2: Resolving entities against existing graph")
        existing = _load_existing_entities(memory_path)
        from api.services.entity_resolver import resolve
        resolved_result = await resolve(extracted, existing, settings)
        resolved_changes = resolved_result["changes"]
        resolved_edges = resolved_result["relationships"]
        creates = sum(1 for r in resolved_changes if r.get("action") == "create")
        updates = sum(1 for r in resolved_changes if r.get("action") == "update")
        logger.info(f"Stage 2 complete: {creates} new entities, {updates} updates, {len(resolved_edges)} relationships")

        # Stage 3: Conflict Resolution & Pruning
        _state.progress = "Stage 3/5: Resolving conflicts..."
        logger.info("Stage 3: Conflict resolution & temporal decay")
        from api.services.conflict_resolver import resolve_and_prune
        changes = await resolve_and_prune(resolved_changes, existing, settings)
        logger.info(f"Stage 3 complete: {len(changes)} total changes")

        # Stage 4: Pattern Detection & Skill Extraction
        _state.progress = "Stage 4/5: Extracting skills..."
        logger.info("Stage 4: Pattern detection & skill extraction")
        from api.services.skill_extractor import detect_patterns
        skills = await detect_patterns(changes, existing, settings)
        logger.info(f"Stage 4 complete: {len(skills)} skills detected")

        # Stage 5: Nudge Generation & Versioning
        _state.progress = "Stage 5/5: Writing changes..."
        logger.info("Stage 5: Writing entities, nudges, clarifications, and relationships")
        from api.services.nudge_generator import generate
        await generate(changes, skills, memory_path, relationships=resolved_edges)

        # Mark episodes as processed
        _mark_episodes_processed(episodes)
        logger.info(f"Marked {len(episodes)} episodes as processed")

        # Commit
        await _finalize(memory_path, cycle_id, changes)
        _state.progress = "Completed"
        logger.success(f"Sleep cycle {cycle_id} completed — {len(changes)} changes committed")

    except Exception as e:
        _state.progress = f"Failed: {e}"
        logger.error(f"Sleep cycle failed: {e}")
        logger.exception("Full traceback:")
    finally:
        _state.status = "idle"


def _get_unprocessed_episodes(memory_path: Path) -> list[dict]:
    """Load all episodes with processed: false."""
    episodes_dir = memory_path / "episodes"
    results: list[dict] = []
    for filepath in sorted(episodes_dir.glob("*.md")):
        parsed = markdown_parser.parse(filepath)
        if not parsed.frontmatter.get("processed", False):
            results.append({
                "id": parsed.frontmatter.get("id", filepath.stem),
                "content": parsed.body,
                "source": parsed.frontmatter.get("source", "unknown"),
                "timestamp": parsed.frontmatter.get("timestamp", ""),
                "filepath": filepath,
            })
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
    """Commit all changes from the sleep cycle."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    body_lines: list[str] = []
    for change in changes:
        if isinstance(change, dict):
            entity_id = change.get("id", "unknown")
            action = change.get("action", "updated")
            source = change.get("source_episode", "")
            trigger = change.get("trigger", "sleep/extraction")
            body_lines.append(
                f"entities/{entity_id}.md: {action} (source: {source}, trigger: {trigger})"
            )

    message = f"Sleep cycle {date_str}\n\n" + "\n".join(body_lines)
    async with _lock:
        await git_service.commit_changes(memory_path, message)
