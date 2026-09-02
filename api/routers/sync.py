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
            # Devin PR #27 round 1, finding 4: the key used to omit
            # `volume_pct`/`age_pct`/`has_run_before` entirely, and
            # `hours_since_last_cycle` (a continuously-increasing float, so
            # it can't go in RAW without firing an event every single tick
            # and defeating the whole point of change-gating). When volume
            # dominates `rested_pct = 100 - max(volume_pct, age_pct)`, `age_pct`
            # can move — or `hours_since_last_cycle` can cross a UI threshold
            # (the Swift side's 48h "hungry" read) — with NOTHING in the old
            # key changing, so no event ever fires and a connected client
            # holds stale data indefinitely. Every discrete debt field the
            # payload carries is now in the key exactly (no approximation
            # needed — they're already coarse integers/booleans); the one
            # continuous field is rounded to 0.1h (6-minute) buckets, which
            # bounds event frequency to something sane while guaranteeing
            # ANY threshold a client might read off it — 48h or otherwise —
            # is crossed within one bucket's width of the real moment,
            # rather than hardcoding one specific threshold value here.
            hours_bucket = (
                round(debt.hours_since_last_cycle, 1)
                if debt.hours_since_last_cycle is not None else None
            )
            sleep_key = (
                state.status, state.cycle_id, state.stage, state.progress,
                debt.rested_pct, debt.volume_pct, debt.age_pct, debt.has_run_before,
                debt.unprocessed_count, progress, hours_bucket,
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
