from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    HealthResponse,
    StatusConnections,
    StatusEpisodes,
    StatusInbox,
    StatusResponse,
    StatusSleep,
)
from api.services import bank_index, git_service, inbox_service, sleep_scheduler, sync_service
from api.services.sleep_cycle import get_sleep_state

router = APIRouter()

# module-level cache: git_head(memory_path) -> last_sleep_at, so /status only
# shells out to `git log` when HEAD actually moved (a Sleep-cycle commit).
_last_sleep_cache: dict[str, str | None] = {}


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
    """True if a vector index has been built.

    Checks the sqlite-vec index first (``vector_index.db`` with recorded
    ``index_meta``); falls back to detecting legacy LEANN ``*.meta.json``
    sidecars so a not-yet-reindexed install still reports an index as present.
    (Field name kept as ``leann_present`` in the API response for now to avoid
    a coordinated Swift-side rename.)
    """
    if (memory_path / "vector_index.db").exists():
        try:
            from api.services.vector_index import SqliteVecIndexer

            if SqliteVecIndexer(memory_path).index_info():
                return True
        except Exception:
            pass
    leann_dir = memory_path / "leann"
    return leann_dir.exists() and any(leann_dir.glob("*.meta.json"))


@router.get("/status", response_model=StatusResponse)
async def get_status(settings: Settings = Depends(get_settings)):
    state = get_sleep_state()
    total, by_kind, unprocessed, last_ingested = await run_in_threadpool(
        _scan_bank, settings.memory_path
    )

    last_sleep = await _last_sleep_at(settings.memory_path)
    next_sleep = _next_sleep_at(settings.memory_path)

    from api.services.connections.registry import get_registry

    conn_statuses = get_registry(settings).cached_statuses()
    connected_ids = [c.id for c in conn_statuses if c.connected]
    engine = next((c.engine_role for c in conn_statuses if c.connected), None)

    return StatusResponse(
        sleep=StatusSleep(
            status=state.status,
            stage=state.stage,
            total_stages=state.total_stages,
            cycle_id=state.cycle_id,
            error=state.error,
        ),
        inbox=StatusInbox(total=total, by_kind=by_kind),
        episodes=StatusEpisodes(
            unprocessed=unprocessed,
            last_ingested_at=last_ingested,
        ),
        last_sleep_at=last_sleep,
        next_sleep_at=next_sleep,
        connections=StatusConnections(connected=connected_ids, engine=engine),
    )


def _scan_bank(memory_path: Path) -> tuple[int, dict[str, int], int, str | None]:
    """Sync helper for the blocking file-scanning pieces of ``/status``.

    Uses the bank_index cache (frontmatter-only, mtime-gated) for both the
    inbox count/by-kind breakdown and the episodes bank_index in one
    threadpool hop so the event loop isn't blocked by filesystem/YAML work.
    """
    total, by_kind = _inbox_counts(memory_path)
    unprocessed = 0
    last_ingested = _last_ingested_at(memory_path)
    for f in bank_index.files(memory_path, "episodes"):
        if not f.frontmatter.get("processed", False):
            unprocessed += 1
    return total, by_kind, unprocessed, last_ingested


def _inbox_counts(memory_path: Path) -> tuple[int, dict[str, int]]:
    """Inbox total + by-kind breakdown from bank_index frontmatter.

    Reads the ``kind`` field straight off each cached ``inbox-*.md`` file's
    frontmatter (see ``inbox_service._item_from_file``) instead of fully
    parsing every item via ``inbox_service.load_inbox``. Falls back to
    ``load_inbox`` only if some file's frontmatter doesn't carry ``kind`` at
    all (as opposed to relying on ``_item_from_file``'s ``"decay"`` default).
    """
    total = 0
    by_kind: Counter = Counter()
    for f in bank_index.files(memory_path, "inbox"):
        if not f.stem.startswith("inbox-"):
            continue
        fm = f.frontmatter
        if "kind" not in fm:
            items = inbox_service.load_inbox(memory_path)
            return len(items), dict(Counter(i.kind.value for i in items))
        total += 1
        by_kind[str(fm["kind"])] += 1
    return total, dict(by_kind)


def _last_ingested_at(memory_path: Path) -> str | None:
    """Latest episode timestamp across all episodes, or None."""
    return max(
        (str(f.frontmatter.get("timestamp") or "") for f in bank_index.files(memory_path, "episodes")),
        default="",
    ) or None


async def _last_sleep_at(memory_path: Path) -> str | None:
    """Date of the most recent Sleep cycle commit, or None.

    Cached per HEAD (read from ``.git/HEAD``, no subprocess — see
    ``sync_service.git_head``) so ``git log`` only runs again once HEAD
    actually moves, instead of on every ``/status`` call.
    """
    head = sync_service.git_head(memory_path)
    cache_key = f"{memory_path}:{head}"
    if cache_key in _last_sleep_cache:
        return _last_sleep_cache[cache_key]

    history = await git_service.get_sleep_history(memory_path)
    result = None
    for entry in history:
        if entry.message.lower().startswith("sleep cycle"):
            result = entry.date
            break

    _last_sleep_cache[cache_key] = result
    return result


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
