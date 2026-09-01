"""Version vector + SSE change stream for the app's sync engine (G58)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import sleep_debt, sync_service
from api.services.sleep_cycle import get_sleep_state, progress_pct

router = APIRouter(prefix="/sync")
POLL_SECONDS = 1.0
# Keep-alive cadence for the SSE stream. This MUST stay comfortably below the
# companion app's SSE idle timeout (`APIClient.syncEventLines` sets
# `timeoutInterval = 3600`, an *idle* timeout): a silent stream longer than
# that interval is torn down client-side and the app falls back to polling.
# It must also stay below any proxy's idle timeout if one is ever put in front.
PING_SECONDS = 15.0


@router.get("/version")
async def get_version(settings: Settings = Depends(get_settings)):
    info = await run_in_threadpool(sync_service.version, settings.memory_path, get_sleep_state())
    return {"version": info.version, "components": info.components}


def _event(name: str, payload) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


@router.get("/events")
async def events(settings: Settings = Depends(get_settings)):
    async def stream():
        last = None
        last_sleep = None
        since_ping = 0.0
        while True:
            info = await run_in_threadpool(sync_service.version, settings.memory_path, get_sleep_state())
            if info.version != last:
                last = info.version
                yield _event("version", {"version": info.version, "components": info.components})
                since_ping = 0.0
            state = get_sleep_state()
            # G106 amendment: Rested % and Progress % are both "SSE-driven,
            # continuous" — computed fresh every tick alongside the existing
            # status fields so the mascot screen never needs its own poll
            # loop just to watch these two numbers move. `sleep_debt.compute`
            # is cheap (a cached frontmatter scan + one bounded git-log read)
            # and safe on every tick per its own docstring.
            debt = await sleep_debt.compute(settings.memory_path, settings)
            progress = progress_pct(state)
            sleep_key = (
                state.status, state.cycle_id, state.stage, state.progress,
                debt.rested_pct, debt.unprocessed_count, progress,
            )
            if sleep_key != last_sleep:
                last_sleep = sleep_key
                yield _event("sleep", {
                    "status": state.status, "cycleId": state.cycle_id, "stage": state.stage,
                    "totalStages": state.total_stages, "progress": state.progress, "error": state.error,
                    "progressPct": progress,
                    "restedPct": debt.rested_pct,
                    "volumePct": debt.volume_pct,
                    "agePct": debt.age_pct,
                    "unprocessedCount": debt.unprocessed_count,
                    "hasRunBefore": debt.has_run_before,
                    "hoursSinceLastCycle": debt.hours_since_last_cycle,
                })
            if since_ping >= PING_SECONDS:
                yield "event: ping\ndata: {}\n\n"
                since_ping = 0.0
            await asyncio.sleep(POLL_SECONDS)
            since_ping += POLL_SECONDS

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
