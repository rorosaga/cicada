"""Version vector + SSE change stream for the app's sync engine (G58)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import sync_service
from api.services.sleep_cycle import get_sleep_state

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
            sleep_key = (state.status, state.cycle_id, state.stage, state.progress)
            if sleep_key != last_sleep:
                last_sleep = sleep_key
                yield _event("sleep", {"status": state.status, "cycleId": state.cycle_id, "stage": state.stage,
                                       "totalStages": state.total_stages, "progress": state.progress, "error": state.error})
            if since_ping >= PING_SECONDS:
                yield "event: ping\ndata: {}\n\n"
                since_ping = 0.0
            await asyncio.sleep(POLL_SECONDS)
            since_ping += POLL_SECONDS

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
