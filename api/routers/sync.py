"""Version vector + SSE change stream for the app's sync engine (G58)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import sleep_cycle, sleep_drain, sleep_paused, sync_service, sync_ticker
from api.services.sleep_cycle import get_sleep_state, progress_pct

router = APIRouter(prefix="/sync")
POLL_SECONDS = 1.0
# Keep-alive cadence for the SSE stream. This MUST stay comfortably below the
# companion app's SSE idle timeout (`APIClient.syncEventLines` sets
# `timeoutInterval = 3600`, an *idle* timeout): a silent stream longer than
# that interval is torn down client-side and the app falls back to polling.
# It must also stay below any proxy's idle timeout if one is ever put in front.
PING_SECONDS = 15.0
# A tick younger than this is shared with every other subscriber of the bank (audit A10): below POLL_SECONDS, so
# each stream still sees a fresh computation every poll.
SHARED_TICK_SECONDS = 0.9 * POLL_SECONDS


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
            # Audit A10: one version + debt computation per bank per tick, shared by every subscriber, off the loop.
            tick = await sync_ticker.current(settings.memory_path, settings, max_age=SHARED_TICK_SECONDS)
            # Phase-lock onto the shared tick: a stream handed a tick computed `age` seconds ago polls again when it
            # is POLL_SECONDS old, so every stream of a bank converges on one computation per second and none
            # sees a change later than it would have alone (audit A10 review).
            next_poll = sync_ticker.next_poll_delay(tick, POLL_SECONDS)
            info = tick.info
            if info.version != last:
                last = info.version
                yield _event("version", {"version": info.version, "components": info.components})
                since_ping = 0.0
            state = get_sleep_state()
            # G106 amendment: Rested % and Progress % are both "SSE-driven,
            # continuous" — computed fresh every tick alongside the existing
            # status fields so the mascot screen never needs its own poll
            # loop just to watch these two numbers move. The debt comes from
            # the same shared tick as the version (audit A10): one
            # `sleep_debt.compute` per bank per second, whatever the number
            # of streams.
            debt = tick.debt
            progress = progress_pct(state)
            # Sleep page v5: the run of THIS bank only (a lingering one of another is hidden), the
            # paused record from its stat-keyed cache, and the drain's compact block with the live
            # arrival count from the debt this tick already computed — no directory scan per tick.
            ds = state.drain
            if ds is not None and getattr(ds, "memory_path", None) not in (None, settings.memory_path):
                ds = None
            drain_sse = sleep_drain.to_sse(ds, debt.unprocessed_count)
            # G177 — the write window the app's controls follow; it flips between batches with no status change.
            writing = sleep_cycle.writing_of(state)
            paused = (None if state.status == "running" and not getattr(state, "tail_only", False)
                      else sleep_paused.get_paused(settings.memory_path))
            paused_sse = ({
                "runId": paused.get("run_id"), "reason": paused.get("reason"),
                "engineKind": (paused.get("engine_kind") or "needs_fix") if paused.get("reason") == "engine" else None,
                "autoArmed": bool((paused.get("auto_continue") or {}).get("armed")),
                "autoLeft": (paused.get("auto_continue") or {}).get("left"),
            } if paused else None)
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
                # G125 R3: `progress` is an integer PERCENT that can sit
                # still for many episodes on a big queue (1/300 rounds to
                # 0% same as 0/300) — the study list needs a per-episode
                # tick, so the change key includes the raw counter too.
                state.stage1_progress,
                # A person-started run's batch / filed count moves between stage ticks.
                drain_sse and tuple(drain_sse.items()),
                # A pause appears, is armed or is cleared without any status change (Sleep page v5).
                paused_sse and tuple(paused_sse.items()),
                debt.parked_count,
                writing,
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
                    "queueByOrigin": dict(state.queue_by_origin),
                    "readByOrigin": dict(state.read_by_origin),
                    "drain": drain_sse,
                    "parkedCount": debt.parked_count,
                    "readableCount": debt.readable_count,
                    "paused": paused_sse,
                    "writing": writing,
                })
            if since_ping >= PING_SECONDS:
                yield "event: ping\ndata: {}\n\n"
                since_ping = 0.0
            await asyncio.sleep(next_poll)
            since_ping += next_poll

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
