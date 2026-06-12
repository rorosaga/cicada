from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends

from api.config import Settings, get_settings
from api.models.schemas import (
    StatusEpisodes,
    StatusInbox,
    StatusResponse,
    StatusSleep,
)
from api.services import git_service, inbox_service, sleep_scheduler
from api.services.sleep_cycle import _get_unprocessed_episodes, get_sleep_state

router = APIRouter()


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
