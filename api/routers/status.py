from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from api.config import Settings, get_settings
from api.models.schemas import (
    HealthResponse,
    StatusEpisodes,
    StatusInbox,
    StatusResponse,
    StatusSleep,
)
from api.services import git_service, inbox_service, sleep_scheduler
from api.services.sleep_cycle import _get_unprocessed_episodes, get_sleep_state

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz(request: Request, settings: Settings = Depends(get_settings)):
    """Auth-free liveness probe for the installer / doctor.

    Reports counts, the *resolved* embedding mode (post auto-degrade), and
    whether any LEANN index has been built so doctor can verify the offline
    path is active and the indexes exist without parsing logs.
    """
    memory_path = settings.memory_path
    entity_count = _count_md(memory_path / "entities")
    episode_count = _count_md(memory_path / "episodes")
    return HealthResponse(
        status="ok",
        version=request.app.version,
        entity_count=entity_count,
        episode_count=episode_count,
        embedding_mode=settings.resolved_embedding_mode,
        memory_path=str(memory_path),
        leann_present=_leann_present(memory_path),
    )


def _count_md(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(1 for _ in directory.glob("*.md"))


def _leann_present(memory_path: Path) -> bool:
    """True if any LEANN index sidecar exists.

    A built index writes ``<prefix>.meta.json`` (the same marker
    ``LeannIndexer._search`` checks), so the presence of any such sidecar
    under ``leann/`` means at least one index has been built.
    """
    leann_dir = memory_path / "leann"
    if not leann_dir.exists():
        return False
    return any(leann_dir.glob("*.meta.json"))


@router.get("/status", response_model=StatusResponse)
async def get_status(settings: Settings = Depends(get_settings)):
    state = get_sleep_state()
    items = inbox_service.load_inbox(settings.memory_path)
    by_kind = Counter(i.kind.value for i in items)

    episodes = _get_unprocessed_episodes(settings.memory_path)
    last_ingested = _last_ingested_at(settings.memory_path)
    last_sleep = await _last_sleep_at(settings.memory_path)
    next_sleep = _next_sleep_at(settings.memory_path)

    return StatusResponse(
        sleep=StatusSleep(
            status=state.status,
            stage=state.stage,
            total_stages=state.total_stages,
            cycle_id=state.cycle_id,
            error=state.error,
        ),
        inbox=StatusInbox(total=len(items), by_kind=dict(by_kind)),
        episodes=StatusEpisodes(
            unprocessed=len(episodes),
            last_ingested_at=last_ingested,
        ),
        last_sleep_at=last_sleep,
        next_sleep_at=next_sleep,
    )


def _last_ingested_at(memory_path: Path) -> str | None:
    """Latest episode timestamp across all episodes, or None."""
    from api.services import markdown_parser

    episodes_dir = memory_path / "episodes"
    latest: str | None = None
    if not episodes_dir.exists():
        return None
    for filepath in episodes_dir.glob("*.md"):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        ts = str(parsed.frontmatter.get("timestamp", "") or "").strip()
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


async def _last_sleep_at(memory_path: Path) -> str | None:
    """Date of the most recent Sleep cycle commit, or None."""
    history = await git_service.get_sleep_history(memory_path)
    for entry in history:
        if entry.message.lower().startswith("sleep cycle"):
            return entry.date
    return None


def _next_sleep_at(memory_path: Path) -> str | None:
    """Next occurrence of the persisted schedule, or None when disabled."""
    cfg = sleep_scheduler.load_schedule(memory_path)
    if not cfg.enabled:
        return None
    now = datetime.now()
    candidate = now.replace(hour=cfg.hour, minute=cfg.minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.isoformat()
