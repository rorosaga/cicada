import asyncio
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

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

    try:
        # Collect unprocessed episodes
        episodes = _get_unprocessed_episodes(memory_path)
        if not episodes:
            _state.progress = "No unprocessed episodes found"
            await _finalize(memory_path, cycle_id, [])
            return

        # Stage 1: Entity & Relationship Extraction
        _state.progress = "Stage 1/5: Extracting entities..."
        from api.services.entity_extractor import extract
        extracted = await extract(episodes, settings)

        # Stage 2: Entity Resolution & Deduplication
        _state.progress = "Stage 2/5: Resolving entities..."
        existing = _load_existing_entities(memory_path)
        from api.services.entity_resolver import resolve
        resolved = await resolve(extracted, existing, settings)

        # Stage 3: Conflict Resolution & Pruning
        _state.progress = "Stage 3/5: Resolving conflicts..."
        from api.services.conflict_resolver import resolve_and_prune
        changes = await resolve_and_prune(resolved, existing, settings)

        # Stage 4: Pattern Detection & Skill Extraction
        _state.progress = "Stage 4/5: Extracting skills..."
        from api.services.skill_extractor import detect_patterns
        skills = await detect_patterns(changes, existing, settings)

        # Stage 5: Nudge Generation & Versioning
        _state.progress = "Stage 5/5: Generating nudges..."
        from api.services.nudge_generator import generate
        await generate(changes, skills, memory_path)

        # Mark episodes as processed
        _mark_episodes_processed(episodes)

        # Commit
        await _finalize(memory_path, cycle_id, changes)
        _state.progress = "Completed"

    except Exception as e:
        _state.progress = f"Failed: {e}"
        traceback.print_exc()
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
