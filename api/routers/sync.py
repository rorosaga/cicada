"""Version vector + SSE change stream for the app's sync engine (G58)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import sync_service, sync_status, sync_ticker
from api.services.sleep_cycle import get_sleep_state

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
            # G106 amendment: Rested % and Progress % are SSE-driven, computed fresh every tick; the debt comes from
            # the same shared tick as the version (audit A10). The event is built in one place (`sync_status`), so
            # the home's published status frame (G132) carries the same keys by construction.
            sleep_key, sleep_payload = sync_status.sleep_event(state, tick.debt, settings.memory_path)
            if sleep_key != last_sleep:
                last_sleep = sleep_key
                yield _event("sleep", sleep_payload)
            if since_ping >= PING_SECONDS:
                yield "event: ping\ndata: {}\n\n"
                since_ping = 0.0
            await asyncio.sleep(next_poll)
            since_ping += next_poll

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- G132 phase 1 (ruling 51): the home publishes its log -------------------------------------------------------------
#
# Off by default (`sync_publish`): off, every route below but the switch answers a plain 404 and nothing is written.
# A full device token or the server's own token; a capture-only device is refused by `require_token` (its exact route
# list), the switch's writes are the server's own token only (`auth.MASTER_ONLY_WRITE_PREFIXES`). A demo bank is never
# published. The log carries seq, sha, parent and time only; subjects and paths travel inside the pack alone.


class PublishSwitch(BaseModel):
    publish: bool


def _published_bank(settings: Settings) -> Path:
    from api.services import sync_publish

    if not sync_publish.publishable(settings.memory_path):
        raise HTTPException(status_code=404)
    from api.services import capture_commit

    capture_commit.resume(settings.memory_path)   # records a previous process left are committed once settled
    return settings.memory_path


def _bank_id() -> str | None:
    from api.services import bank_registry

    pin = bank_registry.pinned_bank()
    return pin.id if pin is not None else None


def _refused(exc: Exception) -> JSONResponse:
    from api.services import sync_log

    if isinstance(exc, sync_log.HistoryRewritten):
        return JSONResponse(status_code=409, content=exc.body())
    return JSONResponse(status_code=503, content={
        "code": "unavailable", "detail": "This memory's history could not be read just now; nothing was changed."})


async def _fresh_primer(memory_path: Path, settings: Settings) -> None:
    """A replica never serves an older primer than the home's `_state.md`: bring it current before the log is read
    (it commits alone, and is skipped while Sleep holds the pages — the run's tail refreshes it then)."""
    from api.services import state_dictionary

    await state_dictionary.refresh_admitted(memory_path, settings)


def _switch_body(settings: Settings) -> dict:
    from api.services import sync_log, sync_publish

    on = sync_publish.enabled()
    body = {"publish": on, "source": sync_publish.source(), "demo": False, "log": None}
    if on:
        from api.services import demo_guard

        body["demo"] = demo_guard.is_demo(settings.memory_path)
        if sync_publish.publishable(settings.memory_path):
            body["log"] = sync_log.state(settings.memory_path)
    return body


@router.get("/publish")
async def get_publish(settings: Settings = Depends(get_settings)):
    return await run_in_threadpool(_switch_body, settings)


@router.put("/publish")
async def put_publish(body: PublishSwitch, settings: Settings = Depends(get_settings)):
    from api.services import sync_publish

    await run_in_threadpool(sync_publish.set_enabled, body.publish)
    return await run_in_threadpool(_switch_body, settings)


@router.post("/publish/from-here")
async def publish_from_here(settings: Settings = Depends(get_settings)):
    """The person's "publish from here" after a rewritten history (51e3): this history is published from now on, and
    replicas copy the bank again."""
    from api.services import sync_log

    memory_path = _published_bank(settings)
    try:
        head = await run_in_threadpool(sync_log.publish_from_here, memory_path)
    except (sync_log.HistoryRewritten, sync_log.Unavailable) as exc:
        return _refused(exc)
    return {"bankId": _bank_id(), "head": head.wire()}


@router.get("/log")
async def get_log(since: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=1000),
                  settings: Settings = Depends(get_settings)):
    from api.services import sync_log

    memory_path = _published_bank(settings)
    await _fresh_primer(memory_path, settings)
    try:
        head, entries, more = await run_in_threadpool(sync_log.since, memory_path, since, limit)
    except (sync_log.HistoryRewritten, sync_log.Unavailable) as exc:
        return _refused(exc)
    return {"bankId": _bank_id(), "head": head.wire(), "entries": entries, "more": more}


@router.get("/pack")
async def get_pack(have: str | None = Query(None, max_length=64), settings: Settings = Depends(get_settings)):
    from api.services import sync_log, sync_pack

    memory_path = _published_bank(settings)
    try:
        pack = await run_in_threadpool(sync_pack.build, memory_path, have)
    except sync_pack.UnknownBase:
        return JSONResponse(status_code=404, content={
            "code": "unknown_base", "detail": "That commit is not one this memory published; ask without `have`."})
    except sync_pack.TooLarge:
        return JSONResponse(status_code=413, content={
            "code": "too_large", "detail": "This memory's history is larger than one pack may be."})
    except (sync_log.HistoryRewritten, sync_log.Unavailable) as exc:
        return _refused(exc)
    headers = {"X-Cicada-Seq": str(pack.seq), "X-Cicada-Head": pack.sha, "X-Cicada-Bank-Id": _bank_id() or ""}
    if pack.path is None:
        return Response(status_code=204, headers=headers)
    return FileResponse(pack.path, media_type="application/x-git-bundle", headers=headers,
                        background=BackgroundTask(pack.cleanup))


@router.get("/status")
async def get_status(settings: Settings = Depends(get_settings)):
    memory_path = _published_bank(settings)
    await _fresh_primer(memory_path, settings)
    tick = await sync_ticker.current(memory_path, settings, max_age=SHARED_TICK_SECONDS)
    return await run_in_threadpool(sync_status.frame, memory_path, settings, get_sleep_state(), tick.debt,
                                   bank_id=_bank_id())
