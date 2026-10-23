"""Activity traces (G218): the app posts what it captured; the backend keeps it sealed outside every bank.

The app is the only capturer (Screen Recording, Accessibility and Automation are the app's, never the backend's). It
posts focus spans and screenshots here; :mod:`trace_store` re-applies the policy, seals and keeps them; :mod:`trace_memory`
promotes only what the person's switches allow into the active bank (YouTube views into the watch history, a counted
day summary) in one ``user`` commit per sync (trigger ``capture/traces``).

**This Mac only.** Every route refuses a device token (403): a client machine's traces stay on it and a server never
serves them (G181). The remote listener (G135) serves only ``/mcp`` and ``/v1``, so none of these is reachable there.
No route serves traces to a model: there is no MCP tool and Ask never reads the store. Search is a POST so the query is
never in an access log, and nothing here logs a title, an address, recognized text or a query — counts only.

Writes go to ``$CICADA_HOME/traces/``, never a bank, so a demo bank does not refuse them; a promotion skips a demo bank.
"""
from __future__ import annotations

import base64
import binascii
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import auth, folder_source, trace_keys, trace_memory, trace_policy, trace_store

router = APIRouter()

ON_THIS_MAC_ONLY = "Traces stay on the Mac that recorded them; another device cannot read or send them."


def on_this_mac(request: Request) -> None:
    """403 for a device token: traces are never read from, or sent by, another machine (G218, G181)."""
    if auth.request_device(request) is not None:
        raise HTTPException(status_code=403, detail=ON_THIS_MAC_ONLY)


_LOCAL = [Depends(on_this_mac)]


class TurnOnRequest(BaseModel):
    consent_version: int


class PauseRequest(BaseModel):
    #: A zoned instant, ``until-resumed``, or null to resume.
    until: str | None = None


class SyncRequest(BaseModel):
    spans: list[dict] = Field(default_factory=list)


class FrameRequest(BaseModel):
    id: str
    at: str
    bundle_id: str
    app: str = ""
    host: str = ""
    span_id: str = ""
    width: int
    height: int
    private: bool = False
    #: The app found this app registered to open https: links (B3): a browser, kept only through a verified tab.
    browser: bool = False
    image: str
    text: str = ""


class SearchRequest(BaseModel):
    query: str


class ForgetRequest(BaseModel):
    minutes: int = 15


class WipeRequest(BaseModel):
    confirm: bool = False


def _store() -> trace_store.TraceStore:
    return trace_store.store()


def _answer(values: dict) -> dict:
    s = _store()
    return {"settings": values, "status": s.status(), "policy": trace_policy.served(),
            "consent_version": trace_store.CONSENT_VERSION}


def _refuse(exc: Exception):
    if isinstance(exc, trace_store.TracesOff):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, trace_store.PayloadError):
        raise HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, trace_keys.KeyRefused):
        raise HTTPException(status_code=423, detail=str(exc))
    raise exc


@router.get("/sources/traces/settings", dependencies=_LOCAL)
async def get_traces_settings():
    """The person's choices, the store's state, and the lists the app applies before anything leaves it."""
    try:
        return _answer(await run_in_threadpool(_store().settings))
    except trace_keys.KeyRefused as exc:
        _refuse(exc)


@router.put("/sources/traces/settings", dependencies=_LOCAL)
async def put_traces_settings(patch: dict):
    try:
        return _answer(await run_in_threadpool(_store().update, patch))
    except (trace_store.TracesOff, trace_store.PayloadError, trace_keys.KeyRefused) as exc:
        _refuse(exc)


@router.post("/sources/traces/on", dependencies=_LOCAL)
async def turn_traces_on(req: TurnOnRequest):
    """The consent sheet's Turn on. Refused for a sheet version the person did not see."""
    try:
        return _answer(await run_in_threadpool(_store().turn_on, req.consent_version))
    except (trace_store.PayloadError, trace_keys.KeyRefused) as exc:
        _refuse(exc)


@router.post("/sources/traces/off", dependencies=_LOCAL)
async def turn_traces_off():
    try:
        return _answer(await run_in_threadpool(_store().turn_off))
    except trace_keys.KeyRefused as exc:
        _refuse(exc)


@router.post("/sources/traces/pause", dependencies=_LOCAL)
async def pause_traces(req: PauseRequest):
    try:
        return _answer(await run_in_threadpool(_store().pause, req.until))
    except (trace_store.TracesOff, trace_store.PayloadError, trace_keys.KeyRefused) as exc:
        _refuse(exc)


@router.post("/sources/traces/sync", dependencies=_LOCAL)
async def sync_traces(req: SyncRequest, settings: Settings = Depends(get_settings)):
    """Closed focus spans from the app. 409 while off; paused moments are dropped; the policy is re-applied. What the
    person's switches promote lands in the active bank in one commit."""
    s = _store()
    try:
        result = await run_in_threadpool(s.add_spans, req.spans)
    except (trace_store.TracesOff, trace_store.PayloadError, trace_keys.KeyRefused) as exc:
        _refuse(exc)
    memory_path = settings.memory_path
    promoted = 0
    try:
        values = await run_in_threadpool(s.settings)
        paths = await run_in_threadpool(trace_memory.promote, memory_path, s, values, bank=memory_path.name)
        promoted = len(paths)
        if paths:
            await folder_source.commit_paths_for(memory_path, paths, subject="Activity traces",
                                                 trigger="capture/traces")
    except Exception as exc:  # noqa: BLE001 — the traces are kept; a promotion retries on the next sync
        logger.warning(f"traces promotion failed ({type(exc).__name__})")
    return {**result.as_dict(), "promoted_files": promoted}


@router.post("/sources/traces/frames", dependencies=_LOCAL)
async def add_trace_frame(req: FrameRequest):
    """One downscaled screenshot and the text the app's on-device recognizer read from it."""
    try:
        image = base64.b64decode(req.image, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="the screenshot is not base64")
    meta = req.model_dump(exclude={"image", "text"})
    try:
        fid = await run_in_threadpool(_store().add_frame, meta, image, req.text)
    except (trace_store.TracesOff, trace_store.PayloadError, trace_keys.KeyRefused) as exc:
        _refuse(exc)
    return {"id": fid}


@router.get("/sources/traces/days", dependencies=_LOCAL)
async def trace_days():
    return {"days": await run_in_threadpool(_store().days)}


@router.get("/sources/traces/timeline", dependencies=_LOCAL)
async def trace_timeline(day: str):
    try:
        the_day = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=422, detail="day is YYYY-MM-DD")
    return await run_in_threadpool(_store().timeline, the_day)


@router.post("/sources/traces/search", dependencies=_LOCAL)
async def search_traces(req: SearchRequest):
    """Titles, sites and recognized text holding every word. A POST, so the words never reach an access log."""
    return {"hits": await run_in_threadpool(_store().search, req.query)}


@router.get("/sources/traces/frames/{frame_id}", dependencies=_LOCAL)
async def trace_frame(frame_id: str):
    """One screenshot, for the app's browser — which asks the person's Touch ID before it calls this."""
    found = await run_in_threadpool(_store().frame, frame_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no such screenshot (retention may have removed it)")
    row, data = found
    media = "image/jpeg" if row.get("kind") == "jpeg" else "image/png"
    return Response(content=data, media_type=media,
                    headers={"Cache-Control": "no-store", "X-Trace-Text": "1" if row.get("text") else "0"})


@router.get("/sources/traces/frames/{frame_id}/text", dependencies=_LOCAL)
async def trace_frame_text(frame_id: str):
    found = await run_in_threadpool(_store().frame, frame_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no such screenshot (retention may have removed it)")
    row, _ = found
    return {"id": row["id"], "at": row["at"], "app": row.get("app"), "text": row.get("text") or ""}


@router.post("/sources/traces/forget", dependencies=_LOCAL)
async def forget_traces(req: ForgetRequest):
    try:
        return await run_in_threadpool(_store().forget, req.minutes)
    except trace_store.PayloadError as exc:
        _refuse(exc)


@router.post("/sources/traces/wipe", dependencies=_LOCAL)
async def wipe_traces(req: WipeRequest):
    """Every trace, every screenshot, the settings and the key, gone. What was already promoted into memory stays
    (a watched day, a summary): those are the bank's, and the sheet says so."""
    if not req.confirm:
        raise HTTPException(status_code=422, detail="wiping traces needs confirm: true")
    await run_in_threadpool(_store().wipe)
    return _answer(trace_store.DEFAULTS | {})
