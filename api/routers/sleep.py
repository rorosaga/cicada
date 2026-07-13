from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from api.config import Settings, get_settings
from api.models.schemas import (
    EpisodeQueueItem,
    ScheduleConfig,
    SleepHistoryEntry,
    SleepStatusResponse,
    SleepTriggerResponse,
)
from api.services import git_service, sleep_scheduler
from api.services.sleep_cycle import get_sleep_state, list_all_episodes, run

router = APIRouter()


@router.post("/sleep/trigger", response_model=SleepTriggerResponse)
async def trigger_sleep(
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    state = get_sleep_state()
    if state.status == "running":
        return SleepTriggerResponse(
            status="already_running",
            message="A sleep cycle is already in progress",
            cycle_id=state.cycle_id,
        )

    cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    background_tasks.add_task(run, settings, cycle_id)
    return SleepTriggerResponse(
        status="started",
        message="Sleep cycle initiated",
        cycle_id=cycle_id,
    )


@router.get("/sleep/status", response_model=SleepStatusResponse)
async def sleep_status():
    state = get_sleep_state()
    return SleepStatusResponse(
        status=state.status,
        cycle_id=state.cycle_id,
        started_at=state.started_at,
        progress=state.progress,
        error=state.error,
        index_warning=state.index_warning,
        stage=state.stage,
        total_stages=state.total_stages,
        episodes_total=state.episodes_total,
        entities_created=state.entities_created,
        entities_updated=state.entities_updated,
        relationships_created=state.relationships_created,
        skills_detected=state.skills_detected,
        episodes_processed=state.episodes_processed,
        episodes_requeued=state.episodes_requeued,
    )


@router.get("/sleep/history", response_model=list[SleepHistoryEntry])
async def sleep_history(settings: Settings = Depends(get_settings)):
    return await git_service.get_sleep_history(settings.memory_path)


@router.get("/sleep/episodes", response_model=list[EpisodeQueueItem])
async def sleep_episodes(settings: Settings = Depends(get_settings)):
    """Return every episode (queued + processed), sorted by frontmatter timestamp."""
    items: list[EpisodeQueueItem] = []
    for ep in list_all_episodes(settings.memory_path):
        body = (ep.get("body") or "").lstrip()
        preview = body[:200].strip()
        items.append(
            EpisodeQueueItem(
                id=ep["id"],
                timestamp=ep.get("timestamp", ""),
                source=ep.get("source", "unknown"),
                title=ep.get("title"),
                preview=preview,
                processed=ep.get("processed", False),
            )
        )
    return items


@router.get("/sleep/schedule", response_model=ScheduleConfig)
async def get_schedule(settings: Settings = Depends(get_settings)):
    return sleep_scheduler.load_schedule(settings.memory_path)


@router.put("/sleep/schedule", response_model=ScheduleConfig)
async def put_schedule(
    cfg: ScheduleConfig,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    sleep_scheduler.save_schedule(settings.memory_path, cfg)
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        sleep_scheduler.register_job(scheduler, settings, cfg)
    return cfg
