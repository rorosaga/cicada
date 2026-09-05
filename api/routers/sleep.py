from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from api.config import Settings, get_settings
from api.models.schemas import (
    EpisodeQueueItem,
    ScheduleConfig,
    SleepCancelResponse,
    SleepCycleDetail,
    SleepDebtResponse,
    SleepHistoryEntry,
    SleepStatusResponse,
    SleepTriggerResponse,
)
from api.services import git_service, sleep_debt, sleep_scheduler
from api.services.sleep_cycle import (
    cancelled_is_visible,
    get_sleep_state,
    list_all_episodes,
    progress_pct,
    request_cancel,
    reserve_cycle,
    run,
)

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
    # Devin PR #27 round 1, finding 2: reserve the slot SYNCHRONOUSLY,
    # before scheduling the background task — a FastAPI background task
    # only starts running once this response has been sent, so without this
    # an immediate `POST /sleep/cancel` would see `status == "idle"` and
    # report "not_running", silently losing the cancel. `run()` (below)
    # detects the reservation and preserves whatever got requested in the
    # window between this call and its own first line.
    reserve_cycle(cycle_id)
    # Fix round 1, H1: explicit, not just the default — this IS the
    # human-pressed-Run path spec §7 scopes the toggle/auto engine
    # selection to.
    background_tasks.add_task(run, settings, cycle_id, user_triggered=True)
    return SleepTriggerResponse(
        status="started",
        message="Sleep cycle initiated",
        cycle_id=cycle_id,
    )


@router.post("/sleep/cancel", response_model=SleepCancelResponse)
async def cancel_sleep():
    """Cooperative-cancel whatever cycle is currently running.

    Same "no 404/409, an honest 200 body" convention as ``/sleep/trigger``'s
    own ``already_running`` status: ``status`` is ``"not_running"`` when there
    was nothing to cancel (idempotent — calling this twice, or calling it
    when nothing is running, is always safe), else ``"cancelling"``. The
    cancel itself is cooperative: it takes effect at the pipeline's next safe
    point (see ``sleep_cycle.request_cancel``), never mid-write or mid-commit,
    so nothing already captured is ever lost — episodes not yet consolidated
    simply stay queued for the next cycle.
    """
    was_running, cycle_id = request_cancel()
    if not was_running:
        return SleepCancelResponse(
            status="not_running",
            message="No sleep cycle is currently running",
            cycle_id=None,
        )
    return SleepCancelResponse(
        status="cancelling",
        message=(
            "Cancellation requested — the cycle stops at its next safe "
            "point, never mid-write. Nothing already captured is lost: any "
            "episodes not yet consolidated stay queued for the next cycle."
        ),
        cycle_id=cycle_id,
    )


@router.get("/sleep/status", response_model=SleepStatusResponse)
async def sleep_status(settings: Settings = Depends(get_settings)):
    state = get_sleep_state()
    debt = await sleep_debt.compute(settings.memory_path, settings)
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
        questions_refreshed=state.questions_refreshed,
        organic_resolutions=state.organic_resolutions,
        last_engine=state.last_engine,
        engine_detail=state.engine_detail,
        episode_cap=state.episode_cap,
        episodes_queued=state.episodes_queued,
        cancel_requested=state.cancel_requested,
        cancelled=cancelled_is_visible(state),
        progress_pct=progress_pct(state),
        queue_by_origin=dict(state.queue_by_origin),
        read_by_origin=dict(state.read_by_origin),
        debt=SleepDebtResponse(
            unprocessed_count=debt.unprocessed_count,
            oldest_unprocessed_age_hours=debt.oldest_unprocessed_age_hours,
            hours_since_last_cycle=debt.hours_since_last_cycle,
            has_run_before=debt.has_run_before,
            volume_pct=debt.volume_pct,
            age_pct=debt.age_pct,
            rested_pct=debt.rested_pct,
        ),
    )


@router.get("/sleep/history", response_model=list[SleepHistoryEntry])
async def sleep_history(limit: int = Query(15, ge=1, le=100), settings: Settings = Depends(get_settings)):
    return await git_service.get_sleep_history(settings.memory_path, limit=limit)


@router.get("/sleep/history/{commit}", response_model=SleepCycleDetail)
async def sleep_cycle_detail(commit: str, settings: Settings = Depends(get_settings)):
    detail = await git_service.get_sleep_cycle_detail(settings.memory_path, commit)
    if detail is None:
        raise HTTPException(status_code=404, detail="Not a Sleep cycle commit")
    return detail


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
                origin=ep.get("origin", "unknown"),
                title=ep.get("title"),
                preview=preview,
                chars=len(ep.get("body") or ""),
                processed=ep.get("processed", False),
                processed_by=ep.get("processed_by"),
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
