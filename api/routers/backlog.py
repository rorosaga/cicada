"""G150 — a project's backlog over HTTP (R-B7, R-B8, R-B18).

Six routes over the ONE writer (`services/backlog.py`): two reads, the
person's three writes, and the importer's live path (R-B15).

The reads are fetched on demand, like the Projects reads (R-PJ7): neither is a
Store domain, so there is no `VersionVector` mapping and the ship-together
rule has nothing to pair. Both ETags fold the `backlog` component (every item
file's stamp) and `entities` (the project's name and `backlog_prefix:`), plus
`BACKLOG_SHAPE`, `git_service.AUTHOR_SHAPE` — the body carries an author kind
(the G118 rule) — and the machine zone's NAME, because `lastNoteDay` is a day
in it. Never today.

The person's writes are `Cicada-Author: user`, trigger `user/companion_app`
(an import: `user/backlog_import`), each committed alone over the item's own
file (R-B7), and every one answers 409 while Sleep runs (R-B8, the
`routers/projects.py` precedent): Sleep's `_finalize` stages with
`git add -A`, so a file written between its read and its commit would ride the
cycle's commit under a model's name. This module decides nothing about
validity — it picks the project, the author, the clock and the status code.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (BacklogImportRequest, BacklogImportResponse, BacklogItemCreate, BacklogItemModel,
                                BacklogItemPatch, BacklogItemSummary, BacklogLink, BacklogListResponse,
                                BacklogNoteCreate, BacklogNoteModel)
from api.services import backlog, backlog_import, git_service, handshake, sync_service, when

router = APIRouter()

# One write at a time in this process (the `routers/projects.py` reason): two
# quick taps would read the same file before either commit ran. Across
# processes the item file's own lock holds (`backlog._locked`).
_write_lock = asyncio.Lock()
BUSY = "Sleep is writing memory right now, try again in a moment"
TRIGGER = "user/companion_app"


def _tz() -> str:
    return handshake.local_timezone() or "UTC"


def _now() -> datetime:
    """The one clock every write here reads — a seam so tests pin a day."""
    return datetime.now(when.zone(_tz()))


def _guard() -> None:
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(409, BUSY)


def _project(memory_path, project_id: str) -> tuple[str, dict]:
    got = backlog.project_page(memory_path, project_id)
    if isinstance(got, dict):
        raise HTTPException(404, got["error"])
    return got


def _etag(memory_path, *parts: str) -> str:
    extra = "|".join(["backlog", *parts, backlog.BACKLOG_SHAPE, git_service.AUTHOR_SHAPE, _tz()])
    return sync_service.etag_for(memory_path, "backlog", "entities", extra=extra)


def _raise_for(result: dict) -> None:
    action = result.get("action")
    if action == "not_found":
        raise HTTPException(404, result.get("error") or "Not found")
    if action in ("duplicate", "exists"):
        raise HTTPException(409, result.get("error") or "That's already on the backlog")
    if action == "error":
        raise HTTPException(400, result.get("error") or "That couldn't be saved")


def _summary(item: backlog.Item, tz: str) -> BacklogItemSummary:
    kind, _provider = git_service.author_identity(item.added_by)
    return BacklogItemSummary(
        id=item.id, project=item.project, title=item.title, status=item.status, triage=item.triage,
        paid=item.paid, created=item.created, updated=item.updated, added_by=item.added_by, added_by_kind=kind,
        added_by_label=backlog.who_label(item.added_by), note_count=item.note_count,
        last_note_day=backlog.local_day(item.last_note_at, tz), last_note_by=item.last_note_by, order=item.order)


def _note(note: backlog.Note) -> BacklogNoteModel:
    """R-B6's seam: once round 4's C3 join is on `dev`, its one helper is
    called here with `(note.session, note.at)` to fill `author_model` and
    `author_effort` — never a second implementation of that join."""
    by = backlog.author_of(note)
    kind, provider = git_service.author_identity(by)
    return BacklogNoteModel(day=note.day, text=note.text, by=by, by_kind=kind, by_provider=provider,
                            by_label=note.who, at=note.at, session=note.session)


def _item(item: backlog.Item, tz: str) -> BacklogItemModel:
    return BacklogItemModel(**_summary(item, tz).model_dump(by_alias=False), description=item.description,
                            notes=[_note(n) for n in item.notes],
                            links=[BacklogLink(**link) for link in item.links], session=item.session,
                            path=item.path)


async def _commit(memory_path, paths: list[str], action: str, *, subject: str = "Backlog update",
                  trigger: str = TRIGGER) -> None:
    if not paths:
        return
    message = backlog.commit_message(paths, action=action, subject=subject, trigger=trigger,
                                     day=_now().date().isoformat())
    try:
        await git_service.commit_paths(memory_path, message, sorted(set(paths)))
    except Exception as exc:  # noqa: BLE001 — the write stands; a later writer's commit picks it up
        logger.warning(f"backlog commit skipped: {type(exc).__name__}")


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/backlog", response_model=BacklogListResponse)
async def list_backlog(project_id: str, request: Request, response: Response, status: Optional[str] = None,
                       settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    stem, fm = _project(mp, project_id)
    if status is not None and status not in backlog.STATUSES:
        raise HTTPException(400, f"status is one of {', '.join(backlog.STATUSES)}")
    etag = _etag(mp, "list", stem, status or "")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    tz = _tz()

    def build() -> BacklogListResponse:
        items = backlog.list_items(mp, stem)
        shown = [i for i in items if status is None or i.status == status]
        return BacklogListResponse(project=stem, project_name=str(fm.get("name") or stem),
                                   prefix=backlog.prefix_for(mp, stem, fm), counts=backlog.counts(items),
                                   items=[_summary(i, tz) for i in shown], tz_name=tz)

    return await run_in_threadpool(build)


@router.get("/backlog/{project_id}/{item_id}", response_model=BacklogItemModel)
async def get_backlog_item(project_id: str, item_id: str, request: Request, response: Response,
                           settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    iid = backlog.normalize_id(item_id)
    if iid is None:
        raise HTTPException(404, f"{item_id!r} isn't an item id")
    etag = _etag(mp, "item", stem, iid)
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    item = await run_in_threadpool(backlog.get_item, mp, stem, iid)
    if item is None:
        raise HTTPException(404, f"No {iid} on this project's backlog")
    return _item(item, _tz())


# --------------------------------------------------------------------------- #
# the person's writes
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/backlog", response_model=BacklogItemModel)
async def add_backlog_item(project_id: str, body: BacklogItemCreate, settings: Settings = Depends(get_settings)):
    _guard()
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    async with _write_lock:
        result = await run_in_threadpool(
            backlog.add_item, mp, project=stem, title=body.title, description=body.description,
            triage=body.triage, paid=body.paid, author=backlog.USER, now=_now(), tz_name=_tz())
        _raise_for(result)
        await _commit(mp, result["paths"], "created")
    return _item(result["item"], _tz())


@router.post("/backlog/{project_id}/{item_id}/notes", response_model=BacklogItemModel)
async def add_backlog_note(project_id: str, item_id: str, body: BacklogNoteCreate,
                           settings: Settings = Depends(get_settings)):
    _guard()
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    async with _write_lock:
        result = await run_in_threadpool(
            backlog.add_note, mp, project=stem, item=item_id, note=body.note, status=body.status,
            author=backlog.USER, now=_now(), tz_name=_tz())
        _raise_for(result)
        await _commit(mp, result["paths"], "updated")
    return _item(result["item"], _tz())


@router.patch("/backlog/{project_id}/{item_id}", response_model=BacklogItemModel)
async def change_backlog_item(project_id: str, item_id: str, body: BacklogItemPatch,
                              settings: Settings = Depends(get_settings)):
    _guard()
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    links = None if body.links is None else [link.model_dump(by_alias=False) for link in body.links]
    async with _write_lock:
        result = await run_in_threadpool(
            backlog.update_item, mp, project=stem, item=item_id, title=body.title, status=body.status,
            triage=body.triage, paid=body.paid, links=links, author=backlog.USER, now=_now(), tz_name=_tz())
        _raise_for(result)
        await _commit(mp, result["paths"], "updated")
    return _item(result["item"], _tz())


@router.post("/projects/{project_id}/backlog/import", response_model=BacklogImportResponse)
async def import_backlog(project_id: str, body: BacklogImportRequest, settings: Settings = Depends(get_settings)):
    """R-B15's live path: one `Backlog import` commit as the person, or none —
    an id already on the backlog is skipped, so a second post changes nothing."""
    _guard()
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    if len(body.markdown) > backlog_import.MAX_CHARS:
        raise HTTPException(413, "That file is too large to import")
    async with _write_lock:
        report = await run_in_threadpool(
            backlog_import.import_markdown, mp, project=stem, text=body.markdown, prefix=body.prefix,
            author=backlog.USER, now=_now(), tz_name=_tz())
        if report.error:
            raise HTTPException(400, report.error)
        await _commit(mp, report.paths, "created", subject="Backlog import", trigger=backlog_import.IMPORT_TRIGGER)
    return BacklogImportResponse(created=report.created, skipped=report.skipped, failed=report.failed)
