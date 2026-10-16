import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from api.config import Settings, get_settings
from api.models.schemas import CheckCensus, InboxItem, InboxResolveRequest, SettledCheck
from api.services import inbox_service, source_check, sync_service

router = APIRouter()


@router.get("/inbox", response_model=list[InboxItem])
async def list_inbox(
    request: Request,
    response: Response,
    kind: Optional[str] = Query(None),
    settings: Settings = Depends(get_settings),
):
    # G97 ship-together trap (G115 R3): the response now embeds entity- and
    # episode-derived context (cause excerpt, entity type), so an entity edit
    # or a new episode must move this ETag too. The CLIENT half — `.inbox`
    # on `VersionVector`'s `entities`/`episodes` mappings — lands in the same
    # commit; without it SnapshotCache serves stale context until the inbox
    # itself changes.
    etag = sync_service.etag_for(settings.memory_path, "inbox", "entities", "episodes", extra=kind or "")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    items = inbox_service.load_inbox(settings.memory_path)
    if kind:
        wanted = {k.strip() for k in kind.split(",") if k.strip()}
        items = [i for i in items if i.kind.value in wanted]
    return items


@router.get("/inbox/check-census", response_model=CheckCensus)
async def check_census(settings: Settings = Depends(get_settings)):
    """G61 phase 2 S2 — how much of the pending inbox a source could answer.

    Counts per state, reason, kind, locus, rung and target access — enum keys
    only, never an item id, page id, link or host, so the census can be pasted
    into a PR or a backlog row. Read-only and engine-free; it parses the bank,
    so it runs off the event loop. No ETag: not a Store domain, and no screen
    polls it. The same numbers: ``scripts/check-census.sh <bank>``.
    """
    return CheckCensus(**await asyncio.to_thread(source_check.census, settings.memory_path))


@router.get("/inbox/settled", response_model=list[SettledCheck])
async def list_settled(settings: Settings = Depends(get_settings)):
    """"Settled by a check" (owner ruling 2026-10-16): the questions a web lookup or the person's own agent settled,
    newest first, each with its answer and the citation it rests on. On demand, not a Store domain: the Inbox fetches it
    when it opens and after an undo, and caches it in memory. Engine-free; it reads ``inbox/settled/``."""
    from api.services import web_settle

    return [SettledCheck(**row) for row in await asyncio.to_thread(web_settle.list_settled, settings.memory_path)]


@router.post("/inbox/settled/{item_id}/undo")
async def undo_settled(item_id: str, settings: Settings = Depends(get_settings)):
    """The one-tap undo: the check's claim is withdrawn, what it closed reopens (only a claim still as the check left
    it), and the question returns to the inbox. Committed as the person's (``Web check undone <date>``). 409 while
    Sleep holds the pages, 404 for no such settled question."""
    from api.services import git_service, page_lock, state_dictionary, web_settle, write_admission
    from api.services.sleep_refusal import SleepWriting

    memory_path = settings.memory_path
    # An edit already on a page the undo rewrites is committed apart, never as the person's undo (audit P1-3).
    before = await git_service.snapshot_dirty(memory_path)

    def work() -> str:
        with page_lock.page_lock(memory_path):
            target, paths, lines = web_settle.undo(memory_path, item_id)
            web_settle.commit_sync(memory_path, web_settle.commit_message("Web check undone", lines, authors=["user"]),
                                   paths, before=before)
            return target

    try:
        target = await write_admission.run_admitted(
            memory_path, lambda: asyncio.to_thread(work),
            refuse=lambda: SleepWriting(inbox_service.SLEEP_BUSY))
    except web_settle.NotSettleable as exc:
        raise HTTPException(404, str(exc)) from exc
    web_settle.record_event(memory_path, action="undo", item_id=item_id, entity_id=None, by_kind="person")
    try:
        await state_dictionary.refresh_and_commit(memory_path, settings)
    except Exception:  # noqa: BLE001 — the projection never fails the person's undo
        pass
    return {"status": "reopened", "id": target}


@router.post("/inbox/{item_id}/resolve")
async def resolve_inbox(
    item_id: str,
    request: InboxResolveRequest,
    settings: Settings = Depends(get_settings),
):
    return await inbox_service.resolve(item_id, request, settings)
