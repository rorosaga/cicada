from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response

from api.config import Settings, get_settings
from api.models.schemas import (
    EpisodeQueueItem,
    ScheduleConfig,
    SleepCancelResponse,
    SleepCycleDetail,
    SleepDebtResponse,
    SleepDrain,
    SleepEndRunResponse,
    SleepEngineChoice,
    SleepEngineResponse,
    SleepHistoryEntry,
    SleepPaused,
    SleepParkedRetryBody,
    SleepQueueItem,
    SleepQueueResponse,
    SleepRunDetail,
    SleepRunOptions,
    SleepRunOptionsUpdate,
    SleepStatusResponse,
    SleepTriggerBody,
    SleepTriggerResponse,
)
from api.services import (
    bank_index,
    episode_copy,
    git_service,
    sleep_autocontinue,
    sleep_debt,
    sleep_drain,
    sleep_engine_prefs,
    sleep_paused,
    sleep_parked,
    sleep_run_detail,
    sleep_run_prefs,
    sleep_runs,
    sleep_scheduler,
    sync_service,
)
from api.services.connections.registry import get_registry
from api.services.sleep_cycle import (
    _derive_origin,
    _episode_sort_key,
    cancelled_is_visible,
    configured_batch_size,
    get_sleep_state,
    is_writing,
    list_all_episodes,
    progress_pct,
    request_cancel,
    reserve_cycle,
    run,
)

router = APIRouter()


def active_drain(state, settings):
    """The run's state for the active bank. ``_state.drain`` lingers after a run ends, and
    a bank switch must not show one bank's run beside another's paused record."""
    ds = state.drain
    if ds is not None and getattr(ds, "memory_path", None) not in (None, settings.memory_path):
        return None
    return ds


def paused_block(state, settings):
    """The paused run of the active bank from its sidecar (a ``stat``-keyed cache), or ``None``."""
    if state.status == "running" and not getattr(state, "tail_only", False):
        return None
    wire = sleep_paused.to_wire(sleep_paused.get_paused(settings.memory_path))
    return SleepPaused(**wire) if wire else None


@router.post("/sleep/trigger", response_model=SleepTriggerResponse)
async def trigger_sleep(
    background_tasks: BackgroundTasks,
    body: SleepTriggerBody | None = None,
    settings: Settings = Depends(get_settings),
):
    """Start a run that reads everything waiting (TODO ruling 13).

    No body — the documented curl — is a fresh run, and it clears any paused one.
    ``{"continue": true}`` resumes the paused run for the active bank (same run id, its
    counters carried); with no paused run it is a fresh run. The app's doors all route
    to the Sleep page while a run is paused; only the page's Continue sends this body."""
    state = get_sleep_state()
    if state.status == "running":
        return SleepTriggerResponse(
            status="already_running",
            message="A sleep cycle is already in progress",
            cycle_id=state.cycle_id,
        )

    cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    record = sleep_paused.get_paused(settings.memory_path) if (body and body.continue_run) else None
    # Devin PR #27 round 1, finding 2: reserve the slot SYNCHRONOUSLY,
    # before scheduling the background task — a FastAPI background task
    # only starts running once this response has been sent, so without this
    # an immediate `POST /sleep/cancel` would see `status == "idle"` and
    # report "not_running", silently losing the cancel. `run()` (below)
    # detects the reservation and preserves whatever got requested in the
    # window between this call and its own first line.
    reserve_cycle(cycle_id, drain=True)
    sleep_autocontinue.disarm(settings.memory_path)   # a person's trigger replaces any armed automatic continue
    # Fix round 1, H1: explicit, not just the default — this IS the
    # human-pressed-Run path spec §7 scopes the toggle/auto engine
    # selection to. `drain=True` (owner, 2026-09-29): a person pressing
    # Consolidate reads everything that is waiting, in batches.
    if record is not None:
        background_tasks.add_task(run, settings, cycle_id, user_triggered=True, drain=True, continue_from=record)
        return SleepTriggerResponse(status="started", message="Sleep run resumed", cycle_id=cycle_id)
    background_tasks.add_task(run, settings, cycle_id, user_triggered=True, drain=True)
    return SleepTriggerResponse(
        status="started",
        message="Sleep cycle initiated",
        cycle_id=cycle_id,
    )


@router.post("/sleep/run/end", response_model=SleepEndRunResponse)
async def end_run(settings: Settings = Depends(get_settings)):
    """End this run: forget the paused record. The queue is untouched — every conversation is
    still waiting, and a fresh Consolidate reads them. 409 while a run is reading."""
    if get_sleep_state().status == "running":
        raise HTTPException(status_code=409, detail="A run is reading right now — pause it first.")
    record = sleep_paused.load(settings.memory_path)
    if not record:
        return SleepEndRunResponse(status="none", message="There is no paused run.")
    sleep_autocontinue.disarm(settings.memory_path)
    sleep_paused.clear(settings.memory_path)
    sleep_runs.close_open_pause(settings.memory_path, str(record.get("run_id")))
    return SleepEndRunResponse(status="ended", message="The paused run was ended. Nothing waiting was changed.")


@router.post("/sleep/parked/retry", response_model=SleepTriggerResponse)
async def retry_parked(
    background_tasks: BackgroundTasks,
    body: SleepParkedRetryBody | None = None,
    settings: Settings = Depends(get_settings),
):
    """Retry conversations that could not be read: unpark them and read exactly those in a
    run of their own (each gets its one more try, then parks again if it fails again). No ids
    means every parked one. 409 while a run is reading or paused — continue or end that first."""
    state = get_sleep_state()
    if state.status == "running":
        raise HTTPException(status_code=409, detail="A sleep run is already in progress.")
    if sleep_paused.exists(settings.memory_path):
        raise HTTPException(status_code=409, detail="Continue or end the paused run first.")
    parked = sleep_parked.valid(settings.memory_path)
    want = [i for i in (body.ids if body and body.ids is not None else list(parked)) if i in parked]
    if not want:
        return SleepTriggerResponse(status="nothing_parked", message="No conversation is parked.", cycle_id=None)
    sleep_parked.unpark(settings.memory_path, want)
    cycle_id = f"sleep_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    reserve_cycle(cycle_id, drain=True)
    background_tasks.add_task(run, settings, cycle_id, user_triggered=True, drain=True, only_ids=want)
    return SleepTriggerResponse(status="started", message="Retrying parked conversations", cycle_id=cycle_id)


@router.post("/sleep/cancel", response_model=SleepCancelResponse)
async def cancel_sleep():
    """Cooperative-cancel whatever cycle is currently running.

    Same "no 404/409, an honest 200 body" convention as ``/sleep/trigger``'s
    own ``already_running`` status: ``status`` is ``"not_running"`` when there
    was nothing to cancel (idempotent — calling this twice, or calling it
    when nothing is running, is always safe), else ``"cancelling"``. The
    cancel itself is cooperative: it takes effect at the pipeline's next safe
    point (see ``sleep_cycle.request_cancel``), never mid-write or mid-commit,
    so nothing already filed is ever lost. Episodes not yet consolidated
    stay queued for the next cycle. In a Consolidate drain, the batch that is
    still reading when the cancel lands is dropped before it is filed and is
    read again next time (its reads were paid for and are lost); batches
    already filed stay filed.
    """
    was_running, cycle_id = request_cancel()
    if not was_running:
        return SleepCancelResponse(
            status="not_running",
            message="No sleep cycle is currently running",
            cycle_id=None,
        )
    if get_sleep_state().drain_run:
        return SleepCancelResponse(
            status="cancelling",
            message=(
                "Cancellation requested — the batch in progress stops at its next "
                "safe point, never mid-write. Batches already filed stay filed; "
                "the batch still reading is dropped and read again next time, "
                "and everything not yet read stays queued for the next Consolidate."
            ),
            cycle_id=cycle_id,
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
    ds = active_drain(state, settings)

    def counter(name: str) -> int:
        # Batch-local in the state; a person-started run reports its running sum.
        live = getattr(state, name)
        return sleep_drain.merged(ds, name, live) if ds is not None else live

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
        entities_created=counter("entities_created"),
        entities_updated=counter("entities_updated"),
        relationships_created=counter("relationships_created"),
        skills_detected=counter("skills_detected"),
        episodes_processed=counter("episodes_processed"),
        episodes_requeued=counter("episodes_requeued"),
        questions_refreshed=counter("questions_refreshed"),
        organic_resolutions=counter("organic_resolutions"),
        last_engine=state.last_engine,
        engine_detail=state.engine_detail,
        episode_cap=state.episode_cap,
        batch_size=configured_batch_size(settings),
        episodes_queued=state.episodes_queued,
        cancel_requested=state.cancel_requested,
        cancelled=cancelled_is_visible(state),
        writing=is_writing(),
        progress_pct=progress_pct(state),
        queue_by_origin=dict(state.queue_by_origin),
        read_by_origin=dict(state.read_by_origin),
        drain=SleepDrain(**sleep_drain.to_wire(
            ds, completed=state.stage, running=state.status == "running",
            unprocessed=debt.unprocessed_count)) if ds is not None else None,
        paused=paused_block(state, settings),
        debt=SleepDebtResponse(
            unprocessed_count=debt.unprocessed_count,
            oldest_unprocessed_age_hours=debt.oldest_unprocessed_age_hours,
            hours_since_last_cycle=debt.hours_since_last_cycle,
            has_run_before=debt.has_run_before,
            volume_pct=debt.volume_pct,
            age_pct=debt.age_pct,
            rested_pct=debt.rested_pct,
            parked_count=debt.parked_count,
            readable_count=debt.readable_count,
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


@router.get("/sleep/runs/{drain_id}", response_model=SleepRunDetail)
async def sleep_run_detail_route(drain_id: str, request: Request, response: Response,
                                 settings: Settings = Depends(get_settings)):
    """One whole run: its batches, pauses, models and cost (summed by ``drain_id`` over every
    call, a discarded batch's included), and the pages it touched. Engine-free; ids, counts and
    enums only. Not a Store domain — the app keeps it in memory and revalidates with the ETag."""
    if not drain_id.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=404, detail="Not a run")
    runs_stamp = ""
    try:
        st = (sleep_runs._path(settings.memory_path)).stat()
        runs_stamp = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        pass
    etag = sync_service.etag_for(settings.memory_path, "telemetry", "git_head", "sleep",
                                 extra=f"run|{drain_id}|{runs_stamp}")
    not_modified = sync_service.conditional(request, response, etag)
    if not_modified is not None:
        return not_modified
    detail = await sleep_run_detail.build(settings.memory_path, drain_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Not a run")
    return detail


@router.get("/sleep/queue", response_model=SleepQueueResponse)
async def sleep_queue(
    origin: str | None = Query(None),
    state: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    settings: Settings = Depends(get_settings),
):
    """What is waiting, one row per conversation, with where it stands in the running run —
    ``waiting | reading | read | filed | could_not_be_read | parked`` and, for a failure, a
    reason enum and how many tries it has had. Frontmatter only (the bank index, never a body),
    bounded (``limit`` ≤ 200); the app refetches it when the run's counts move, not per tick."""
    ds = active_drain(get_sleep_state(), settings)
    parked = sleep_parked.valid(settings.memory_path)
    frozen = set(ds.frozen_ids) if ds is not None else set()
    in_batch = set(ds.live.ids) if ds is not None and not ds.batch_counted else set()
    rows: list[SleepQueueItem] = []
    for f in bank_index.files(settings.memory_path, "episodes"):
        fm = f.frontmatter
        ep_id = str(fm.get("id", f.stem))
        processed = bool(fm.get("processed", False))
        if processed and (ds is None or ep_id not in ds.filed_ids):
            continue
        o = str(fm.get("origin") or _derive_origin(fm.get("source")))
        st, reason, attempts = "waiting", None, 0
        if ds is not None and (ep_id in frozen or ep_id in ds.filed_ids):
            st, reason, attempts = sleep_drain.episode_state(ds, ep_id)
        elif ep_id in parked:
            st, reason, attempts = "parked", parked[ep_id].get("reason"), int(parked[ep_id].get("attempts") or 0)
        if origin and o != origin:
            continue
        if state and st != state:
            continue
        rows.append(SleepQueueItem(
            id=ep_id, timestamp=str(fm.get("timestamp", "") or ""), origin=o,
            title=(str(fm["title"]) if fm.get("title") else None), state=st, reason=reason,
            attempts=attempts,
            batch=ds.live.index if (ds is not None and ep_id in in_batch) else None,
        ))
    rows.sort(key=lambda r: _episode_sort_key({"timestamp": r.timestamp, "id": r.id}))
    return SleepQueueResponse(total=len(rows), offset=offset, items=rows[offset:offset + limit])


@router.get("/sleep/episodes", response_model=list[EpisodeQueueItem])
async def sleep_episodes(settings: Settings = Depends(get_settings)):
    """Return every episode (queued + processed), sorted by frontmatter timestamp."""
    items: list[EpisodeQueueItem] = []
    roots = episode_copy.folder_roots(settings.memory_path)
    for ep in list_all_episodes(settings.memory_path):
        body = (ep.get("body") or "").lstrip()
        preview = body[:200].strip()
        fm = ep.get("frontmatter") or {}
        kind, value = episode_copy.copy_target(fm, ep.get("body") or "", roots)
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
                copy_kind=kind,
                copy_value=value or ep["id"],
                changed_at=episode_copy.changed_at(fm) or ep.get("timestamp", ""),
            )
        )
    return items


def _run_options_response(settings: Settings) -> SleepRunOptions:
    opts = sleep_run_prefs.load(get_registry(settings))
    return SleepRunOptions(
        batch_size=sleep_run_prefs.effective_batch_size(opts, settings),
        batch_size_choices=list(sleep_run_prefs.BATCH_CHOICES),
        continue_after_reset=opts.continue_after_reset,
        reserve_pct=opts.reserve_pct,
        reserve_choices=list(sleep_run_prefs.RESERVE_CHOICES),
    )


@router.get("/sleep/run-options", response_model=SleepRunOptions)
async def get_run_options(settings: Settings = Depends(get_settings)):
    """Reading options: how often progress is saved, the opt-in continue-after-reset switch
    (TODO ruling 15, off) and the reserve line (off). Not a Store domain — no ETag."""
    return _run_options_response(settings)


@router.put("/sleep/run-options", response_model=SleepRunOptions)
async def put_run_options(body: SleepRunOptionsUpdate, settings: Settings = Depends(get_settings)):
    """Merge the fields sent; validate against the choice lists (422 otherwise). Never 409s: a
    run snapshots its options when it starts, so a change applies to the next start or Continue."""
    sent = body.model_fields_set
    changes: dict = {}
    if "batch_size" in sent:
        if body.batch_size not in sleep_run_prefs.BATCH_CHOICES:
            raise HTTPException(status_code=422, detail=f"batchSize must be one of {list(sleep_run_prefs.BATCH_CHOICES)}")
        changes["batch_size"] = body.batch_size
    if "continue_after_reset" in sent:
        if body.continue_after_reset is None:
            raise HTTPException(status_code=422, detail="continueAfterReset must be true or false")
        changes["continue_after_reset"] = body.continue_after_reset
    if "reserve_pct" in sent:
        if body.reserve_pct is not None and body.reserve_pct not in sleep_run_prefs.RESERVE_CHOICES:
            raise HTTPException(status_code=422, detail=f"reservePct must be null or one of {list(sleep_run_prefs.RESERVE_CHOICES)}")
        changes["reserve_pct"] = body.reserve_pct
    if changes:
        sleep_run_prefs.write(get_registry(settings), **changes)
    return _run_options_response(settings)


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


@router.get("/sleep/engine", response_model=SleepEngineResponse)
async def get_sleep_engine(settings: Settings = Depends(get_settings)):
    """G122 — Settings → Engines's engine & model picker: what's configured
    now, every candidate's live state, and both trigger-source previews
    (ruling 4 made visible, not hidden — see `SleepEnginePreviews`)."""
    return await sleep_engine_prefs.build_response(settings, get_registry(settings))


@router.put("/sleep/engine", response_model=SleepEngineResponse)
async def put_sleep_engine(body: SleepEngineChoice, settings: Settings = Depends(get_settings)):
    """Validates and persists the choice, then re-reads through the same
    `build_response` a GET would use — the echoed body can never drift from
    what a follow-up GET reports."""
    reg = get_registry(settings)
    pinned, source = sleep_engine_prefs.configured_choice(settings, reg)
    if source == "env" and body.mode != pinned:
        # CICADA_LLM_MODE in the environment outranks the stored choice, so a
        # write here would answer 200 and change nothing the person can see.
        raise HTTPException(status_code=409, detail=sleep_engine_prefs.env_pin_sentence(pinned))
    sleep_engine_prefs.validate_and_write(body, reg)
    return await sleep_engine_prefs.build_response(settings, reg)
