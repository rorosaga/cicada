from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends

from api.config import Settings, get_settings
from api.models.schemas import SleepHistoryEntry, SleepStatusResponse, SleepTriggerResponse
from api.services import git_service
from api.services.sleep_cycle import get_sleep_state, run

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
    )


@router.get("/sleep/history", response_model=list[SleepHistoryEntry])
async def sleep_history(settings: Settings = Depends(get_settings)):
    return await git_service.get_sleep_history(settings.memory_path)
