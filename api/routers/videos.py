"""G162 — the video queue and the honest state of every saved video, over HTTP.

Six routes, none of them a Store domain (like provenance and the Projects reads),
so there is no ``VersionVector`` mapping: the app's ``VideoStateCache`` keeps them in
memory and revalidates on the ``videoQueue`` / ``episodes`` / ``entities`` / ``bank``
components (the ship-together rule: the ETag and its client refresh set change
together).

* ``GET /videos/state`` — one item per saved video, with its derived state and, when
  queued, its queue row. Title, channel, thumbnail and length are **not** repeated:
  the app joins by ``mediaEntityId|url`` to the row it already holds.
* ``GET /videos/summary`` — the counts and the active batch, no items (the Sleep row
  and the Feed strip). Both come from one function (``video_state.summary_from``).
* ``PUT|DELETE /videos/queue/{key}``, ``POST /videos/queue/{key}/retry`` — one video.
* ``POST /videos/run/handoff`` — the run's one write: every selected video into the
  queue, one batch, **no cap** (P1), and the prompt to copy. All or nothing.
* ``GET /videos/run/prompt`` — the prompt, pure; with ``?count=&method=`` it previews
  before Copy and writes nothing.

**No route touches the bank** — the queue is ``$CICADA_HOME/video_queue/<bank>.json`` —
so none answers 409 while Sleep runs, and none sits under ``/capture/`` or ``/sources/``
(the demo gate is for bank writes; queueing in the demo bank is a picture of the flow,
and no agent can claim from it). Bearer auth like every route.

Nothing here fetches a video, a caption, a frame or a stream.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import sync_service, video_prompt, video_queue, video_state

router = APIRouter()

_COMPONENTS = ("entities", "episodes", "sources", "videoQueue")


def _now() -> datetime:
    """The one clock every route here reads — a seam so a test pins the instant."""
    return datetime.now(timezone.utc)


def _holding() -> bool:
    from api.services import sleep_cycle

    return sleep_cycle.is_writing()


def browser_clause() -> str | None:
    """H1: the hand-off carries the person's browser permission as an instruction only
    when the single reading permission is on — read per request, never cached (the
    file is read on every call by design). A backend without the reading branch has
    no such switch, and the clause stays off. No host is consulted (P3)."""
    try:
        from api.services import reading_settings

        return video_prompt.BROWSER_CLAUSE if reading_settings.agent_enabled() else None
    except Exception:  # noqa: BLE001 — ImportError, or an unreadable settings file
        return None


def _view(memory_path):
    """Everything both reads need, computed once: saved videos, records, the settled
    queue (in memory) and the active batch."""
    now = _now()
    saved = video_state.saved_videos(memory_path)
    records = video_state.watch_records(memory_path)
    rows, batches = video_queue.view(memory_path, now, records=lambda: records, holding=_holding)
    rows = [r for r in rows if r["key"] in saved]
    batch = video_queue.batch_view(rows, batches, saved)
    return saved, records, rows, batch, video_queue.next_change_at(memory_path, now)


def _state(memory_path) -> dict:
    saved, records, rows, batch, next_change = _view(memory_path)
    return video_state.build(memory_path, rows, batch, saved=saved, records=records, next_change_at=next_change)


def _summary(memory_path) -> dict:
    body = _state(memory_path)
    out = {**body["queue"]}
    if "nextChangeAt" in body:
        out["nextChangeAt"] = body["nextChangeAt"]
    out["shape"] = video_state.VIDEO_SHAPE
    return out


def _etag(memory_path, name: str) -> str:
    return sync_service.etag_for(memory_path, *_COMPONENTS, extra=f"{name}|{video_state.VIDEO_SHAPE}|{int(bool(_holding()))}")


@router.get("/videos/state")
async def get_video_state(request: Request, response: Response, settings: Settings = Depends(get_settings)):
    memory_path = settings.memory_path
    etag = _etag(memory_path, "state")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    return await run_in_threadpool(_state, memory_path)


@router.get("/videos/summary")
async def get_video_summary(request: Request, response: Response, settings: Settings = Depends(get_settings)):
    memory_path = settings.memory_path
    etag = _etag(memory_path, "summary")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    return await run_in_threadpool(_summary, memory_path)


class QueueBody(BaseModel):
    want: str


def _item(memory_path, key: str) -> dict:
    """The one item the person just changed, in the ``/videos/state`` shape."""
    body = _state(memory_path)
    return next((i for i in body["items"] if i["key"] == key), {"key": key})


def _refuse(exc: video_queue.QueueError, *, single: bool = False):
    if isinstance(exc, video_queue.NotAVideo):
        # One video's route: a plain 404. A hand-off names every unknown key (all or nothing): a 422.
        if single:
            raise HTTPException(404, "not a saved video")
        raise HTTPException(422, {"message": "not saved videos", "keys": exc.keys})
    raise HTTPException(422, str(exc))


def _put(memory_path, key: str, want: str) -> dict:
    video_queue.put(memory_path, key, want, holding=_holding)
    return _item(memory_path, key)


@router.put("/videos/queue/{key}")
async def put_video_queue(key: str, body: QueueBody, settings: Settings = Depends(get_settings)):
    try:
        return await run_in_threadpool(_put, settings.memory_path, key, body.want)
    except video_queue.QueueError as exc:
        _refuse(exc, single=True)


@router.delete("/videos/queue/{key}")
async def delete_video_queue(key: str, settings: Settings = Depends(get_settings)):
    removed = await run_in_threadpool(video_queue.remove, settings.memory_path, key, holding=_holding)
    return {"removed": removed}


def _retry(memory_path, key: str) -> dict | None:
    if video_queue.retry(memory_path, key, holding=_holding) is None:
        return None
    return _item(memory_path, key)


@router.post("/videos/queue/{key}/retry")
async def retry_video_queue(key: str, settings: Settings = Depends(get_settings)):
    item = await run_in_threadpool(_retry, settings.memory_path, key)
    if item is None:
        raise HTTPException(404, "that video has nothing to try again")
    return item


class HandoffItem(BaseModel):
    key: str
    want: str


class HandoffBody(BaseModel):
    items: list[HandoffItem]
    method: str = "auto"


def _handoff(memory_path, body: HandoffBody) -> dict:
    batch, queued = video_queue.handoff(memory_path, [i.model_dump() for i in body.items], body.method,
                                        holding=_holding)
    prompt = video_prompt.build(queued, body.method, browser_clause=browser_clause(),
                                method_clause=video_prompt.method_clause(memory_path))
    return {"batch": batch, "prompt": prompt}


@router.post("/videos/run/handoff")
async def post_video_handoff(body: HandoffBody, settings: Settings = Depends(get_settings)):
    try:
        return await run_in_threadpool(_handoff, settings.memory_path, body)
    except video_queue.QueueError as exc:
        _refuse(exc)


def _prompt(memory_path, count: Optional[int], method: Optional[str]) -> dict | None:
    saved, _records, rows, batch, _ = _view(memory_path)
    if count is None and batch is None and method is None:
        return None
    waiting = count if count is not None else sum(1 for r in rows if r["state"] == "queued")
    chosen = method if method is not None else (batch or {}).get("method", "auto")
    if chosen not in video_queue.METHODS:
        raise video_queue.QueueError("method must be auto, captions or link")
    return {"prompt": video_prompt.build(waiting, chosen, browser_clause=browser_clause(),
                                         method_clause=video_prompt.method_clause(memory_path))}


@router.get("/videos/run/prompt")
async def get_video_prompt(count: Optional[int] = Query(None, ge=0), method: Optional[str] = Query(None),
                           settings: Settings = Depends(get_settings)):
    """Pure. With ``count``/``method`` it is the preview shown before Copy (writes
    nothing); with neither it is the active batch's prompt for "Copy the prompt again"
    (404 when there is no batch)."""
    try:
        out = await run_in_threadpool(_prompt, settings.memory_path, count, method)
    except video_queue.QueueError as exc:
        _refuse(exc)
    if out is None:
        raise HTTPException(404, "there is no video run to copy a prompt for")
    return out
