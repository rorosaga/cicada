"""Activity traces (G218): the app posts what it captured; the backend keeps it sealed outside every bank.

The app is the only capturer (Screen Recording, Accessibility and Automation are the app's, never the backend's). It
posts focus spans and screenshots here; :mod:`trace_store` re-applies the policy, seals and keeps them; :mod:`trace_memory`
promotes only what the person's switches allow into the active bank (what they watched and read on any site, the
counted day digest) in one ``user`` commit per sync (trigger ``capture/traces``). The page reads its days as cards,
deletes what the person picks, previews the digest Sleep would read, and takes back what traces added (one commit,
with Undo) — every route here, nothing on another door.

**This Mac only.** Every route refuses a device token (403): a client machine's traces stay on it and a server never
serves them (G181). The remote listener (G135) serves only ``/mcp`` and ``/v1``, so none of these is reachable there.
No route serves traces to a model: there is no MCP tool and Ask never reads the store. Search is a POST so the query is
never in an access log, and nothing here logs a title, an address, recognized text or a query — counts only.

Writes go to ``$CICADA_HOME/traces/``, never a bank, so a demo bank does not refuse them; a promotion skips a demo bank.
"""
from __future__ import annotations

import base64
import binascii
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import auth, folder_source, trace_keys, trace_memory, trace_policy, trace_store, write_admission

router = APIRouter()

ON_THIS_MAC_ONLY = "Traces stay on the Mac that recorded them; another device cannot read or send them."


def on_this_mac(request: Request) -> None:
    """403 for a device token: traces are never read from, or sent by, another machine (G218, G181)."""
    if auth.request_device(request) is not None:
        raise HTTPException(status_code=403, detail=ON_THIS_MAC_ONLY)


_LOCAL = [Depends(on_this_mac)]


class TurnOnRequest(BaseModel):
    consent_version: int
    #: The sheet the app actually displayed (its own constant); absent from an app before 2026-10-28, which showed 1.
    displayed_version: int | None = None


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
    #: Every connected screen (2026-10-28): this frame is screen ``display`` of ``displays`` at that moment.
    display: int = 0
    displays: int = 0


class SearchRequest(BaseModel):
    query: str


class ForgetRequest(BaseModel):
    minutes: int = 15


class WipeRequest(BaseModel):
    confirm: bool = False


class DeleteRequest(BaseModel):
    day: str
    spans: list[str] = Field(default_factory=list, max_length=5000)
    frames: list[str] = Field(default_factory=list, max_length=5000)
    #: The whole day: every span and screenshot filed under it.
    all: bool = False


class UndoRemovalRequest(BaseModel):
    removal_id: str


SLEEP_HOLDS = "Sleep is writing your memory right now — try again in a moment."


def _sleep_holds() -> HTTPException:
    return HTTPException(status_code=409, detail=SLEEP_HOLDS)


_admitted = write_admission.route(refuse=_sleep_holds)


def _day(raw: str | None, default: date | None = None) -> date:
    if not raw and default is not None:
        return default
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise HTTPException(status_code=422, detail="day is YYYY-MM-DD")


def _store() -> trace_store.TraceStore:
    return trace_store.store()


def _answer(values: dict) -> dict:
    s = _store()
    # The removals' claim ids are Undo's (``/added`` lists them by count); the settings answer stays the person's
    # choices.
    shown = {k: v for k, v in values.items() if k != "removals"}
    return {"settings": shown, "status": s.status(), "policy": trace_policy.served(),
            "consent_version": trace_store.CONSENT_VERSION,
            "all_screens_consent": trace_store.ALL_SCREENS_CONSENT}


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
        return _answer(await run_in_threadpool(lambda: _store().turn_on(req.consent_version,
                                                                         displayed_version=req.displayed_version)))
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
    return await run_in_threadpool(_store().timeline, _day(day))


@router.get("/sources/traces/day-cards", dependencies=_LOCAL)
async def trace_day_cards():
    """The page's days, newest first: counts, the screens connected, and the id of the screenshot that stands for the
    day (its pixels stay behind Touch ID, fetched through ``/frames/{id}`` like any other)."""
    return {"days": await run_in_threadpool(_store().day_cards)}


@router.post("/sources/traces/delete", dependencies=_LOCAL)
async def delete_traces(req: DeleteRequest):
    """Delete what the person picked from one day — spans (with the screenshots taken of them), screenshots, or the
    whole day. Never the bank: what already joined memory stays."""
    the_day = _day(req.day)
    if not req.all and not req.spans and not req.frames:
        raise HTTPException(status_code=422, detail="say what to delete: spans, frames, or all")
    return await run_in_threadpool(_store().delete, the_day, spans=req.spans, frames=req.frames, whole_day=req.all)


@router.get("/sources/traces/preview", dependencies=_LOCAL)
async def preview_digest(day: str | None = None, settings: Settings = Depends(get_settings)):
    """Exactly the digest Sleep would read for a day (yesterday by default), counted here with no model — shown
    before "Learn from my day" is on, so turning it on is informed. Reads the bank only for the person's projects."""
    yesterday = trace_store.local_day(datetime.now(timezone.utc)) - timedelta(days=1)
    return await run_in_threadpool(trace_memory.preview, settings.memory_path, _store(), _day(day, yesterday))


@router.get("/sources/traces/added", dependencies=_LOCAL)
async def traces_added(settings: Settings = Depends(get_settings)):
    """What traces added to memory: the open beliefs and progress notes whose only evidence is a day digest, and the
    removals that can still be undone."""
    out = await run_in_threadpool(trace_memory.added, settings.memory_path)
    values = await run_in_threadpool(_store().settings)
    out["removals"] = [{"id": r.get("id"), "day": r.get("day"), "count": len(r.get("items") or [])}
                       for r in values.get("removals") or [] if isinstance(r, dict)]
    return out


@router.post("/sources/traces/remove-from-memory", dependencies=_LOCAL)
@_admitted
async def remove_from_memory(settings: Settings = Depends(get_settings)):
    """Take back everything traces added — every open belief and progress note whose only evidence is a day digest —
    as ONE commit, undoable (``…/remove-from-memory/undo``). The digests themselves stay: they are what was read."""
    mp = settings.memory_path
    try:
        result = await run_in_threadpool(trace_memory.remove, mp, _store())
    except (trace_memory.NoUndoPossible, trace_store.TracesOff) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if result["paths"]:
        await folder_source.commit_paths_for(mp, result["paths"], subject="Removed from memory what traces added",
                                             trigger="person/traces-remove")
    return {"removal_id": result["removal_id"], "removed": result["removed"]}


@router.post("/sources/traces/remove-from-memory/undo", dependencies=_LOCAL)
@_admitted
async def undo_remove_from_memory(req: UndoRemovalRequest, settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    try:
        result = await run_in_threadpool(trace_memory.undo, mp, _store(), req.removal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="nothing to undo: that removal is not known here")
    if result["paths"]:
        await folder_source.commit_paths_for(mp, result["paths"], subject="Put back what traces added",
                                             trigger="person/traces-remove-undone")
    return {"restored": result["restored"]}


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
    (a watched or read day, a digest): those are the bank's, and the sheet says so."""
    if not req.confirm:
        raise HTTPException(status_code=422, detail="wiping traces needs confirm: true")
    await run_in_threadpool(_store().wipe)
    return _answer(trace_store.with_aliases(dict(trace_store.DEFAULTS)))
